import os
import subprocess
import inspect
import logging

import crayons

from konverge.pve import ProxmoxAPIClient
from konverge.pvecluster import ProxmoxClusterConfigFile, ClusterConfig
from konverge.kubecluster import KubeClusterConfigFile, KubeCluster


BASE_PATH = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
WORKDIR = os.path.abspath(subprocess.check_output('pwd', universal_newlines=True).strip())

CNI = {
    'flannel': 'https://raw.githubusercontent.com/coreos/flannel/2140ac876ef134e0ed5af15c65e414cf26827915/Documentation/kube-flannel.yml',
    'calico': 'https://docs.projectcalico.org/v3.9/manifests/calico.yaml',
    'weave': "\"https://cloud.weave.works/k8s/net?k8s-version=$(kubectl version | base64 | tr -d '\n')&env.NO_MASQ_LOCAL=1\"",
    'weave-default': "\"https://cloud.weave.works/k8s/net?k8s-version=$(kubectl version | base64 | tr -d '\n')\""
}

KUBE_DASHBOARD_URL = 'https://raw.githubusercontent.com/kubernetes/dashboard/v2.0.0-beta4/aio/deploy/recommended.yaml'


try:
    # TODO read from file if provided
    cluster_config = ProxmoxClusterConfigFile()
    cluster_config_client = ClusterConfig(cluster_config)
    kube_config = KubeClusterConfigFile()
    kube_config_client = KubeCluster(kube_config)
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
