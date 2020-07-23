import os
import subprocess
import inspect
import logging
import json

import crayons

from proxmoxer.backends import https
from requests.exceptions import SSLError

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


def write_pve_credentials(host: str, user: str, password: str, backend='https', verify_ssl=False):
    creds = {
        'host': host,
        'user': user,
        'password': password,
        'backend': backend,
        'verify_ssl': verify_ssl
    }
    location = os.path.join(HOME_DIR, '.konverge')
    filename = os.path.join(location, 'credentials.json')
    try:
        if not os.path.exists(location):
            os.mkdir(location)
        with open(filename, mode='w') as creds_file:
            json.dump(creds, creds_file)
    except Exception as error:
        logging.error(crayons.red(error))


def read_pve_credentials():
    location = os.path.join(HOME_DIR, '.konverge')
    filename = os.path.join(location, 'credentials.json')
    try:
        if not os.path.exists(location):
            logging.error(crayons.red(f'Credentials file {filename} missing.'))
            return {}
        with open(filename, mode='r') as creds_file:
            return json.load(creds_file)
    except Exception as error:
        logging.error(crayons.red(error))
        return {}


PVE_FILENAME = os.getenv('PVE_FILENAME')
KUBE_FILENAME = os.getenv('KUBE_FILENAME')

try:
    pve_cluster_config = cluster_config_factory(filename=PVE_FILENAME, config_type='pve')
    pve_cluster_config_client = PVEClusterConfig(pve_cluster_config)
    kube_config = cluster_config_factory(filename=KUBE_FILENAME, config_type='kube')
    node_scale = len(pve_cluster_config_client.get_nodes())
except Exception as import_error:
    logging.error(crayons.red(import_error))
    pve_cluster_config_client = None
    node_scale = None


VMAPIClientFactory = ProxmoxAPIClient.api_client_factory(instance_type='vm')
LXCAPIClientFactory = ProxmoxAPIClient.api_client_factory(instance_type='lxc')

credentials = read_pve_credentials()
vm_client = None
lxc_client = None
if credentials:
    try:
        vm_client = VMAPIClientFactory(
            host=credentials.get('host'),
            user=credentials.get('user'),
            password=credentials.get('password'),
            backend=credentials.get('backend'),
            verify_ssl=credentials.get('verify_ssl')
        )
        lxc_client = LXCAPIClientFactory(
            host=credentials.get('host'),
            user=credentials.get('user'),
            password=credentials.get('password'),
            backend=credentials.get('backend'),
            verify_ssl=credentials.get('verify_ssl')
        )
    except https.AuthenticationError as auth:
        logging.error(crayons.red(auth))
        logging.warning(crayons.yellow(f'Unauthorized. Authentication failed for {credentials.get("host")}'))
    except SSLError as ssl:
        logging.error(crayons.red(ssl))
        logging.warning(crayons.yellow(f'Verify SSL Failed for {credentials.get("host")}'))
