import os

from konverge.pve import ProxmoxAPIClient
# from konverge.utils import FabricWrapper


client = ProxmoxAPIClient(
    host=os.getenv('PROXMOX_HOST'),
    user=os.getenv('PROXMOX_USER'),
    password=os.getenv('PROXMOX_PASSWORD')
)
