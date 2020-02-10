import os
import subprocess
import inspect
import logging

import crayons

from konverge.pve import ProxmoxAPIClient
from konverge.pvecluster import ProxmoxClusterConfigFile, ClusterConfig
# from konverge.utils import FabricWrapper

BASE_PATH = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
WORKDIR = os.path.abspath(subprocess.check_output('pwd', universal_newlines=True).strip())

try:
    cluster_config = ProxmoxClusterConfigFile()
    cluster_config_client = ClusterConfig(cluster_config)
    node_scale = len(cluster_config_client.get_nodes())
except Exception as import_error:
    logging.error(crayons.red(import_error))

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
