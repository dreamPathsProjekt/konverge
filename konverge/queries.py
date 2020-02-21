from konverge.utils import (
    VMAttributes,
    human_readable_disk_size,
    Storage,
    get_id_prefix
)
from konverge.pve import VMAPIClient
from konverge.settings import node_scale
from konverge.cloudinit import CloudinitTemplate
from konverge.instance import InstanceClone


class VMQuery:
    def __init__(
            self,
            client: VMAPIClient,
            name=None,
            pool=None
    ):
        self.client = client
        self.name = name
        self.pool = pool
        self.all_vms = self.get_all_cluster_vms()

        self.is_template = lambda vm: vm.get('template') == 1
        self.match_node = lambda vm, node: vm.get('node') == node
        self.match_vmid = lambda vm, vmid: vm.get('vmid') == int(vmid)
        self.find_name = lambda vm: self.name in self.instance_name(vm)
        self.match_pool = lambda vm: self.pool == vm.get('pool')

    def instance_name(self, vm):
        config = self.client.get_vm_config(node=vm.get('node'), vmid=vm.get('vmid'))
        return config.get('name') if config else ''

    def get_storage_type_from_volume(self, config, driver='virtio0'):
        storage_name = config.get(driver).split(':')[0]
        storages = self.client.get_cluster_storage(verbose=True)
        for storage in storages:
            if storage.get('storage') == storage_name:
                return Storage.return_value(storage.get('type'))

    def get_all_cluster_vms(self):
        return [vm for vm in self.client.get_cluster_vms(verbose=True)]

    def filter_by_name_or_pool(self, instances):
        predicate = lambda vm: True
        if self.name:
            predicate = lambda vm: self.find_name(vm) and (self.match_pool(vm) if self.pool else True)
        if self.pool:
            predicate = lambda vm: self.match_pool(vm) and (self.find_name(vm) if self.name else True)
        return filter(predicate, instances)

    def filter_by_vmid_node_or_template(self, instances, node=None, vmid=None, template=False):
        predicate = lambda vm: True
        if template:
            predicate = lambda vm: self.is_template(vm) and (
                self.match_node(vm, node) if node else True and (
                    self.match_vmid(vm, vmid) if vmid else True
                )
            )
        if node:
            predicate = lambda vm: self.match_node(vm, node) and (
                self.is_template(vm) if template else True and (
                    self.match_vmid(vm, vmid) if vmid else True
                )
            )
        if vmid:
            predicate = lambda vm: self.match_vmid(vm, vmid) and (
                self.is_template(vm) if template else True and (
                    self.match_node(vm, node) if node else True
                )
            )
        return filter(predicate, instances)

    def serialize(self, filtered, template=False):
        if not filtered:
            return filtered

        vm_instances = []
        for vm_instance in filtered:
            (
                result_vmid,
                result_node,
                result_pool
            ) = vm_instance.get('vmid'), vm_instance.get('node'), vm_instance.get('pool')
            config = self.client.get_vm_config(node=result_node, vmid=result_vmid)
            if not config:
                continue
            ip_address, netmask, gateway = self.client.get_ip_config_from_vm_cloudinit(
                node=result_node,
                vmid=result_vmid
            )

            bootdisk = config.get('bootdisk')
            storage_type = self.get_storage_type_from_volume(config, driver=bootdisk)

            vm_attributes = VMAttributes(
                name=config.get('name'),
                node=result_node,
                pool=result_pool,
                description=config.get('description'),
                cpus=config.get('cores'),
                scsi=('scsi0' in config.keys()),
                memory=config.get('memory'),
                storage_type=storage_type,
                disk_size=human_readable_disk_size(vm_instance.get('maxdisk'))[0],
                gateway=gateway,
                ssh_keyname=config.get('sshkeys')
            )
            if template:
                vm_attributes.os_type = vm_attributes.description_os_type
                template_factory = CloudinitTemplate.os_type_factory(vm_attributes.os_type)
                template_instance = template_factory(
                    vm_attributes=vm_attributes,
                    client=self.client,
                    vmid=result_vmid
                )
                id_prefix = get_id_prefix(proxmox_node_scale=node_scale, node=vm_attributes.node)
                id_suffix = '0' if template_instance.vm_attributes.os_type == 'ubuntu' else '1'
                template_instance.preinstall = int(f'{id_prefix}10{id_suffix}') == template_instance.vmid
                template_instance.allowed_ip = ip_address
                vm_instances.append(template_instance)
            else:
                instance_clone = InstanceClone(
                    vm_attributes=vm_attributes,
                    client=self.client,
                    vmid=result_vmid,
                )
                instance_clone.allowed_ip = ip_address
                vm_instances.append(instance_clone)
        return vm_instances

    def update_instance_template(self, instance: InstanceClone, node=None, vmid=None):
        templates = self.serialize(
            self.filter_by_vmid_node_or_template(
                self.all_vms,
                template=True,
                node=node,
                vmid=vmid
            ),
            template=True
        )
        for template in templates:
            if template.vm_attributes.name in instance.vm_attributes.description or (
                str(template.vmid) in instance.vm_attributes.description
            ):
                instance.template = template
                instance.username = template.username
                instance.vm_attributes.os_type = template.vm_attributes.os_type
        return instance

    def execute(self, node=None, vmid=None, template=False):
        filtered_clones = self.filter_by_vmid_node_or_template(
            self.filter_by_name_or_pool(self.all_vms),
            node=node,
            vmid=vmid,
            template=template
        )
        instances = self.serialize(filtered_clones)
        for instance in instances:
            self.update_instance_template(instance, node=node)
        return instances
