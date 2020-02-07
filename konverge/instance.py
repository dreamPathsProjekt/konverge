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
            username=None
    ):
        self.vm_attributes = vm_attributes
        self.client = client
        self.template = template
        self.proxmox_node = proxmox_node if proxmox_node else FabricWrapper(host=vm_attributes.node)
        self.self_node = FabricWrapper(host=vm_attributes.name)

        self.vmid, _ = vmid, None if vmid else self.get_vmid_and_username()
        _, self.username = None, username if username else self.get_vmid_and_username()
        self.pool = self.client.get_or_create_pool(name=self.vm_attributes.pool)
        self.allowed_ip = ''

        (
            self.storage,
            self.storage_details,
            self.location
        ) = self._get_storage_details()

    def _update_description(self):
        if self.template:
            self.vm_attributes.description = f'Kubernetes node {self.vm_attributes.name} generated from template: {self.template.vm_attributes.name}'
        elif self.vm_attributes.description:
            pass
        else:
            self.vm_attributes.description = f'Kubernetes node {self.vm_attributes.name}'

    def generate_vmid_and_username(self, id_prefix):
        start = int(f'{id_prefix}01')
        end = int(f'{id_prefix + 1}00')
        vmids = [vm.get('vmid') for vm in self.client.get_cluster_vms(node=self.vm_attributes.node)]
        allocated_ids = set(int(vmid) for vmid in vmids) if vmids else None

        for vmid in range(start, end):
            if vmid not in allocated_ids:
                return str(vmid), self.template.username

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