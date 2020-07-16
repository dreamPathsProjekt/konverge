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
            pool=None,
            node=None,
            vmid=None
    ):
        self.client = client
        self.name = name
        self.pool = pool
        self.node = node
        self.vmid = vmid

        self.is_template = lambda vm: vm.get('template') == 1
        self.is_instance = lambda vm: not self.is_template(vm)
        self.find_name = lambda vm: self.name in self.reverse_name_from_vmid(vm)
        self.match_pool = lambda vm: self.pool == vm.get('pool')

    @property
    def all_vms(self):
        all_instances = [vm for vm in self.client.get_cluster_vms(node=self.node, verbose=True)]
        templates = filter(self.is_template, all_instances)
        instances = filter(self.is_instance, all_instances)
        return {
            'templates': list(templates),
            'instances': list(instances)
        }

    @staticmethod
    def reverse_name_from_vmid(vm: dict):
        return vm.get('name')

    def reverse_vm(self, vm: dict):
        """
        Proxmox api only returns fields node, pool when queried without them.
        """
        vmid = self.vmid if self.vmid else vm.get('vmid')
        node = self.node if self.node else vm.get('node')
        pool = self.pool if self.pool else vm.get('pool')
        return vmid, node, pool

    def get_storage_type_from_volume(self, config, driver='virtio0'):
        storage_name = config.get(driver).split(':')[0]
        storages = self.client.get_cluster_storage(verbose=True)
        for storage in storages:
            if storage.get('storage') == storage_name:
                return Storage.return_value(storage.get('type'))

    def get_vm(self, template=False):
        vms = self.all_vms.get('templates') if template else self.all_vms.get('instances')
        for vm in vms:
            if int(vm.get('vmid')) == int(self.vmid):
                return vm

    def filter_vms_by_name(self):
        if not self.name:
            return self.all_vms

        templates = filter(self.find_name, self.all_vms.get('templates'))
        instances = filter(self.find_name, self.all_vms.get('instances'))
        return {
            'templates': list(templates),
            'instances': list(instances)
        }

    def filter_vms_by_pool(self):
        if not self.pool:
            return self.all_vms

        vms = self.client.get_pool_members(poolid=self.pool)
        templates = filter(self.is_template, vms)
        instances = filter(self.is_instance, vms)
        return {
            'templates': list(templates),
            'instances': list(instances)
        }

    def serialize(self, vm: dict, template=False):
        vmid, node, pool = self.reverse_vm(vm=vm)
        vm_config = self.client.get_vm_config(node=node, vmid=vmid)
        if not vm_config:
            return None

        ip_address, netmask, gateway = self.client.get_ip_config_from_vm_cloudinit(
            node=node,
            vmid=int(vmid)
        )
        bootdisk = vm_config.get('bootdisk')
        storage_type = self.get_storage_type_from_volume(vm_config, driver=bootdisk)

        vm_attributes = VMAttributes(
            name=vm_config.get('name'),
            node=node,
            pool=pool,
            description=vm_config.get('description'),
            cpus=vm_config.get('cores'),
            scsi=('scsi0' in vm_config.keys()),
            memory=vm_config.get('memory'),
            storage_type=storage_type,
            disk_size=human_readable_disk_size(vm.get('maxdisk'))[0],
            gateway=gateway,
            ssh_keyname=vm_config.get('sshkeys')
        )
        if template:
            vm_attributes.os_type = vm_attributes.description_os_type
            template_factory = CloudinitTemplate.os_type_factory(vm_attributes.os_type)
            template_instance = template_factory(
                vm_attributes=vm_attributes,
                client=self.client,
                vmid=vmid
            )
            id_prefix = get_id_prefix(proxmox_node_scale=node_scale, node=vm_attributes.node)
            id_suffix = '0' if template_instance.vm_attributes.os_type == 'ubuntu' else '1'
            template_instance.preinstall = int(f'{id_prefix}10{id_suffix}') == template_instance.vmid
            template_instance.allowed_ip = ip_address
            return template_instance
        instance_clone = InstanceClone(
            vm_attributes=vm_attributes,
            client=self.client,
            vmid=vmid,
        )
        instance_clone.allowed_ip = ip_address
        return instance_clone

    def update_instance_template(self, instance: InstanceClone):
        if not self.node:
            filter_templates_per_node = lambda tmpl: tmpl.get('node') == instance.vm_attributes.node
            templates = list(filter(filter_templates_per_node, self.all_vms.get('templates')))
        else:
            templates = self.all_vms.get('templates')

        for template in templates:
            node, pool, vmid = self.reverse_vm(template)
            name = template.get('name')
            if name in instance.vm_attributes.description or (
                str(vmid) in instance.vm_attributes.description
            ):
                cloudinit_template = self.serialize(vm=template, template=True)
                instance.template = cloudinit_template
                instance.username = cloudinit_template.username
                instance.vm_attributes.os_type = cloudinit_template.vm_attributes.os_type
        return instance

    def process_to_instances(self, vms: dict, template=False):
        vms = vms.get('templates') if template else vms.get('instances')
        if not vms:
            return vms
        instances = [self.serialize(vm=vm, template=template) for vm in vms]
        if not template:
            [self.update_instance_template(instance=instance) for instance in instances]
        return instances

    def execute(self, template=False):
        if self.vmid:
            instance = self.serialize(vm=self.get_vm(template=template), template=template)
            if not template:
                self.update_instance_template(instance=instance)
            return instance

        if self.name:
            vms = self.filter_vms_by_name()
            return self.process_to_instances(vms=vms, template=template)

        if self.pool:
            vms = self.filter_vms_by_pool()
            return self.process_to_instances(vms=vms, template=template)

