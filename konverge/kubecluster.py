import typing

from konverge.kuberunner import serializers, kube_runner_factory
from konverge.kube import KubeProvisioner
from konverge.files import KubeClusterConfigFile
from konverge.utils import VMCategory, sleep_intervals, HelmVersion, KubeClusterStages


class KubeCluster:
    def __init__(self, config: KubeClusterConfigFile):
        self.config = config.serialize()
        self.cluster = serializers.ClusterAttributesSerializer(self.config)
        self.control_plane = serializers.ControlPlaneSerializer(self.config)

        self.cluster.serialize()
        self.control_plane.serialize()

        self.templates = serializers.ClusterTemplateSerializer(
            config=self.config.get(VMCategory.template.value),
            cluster_attributes=self.cluster.cluster
        )
        self.templates.serialize()

        self.masters = serializers.ClusterMasterSerializer(
            config=self.config.get(VMCategory.masters.value),
            cluster_attributes=self.cluster.cluster,
            templates=self.templates
        )
        self.masters.serialize()

        self.workers = [
            serializers.ClusterWorkerSerializer(
                config=group,
                cluster_attributes=self.cluster.cluster,
                templates=self.templates
            )
            for group in self.config.get(VMCategory.workers.value)
        ]
        [worker.serialize() for worker in self.workers]

        self.runners = self._generate_runners()
        self.provisioners = self._generate_provisioners()
        self.executor = None

    @property
    def is_control_plane_ha(self):
        if len(self.masters.instances) <= 1:
            self.control_plane.control_plane.ha_masters = False
        return self.control_plane.control_plane.ha_masters

    @property
    def exists(self):
        return self.cluster.exists

    @staticmethod
    def wait(wait_period=120, reason='N/A'):
        print(serializers.crayons.cyan(f'Sleep for {wait_period} seconds. Reason: {reason}'))
        sleep_intervals(wait_period)

    def _generate_runners(self):
        return {
            VMCategory.template.value: kube_runner_factory(self.templates),
            VMCategory.masters.value: kube_runner_factory(self.masters),
            VMCategory.workers.value: [kube_runner_factory(worker) for worker in self.workers]
        }

    def _generate_provisioners(self):
        provisioner = KubeProvisioner.kube_provisioner_factory(
            os_type=self.templates.instances[0].vm_attributes.os_type
        )
        return {
            VMCategory.masters.value: {
                'leader': provisioner(
                    instance=self.masters.instances[0],
                    control_plane=self.control_plane.control_plane
                ),
                'join': [
                    provisioner(
                        instance=self.masters.instances[i],
                        control_plane=self.control_plane.control_plane
                    )
                    for i in range(1, len(self.masters.instances))
                ] if self.is_control_plane_ha else []
            },
            VMCategory.workers.value: {
                worker.role: [
                    provisioner(
                        instance=instance,
                        control_plane=self.control_plane.control_plane
                    )
                    for instance in worker.instances
                ]
                for worker in self.workers
            }
        }

    def _generate_executor(self, dry_run=False):
        """
        Lazy load KubeExecutor with remote feature, until leader is online.
        """
        leader = self.provisioners.get(VMCategory.masters.value).get('leader').instance
        if dry_run:
            title = f'Generating KubeExecutor from leader: {leader.vm_attributes.name}'
            horizontal_sep = '=' * len(title)
            print()
            print(serializers.crayons.green(title))
            print(serializers.crayons.green(horizontal_sep))
            print()
            print(serializers.crayons.green(f'Fabric Wrapper: {leader.self_node}'))
            print(
                serializers.crayons.green(
                    f'Private SSH Key: {leader.vm_attributes.private_pem_ssh_key} Exists: {leader.vm_attributes.private_key_or_pem_ssh_key_exists}'
                )
            )
            print(
                serializers.crayons.green(
                    f'Public SSH Key: {leader.vm_attributes.public_ssh_key} - Exists: {leader.vm_attributes.public_key_exists}'
                )
            )
            print(serializers.crayons.green(f'KubeExecutor generated successfully (dry-run)'))
            print()
            # return dummy executor
            return serializers.KubeExecutor()
        return serializers.KubeExecutor(
            leader.self_node
        )

    def create(self, dry_run=False):
        for category, runners in self.runners.items():
            if category == VMCategory.workers.value:
                [runner.create(dry_run=dry_run) for runner in runners]
            else:
                runners.create(dry_run=dry_run)

    def destroy(self, template=False, dry_run=False):
        for category, runners in self.runners.items():
            if template and category == VMCategory.template.value:
                runners.destroy(dry_run=dry_run)
            elif category == VMCategory.workers.value:
                [runner.destroy(dry_run=dry_run) for runner in runners]
            elif category == VMCategory.masters.value:
                runners.destroy(dry_run=dry_run)

    def install_loadbalancer(self, dry_run=False):
        """
        :return: True if phase is successful.
        """
        if dry_run:
            title = f'Installing and setup keepalived Control Plane LB.'
            horizontal_sep = '=' * len(title)
            print()
            print(serializers.crayons.green(title))
            print(serializers.crayons.green(horizontal_sep))
            print()
        if not self.is_control_plane_ha:
            serializers.logging.warning(serializers.crayons.yellow('Control Plane is not configured for HA.'))
            print(serializers.crayons.cyan('Skipping Control Plane LB Install...'))
            return True
        leader = self.provisioners.get(VMCategory.masters.value).get('leader')
        join = self.provisioners.get(VMCategory.masters.value).get('join')

        print(serializers.crayons.cyan(f'Setup keepalived on Leader master node: {leader.instance.vm_attributes.name}'))
        if not dry_run:
            apiserver_ip = leader.install_control_plane_loadbalancer(is_leader=True)
            if not apiserver_ip:
                serializers.logging.error(
                    serializers.crayons.red(f'Error during control plane generated virtual ip: {apiserver_ip}')
                )
                return False
            self.control_plane.control_plane.apiserver_ip = apiserver_ip
        for master in join:
            print(serializers.crayons.cyan(f'Setup keepalived and join master node: {master.instance.vm_attributes.name}'))
            master.install_control_plane_loadbalancer(is_leader=False) if not dry_run else None
        print(serializers.crayons.green('Successfully installed Control Plane Loadbalancer (dry-run)')) if dry_run else None
        return True

    def boostrap_control_plane(self, dry_run=False):
        leader = self.provisioners.get(VMCategory.masters.value).get('leader')
        join = self.provisioners.get(VMCategory.masters.value).get('join')
        ready = self.install_loadbalancer(dry_run=dry_run)

        if dry_run:
            title = f'Bootstrap Control Plane.'
            horizontal_sep = '=' * len(title)
            print()
            print(serializers.crayons.green(title))
            print(serializers.crayons.green(horizontal_sep))
            print()

        if not ready:
            serializers.logging.error(
                serializers.crayons.red('Abort bootstrapping control plane phase.')
            )
            return

        print(serializers.crayons.cyan(f'Boostrap Leader master node: {leader.instance.vm_attributes.name}'))
        cert_key = leader.bootstrap_control_plane() if not dry_run else None
        if self.is_control_plane_ha:
            for master in join:
                print(serializers.crayons.cyan(f'Join master node: {master.instance.vm_attributes.name}'))
                master.join_node(
                    leader=leader.instance,
                    control_plane_node=True,
                    certificate_key=cert_key
                ) if not dry_run else None
        print(serializers.crayons.green('Successfully Bootstrapped Control Plane (dry-run)')) if dry_run else None

    def rollback_control_plane(self, dry_run=False):
        if dry_run:
            title = f'Rollback Master Nodes.'
            horizontal_sep = '=' * len(title)
            print()
            print(serializers.crayons.green(title))
            print(serializers.crayons.green(horizontal_sep))
            print()
        leader = self.provisioners.get(VMCategory.masters.value).get('leader')
        join = self.provisioners.get(VMCategory.masters.value).get('join')
        if self.is_control_plane_ha:
            for master in join:
                print(serializers.crayons.cyan(f'Rollback master node: {master.instance.vm_attributes.name}'))
                master.rollback_node() if not dry_run else None
            wait = 0 if dry_run else 60
            self.wait(wait_period=wait, reason='Wait for Rollback to complete')
        print(serializers.crayons.cyan(f'Rollback leader master node: {leader.instance.vm_attributes.name}'))
        leader.rollback_node() if not dry_run else None
        print(serializers.crayons.green('Successfully removed master nodes (dry-run)')) if dry_run else None

    def join_workers(self, dry_run=False):
        if dry_run:
            title = f'Join Worker Nodes.'
            horizontal_sep = '=' * len(title)
            print()
            print(serializers.crayons.green(title))
            print(serializers.crayons.green(horizontal_sep))
            print()
        leader = self.provisioners.get(VMCategory.masters.value).get('leader')
        workers = self.provisioners.get(VMCategory.workers.value)
        for role, group in workers.items():
            for worker in group:
                print(serializers.crayons.cyan(f'Joining worker node: {worker.instance.vm_attributes.name}'))
                worker.join_node(leader=leader.instance, control_plane_node=False) if not dry_run else None
        print(serializers.crayons.green('Successfully joined worker nodes (dry-run)')) if dry_run else None

    def rollback_workers(self, dry_run=False):
        if dry_run:
            title = f'Rollback Worker Nodes.'
            horizontal_sep = '=' * len(title)
            print()
            print(serializers.crayons.green(title))
            print(serializers.crayons.green(horizontal_sep))
            print()
        workers = self.provisioners.get(VMCategory.workers.value)
        for role, group in workers.items():
            for worker in group:
                print(serializers.crayons.cyan(f'Rollback worker node: {worker.instance.vm_attributes.name}'))
                worker.rollback_node() if not dry_run else None
        wait = 0 if dry_run else 60
        self.wait(wait_period=wait, reason='Wait for Rollback to complete')
        print(serializers.crayons.green('Successfully removed worker nodes (dry-run)')) if dry_run else None

    def post_installs(self, dry_run=False):
        # TODO: Support loadbalancer arguments yaml file, version, interface, from .cluster.yml - method supports it.
        self.add_local_cluster_config(dry_run=dry_run)

        if self.cluster.cluster.dashboard:
            if dry_run:
                import os
                bootstrap_path = os.path.join(serializers.settings.BASE_PATH, 'bootstrap')
                user_creation = f'{bootstrap_path}/dashboard-adminuser.yaml'
                title = 'Deploying dashboard and dashboard admin'
                horizontal_sep = '=' * len(title)
                print()
                print(serializers.crayons.green(title))
                print(serializers.crayons.green(horizontal_sep))
                print()
                print(serializers.crayons.cyan(f'Deploying Dashboard from {bootstrap_path}'))
                print(serializers.crayons.green(f'Kubernetes Dashboard deployed successfully. (dry-run)'))
                print(serializers.crayons.cyan(f'Deploying User admin-user with role-binding: cluster-admin from {user_creation}'))
                print(serializers.crayons.green(f'User admin-user created successfully. (dry-run)'))
                print()
            self.executor.deploy_dashboard(local=False) if not dry_run else None

        self.label_workers(dry_run=dry_run)
        self.helm_install(dry_run=dry_run)

        if self.cluster.cluster.loadbalancer:
            if dry_run:
                title = 'Deploying Metallb'
                horizontal_sep = '=' * len(title)
                print()
                print(serializers.crayons.green(title))
                print(serializers.crayons.green(horizontal_sep))
                print()
                metallb_range = serializers.settings.pve_cluster_config_client.loadbalancer_ip_range_to_string_or_list()
                if not metallb_range:
                    serializers.logging.error(serializers.crayons.red('Could not deploy MetalLB with given cluster values.'))
                    return
                print(serializers.crayons.green(f'Metallb IP Range: {metallb_range}'))

                interface = 'vmbr0'
                common_iface = serializers.KubeExecutor.get_bridge_common_interface(interface)
                if not common_iface:
                    serializers.logging.error(
                        serializers.crayons.red(f'Interface {interface} not found as common bridge in PVE Cluster nodes.')
                    )
                    serializers.logging.error(serializers.crayons.red('MetalLB install aborted (dry-run)'))
                    return
                print(serializers.crayons.green(f'Common interface {common_iface} found'))
                print()
                print(serializers.crayons.green('MetalLB installed (dry-run)'))
                print()
                return
            self.executor.metallb_install() if not dry_run else None

    def post_destroy(self, dry_run=False):
        self.unset_local_cluster_config(dry_run=dry_run)

    def helm_install(self, dry_run=False):
        if not self.cluster.cluster.helm.local and not self.cluster.cluster.helm.tiller:
            print(serializers.crayons.cyan('Skip Helm Install.'))
            return
        if self.cluster.cluster.helm.version == HelmVersion.v2:
            if dry_run:
                current_context = self.cluster.cluster.context
                title = 'Helm & Tiller install'
                horizontal_sep = '=' * len(title)
                print()
                print(serializers.crayons.green(title))
                print(serializers.crayons.green(horizontal_sep))
                print()
                print(serializers.crayons.green(f'Helm Version: {self.cluster.cluster.helm.version}'))
                print(serializers.crayons.green(f'Install helm local: {self.cluster.cluster.helm.local}'))
                print(serializers.crayons.green(f'Install Tiller component: {self.cluster.cluster.helm.tiller}'))
                print()
                if self.cluster.cluster.helm.local:
                    print(serializers.crayons.green('Helm installed locally (dry-run)'))
                if self.cluster.cluster.helm.tiller:
                    print(serializers.crayons.green(f'Helm initialized with Tiller for context: {current_context} (dry-run)'))
                print(serializers.crayons.magenta('You might need to run "helm init --client-only" to initialize repos (dry-run)'))
                return
            self.executor.helm_install_v2(
                helm=self.cluster.cluster.helm.local,
                tiller=self.cluster.cluster.helm.tiller
            )
        else:
            msg = f'Helm Version {self.cluster.cluster.helm.version.value} not supported yet.'
            serializers.logging.warning(serializers.crayons.yellow(msg))

    def add_local_cluster_config(self, dry_run=False):
        if dry_run:
            title = f'Add Cluster {self.cluster.cluster.name} to ~/.kube/config locally.'
            horizontal_sep = '=' * len(title)
            print()
            print(serializers.crayons.green(title))
            print(serializers.crayons.green(horizontal_sep))
            print()
            print(serializers.crayons.green(f'Custom User: {self.cluster.cluster.user}'))
            print(serializers.crayons.green(f'Custom Cluster: {self.cluster.cluster.name}'))
            print(serializers.crayons.green(f'Custom Context: {self.cluster.cluster.context}'))
            print(serializers.crayons.green(f'~/.kube/config updated successfully (dry-run)'))
            print()
            return
        self.executor.add_local_cluster_config(
            custom_user_name=self.cluster.cluster.user,
            custom_cluster_name=self.cluster.cluster.name,
            custom_context=self.cluster.cluster.context,
            set_current_context=True
        )

    def unset_local_cluster_config(self, dry_run=False):
        if dry_run:
            title = f'Remove Cluster {self.cluster.cluster.name} from ~/.kube/config locally.'
            horizontal_sep = '=' * len(title)
            print()
            print(serializers.crayons.red(title))
            print(serializers.crayons.red(horizontal_sep))
            print()
            print(serializers.crayons.red(f'Custom User: {self.cluster.cluster.user}'))
            print(serializers.crayons.red(f'Custom Cluster: {self.cluster.cluster.name}'))
            print(serializers.crayons.red(f'Custom Context: {self.cluster.cluster.context}'))
            print(serializers.crayons.green(f'~/.kube/config updated successfully (dry-run)'))
            print()
            return
        self.executor.unset_local_cluster_config(self.cluster.cluster)

    def label_workers(self, dry_run=False):
        if dry_run:
            title = f'Adding role labels to worker nodes.'
            horizontal_sep = '=' * len(title)
            print()
            print(serializers.crayons.green(title))
            print(serializers.crayons.green(horizontal_sep))
            print()
        workers = self.provisioners.get(VMCategory.workers.value)
        for role, group in workers.items():
            for worker in group:
                if dry_run:
                    label_node = f'node-role.kubernetes.io/{role}='
                    labeled = f'kubectl label nodes {worker.instance.vm_attributes.name} {label_node}'
                    print(serializers.crayons.green(f'Applying label to node {worker.instance.vm_attributes.name}'))
                    print(serializers.crayons.cyan(labeled))
                    print(serializers.crayons.green(f'Added label {label_node} to {worker.instance.vm_attributes.name} (dry-run)'))
                    print()
                else:
                    self.executor.apply_label_node(role=role, instance_name=worker.instance.vm_attributes.name)

    def execute(
            self,
            destroy=False,
            destroy_template=False,
            wait_period=120,
            stage: typing.Union[KubeClusterStages, None] = None,
            dry_run=False
    ):
        if self.exists:
            serializers.logging.warning(
                serializers.crayons.yellow(f'Cluster {self.cluster.cluster.name} already exists. Abort...')
            )
            return

        stagemsg = f' Stage: {stage.value}' if stage else ''
        dry = ' (dry-run)' if dry_run else ''
        action = 'destroyed' if destroy else 'created'
        msg = f'Cluster {self.cluster.cluster.name} successfully {action}.{stagemsg}{dry}'
        stage_output = serializers.crayons.yellow(f'Running Stage: {stage.value}') if stage else ''
        stage_create = serializers.crayons.yellow(f'Running Stage: {KubeClusterStages.create.value}')
        stage_bootstrap = serializers.crayons.yellow(f'Running Stage: {KubeClusterStages.bootstrap.value}')
        stage_join = serializers.crayons.yellow(f'Running Stage: {KubeClusterStages.join.value}')
        stage_post_installs = serializers.crayons.yellow(f'Running Stage: {KubeClusterStages.post_installs.value}')
        wait_create = 0 if dry_run else wait_period
        wait_bootstrap = 0 if dry_run else 120

        if destroy:
            print()
            if not stage:
                print(stage_join)
                self.rollback_workers(dry_run=dry_run)
                print(stage_bootstrap)
                self.rollback_control_plane(dry_run=dry_run)
                print(stage_create)
                self.destroy(template=destroy_template, dry_run=dry_run)
                self.executor = self._generate_executor(dry_run=dry_run)
                print(stage_post_installs)
                self.post_destroy(dry_run=dry_run)
                print(serializers.crayons.green(msg))
                return

            print()
            if stage.value == KubeClusterStages.join.value:
                print(stage_output)
                self.rollback_workers(dry_run=dry_run)
            if stage.value == KubeClusterStages.bootstrap.value:
                print(stage_output)
                self.rollback_control_plane(dry_run=dry_run)
            if stage.value == KubeClusterStages.create.value:
                print(stage_output)
                self.destroy(template=destroy_template, dry_run=dry_run)
            if stage.value == KubeClusterStages.post_installs.value:
                print(stage_output)
                self.executor = self._generate_executor(dry_run=dry_run)
                self.post_destroy(dry_run=dry_run)
            print(serializers.crayons.green(msg))
            return

        if not stage:
            print()
            print(stage_create)
            self.create(dry_run=dry_run)
            self.wait(wait_period=wait_create, reason='Create & Start Cluster VMs')
            self.executor = self._generate_executor(dry_run=dry_run)
            print(stage_bootstrap)
            self.boostrap_control_plane(dry_run=dry_run)
            self.wait(wait_period=wait_bootstrap, reason='Bootstrap Control Plane')
            print(stage_join)
            self.join_workers(dry_run=dry_run)
            print(stage_post_installs)
            self.post_installs(dry_run=dry_run)
            print(serializers.crayons.green(msg))
            return

        print()
        if stage.value == KubeClusterStages.create.value:
            print(stage_output)
            self.create(dry_run=dry_run)
            self.wait(wait_period=wait_create, reason='Create & Start Cluster VMs')
        if stage.value == KubeClusterStages.bootstrap.value:
            print(stage_output)
            self.executor = self._generate_executor(dry_run=dry_run)
            self.boostrap_control_plane(dry_run=dry_run)
            self.wait(wait_period=wait_bootstrap, reason='Bootstrap Control Plane')
        if stage.value == KubeClusterStages.join.value:
            print(stage_output)
            self.join_workers(dry_run=dry_run)
        if stage.value == KubeClusterStages.post_installs.value:
            print(stage_output)
            self.post_installs(dry_run=dry_run)
        print(serializers.crayons.green(msg))
