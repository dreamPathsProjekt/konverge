import os
import subprocess
import inspect
import logging

import crayons

from konverge.pve import ProxmoxAPIClient
from konverge.pvecluster import ProxmoxClusterConfigFile, PVEClusterConfig
from konverge.files import KubeClusterConfigFile


BASE_PATH = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
WORKDIR = os.path.abspath(subprocess.check_output('pwd', universal_newlines=True).strip())
HOME_DIR = os.path.expanduser('~')

CNI = {
    'flannel': 'https://raw.githubusercontent.com/coreos/flannel/2140ac876ef134e0ed5af15c65e414cf26827915/Documentation/kube-flannel.yml',
    'calico': 'https://docs.projectcalico.org/v3.9/manifests/calico.yaml',
    'weave': "\"https://cloud.weave.works/k8s/net?k8s-version=$(kubectl version | base64 | tr -d '\n')&env.NO_MASQ_LOCAL=1\"",
    'weave-default': "\"https://cloud.weave.works/k8s/net?k8s-version=$(kubectl version | base64 | tr -d '\n')\""
}

KUBE_DASHBOARD_URL = 'https://raw.githubusercontent.com/kubernetes/dashboard/v2.0.0-beta4/aio/deploy/recommended.yaml'

VMID_PLACEHOLDER = 9999
allocated_vmids = set()

def cluster_config_factory(filename=None, config_type='pve'):
    cluster_type = {
        'pve': ProxmoxClusterConfigFile,
        'kube': KubeClusterConfigFile
    }
    factory = cluster_type.get(config_type)
    if filename and os.path.exists(os.path.join(WORKDIR, filename)):
        return factory(filename)
    return factory()


PVE_FILENAME = os.getenv('PVE_FILENAME')
KUBE_FILENAME = os.getenv('KUBE_FILENAME')

try:
    pve_cluster_config = cluster_config_factory(filename=PVE_FILENAME, config_type='pve')
    pve_cluster_config_client = PVEClusterConfig(pve_cluster_config)
    kube_config = cluster_config_factory(filename=KUBE_FILENAME, config_type='kube')
    node_scale = len(pve_cluster_config_client.get_nodes())
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
