from konverge.utils import VMAttributes, human_readable_disk_size, Storage
from konverge.settings import vm_client
from konverge.instance import InstanceClone


def get_storage_type_from_volume(config, driver='virtio0'):
    storage_name = config.get(driver).split(':')[0]
    storages = vm_client.get_cluster_storage(verbose=True)
    for storage in storages:
        if storage.get('storage') == storage_name:
            return Storage.return_value(storage.get('type'))


def get_cluster_vms(node=None, vmid=None, template=False):
    vm_instances = []
    vms = [vm for vm in vm_client.get_cluster_vms(verbose=True)]

    is_template = lambda vm: vm.get('template') == 1
    match_node = lambda vm: vm.get('node') == node
    match_vmid = lambda vm: vm.get('vmid') == int(vmid)

    predicate = lambda: True
    if template:
        predicate = lambda vm: is_template(vm) and match_node(vm) if node else True and match_vmid(vm) if vmid else True
    if node:
        predicate = lambda vm: match_node(vm) and is_template(vm) if template else True and match_vmid(vm) if vmid else True
    if vmid:
        predicate = lambda vm: match_vmid(vm) and is_template(vm) if template else True and match_node(vm) if node else True
    filtered = list(filter(predicate, vms))

    if not filtered:
        return filtered

    for vm_instance in filtered:
        result_vmid, result_node, result_pool = vm_instance.get('vmid'), vm_instance.get('node'), vm_instance.get('pool')
        config = vm_client.get_vm_config(node=result_node, vmid=result_vmid)
        ip_address, netmask, gateway = vm_client.get_ip_config_from_vm_cloudinit(node=result_node, vmid=result_vmid)

        bootdisk = config.get('bootdisk')
        storage_type = get_storage_type_from_volume(config, driver=bootdisk)

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

        vm_instances.append(
            {
                'instance': InstanceClone(
                    vm_attributes=vm_attributes,
                    client=vm_client,
                    vmid=result_vmid,
                    username='ubuntu'
                ),
                'ip_address': ip_address
            }
        )
    return vm_instances