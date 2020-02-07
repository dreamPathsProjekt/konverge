from konverge.settings import vm_client
from konverge.utils import VMAttributes, Storage, FabricWrapper
from konverge.cloudinit import CloudinitTemplate


def execute():
    proxmox_node = FabricWrapper(host='vhost3.proxmox')
    template_attributes = VMAttributes(
        name='ubuntu18-kubernetes-template',
        node='vhost3',
        pool='development',
        os_type='ubuntu',
        storage_type=Storage.nfs,
        image_storage_type=Storage.nfs,
        ssh_keyname='/home/dritsas/.ssh/vhost3-vms',
        gateway='10.0.100.105'
    )
    ubuntu_template_factory = CloudinitTemplate.os_type_factory(template_attributes.os_type)
    ubuntu_template = ubuntu_template_factory(vm_attributes=template_attributes, client=vm_client, proxmox_node=proxmox_node)
    ubuntu_template.execute()
    # ubuntu_template.destroy_vm()

    # Tested add and remove ssh config entries with local fabric object.

