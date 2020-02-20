import os
import time

from typing import NamedTuple
from fabric2 import Result

from konverge.instance import logging, crayons, InstanceClone, FabricWrapper
from konverge.utils import LOCAL
from konverge.settings import WORKDIR


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
    # TODO: Check for nc, wget & ip commands availability
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

    @staticmethod
    def write_config_to_file(file, local_file_path, script_body):
        try:
            with open(local_file_path, mode='w') as local_script_fp:
                local_script_fp.write('\n'.join(script_body))
            return file, local_file_path, None
        except (OSError, IOError) as file_write_error:
            logging.error(crayons.red(file_write_error))
            return None, None, file_write_error

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

    def generate_keepalived_healthcheck(self, virtual_ip):
        local = LOCAL
        script_file = 'check_apiserver.sh'
        local_workdir = os.path.join(WORKDIR, 'bootstrap')
        local_script_path = os.path.join(local_workdir, script_file)
        local.run(f'mkdir -p {local_workdir}')

        check_apiserver_sh = (
            '# !/bin/sh',
            '',
            'errorExit() {',
            '    echo "*** $*" 1>&2',
            '    exit 1',
            '}',
            '',
            f'curl --silent --max-time 2 --insecure https://localhost:{self.control_plane.apiserver_port}/ -o /dev/null || errorExit "Error GET https://localhost:{self.control_plane.apiserver_port}/"',
            f'if ip addr | grep -q {virtual_ip}; then',
            f'    curl --silent --max-time 2 --insecure https://{virtual_ip}:{self.control_plane.apiserver_port}/ -o /dev/null || errorExit "Error GET https://{virtual_ip}:{self.control_plane.apiserver_port}/"',
            'fi'
        )
        return self.write_config_to_file(
            file=script_file,
            local_file_path=local_script_path,
            script_body=check_apiserver_sh
        )

    def generate_keepalived_config(self, virtual_ip, interface, state, priority):
        local = LOCAL
        config_file = 'keepalived.conf'
        local_workdir = os.path.join(WORKDIR, 'bootstrap')
        local_config_path = os.path.join(local_workdir, config_file)
        local.run(f'mkdir -p {local_workdir}')

        keepalived_config = (
            'vrrp_script check_apiserver {',
            '  script "/etc/keepalived/check_apiserver.sh"',
            '  interval 3',
            '  weight -2',
            '  fall 10',
            '  rise 2',
            '}',
            '',
            'vrrp_instance CLUSTER {',
            f'  state {state}',
            f'  interface {interface}',
            '  virtual_router_id 51',
            f'  priority {priority}',
            '  authentication {',
            '    auth_type PASS',
            '    auth_pass pass1234',
            '  }',
            '  virtual_ipaddress {',
            f'    {virtual_ip}',
            '  }',
            '  track_script {',
            '    check_apiserver',
            '  }',
            '}'
        )
        return self.write_config_to_file(
            file=config_file,
            local_file_path=local_config_path,
            script_body=keepalived_config
        )

    def get_instance_interface(self):
        interfaces = self.instance.client.agent_get_interfaces(
            node=self.instance.vm_attributes.node, vmid=self.instance.vmid
        )
        interface = interfaces[0].get('name') if interfaces else 'eth0'
        return interface

    def get_control_plane_virtual_ip(self):
        if not self.control_plane.apiserver_ip:
            self.control_plane.apiserver_ip = self.instance.generate_allowed_ip()
        return self.control_plane.apiserver_ip

    def install_control_plane_loadbalancer(self, is_leader=True):
        if not self.control_plane.ha_masters:
            logging.warning(crayons.yellow('Skip install keepalived. Control Plane not Deployed in High Available Mode.'))
            return None

        local = LOCAL
        host = self.instance.vm_attributes.name

        remote_path = '/etc/keepalived'
        state = 'MASTER' if is_leader else 'BACKUP'
        priority = '101' if is_leader else '100'

        interface = self.get_instance_interface()
        virtual_ip = self.get_control_plane_virtual_ip()
        script_file, local_script_path, script_error = self.generate_keepalived_healthcheck(virtual_ip)
        config_file, local_config_path, config_error = self.generate_keepalived_config(
            virtual_ip=virtual_ip,
            interface=interface,
            state=state,
            priority=priority
        )

        if script_error or config_error:
            logging.error(crayons.red(f'Abort keepalived install on {host}'))
            return None

        print(crayons.cyan(f'Sending config files to {host}'))
        sent1 = local.run(f'scp {local_config_path} {host}:~')
        sent2 = local.run(f'scp {local_script_path} {host}:~')

        if sent1.ok and sent2.ok:
            print(crayons.blue(f'Installing keepalived service on {host}'))

            if self.instance.vm_attributes.os_type == 'ubuntu':
                self.instance.self_node_sudo.execute('apt-get install -y keepalived')
            elif self.instance.vm_attributes.os_type == 'centos':
                self.instance.self_node_sudo.execute('yum install -y keepalived')
            else:
                logging.error(crayons.red(f'Abort. Distribution: {self.instance.vm_attributes.os_type} not supported for keepalived.'))
                return None

            self.instance.self_node.execute(f'sudo mv {config_file} {remote_path} && sudo mv {script_file} {remote_path}')
            self.instance.self_node_sudo.execute(f'chmod 0666 {remote_path}/{config_file}')

            restart = self.instance.self_node_sudo.execute(f'systemctl restart keepalived')
            if restart.ok:
                self.instance.self_node_sudo.execute('systemctl status keepalived')
                test_connection = f'if nc -v -w 5 {virtual_ip} {self.control_plane.apiserver_port}; then echo "Success"; fi'
                output = self.instance.self_node.execute(test_connection).stderr
                if 'Connection refused' in output.strip():
                    print(crayons.green(f'Keepalived running on {host} with virtual ip: {virtual_ip}'))
            return virtual_ip

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
            logging.error(crayons.red(f'Container networking {self.control_plane.networking} failed to deploy correctly.'))
            return None

        KubeExecutor.wait_for_running_system_status(self.instance.self_node, namespace='kube-system', master_node=True)
        if self.control_plane.ha_masters:
            return self.get_certificate_key(deployed)
        return None

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
    def __init__(self, wrapper: FabricWrapper = None):
        self.wrapper = wrapper
        self.local = LOCAL

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