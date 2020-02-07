from konverge.utils import VMAttributes, human_readable_disk_size
from konverge.settings import vm_client

VMID_SEARCH = '208'

# Templates all
# templates = [vm for vm in vm_client.get_cluster_vms(verbose=True) if vm.get('template') == 1]
# for template in templates:
#     print(template)
#     print(vm_client.get_vm_config(node=template.get('node'), vmid=template.get('vmid')))

# Queries PVE by vmid
vm = [vm for vm in vm_client.get_cluster_vms(verbose=True) if vm.get('vmid') == int(VMID_SEARCH)][0]
vmid, node, pool = vm.get('vmid'), vm.get('node'), vm.get('pool')
config = vm_client.get_vm_config(node=node, vmid=vmid)

ip_address, netmask, gateway = vm_client.get_ip_config_from_vm_cloudinit(node=node, vmid=vmid)

bootdisk = config.get('bootdisk')

print()
print()
vm_attrs = VMAttributes(
    name=config.get('name'),
    node=node,
    pool=pool,
    description=config.get('description'),
    cpus=config.get('cores'),
    scsi=('scsi0' in config.keys()),
    memory=config.get('memory'),
    storage_type=None,
    disk_size=human_readable_disk_size(vm.get('maxdisk'))[0],
    gateway=gateway,
    ssh_keyname=config.get('sshkeys')
)
