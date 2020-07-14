import logging
import crayons
from typing import NamedTuple
from functools import singledispatch

from konverge import settings
from konverge.utils import (
    KubeClusterAction,
    KubeStorage,
    HelmVersion,
    VMCategory,
    VMAttributes,
    Storage,
    get_kube_versions,
    get_id_prefix,
    sleep_intervals
)
from konverge import output
from konverge.kube import ControlPlaneDefinitions, KubeExecutor, KubeProvisioner
from konverge.cloudinit import CloudinitTemplate
from konverge.instance import InstanceClone
from konverge.queries import VMQuery


VMID_PLACEHOLDER = 9999


class HelmAtrributes(NamedTuple):
    version: HelmVersion = HelmVersion.v2
    local: bool = False
    tiller: bool = True


class ClusterAttributes(NamedTuple):
    name: str
    pool: str
    os_type: str = 'ubuntu'
    user: str = None
    context: str = None
    dashboard: bool = True
    storage: KubeStorage = None
    loadbalancer: bool = True
    version: str = None
    docker: str = None
    docker_ce: bool = False
    helm: HelmAtrributes = HelmAtrributes()


class KubeCluster:
    def __init__(self, cluster_config: dict):
        self.cluster_config = cluster_config
        self.control_plane = self._serialize_control_plane()
        self.cluster_attributes = self._serialize_cluster_attributes()
        self.cluster_ssh_key = self.cluster_config.get('ssh_key')

        self.vms_response_is_empty = singledispatch(self.vms_response_is_empty_dict)
        self.vms_response_is_empty.register(list, self.vms_response_is_empty_list)
        self.vms_response_is_empty.register(dict, self.vms_response_is_empty_dict)

        self.template_creation = self._get_template_creation()

        self.template = None
        self.masters = None
        self.workers = None
        self.on_delete_hooks = {'template': False, 'rollback_only': False}
        self.initialize()

    @property
    def metallb_range(self):
        if self.cluster_attributes.loadbalancer:
            return settings.pve_cluster_config_client.loadbalancer_ip_range_to_string_or_list()
        return ''

    @property
    def masters_leader(self):
        return self.masters[0] if self.masters else None

    @property
    def masters_joiners(self):
        predicate = self.masters and self.control_plane.ha_masters and len(self.masters) > 1
        return self.masters[1:] if predicate else []

    def _get_template_creation(self):
        template_config = self.cluster_config.get(VMCategory.template.value)
        create = template_config.get('create')
        if create is not None:
            return create
        return True

    def _serialize_cluster_attributes(self):
        os_type = self.cluster_config.get('os_type') or 'ubuntu'
        user = self.cluster_config.get('user')
        context = self.cluster_config.get('context')
        dashboard = self.cluster_config.get('dashboard', True) or True
        storage = KubeStorage.return_value(self.cluster_config.get('storage'))
        loadbalancer = self.cluster_config.get('loadbalancer') or True

        versions = self.cluster_config.get('versions')
        docker = None
        docker_ce = False
        if not versions:
            version = None
        else:
            version = versions.get('kubernetes')
            docker_ce = versions.get('docker_ce', False)
            if version:
                version, docker = self.infer_full_versions_from_major(kubernetes=version, docker_ce=docker_ce)
            print(crayons.green(f'Kubernetes version: {version}'))
            ce='Docker CE'
            io='docker.io'
            print(crayons.green(f'{ce if docker_ce else io} version: {docker}'))

        helm_attributes = self.cluster_config.get('helm')
        if not helm_attributes:
            helm = HelmAtrributes()
        else:
            helm_version = HelmVersion.return_value(helm_attributes.get('version')) or HelmVersion.v2
            local = helm_attributes.get('local') or False
            tiller = helm_attributes.get('tiller') or True
            helm = HelmAtrributes(
                version=helm_version,
                local=local,
                tiller=tiller
            )

        return ClusterAttributes(
            name=self.cluster_config.get('name'),
            pool=self.cluster_config.get('pool'),
            os_type=os_type,
            user=user,
            context=context,
            dashboard=dashboard,
            storage=storage,
            loadbalancer=loadbalancer,
            version=version,
            docker=docker,
            docker_ce=docker_ce,
            helm=helm
        )

    def _serialize_control_plane(self):
        control_plane_definitions = ControlPlaneDefinitions()
        control_plane = self.cluster_config.get('control_plane')
        if not control_plane:
            return control_plane_definitions

        for key, value in control_plane.items():
            if key != 'apiserver':
                setattr(control_plane_definitions, key, value)
        apiserver = control_plane.get('apiserver')
        if not apiserver:
            return control_plane_definitions
        for key, value in apiserver.items():
            setattr(control_plane_definitions, f'apiserver_{key}', value)
        return control_plane_definitions

    @staticmethod
    def infer_full_versions_from_major(kubernetes='1.17', docker_ce=False):
        versions = get_kube_versions(kube_major=kubernetes, docker_ce=docker_ce)
        lines = versions.splitlines()
        start = 0
        end = len(lines)
        docker_ce_start = 0
        docker_ce_end = len(lines)
        docker_io_start = 0
        docker_io_end = len(lines)
        for line in lines:
            if '=== kubelet ===' in line:
                start = lines.index(line)
            if '=== kubectl ===' in line:
                end = lines.index(line)
            if '=== docker.io ===' in line:
                docker_io_start = lines.index(line)
            if '=== docker-ce ===' in line:
                docker_io_end = lines.index(line)
            if '=== docker-ce ===' in line and docker_ce:
                docker_ce_start = lines.index(line)
            if docker_ce:
                docker_ce_end = -1
        version_list = [entry for entry in lines[start+1:end] if entry]
        docker_ce_list = [entry for entry in lines[docker_ce_start+1:docker_ce_end] if entry] if docker_ce else []
        docker_io_list = [entry for entry in lines[docker_io_start+1:docker_io_end] if entry]
        minor_versions = []
        docker_ce_versions = []
        docker_io_versions = []
        for entry in version_list:
            title, version, url = entry.split('|')
            minor_versions.append(version.strip())
        if docker_ce:
            for entry in docker_ce_list:
                title, version, url = entry.split('|')
                docker_ce_versions.append(version.strip())
        for entry in docker_io_list:
            title, version, url = entry.split('|')
            docker_io_versions.append(version.strip())
        latest = minor_versions[0]
        if docker_ce:
            return latest, docker_ce_versions[0]
        return latest, docker_io_versions[0]

    @staticmethod
    def vms_response_is_empty(vms, category: VMCategory):
        pass

    @staticmethod
    def vms_response_is_empty_list(vms, category: VMCategory):
        if not vms:
            logging.error(crayons.red(f'Instances of type: {category.value} not found'))
            return True
        return False

    @staticmethod
    def vms_response_is_empty_dict(vms, category: VMCategory):
        if not vms:
            logging.error(crayons.red(f'Instances of type: {category.value} not found'))
            return True
        if not any(vms.values()):
            logging.error(crayons.red(f'Instances of type: {category.value} not found'))
            return True
        return False

    @staticmethod
    def generate_template(template_attributes: VMAttributes, preinstall=True):
        factory = CloudinitTemplate.os_type_factory(template_attributes.os_type)
        return factory(vm_attributes=template_attributes, client=settings.vm_client, preinstall=preinstall)

    @staticmethod
    def update_vmid(instance: InstanceClone):
        """
        Update VMID field of instance attributes, dynamically,
        to avoid the same VMIDs, during initialization.
        Can be refactored on InstanceClone.execute()
        """
        vmid, _ = instance.get_vmid_and_username()
        instance.vmid = vmid

    @staticmethod
    def sleep(duration=120, reason='N/A'):
        print(crayons.cyan(f'Sleep for {duration} seconds. Reason: {reason}'))
        sleep_intervals(wait_period=duration)

    @staticmethod
    def is_action_create(action=KubeClusterAction.create):
        return action == KubeClusterAction.create

    @staticmethod
    def is_action_delete(action=KubeClusterAction.delete):
        return action == KubeClusterAction.delete

    @staticmethod
    def is_action_recreate(action=KubeClusterAction.recreate):
        return action == KubeClusterAction.recreate

    @staticmethod
    def is_action_update(action=KubeClusterAction.update):
        return action == KubeClusterAction.update

    def set_on_delete_hooks(self, template=False, rollback_only=False):
        self.on_delete_hooks['template'] = template
        self.on_delete_hooks['rollback_only'] = rollback_only

    def destroy_warning(self, destroy=False):
        msg = f'Deleting Cluster {self.cluster_attributes.name} vms.'
        logging.warning(crayons.yellow(msg)) if destroy else None

    def cluster_exists(self):
        """
        Checks local ~/.kube/config from KubeExecutor.cluster_exists(cluster),
        to determine, if cluster has been already created.
        """
        kube_executor = KubeExecutor()
        if kube_executor.cluster_exists(self):
            logging.warning(crayons.yellow(f'Cluster {self.cluster_attributes.name} exists.'))
            return True
        return False

    def initialize(self):
        """
        Initializes all necessary instances and updates related attributes.
        Retrieve (query) vm groups if cluster exists.
        """
        print(crayons.cyan(f'Gathering initial requirements for cluster: {self.cluster_attributes.name}'))
        retrieve = self.cluster_exists()

        templates = self.get_template_vms()
        if self.vms_response_is_empty(templates, category=VMCategory.template):
            return

        self.template = templates
        masters = self.get_masters_vms(self.template, retrieve=retrieve)
        workers = self.get_workers_vms(self.template, retrieve=retrieve)
        if not self.vms_response_is_empty(masters, category=VMCategory.masters):
            self.masters = masters
        if not self.vms_response_is_empty(workers, category=VMCategory.workers):
            self.workers = workers
        print(crayons.green(f'Cluster: {self.cluster_attributes.name} initialized.'))

    def show(self, action: KubeClusterAction = KubeClusterAction.create):
        output.output_cluster(self)
        output.output_config(self)
        output.output_control_plane(self)
        output.output_tools_settings(self)
        if action == KubeClusterAction.delete and not self.on_delete_hooks['template']:
            output.output_templates(self, action=KubeClusterAction.nothing) if self.template else None
        else:
            output.output_templates(self, action=action) if self.template else None
        output.output_masters(self, action=action, vmid_placeholder=VMID_PLACEHOLDER) if self.masters else None
        output.output_worker_groups(self, action=action, vmid_placeholder=VMID_PLACEHOLDER) if self.workers else None

    def plan(self, action=KubeClusterAction.create):
        self.show(action)
        return self.cluster_exists()

    def action_factory(self, action=KubeClusterAction.create):
        actions = {
            KubeClusterAction.create.value: self.create,
            KubeClusterAction.update.value: self.update,
            KubeClusterAction.delete.value: self.delete,
            KubeClusterAction.recreate.value: self.recreate
        }
        return actions[action.value]

    def is_abort(self, action=KubeClusterAction.create, force=False):
        """
        Runs plan method to determine if cluster exists and show plan output if not.
        :returns True if apply action is to be aborted.
        """
        exists = self.plan(action)
        if force:
            return False
        if self.is_action_create(action) and exists:
            logging.error(crayons.red(f'Apply type: {action.value} aborted.'))
            logging.error(crayons.red(f'Cluster {self.cluster_attributes.name} exists.'))
            return True
        if not self.is_action_create(action) and not exists:
            logging.error(crayons.red(f'Apply type: {action.value} aborted.'))
            logging.error(crayons.red(f'Cluster {self.cluster_attributes.name} does not exist.'))
            return True
        return False

    def apply(self, action=KubeClusterAction.create, force=False):
        """
        Executes only create, delete actions before other actions are implemented.
        """
        if self.is_abort(action, force=force):
            return
        if self.is_action_update(action):
            logging.warning(crayons.yellow(f'Cluster {action.value} not implemented yet.'))
            return
        execute = self.action_factory(action)
        execute()

    def create(self):
        template_vmid_list = self.execute_templates()
        masters_vmid_list = self.execute_masters()
        workers_vmid_list = self.execute_workers()

        create_title = 'Created & Started'
        print(crayons.blue(create_title))
        print(crayons.blue('=' * len(create_title)))
        print(crayons.white(f'Templates VMID: ') + crayons.yellow(template_vmid_list))
        print(crayons.white(f'Masters VMID: ') + crayons.yellow(masters_vmid_list))
        for role, workers in workers_vmid_list.items():
            print(crayons.white(f'Workers {role} VMID') + crayons.yellow(workers))
        print('')

        self.sleep(duration=120, reason=f'Wait all Cluster {self.cluster_attributes.name} VMs to initialize')

        self.boostrap_control_plane()
        self.join_workers()
        self.post_installs()
        return template_vmid_list, masters_vmid_list, workers_vmid_list

    def delete(self):
        """
        De-provisions & deletes cluster VMs. If template flag is used, it also deletes template vms.
        Option rollback_only, just removes nodes from the cluster, without deleting them.
        """
        # TODO: Remove cluster .kube/config after rollback
        logging.warning(crayons.yellow('Performing Rollback of worker nodes'))
        self.rollback_workers()
        complete = crayons.green('Rollback Complete')
        print(complete)
        logging.warning(crayons.yellow('Performing Rollback of master nodes'))
        self.rollback_control_plane()
        print(complete)
        if self.on_delete_hooks['rollback_only']:
            return

        logging.warning(crayons.yellow('Removing Proxmox VMs'))
        workers_vmid_list = self.execute_workers(destroy=True)
        masters_vmid_list = self.execute_masters(destroy=True)

        remove_title = 'Stopped & Removed'
        print(crayons.blue(remove_title))
        print(crayons.blue('=' * len(remove_title)))
        print(crayons.white(f'Masters VMID: ') + crayons.yellow(masters_vmid_list))
        for role, workers in workers_vmid_list.items():
            print(crayons.white(f'Workers {role} VMID') + crayons.yellow(workers))
        print('')
        if not self.on_delete_hooks['template']:
            return

        logging.warning(crayons.yellow('Removing Templates'))
        template_vmid_list = self.execute_templates(destroy=True)
        print(crayons.blue(remove_title))
        print(crayons.blue('=' * len(remove_title)))
        print(crayons.white(f'Templates VMID: ') + crayons.yellow(template_vmid_list))
        print('')

    def update(self):
        pass

    def recreate(self):
        self.delete()
        self.create()

    def execute_templates(self, destroy=False):
        """Creates Cloudinit templates from scratch, or reuses templates if VMIDs exist on node."""
        template_vmids = []
        if self.template_creation or destroy:
            self.destroy_warning(destroy)
            for node, template in self.template.items():
                template_vmids.append(
                    template.execute(
                        kubernetes_version=self.cluster_attributes.version,
                        docker_version=self.cluster_attributes.docker,
                        docker_ce=self.cluster_attributes.docker_ce,
                        destroy=destroy
                    )
                )
        else:
            logging.warning(crayons.yellow('Template generation skipped.'))
            for node, template in self.template.items():
                template_vmids.append(template.vmid)
        return template_vmids

    def execute_masters(self, destroy=False):
        """Template unpacking per node is done, during initialization"""
        masters_vmids = []
        self.destroy_warning(destroy)
        for master in self.masters:
            self.update_vmid(master) if not destroy else None
            masters_vmids.append(master.execute(start=True, destroy=destroy))
        return masters_vmids

    def execute_workers_group(self, workers: list, destroy=False):
        group_vmids = []
        for worker in workers:
            self.update_vmid(worker) if not destroy else None
            group_vmids.append(worker.execute(start=True, destroy=destroy))
        return group_vmids

    def execute_workers(self, destroy=False):
        """Template unpacking per node is done, during initialization"""
        workers_vmids = {}
        self.destroy_warning(destroy)
        for role, workers in self.workers.items():
            workers_vmids[role] = self.execute_workers_group(workers, destroy=destroy)
        return workers_vmids

    def get_master_provisioners(self):
        provision = KubeProvisioner.kube_provisioner_factory(
            os_type=self.masters_leader.vm_attributes.os_type
        )
        leader_provisioner = provision(
            instance=self.masters_leader,
            control_plane=self.control_plane
        )
        if self.control_plane.ha_masters:
            join_provisioners = [
                provision(instance=master_node, control_plane=self.control_plane)
                for master_node in self.masters_joiners
            ]
            return leader_provisioner, join_provisioners
        return leader_provisioner, []

    def get_workers_provisioners(self):
        provision = KubeProvisioner.kube_provisioner_factory(
            os_type=self.masters_leader.vm_attributes.os_type
        )
        return {
            role: [
                provision(instance=worker, control_plane=self.control_plane)
                for worker in group
            ]
            for role, group in self.workers.items()
        }

    def execute_control_plane_lb(self):
        leader, joiners = self.get_master_provisioners()
        if not self.control_plane.ha_masters:
            logging.warning(
                crayons.yellow(f'Skip control plane loadbalancer install for non-HA masters.')
            )
            return True

        self.control_plane.apiserver_ip = leader.install_control_plane_loadbalancer(is_leader=True)
        if not self.control_plane.apiserver_ip:
            logging.error(
                crayons.red(f'Error during control plane generated virtual ip: {self.control_plane.apiserver_ip}')
            )
            return False

        for joiner in joiners:
            joiner.install_control_plane_loadbalancer(is_leader=False)
        return True

    def boostrap_control_plane(self):
        leader, joiners = self.get_master_provisioners()
        ready = self.execute_control_plane_lb()
        if not ready:
            logging.error(crayons.red('Abort bootstrapping control plane phase.'))
            return

        cert_key = leader.bootstrap_control_plane()
        if self.control_plane.ha_masters:
            for joiner in joiners:
                joiner.join_node(self.masters_leader, control_plane_node=True, certificate_key=cert_key)

    def rollback_control_plane(self):
        leader, joiners = self.get_master_provisioners()
        for joiner in joiners:
            joiner.rollback_node()
        self.sleep(duration=60, reason='Wait for Rollback to complete')
        leader.rollback_node()

    def join_workers(self):
        workers = self.get_workers_provisioners()
        for role, group in workers.items():
            for worker in group:
                worker.join_node(leader=self.masters_leader, control_plane_node=False)

    def rollback_workers(self):
        workers = self.get_workers_provisioners()
        for role, group in workers.items():
            for worker in group:
                worker.rollback_node()
        self.sleep(duration=60, reason='Wait for Rollback to complete')

    def post_installs(self):
        # TODO: Support loadbalancer arguments yaml file, version, interface, from .cluster.yml
        leader_executor = KubeExecutor(wrapper=self.masters_leader.self_node)
        leader_executor.add_local_cluster_config(
            custom_user_name=self.cluster_attributes.user,
            custom_cluster_name=self.cluster_attributes.name,
            custom_context=self.cluster_attributes.context,
            set_current_context=True
        )

        if self.cluster_attributes.dashboard:
            leader_executor.deploy_dashboard(local=False)

        for role, workers in self.workers.items():
            for worker in workers:
                leader_executor.apply_label_node(role=role, instance_name=worker.vm_attributes.name)

        # TODO: Determine patch value for helm_install_v2 from kube version.
        if self.cluster_attributes.helm.local or self.cluster_attributes.helm.tiller:
            if self.cluster_attributes.helm.version == HelmVersion.v2:
                leader_executor.helm_install_v2(
                    helm=self.cluster_attributes.helm.local,
                    tiller=self.cluster_attributes.helm.tiller
                )
            else:
                msg = f'Helm Version {self.cluster_attributes.helm.version.value} not supported yet.'
                logging.warning(crayons.yellow(msg))

        if self.cluster_attributes.loadbalancer:
            leader_executor.metallb_install()

        # TODO: Storage feature.

    def get_template_vms(self, preinstall=True):
        create = self.template_creation

        templates = {}
        template_attribute_list = self.get_vm_group(category=VMCategory.template)
        if not template_attribute_list:
            logging.error(crayons.red(f'Failed to generate templates from configuration.'))
            return {}

        for template_attributes in template_attribute_list:
            template_query = self.query_vms(template_attributes, template=True) if not create else None
            if template_query:
                templates[template_attributes.node] = self.query_template_by_name_or_vmid(
                    template_attributes=template_attributes,
                    template_query=template_query,
                    preinstall=preinstall
                )
            else:
                msg = (
                    f'Template create is false and template {template_attributes.name} was not found ' +
                    f'on node: {template_attributes.node}. Generating from config'
                )
                logging.warning(crayons.yellow(msg)) if not create else None
                if not template_attributes.name:
                    err = (
                        'Argument template.name is missing and template.create is true. '+
                        'Cannot create template with no name.'
                    )
                    logging.error(crayons.red(err))
                    return {}
                template = self.generate_template(template_attributes, preinstall=preinstall)
                templates[template_attributes.node] = template
        return templates

    def query_template_by_name_or_vmid(self, template_attributes, template_query, preinstall=True):
        id_prefix = get_id_prefix(proxmox_node_scale=settings.node_scale, node=template_attributes.node)
        template_vmid = int(f'{id_prefix}100') if preinstall else int(f'{id_prefix}000')
        if not template_attributes.name:
            warning = (
                f'Argument template.name is missing. ' +
                f'Searching for known template VMID {template_vmid} in Proxmox node {template_attributes.node}'
            )
            logging.warning(crayons.yellow(warning))
            valid_templates = [vm for vm in template_query if vm.vmid == template_vmid]
            return valid_templates[0] if valid_templates else self.generate_template(
                template_attributes, preinstall=preinstall
            )
        else:
            return template_query[0]

    def get_masters_vms(self, templates: dict, retrieve=False):
        """
        InstanceClone.vmid is pre-populated,
        to be filled with InstanceClone.generate_vmid_and_username(),
        dynamically at creation time (apply).
        Avoids multiple VMs to retrieve the same vmid, during initialization.
        Template matching for vm, per node is done, by self.get_vms() method.
        """
        disk = self.cluster_config.get(VMCategory.masters.value).get('disk')
        username = self.cluster_config.get(VMCategory.masters.value).get('username')
        masters_attributes = self.get_vm_group(category=VMCategory.masters)
        return self.get_vms(
            vm_attributes_list=masters_attributes,
            role=VMCategory.masters.value,
            templates=templates,
            disk=disk,
            vmid=VMID_PLACEHOLDER,
            username=username,
            query=retrieve
        )

    def get_workers_vms(self, templates: dict, retrieve=False):
        """
        InstanceClone.vmid is pre-populated,
        to be filled with InstanceClone.generate_vmid_and_username(),
        dynamically at creation time (apply).
        Avoids multiple VMs to retrieve the same vmid, during initialization.
        """
        worker_groups = self.get_vm_group(category=VMCategory.workers)
        if not worker_groups:
            logging.error(crayons.red('Empty "workers" groups entry in configuration.'))
            return {}

        workers = {}
        for role, vm_attributes in worker_groups.items():
            groups = self.cluster_config.get(VMCategory.workers.value)
            if role == 'default':
                targets = list(filter(lambda group: not group.get('role'), groups))
            else:
                targets = list(filter(lambda group: group.get('role') == role, groups))
            if len(targets) > 1:
                    logging.error(
                        crayons.red(f'Cannot allow duplicate role: "{role}", between "workers" groups ')
                    )
                    return {}
            if not targets:
                logging.error(crayons.red(f'Workers group with role: "{role}" not found.'))
                continue

            target = targets[0]
            disk = target.get('disk')
            username = target.get('username')
            workers[role] = self.get_vms(
                vm_attributes_list=vm_attributes,
                role=role,
                templates=templates,
                disk=disk,
                vmid=VMID_PLACEHOLDER,
                username=username,
                query=retrieve
            )
        return workers

    def query_vms(self, config: VMAttributes, template=False):
        try:
            query = VMQuery(
                client=settings.vm_client,
                name=config.name,
                pool=self.cluster_attributes.pool
            )
        except AttributeError as query_missing_name:
            logging.warning(f'Missing attribute {query_missing_name}')
            query = VMQuery(client=settings.vm_client, pool=self.cluster_attributes.pool)
        return query.execute(
            node=config.node,
            template=template
        )

    def get_vms(
            self,
            vm_attributes_list: list,
            role: str,
            templates: dict,
            disk: dict,
            vmid: int = None,
            username: str = None,
            query: bool = False
    ):
        hotplug_disk = disk.get('hotplug')
        hotplug_disk_size = disk.get('hotplug_size')
        if hotplug_disk and not hotplug_disk_size:
            logging.error(crayons.red(f'Hotplug disk enabled for VMS with role: {role} but no "hotplug_size" is provided.'))
            return []

        if not vm_attributes_list:
            logging.error(crayons.red(f'Failed to generate VM instances with role: {role} from configuration.'))
            return []

        vms = []
        for vm_attributes in vm_attributes_list:
            template = templates.get(vm_attributes.node)
            # Inherit template instance storage type.
            vm_attributes.storage_type = template.vm_attributes.storage_type
            if query:
                vm_attributes.name = vm_attributes.name.strip('-0')
                return self.query_vms(config=vm_attributes)
            clone = InstanceClone(
                vm_attributes=vm_attributes,
                client=settings.vm_client,
                template=template,
                vmid=vmid,
                username=username
            )
            if hotplug_disk:
                clone.hotplug_disk_size = hotplug_disk_size
            vms.append(clone) if clone else None
        return vms

    def get_vm_group(self, category: VMCategory):
        group = self.cluster_config.get(category.value)
        if category.value == 'template':
            return self.get_vm_attributes(group, template=True)
        if category.value == 'workers':
            workers = {}
            for instances in group:
                role = instances.get('role') or 'default'
                workers[role] = self.get_vm_attributes(instances)
            return workers
        return self.get_vm_attributes(group)

    def get_vm_attributes(self, group: dict, template=False):
        gateway = settings.pve_cluster_config_client.gateway
        name = group.get('name')
        scale = group.get('scale') if not template else None
        node = group.get('node')
        cpus = group.get('cpus')
        memory = group.get('memory')
        disk = group.get('disk')
        scsi = group.get('scsi') or False
        disk_size = disk.get('size') if disk else None

        if template:
            storage_type, image_storage_type = self.get_pve_storage(group, name)
            if not storage_type or not image_storage_type:
                return []

            nodes = node.split(',') if ',' in node else [node]
            templates = []

            for node_template in nodes:
                template_attributes = VMAttributes(
                    name=f'{node_template}-{name}' if name else None,
                    node=node_template,
                    pool=self.cluster_attributes.pool,
                    os_type=self.cluster_attributes.os_type,
                    storage_type=storage_type,
                    image_storage_type=image_storage_type,
                    scsi=scsi,
                    ssh_keyname=self.cluster_ssh_key,
                    gateway=gateway
                )
                if cpus:
                    template_attributes.cpus = cpus
                if memory:
                    template_attributes.memory = memory
                if disk_size:
                    template_attributes.disk_size = disk_size
                templates.append(template_attributes)
            return templates

        vm_group = []
        for vm_counter in range(scale):
            vm_group.append(
                VMAttributes(
                    name=f'{name}-{vm_counter}',
                    node=node,
                    pool=self.cluster_attributes.pool,
                    os_type=self.cluster_attributes.os_type,
                    cpus=cpus,
                    memory=memory,
                    disk_size=disk_size,
                    scsi=scsi,
                    ssh_keyname=self.cluster_ssh_key,
                    gateway=gateway
                )
            )
        return vm_group

    @staticmethod
    def get_pve_storage(group, name):
        pve_storage = group.get('pve_storage')
        storage_type = None
        image_storage_type = None
        try:
            storage_type = Storage.return_value(pve_storage.get('instance').get('type'))
            image_storage_type = Storage.return_value(pve_storage.get('image').get('type'))
        except AttributeError as attr_error:
            logging.error(crayons.red(attr_error))
        if not storage_type:
            logging.error(crayons.red(f'Template {name} has invalid instance storage type: {storage_type}'))
        if not image_storage_type:
            logging.error(crayons.red(f'Template {name} has invalid imagestorage type: {storage_type}'))
        return storage_type, image_storage_type
