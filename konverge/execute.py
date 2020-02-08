from konverge.settings import vm_client
from konverge.utils import VMAttributes, Storage, FabricWrapper
from konverge.cloudinit import CloudinitTemplate
# from konverge.instance import InstanceClone
from konverge.queries import get_cluster_vms

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

    # Create Template with preinstall
    # ubuntu_template.execute()
    # ubuntu_template.destroy_vm()

    # Tested add and remove ssh config entries with local fabric object.

    for instance in get_cluster_vms(node='vhost3', template=True):
        print(vars(instance.get('instance')))
        print(instance.get('ip_address'))
    # Create clones
    # print(ubuntu_template.client.get_cluster_vms(node='vhost3'))
    # print(ubuntu_template.get_unallocated_disk_slots())
    # instance_clone = InstanceClone(
    #     vm_attributes=template_attributes,
    #     client=vm_client,
    #     proxmox_node=proxmox_node,
    #     template=ubuntu_template
    # )

    # ubuntu_template.inject_cloudinit_values(invalidate=True)