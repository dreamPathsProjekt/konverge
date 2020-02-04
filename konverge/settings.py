import os

from konverge.pve import ProxmoxAPIClient
# from konverge.utils import FabricWrapper


VMFactory = ProxmoxAPIClient.api_client_factory(instance_type='vm')
vm_client = VMFactory(
    host=os.getenv('PROXMOX_HOST'),
    user=os.getenv('PROXMOX_USER'),
    password=os.getenv('PROXMOX_PASSWORD')
)
