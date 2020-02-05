import os
import crayons

from konverge.pve import VMAPIClient
from konverge.utils import (
    VMAttributes,
    FabricWrapper,
    BootMedia,
    get_id_prefix
)


class CommonVMMixin:
    """
    Mixin class attributes only declared as types.
    No instantiation of attributes on class level.
    """
    vm_attributes: VMAttributes
    client: VMAPIClient
    proxmox_node: FabricWrapper
    vmid: str
    driver: str
    unused_driver: str
    storage: str

    def _update_description(self):
        self.vm_attributes.description = ''

    def _get_storage_details(self):
        storage_details = self.client.get_storage_detail_path_content(storage_type=self.vm_attributes.storage_type)
        directory = 'images' if 'images' in storage_details.get('content') else ''
        location = os.path.join(storage_details.get('path'), directory)
        storage = storage_details.get('name')
        return storage, storage_details, location

    def generate_vmid(self, id_prefix):
        raise NotImplementedError

    def get_vmid_and_username(self):
        id_prefix = get_id_prefix(scale=1, node=self.vm_attributes.node)
        return self.generate_vmid(id_prefix=id_prefix)

    def get_vm_config(self):
        return self.client.get_vm_config(node=self.vm_attributes.node, vmid=self.vmid)

    def get_storage_from_config(self, driver):
        config = self.get_vm_config()
        volume = config.get(driver) if config else None
        return volume.split(',')[0].strip() if volume else None

    def get_storage(self, unused=False):
        driver = self.unused_driver if unused else self.driver
        return self.get_storage_from_config(driver)

    def get_allocated_ips_per_node_interface(self):
        interfaces = self.client.get_cluster_node_bridge_interfaces(self.vm_attributes.node)
        bridges = [
            (
                interface.get('name'),
                interface.get('cidr')
            )
            for interface in interfaces
            if interface.get('cidr') and interface.get('address')
        ]
        allocated_set = set()
        for bridge in bridges:
            interface, cidr = bridge
            arp_scan_exists = self.proxmox_node.execute('command arp-scan --help; echo $?', hide=True)
            exit_code = arp_scan_exists.stdout.split()[-1].strip()
            if exit_code != '0':
                print(crayons.cyan('arp-scan not found. Installing.'))
                self.proxmox_node.execute('apt-get install -y arp-scan')
            awk_routine = "'{print $1}'"
            ips = self.proxmox_node.execute(
                f'arp-scan --interface={interface} {cidr} | awk {awk_routine}', hide=False
            ).stdout.split()[2:-2]
            [allocated_set.add(ip) for ip in ips]
        print(crayons.white(f'Allocated: {allocated_set}'))
        return allocated_set

    def create_vm(self):
        return self.client.create_vm(
            vm_attributes=self.vm_attributes,
            vmid=self.vmid
        )
    def attach_volume_to_vm(self, volume):
        return self.client.attach_volume_to_vm(
            node=self.vm_attributes.node,
            vmid=self.vmid,
            scsi=self.vm_attributes.scsi,
            volume=volume,
            disk_size=self.vm_attributes.disk_size
        )

    def add_cloudinit_drive(self, drive_slot='2'):
        return self.client.add_cloudinit_drive(
            node=self.vm_attributes.node,
            vmid=self.vmid,
            storage_name=self.storage,
            drive_slot=drive_slot
        )

    def set_boot_disk(self):
        return self.client.set_boot_disk(
            node=self.vm_attributes.node,
            vmid=self.vmid,
            boot=BootMedia.hard_disk,
            driver=self.driver
        )

    def resize_disk(self):
        self.client.resize_disk(
            node=self.vm_attributes.node,
            vmid=self.vmid,
            driver=self.driver,
            disk_size=self.vm_attributes.disk_size
        )

    def set_vga_display(self):
        """
        Set VGA display. Many Cloud-Init images rely on this, as it is an requirement for OpenStack images.
        """
        self.client.update_vm_config(
            node=self.vm_attributes.node,
            vmid=self.vmid,
            storage_operation=False,
            serial0='socket',
            vga='serial0'
        )

    def start_vm(self):
        return self.client.start_vm(
            node=self.vm_attributes.node,
            vmid=self.vmid
        )

    def stop_vm(self):
        return self.client.stop_vm(
            node=self.vm_attributes.node,
            vmid=self.vmid
        )

    def export_template(self):
        self.client.export_vm_template(
            node=self.vm_attributes.node,
            vmid=self.vmid
        )

    def inject_cloudinit_values(self):
        self.client.inject_vm_cloudinit(
            node=self.vm_attributes.node,
            vmid=self.vmid,
            ssh_keyname=self.vm_attributes.public_ssh_key,
            vm_ip='',
            gateway=self.vm_attributes.gateway
        )
