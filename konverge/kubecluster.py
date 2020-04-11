import logging
import crayons
from typing import NamedTuple

from konverge import settings
from konverge.utils import KubeStorage, HelmVersion, VMCategory, VMAttributes, Storage
from konverge.kube import ControlPlaneDefinitions
from konverge.cloudinit import CloudinitTemplate
from konverge.instance import InstanceClone


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
    helm: HelmAtrributes = HelmAtrributes()


class KubeCluster:
    def __init__(self, cluster_config: dict):
        self.cluster_config = cluster_config
        self.control_plane = self._serialize_control_plane()
        self.cluster_attributes = self._serialize_cluster_attributes()
        self.cluster_ssh_key = self.cluster_config.get('ssh_key')

    def _serialize_cluster_attributes(self):
        os_type = self.cluster_config.get('os_type') or 'ubuntu'
        user = self.cluster_config.get('user')
        context = self.cluster_config.get('context')
        storage = KubeStorage.return_value(self.cluster_config.get('storage'))
        loadbalancer = self.cluster_config.get('loadbalancer') or True

        helm_attributes = self.cluster_config.get('helm')
        if not helm_attributes:
            helm = HelmAtrributes()
        else:
            version = HelmVersion.return_value(helm_attributes.get('version')) or HelmVersion.v2
            local = helm_attributes.get('local') or False
            tiller = helm_attributes.get('tiller') or True
            helm = HelmAtrributes(
                version=version,
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

    def get_cluster(self):
        templates = self.get_template_vms()
        masters = self.get_masters_vms(templates)
        workers = self.get_workers_vms(templates)

        # Debug only & during execute/plan
        for key, value in templates.items():
            if key == 'create':
                print(crayons.cyan(key))
                print(value)
            else:
                print(crayons.cyan(key))
                print(crayons.yellow(value.vm_attributes.name))
                print(crayons.green(value.vm_attributes.description))
                print(vars(value))
                print(value.proxmox_node.connection.original_host)

        for master in masters:
            print(crayons.yellow(master.vm_attributes.name))
            print(crayons.green(master.vm_attributes.description))
            print(vars(master))

        for key, value in workers.items():
            print(crayons.cyan(key))
            for vm in value:
                print(crayons.yellow(vm.vm_attributes.name))
                print(crayons.green(vm.vm_attributes.description))
                print(vars(vm))

    def get_template_vms(self):
        # TODO: Support preinstall option as argument
        create = self.cluster_config.get(VMCategory.template.value).get('create')
        if create is None:
            create = True

        templates = {}
        template_attribute_list = self.get_vm_group(category=VMCategory.template)
        if not template_attribute_list:
            logging.error(crayons.red(f'Failed to generate templates from configuration.'))
            return {}
        for template_attributes in template_attribute_list:
            factory = CloudinitTemplate.os_type_factory(template_attributes.os_type)
            templates[template_attributes.node] = factory(vm_attributes=template_attributes, client=settings.vm_client)
            templates['create'] = create
        return templates

    def get_masters_vms(self, templates: dict):
        disk = self.cluster_config.get(VMCategory.masters.value).get('disk')
        username = self.cluster_config.get(VMCategory.masters.value).get('username')
        masters_attributes = self.get_vm_group(category=VMCategory.masters)
        return self.get_vms(
            vm_attributes_list=masters_attributes,
            role=VMCategory.masters.value,
            templates=templates,
            disk=disk,
            username=username
        )

    def get_workers_vms(self, templates: dict):
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
                username=username
            )
        return workers

    @staticmethod
    def get_vms(vm_attributes_list: list, role: str, templates: dict, disk: dict, username: str = None):
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
            clone = InstanceClone(
                vm_attributes=vm_attributes,
                client=settings.vm_client,
                template=templates.get(vm_attributes.node),
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
        gateway = settings.cluster_config_client.gateway
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
                    name=f'{node_template}-{name}',
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
