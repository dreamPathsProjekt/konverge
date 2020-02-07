import os
import inspect

from konverge.pve import ProxmoxAPIClient
from konverge.pvecluster import ProxmoxClusterConfigFile, ClusterConfig
# from konverge.utils import FabricWrapper

BASE_PATH = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))

cluster_config = ProxmoxClusterConfigFile()
cluster_config_client = ClusterConfig(cluster_config)

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
