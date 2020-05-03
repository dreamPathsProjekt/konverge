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
    get_id_prefix
)
from konverge import output
from konverge.kube import ControlPlaneDefinitions, KubeExecutor
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
    storage: KubeStorage = None
    loadbalancer: bool = True
    version: str = None
    docker: str = None
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
        self.retrieve() if self.cluster_exists() else self.initialize()

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
        storage = KubeStorage.return_value(self.cluster_config.get('storage'))
        loadbalancer = self.cluster_config.get('loadbalancer') or True

        versions = self.cluster_config.get('versions')
        docker = None
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
            storage=storage,
            loadbalancer=loadbalancer,
            version=version,
            docker=docker,
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
    def generate_template(template_attributes: VMAttributes):
        factory = CloudinitTemplate.os_type_factory(template_attributes.os_type)
        return factory(vm_attributes=template_attributes, client=settings.vm_client)

    def cluster_exists(self):
        kube_executor = KubeExecutor()
        if kube_executor.cluster_exists(self):
            logging.warning(crayons.yellow(f'Cluster {self.cluster_attributes.name} exists.'))
            return True
        return False

    def initialize(self):
        print(crayons.cyan(f'Getting initial requirements for cluster: {self.cluster_attributes.name}'))
        templates = self.get_template_vms()
        if self.vms_response_is_empty(templates, category=VMCategory.template):
            return

        self.template = templates
        masters = self.get_masters_vms(self.template)
        workers = self.get_workers_vms(self.template)
        if not self.vms_response_is_empty(masters, category=VMCategory.masters):
            self.masters = masters
        if not self.vms_response_is_empty(workers, category=VMCategory.workers):
            self.workers = workers
        print(crayons.green(f'Cluster: {self.cluster_attributes.name} initialized.'))

    def retrieve(self):
        # TODO: Query vms if cluster exists.
        pass

    def update(self):
        pass

    def show(self, action: KubeClusterAction = KubeClusterAction.create):
        output.output_cluster(self)
        output.output_config(self)
        output.output_control_plane(self)
        output.output_templates(self, action=action)
        # TODO: Implement master, worker groups & helm/storage/loadbalancer outputs.

    def plan(self):
        if not self.cluster_exists():
            self.show(action=KubeClusterAction.create)
            return
        logging.warning(crayons.yellow('Cluster update not implemented yet.'))

    def apply(self):
        pass

    def delete(self):
        pass

    def get_template_vms(self, preinstall=True):
        # TODO: Support preinstall option as argument, on other calling methods & generation.
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
                template = self.generate_template(template_attributes)
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
            return valid_templates[0] if valid_templates else self.generate_template(template_attributes)
        else:
            return template_query[0]

    def get_masters_vms(self, templates: dict):
        """
        InstanceClone.vmid is pre-populated,
        to be filled with InstanceClone.generate_vmid_and_username(),
        dynamically at creation time (apply).
        Avoids multiple VMs to retrieve the same vmid, during initialization.
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
            username=username
        )

    def get_workers_vms(self, templates: dict):
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
                username=username
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

    @staticmethod
    def get_vms(
            vm_attributes_list: list,
            role: str,
            templates: dict,
            disk: dict,
            vmid: int = None,
            username: str = None
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
            clone = InstanceClone(
                vm_attributes=vm_attributes,
                client=settings.vm_client,
                template=template,
                vmid=vmid,
                username=username
            )
            if hotplug_disk:
                clone.hotplug_disk_size = hotplug_disk_size
            vms.append(clone)
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
