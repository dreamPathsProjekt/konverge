import os

from .operations import ProxmoxAPIClient
from .utils import get_template_id_prefix, get_template_vmid_from_os_type


def execute():
    client = ProxmoxAPIClient(
        host=os.getenv('PROXMOX_HOST'),
        user=os.getenv('PROXMOX_USER'),
        password=os.getenv('PROXMOX_PASSWORD')
    )
    # print(client.get_cluster_vms())
    # id_prefix = get_template_id_prefix(scale=3, node='vhost2')
    # print(get_template_vmid_from_os_type(id_prefix, os_type='ubuntu'))
    print(client.get_or_create_pool('test'))
    print(client.get_cluster_node_interfaces())