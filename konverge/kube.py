import os
import time

from typing import NamedTuple
from fabric2 import Result

from konverge.instance import logging, crayons, InstanceClone, FabricWrapper
from konverge.utils import LOCAL


CNI = {
    'flannel': 'https://raw.githubusercontent.com/coreos/flannel/2140ac876ef134e0ed5af15c65e414cf26827915/Documentation/kube-flannel.yml',
    'calico': 'https://docs.projectcalico.org/v3.9/manifests/calico.yaml',
    'weave': "\"https://cloud.weave.works/k8s/net?k8s-version=$(kubectl version | base64 | tr -d '\n')&env.NO_MASQ_LOCAL=1\"",
    'weave-default': "\"https://cloud.weave.works/k8s/net?k8s-version=$(kubectl version | base64 | tr -d '\n')\""
}


class ControlPlaneDefinitions(NamedTuple):
    ha_masters: bool = False
    networking: str = 'weave'
    apiserver_ip: str = ''
    apiserver_port: int = 6443
    dashboard_url: str = 'https://raw.githubusercontent.com/kubernetes/dashboard/v2.0.0-beta4/aio/deploy/recommended.yaml'


class CNIDefinitions(NamedTuple):
    cni_url: str
    pod_network_cidr: str = ''
    networking_option: str = ''
    file:str = ''


class KubeProvisioner:
    def __init__(
            self,
            instance: InstanceClone,
            control_plane: ControlPlaneDefinitions,
            remote_path='/opt/kube/bootstrap'
    ):
        self.instance = instance
        self.control_plane = control_plane
        self.remote_path = remote_path
        self.dashboard_user = os.path.join(remote_path, 'dashboard-adminuser.yaml')

    @staticmethod
    def supported_cnis(networking='weave'):
        if networking not in CNI.keys():
            logging.error(crayons.red(f'CNI option: {networking} not supported'))
            return None

        if networking == 'calico':
            return CNIDefinitions(
                cni_url=CNI.get(networking),
                pod_network_cidr = '192.168.0.0/16',
                networking_option = f'--pod-network-cidr=192.168.0.0/16',
                file = 'calico.yaml'
            )
        return CNIDefinitions(cni_url=CNI.get(networking))

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
        self.instance.self_node_sudo.execute(f'mkdir -p {self.remote_path}')
        self.instance.self_node_sudo.execute(f'chown -R $USER:$USER {self.remote_path}')
        if self.control_plane.networking == 'calico':
            self.instance.self_node.execute(f'wget {cni_definitions.cni_url} -O {os.path.join(self.remote_path, cni_definitions.file)}')

        print(crayons.cyan('Pulling Required Images from gcr.io'))
        self.instance.self_node_sudo.execute('kubeadm config images pull')

        print(crayons.blue('Running pre-flight checks & deploying Control Plane'))
        init_command = (
            f'kubeadm init --control-plane-endpoint "{self.control_plane.apiserver_ip}:{self.control_plane.apiserver_port}" --upload-certs {cni_definitions.networking_option}'
        ) if self.control_plane.ha_masters else (
            f'kubeadm init {cni_definitions.networking_option}'
        )

        deployed = self.instance.self_node_sudo.execute(init_command)
        if deployed.failed:
            logging.error(crayons.red(f'Master {self.instance.vm_attributes.name} initialization was not performed correctly.'))
            self.rollback_node()
            return None

        print(crayons.green('Initial master deployment success.'))
        time.sleep(60)
        self.post_install_steps()
        if not self.deploy_container_networking(cni_definitions):
            logging.error(crayons.red(''))
            return None

        KubeExecutor.wait_for_running_system_status(self.instance.self_node, namespace='kube-system', master_node=True)
        if self.control_plane.ha_masters:
            return self.get_certificate_key(deployed)

    def rollback_node(self):
        logging.warning(crayons.yellow(f'Performing Node {self.instance.vm_attributes.name} Rollback.'))
        rollback = self.instance.self_node_sudo.execute('kubeadm reset -f --v=5')
        config_reset = self.instance.self_node.execute(f'rm -f $HOME/.kube/config', warn=True)
        iptables_reset = self.instance.self_node_sudo.execute('su - root -c \'iptables -F && iptables -t nat -F && iptables -t mangle -F && iptables -X\'')

        if rollback.ok:
            print(crayons.green('Rollback completed.'))
        else:
            logging.error(crayons.red('Rollback failed'))
            return
        if config_reset.ok:
            print(crayons.green('Config removed.'))
        else:
            logging.warning(crayons.yellow('Config removal not performed.'))
        if iptables_reset.ok:
            print(crayons.green('IPTables reset completed.'))
        else:
            logging.error(crayons.red('IPTables reset failed.'))
            return

    def post_install_steps(self):
        print(crayons.cyan('Post-Install steps'))
        self.instance.self_node.execute('mkdir -p $HOME/.kube')
        self.instance.self_node_sudo.execute('cp -i /etc/kubernetes/admin.conf $HOME/.kube/config')
        self.instance.self_node_sudo.execute('chown $(id -u):$(id -g) $HOME/.kube/config')

    def deploy_container_networking(self, cni_definitions: CNIDefinitions):
        print(f'Deploying Container networking {self.control_plane.networking}')
        if self.control_plane.networking == 'calico':
            network = self.instance.self_node.execute(f'kubectl apply -f {os.path.join(self.remote_path, cni_definitions.file)}')
        elif self.control_plane.networking in ('weave', 'weave-default'):
            network = self.instance.self_node.execute(f'kubectl apply -f {cni_definitions.cni_url}')
        else:
            logging.warning(crayons.yellow(f'Networking {self.control_plane.networking} not supported currently.'))
            return False
        if network.ok:
            print(crayons.green(f'Container Networking {self.control_plane.networking} deployed successfully.'))
            return True


