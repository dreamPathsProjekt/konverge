import os

from konverge.pve import ProxmoxAPIClient
# from konverge.utils import FabricWrapper


VMAPIClientFactory = ProxmoxAPIClient.api_client_factory(instance_type='vm')
vm_client = VMAPIClientFactory(
    host=os.getenv('PROXMOX_HOST'),
    user=os.getenv('PROXMOX_USER'),
    password=os.getenv('PROXMOX_PASSWORD')
)


LXCAPIClientFactory = ProxmoxAPIClient.api_client_factory(instance_type='lxc')
lxc_client = LXCAPIClientFactory(
    host=os.getenv('PROXMOX_HOST'),
    user=os.getenv('PROXMOX_USER'),
    password=os.getenv('PROXMOX_PASSWORD')
)
