import os

from konverge.operations import ProxmoxAPIClient


client = ProxmoxAPIClient(
    host=os.getenv('PROXMOX_HOST'),
    user=os.getenv('PROXMOX_USER'),
    password=os.getenv('PROXMOX_PASSWORD')
)