class UbuntuKubeProvisioner(KubeProvisioner):
    pass


class KubeExecutor:
    @staticmethod
    def wait_for_running_system_status(wrapper: FabricWrapper, namespace='kube-system', master_node=False, poll_interval=1):
        runner = LOCAL.run if not master_node else wrapper.execute
        home = runner('echo ~').stdout.strip()

        awk_table_1 = 'awk \'{print $1}\''
        awk_table_2 = 'awk \'{print $2}\''
        non_running_command = f'kubectl get pods -n {namespace} --field-selector=status.phase!=Running'
        running_command = f'kubectl get pods -n {namespace} --field-selector=status.phase=Running | {awk_table_1}'
        running_command_current_desired = f'kubectl get pods -n {namespace} --field-selector=status.phase=Running | {awk_table_2}'

        pods_not_ready = 'initial'
        while pods_not_ready:
            print(crayons.white(f'Wait for all {namespace} pods to enter "Running" phase'))
            pods_not_ready = runner(f'HOME={home} {non_running_command}').stdout.strip()
            time.sleep(poll_interval)
        print(crayons.green(f'All {namespace} pods entered "Running" phase.'))

        all_complete = False
        while not all_complete:
            print(crayons.white(f'Wait for all {namespace} pods to reach "Desired" state'))
            names_table = runner(f'HOME={home} {running_command}', hide=True).stdout.strip()
            current_to_desired_table = runner(f'HOME={home} {running_command_current_desired}', hide=True).stdout.strip()
            clean_table = current_to_desired_table.split()[1:]
            names = names_table.split()[1:]
            complete_table = []
            state_table = [
                {
                    'name': names[clean_table.index(entry)],
                    'current': int(entry.split('/')[0]),
                    'desired': int(entry.split('/')[1]),
                    'complete': False
                }
                for entry in clean_table
            ]
            for state_entry in state_table:
                complete = state_entry.get('current') == state_entry.get('desired')
                state_entry['complete'] = complete
                complete_table.append(complete)
                print(
                    crayons.white(f'Name: {state_entry.get("name")} Complete: ') + (
                        crayons.green(f'{complete}') if complete else crayons.red(f'{complete}')
                    )
                )

            all_complete = all(complete_table)
            time.sleep(poll_interval)
        print(crayons.green(f'All {namespace} pods reached "Desired" state.'))