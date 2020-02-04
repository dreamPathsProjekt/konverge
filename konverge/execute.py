from konverge.settings import client
from konverge.utils import VMAttributes, Storage, FabricWrapper
from konverge.templates import (
    CloudinitTemplate
)


def execute():

    # print(client.get_cluster_vms(node='vhost2', verbose=True))
    # id_prefix = get_template_id_prefix(scale=3, node='vhost2')
    # print(get_template_vmid_from_os_type(id_prefix, os_type='ubuntu'))
    proxmox_node = FabricWrapper(host='vhost3.proxmox')
    template_attributes = VMAttributes(
        name='test-template',
        node='vhost3',
        pool='utils',
        storage_type=Storage.nfs
    )
    ubuntu_template_factory = CloudinitTemplate.os_type_factory(template_attributes.os_type)
    ubuntu_template = ubuntu_template_factory(vm_attributes=template_attributes, client=client, proxmox_node=proxmox_node)
    # print(ubuntu_template.vm_attributes.description)
    print(ubuntu_template.download_cloudinit_image())
    # print(ubuntu_template.get_storage_from_config(vmid='3000'))
    # print(client.get_storage_content_items('vhost', type='nfs'))
    # print(client.get_cluster_node_interfaces())
    # print(client.get_cluster_node_dns('vhost2'))

