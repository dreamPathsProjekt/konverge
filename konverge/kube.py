import os
import time
from collections import namedtuple
from fabric2 import Result

from konverge.instance import logging, crayons, InstanceClone


ControlPlaneDefinitions = namedtuple(
    'ControlPlaneDefinitions',
    [
        'ha_masters',
        'networking',
        'apiserver_ip',
        'apiserver_port',
        'dashboard_url'
    ]
)

CNIDefinitions = namedtuple(
    'CNIDefinitions',
    [
        'cni_url',
        'pod_network_cidr',
        'networking_option',
        'file'
    ]
)


class KubeProvisioner:
    def __init__(
            self,
            instance: InstanceClone,
            control_plane: ControlPlaneDefinitions = ControlPlaneDefinitions(
                ha_masters=False,
                networking='weave',
                apiserver_ip='',
                apiserver_port=6443,
                dashboard_url='https://raw.githubusercontent.com/kubernetes/dashboard/v2.0.0-beta4/aio/deploy/recommended.yaml'
            ),
            remote_path='/opt/kube/bootstrap'
    ):
        self.instance = instance
        self.control_plane = control_plane
        self.remote_path = remote_path
        self.dashboard_user = os.path.join(remote_path, 'dashboard-adminuser.yaml')

    @staticmethod
    def supported_cnis(networking='weave'):
        cnis = {
            'flannel': 'https://raw.githubusercontent.com/coreos/flannel/2140ac876ef134e0ed5af15c65e414cf26827915/Documentation/kube-flannel.yml',
            'calico': 'https://docs.projectcalico.org/v3.9/manifests/calico.yaml',
            'weave': "\"https://cloud.weave.works/k8s/net?k8s-version=$(kubectl version | base64 | tr -d '\n')&env.NO_MASQ_LOCAL=1\"",
            'weave-default': "\"https://cloud.weave.works/k8s/net?k8s-version=$(kubectl version | base64 | tr -d '\n')\""
        }
        if networking not in cnis.keys():
            logging.error(crayons.red(f'CNI option: {networking} not supported'))
            return None

        if networking == 'calico':
            return CNIDefinitions(
                cni_url=cnis.get(networking),
                pod_network_cidr = '192.168.0.0/16',
                networking_option = f'--pod-network-cidr=192.168.0.0/16',
                file = 'calico.yaml'
            )
        return CNIDefinitions(
            cni_url=cnis.get(networking),
            pod_network_cidr='',
            networking_option='',
            file=''
        )

    @staticmethod
    def get_certificate_key(deployment: Result):
        lines = deployment.stdout.splitlines()
        for line in lines:
            if '--certificate-key' in line:
                return line.split('--certificate-key')[-1].strip()

    def install_kube(
            self,
            kubernetes_version='1.16.3-00',
            docker_version='18.09.7',
            storageos_requirements=False
    ):
        self.instance.install_kube(
            filename=self.instance.template.filename,
            kubernetes_version=kubernetes_version,
            docker_version=docker_version,
            storageos_requirements=storageos_requirements
        )

    def bootstrap_control_plane(self):
        cni_definitions = self.supported_cnis(networking=self.control_plane.networking)

        print(crayons.cyan(f'Building K8s Control-Plane using High Availability: {self.control_plane.ha_masters}'))
        if self.control_plane.ha_masters:
            if not self.control_plane.apiserver_ip:
                logging.warning(crayons.yellow(f'API Server IP must be provided for HA Control Plane option'))
                return None

        print(crayons.cyan(f'Getting Container Networking Definitions for CNI: {self.control_plane.networking}'))
        self.instance.self_node.execute(f'sudo mkdir -p {self.remote_path}')
        self.instance.self_node.execute(f'sudo chown -R $USER:$USER {self.remote_path}')
        if self.control_plane.networking == 'calico':
            self.instance.self_node.execute(f'wget {cni_definitions.cni_url} -O {os.path.join(self.remote_path, cni_definitions.file)}')

        print(crayons.cyan('Pulling Required Images from gcr.io'))
        self.instance.self_node.execute('sudo kubeadm config images pull')

        print(crayons.blue('Running pre-flight checks & deploying Control Plane'))
        init_command = (
            f'sudo kubeadm init --control-plane-endpoint "{self.control_plane.apiserver_ip}:{self.control_plane.apiserver_port}" --upload-certs {cni_definitions.networking_option}'
        ) if self.control_plane.ha_masters else (
            f'sudo kubeadm init {cni_definitions.networking_option}'
        )

        deployed = self.instance.self_node.execute(init_command)
        if deployed.failed:
            logging.error(crayons.red(f'Master {self.instance.vm_attributes.name} initialization was not performed correctly.'))
            self.rollback_node()
            return None

        if self.control_plane.ha_masters:
            certificate_key = self.get_certificate_key(deployed)

        print(crayons.green('Initial master deployment success.'))
        time.sleep(60)
        self.post_install_steps()
        self.deploy_container_networking(cni_definitions)
        # TODO: WIP

    def rollback_node(self):
        logging.warning(crayons.yellow(f'Performing Node {self.instance.vm_attributes.name} Rollback.'))
        rollback = self.instance.self_node.execute('sudo kubeadm reset')
        # TODO: Add all deprovision steps with iptables & .kubeconfig
        if rollback.ok:
            print(crayons.green('Rollback completed.'))

    def post_install_steps(self):
        print(crayons.cyan('Post-Install steps'))
        self.instance.self_node.execute('mkdir -p $HOME/.kube')
        self.instance.self_node.execute('sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config')
        self.instance.self_node.execute('sudo chown $(id -u):$(id -g) $HOME/.kube/config')

    def deploy_container_networking(self, cni_definitions: CNIDefinitions):
        print(f'Deploying Container networking {self.control_plane.networking}')
        if self.control_plane.networking == 'calico':
            network = self.instance.self_node.execute(f'kubectl apply -f {os.path.join(self.remote_path, cni_definitions.file)}')
        elif self.control_plane.networking == 'weave':
            network = self.instance.self_node.execute(f'kubectl apply -f {cni_definitions.cni_url}')
        else:
            logging.warning(crayons.yellow(f'Networking {self.control_plane.networking} not supported currently.'))
            return
        if network.ok:
            print(crayons.green(f'Container Networking {self.control_plane.networking} deployed successfully.'))

    def wait_for_running_system_status(self, namespace='kube-system', master=False):
        pass


class UbuntuKubeProvisioner(KubeProvisioner):
    pass


class KubeExecutor:
    pass
