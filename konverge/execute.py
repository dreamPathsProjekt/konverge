from konverge.settings import vm_client
from konverge.utils import VMAttributes, Storage, FabricWrapper
from konverge.cloudinit import CloudinitTemplate
from konverge.instance import InstanceClone
from konverge.queries import VMQuery

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
    # ubuntu_template.execute(destroy=True)
    # Tested add and remove ssh config entries with local fabric object.

    query = VMQuery(client=vm_client, name='po')
    for instance in query.execute(node='vhost2'):
        print(vars(instance))
        # print(instance.generate_allowed_ip())

        # Needs agent installed
        # print(instance.client.agent_get_interfaces(node=instance.vm_attributes.node, vmid=instance.vmid))

        # print(vars(instance.vm_attributes))
        # print(instance.execute(destroy=True))
        # print(instance.backup_export(storage=Storage.nfs))

    # Create clones
    # clone_attributes = VMAttributes(
    #     name='test-cluster-0',
    #     node='vhost3',
    #     pool='development',
    #     os_type='ubuntu',
    #     storage_type=Storage.nfs,
    #     disk_size=10,
    #     ssh_keyname='/home/dritsas/.ssh/vhost3-vms',
    #     gateway='10.0.100.105'
    # )
    #
    # instance_clone = InstanceClone(
    #     vm_attributes=clone_attributes,
    #     client=vm_client,
    #     proxmox_node=proxmox_node,
    #     template=ubuntu_template,
    #     hotplug_disk_size=10
    # )
    # instance_clone.execute(start=True)