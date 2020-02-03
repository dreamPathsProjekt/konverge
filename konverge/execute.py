import os

from .operations import ProxmoxAPIClient


def execute():
    client = ProxmoxAPIClient(
        host=os.getenv('PROXMOX_HOST'),
        user=os.getenv('PROXMOX_USER'),
        password=os.getenv('PROXMOX_PASSWORD')
    )
    print(client.get_cluster_vms())
