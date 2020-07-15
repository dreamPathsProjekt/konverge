from konverge.kuberunner import serializers, kube_runner_factory
from konverge.kube import KubeProvisioner
from konverge.files import KubeClusterConfigFile
from konverge.utils import VMCategory, sleep_intervals, HelmVersion


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
        self.executor = serializers.KubeExecutor(
            self.provisioners.get(VMCategory.masters.value).get('leader').instance.self_node
        )

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

    def create(self):
        for category, runners in self.runners:
            if category == VMCategory.workers.value:
                [runner.create() for runner in runners]
            else:
                runners.create()

    def destroy(self, template=False):
        for category, runners in self.runners:
            if template and category == VMCategory.template.value:
                runners.destroy()
            elif category == VMCategory.workers.value:
                [runner.destroy() for runner in runners]
            else:
                runners.destroy()

    def install_loadbalancer(self):
        """
        :return: True if phase is successful.
        """
        if not self.is_control_plane_ha:
            serializers.logging.warning(serializers.crayons.yellow('Control Plane is not configured for HA.'))
            print(serializers.crayons.cyan('Skipping Control Plane LB Install...'))
            return True
        leader = self.provisioners.get(VMCategory.masters.value).get('leader')
        join = self.provisioners.get(VMCategory.masters.value).get('join')

        apiserver_ip = leader.install_control_plane_loadbalancer(is_leader=True)
        if not apiserver_ip:
            serializers.logging.error(
                serializers.crayons.red(f'Error during control plane generated virtual ip: {apiserver_ip}')
            )
            return False
        self.control_plane.control_plane.apiserver_ip = apiserver_ip
        for master in join:
            master.install_control_plane_loadbalancer(is_leader=False)
        return True

    def boostrap_control_plane(self):
        leader = self.provisioners.get(VMCategory.masters.value).get('leader')
        join = self.provisioners.get(VMCategory.masters.value).get('join')
        ready = self.install_loadbalancer()
        if not ready:
            serializers.logging.error(
                serializers.crayons.red('Abort bootstrapping control plane phase.')
            )
            return

        cert_key = leader.bootstrap_control_plane()
        if self.is_control_plane_ha:
            for master in join:
                master.join_node(
                    leader=leader.instance,
                    control_plane_node=True,
                    certificate_key=cert_key
                )

    def rollback_control_plane(self):
        # TODO: Remove cluster .kube/config after rollback
        leader = self.provisioners.get(VMCategory.masters.value).get('leader')
        join = self.provisioners.get(VMCategory.masters.value).get('join')
        if self.is_control_plane_ha:
            for master in join:
                master.rollback_node()
            self.wait(wait_period=60, reason='Wait for Rollback to complete')
        leader.rollback_node()

    def join_workers(self):
        leader = self.provisioners.get(VMCategory.masters.value).get('leader')
        workers = self.provisioners.get(VMCategory.workers.value)
        for role, group in workers.items():
            for worker in group:
                worker.join_node(leader=leader.instance, control_plane_node=False)

    def rollback_workers(self):
        workers = self.provisioners.get(VMCategory.workers.value)
        for role, group in workers.items():
            for worker in group:
                worker.rollback_node()
        self.wait(wait_period=60, reason='Wait for Rollback to complete')

    def post_installs(self):
        self.add_local_cluster_config()

        if self.cluster.cluster.dashboard:
            self.executor.deploy_dashboard(local=False)

        self.label_workers()
        self.helm_install()

        if self.cluster.cluster.loadbalancer:
            self.executor.metallb_install()

    def helm_install(self):
        if not self.cluster.cluster.helm.local and not self.cluster.cluster.helm.tiller:
            print(serializers.crayons.cyan('Skip Helm Install.'))
            return
        if self.cluster.cluster.helm.version == HelmVersion.v2:
            self.executor.helm_install_v2(
                helm=self.cluster.cluster.helm.local,
                tiller=self.cluster.cluster.helm.tiller
            )
        else:
            msg = f'Helm Version {self.cluster.cluster.helm.version.value} not supported yet.'
            serializers.logging.warning(serializers.crayons.yellow(msg))

    def add_local_cluster_config(self):
        # TODO: Support loadbalancer arguments yaml file, version, interface, from .cluster.yml - method supports it.
        self.executor.add_local_cluster_config(
            custom_user_name=self.cluster.cluster.user,
            custom_cluster_name=self.cluster.cluster.name,
            custom_context=self.cluster.cluster.context,
            set_current_context=True
        )

    def label_workers(self):
        workers = self.provisioners.get(VMCategory.workers.value)
        for role, group in workers.items():
            for worker in group:
                self.executor.apply_label_node(role=role, instance_name=worker.instance.vm_attributes.name)

    def execute(self, destroy=False, destroy_template=False, wait_period=120):
        # TODO: Add create and destroy stages.
        if not destroy:
            self.create()
            self.wait(wait_period, reason='')
            self.boostrap_control_plane()
            self.wait(wait_period, reason='')
            self.join_workers()
            self.post_installs()
            print(serializers.crayons.green(f'Cluster {self.cluster.cluster.name} successfully created.'))
        else:
            self.rollback_workers()
            self.rollback_control_plane()
            self.wait(wait_period=30, reason='')
            self.destroy(template=destroy_template)
            print(serializers.crayons.green(f'Cluster {self.cluster.cluster.name} successfully destroyed.'))

