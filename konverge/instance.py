import logging
import crayons

from konverge.pve import VMAPIClient
from konverge.mixins import CommonVMMixin, ExecuteStagesMixin
from konverge.utils import (
    VMAttributes,
    FabricWrapper
)
from konverge.cloudinit import CloudinitTemplate


class InstanceClone(CommonVMMixin, ExecuteStagesMixin):
    def __init__(
            self,
            vm_attributes: VMAttributes,
            client: VMAPIClient,
            template: CloudinitTemplate = None,
            proxmox_node: FabricWrapper = None,
            vmid=None,
            username=None,
            hotplug_disk_size: int = None
    ):
        self.vm_attributes = vm_attributes
        self.client = client
        self.template = template
        self.proxmox_node = proxmox_node if proxmox_node else FabricWrapper(host=vm_attributes.node)
        self.self_node = FabricWrapper(host=vm_attributes.name)

        if not vmid and not username:
            self.vmid, self.username = self.get_vmid_and_username()
        else:
            self.vmid, _ = (vmid, None) if vmid else self.get_vmid_and_username()
            _, self.username = (None, username) if username else self.get_vmid_and_username()
        self.vm_attributes.pool = self.client.get_or_create_pool(name=self.vm_attributes.pool)
        self.volume_type, self.driver = ('--scsi0', 'scsi0') if self.vm_attributes.scsi else ('--virtio0', 'virtio0')
        self.hotplug_disk_size = hotplug_disk_size
        self.allowed_ip = ''
        self.vm_attributes.os_type = self.template.vm_attributes.os_type if self.template else vm_attributes.os_type

        self._update_description()
        (
            self.storage,
            self.storage_details,
            self.location
        ) = self._get_storage_details()

    def _update_description(self):
        if self.template:
            self.vm_attributes.description = (
                f'Kubernetes node {self.vm_attributes.name} ' +
                f'generated from template vmid: {self.template.vmid} ,' +
                f'template name: {self.template.vm_attributes.name}'
            )
        elif self.vm_attributes.description:
            pass
        else:
            self.vm_attributes.description = f'Kubernetes node {self.vm_attributes.name}'

    def generate_vmid_and_username(self, id_prefix):
        start = int(f'{id_prefix}01')
        end = int(f'{id_prefix + 1}00')
        vmids = [vm.get('vmid') for vm in self.client.get_cluster_vms(node=self.vm_attributes.node)]
        allocated_ids = set(int(vmid) for vmid in vmids) if vmids else None

        username = self.template.username if self.template else 'ubuntu'
        for vmid in range(start, end):
            if vmid not in allocated_ids:
                return vmid, username
        return None, username

    def create_vm(self):
        """
        Override to clone VM from template
        """
        pool = self.client.get_or_create_pool(self.vm_attributes.pool)
        print(crayons.cyan(f'Resource pool: {pool}'))
        created = self.client.clone_vm_from_template(
            node=self.vm_attributes.node,
            source_vmid=self.template.vmid,
            target_vmid=self.vmid,
            name=self.vm_attributes.name,
            description=self.vm_attributes.description
        )
        if not self.log_create_delete(created):
            return created
        self.add_ssh_config_entry()
        return created

    def set_instance_resources(self):
        return self.client.update_vm_config(
            node=self.vm_attributes.node,
            vmid=self.vmid,
            memory=self.vm_attributes.memory,
            balloon=self.vm_attributes.memory,
            cores=self.vm_attributes.cpus
        )

    def set_instance_disk_size(self):
        if self.vm_attributes.disk_size < self.template.vm_attributes.disk_size:
            logging.warning(
                crayons.yellow(f'Warning: Requested disk size {self.vm_attributes.disk_size} is smaller than template size: {self.template.vm_attributes.disk_size}.') +
                crayons.yellow(f'Shrinking is not supported; reverting to default: {self.template.vm_attributes.disk_size}')
            )
            self.vm_attributes.disk_size = self.template.vm_attributes.disk_size
        if self.vm_attributes.disk_size != self.template.vm_attributes.disk_size:
            self.resize_disk()

    def execute(self, start=False, destroy=False):
        if destroy:
            self.stop_stage()
            self.destroy_vm()
            return self.vmid

        print(crayons.cyan(f'Stage: Create VM: {self.vm_attributes.name} {self.vmid} on node {self.vm_attributes.node}'))
        logging.warning(crayons.yellow(self.create_vm()))

        print(crayons.cyan(f'Stage: Update resource values for VM: {self.vm_attributes.name} {self.vmid} on node {self.vm_attributes.node}'))
        logging.warning(crayons.yellow(self.set_instance_resources()))

        print(crayons.cyan(f'Stage: Resize disk for VM: {self.vm_attributes.name} {self.vmid} to {self.vm_attributes.disk_size}'))
        self.set_instance_disk_size()
        self.inject_cloudinit_values()

        if self.hotplug_disk_size:
            print(crayons.cyan(f'Enable hotplug for VM: {self.vm_attributes.name} {self.vmid}'))
            self.enable_hotplug()
            print(crayons.cyan(f'Stage: Attach hotplug disk {self.hotplug_disk_size}G to VM: {self.vm_attributes.name} {self.vmid}'))
            self.attach_hotplug_drive(self.hotplug_disk_size)

        if start:
            print(crayons.cyan(f'Start requested - Starting VM: {self.vm_attributes.name} {self.vmid}'))
            self.start_stage()