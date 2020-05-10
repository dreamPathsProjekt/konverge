import os
import time
import uuid
import yaml

from typing import NamedTuple, TYPE_CHECKING
from fabric2 import Result

from konverge.instance import logging, crayons, InstanceClone, FabricWrapper
from konverge.utils import LOCAL
from konverge.settings import BASE_PATH, WORKDIR, CNI, KUBE_DASHBOARD_URL, pve_cluster_config_client, vm_client

# Avoid cyclic import
if TYPE_CHECKING:
    from konverge.kubecluster import KubeCluster

class LinuxPackage(NamedTuple):
    command: str
    package: str


class ControlPlaneDefinitions:
    def __init__(
        self,
        ha_masters: bool = False,
        networking: str = 'weave',
        apiserver_ip: str = '',
        apiserver_port: int = 6443,
    ):
        self.ha_masters = ha_masters if ha_masters is not None else False
        self.networking = networking if networking else 'weave'
        self.apiserver_ip = apiserver_ip if apiserver_ip else None
        self.apiserver_port = apiserver_port if apiserver_port else 6443


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
    def kube_provisioner_factory(os_type='ubuntu'):
        options = {
            'ubuntu': UbuntuKubeProvisioner,
            'centos': CentosKubeProvisioner
        }
        return options.get(os_type)

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
            docker_ce=False,
            storageos_requirements=False
    ):
        self.instance.install_kube(
            filename=self.instance.template.filename,
            kubernetes_version=kubernetes_version,
            docker_version=docker_version,
            docker_ce=docker_ce,
            storageos_requirements=storageos_requirements
        )

    def check_install_prerequisites(self):
        raise NotImplementedError

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
        if not interfaces:
            return 'eth0'

        interface_filtered = [interface.get('name') for interface in interfaces if interface.get('name') == 'eth0']
        if not interface_filtered:
            return 'eth0'
        return interface_filtered[0]

    def get_control_plane_virtual_ip(self):
        if not self.control_plane.apiserver_ip:
            self.control_plane.apiserver_ip = self.instance.generate_allowed_ip()
        return self.control_plane.apiserver_ip

    def install_control_plane_loadbalancer(self, is_leader=False):
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

            self.check_install_prerequisites()
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

        master_executor = KubeExecutor(wrapper=self.instance.self_node)
        master_executor.wait_for_running_system_status(namespace='kube-system', remote=True)
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

    def get_join_token(self, control_plane_node=False, certificate_key=''):
        join_token = ''
        if self.control_plane.ha_masters:
            token_list = self.instance.self_node_sudo.execute("kubeadm token list").stdout.split('\n')
            for line in token_list:
                if 'authentication,signing' in line:
                    print(crayons.white(line))
                    join_token = line.split()[0].strip()
        else:
            join_token = self.instance.self_node_sudo.execute("kubeadm token list | awk '{print $1}'").stdout.split('TOKEN')[-1].strip()
            while not join_token:
                logging.warning(crayons.yellow('Join Token not found on master. Creating new join token...'))
                self.instance.self_node_sudo.execute("kubeadm token create")
                join_token = self.instance.self_node_sudo.execute("kubeadm token list | awk '{print $1}'").stdout.split('TOKEN')[-1].strip()
        cert_hash = self.instance.self_node.execute("openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt | openssl rsa -pubin -outform der 2>/dev/null | openssl dgst -sha256 -hex | sed 's/^.* //'").stdout.strip()
        if not join_token or not cert_hash:
            logging.error(crayons.red('Unable to retrieve join-token or cert-hash'))
            return None

        return (
            f'kubeadm join {self.control_plane.apiserver_ip}:{self.control_plane.apiserver_port} --token {join_token} --discovery-token-ca-cert-hash sha256:{cert_hash} --control-plane --certificate-key {certificate_key}'
        ) if control_plane_node else (
            f'kubeadm join {self.instance.allowed_ip}:{self.control_plane.apiserver_port} --token {join_token} --discovery-token-ca-cert-hash sha256:{cert_hash}'
        )

    def join_node(self, leader: InstanceClone, control_plane_node=False, certificate_key=''):
        leader_provisioner = KubeProvisioner.kube_provisioner_factory(os_type=leader.vm_attributes.os_type)(
            instance=leader,
            control_plane=self.control_plane,
            remote_path=self.remote_path
        )
        join_command = leader_provisioner.get_join_token(control_plane_node, certificate_key)
        if not join_command:
            logging.error(crayons.red('Node Join command not generated. Abort.'))
            return
        print(crayons.cyan(f'Joining Node: {self.instance.vm_attributes.name} to the cluster'))
        join = self.instance.self_node_sudo.execute(join_command)
        if join.failed:
            logging.error(crayons.red(f'Joining Node: {self.instance.vm_attributes.name} failed. Performing Rollback.'))
            self.rollback_node()
            return

        if control_plane_node:
            self.post_install_steps()
        print(crayons.green(f'Node: {self.instance.vm_attributes.name} has joined the cluster.'))


class UbuntuKubeProvisioner(KubeProvisioner):
    def check_install_prerequisites(self):
        keepalived = LinuxPackage(command='keepalived', package='keepalived')
        wget = LinuxPackage(command='wget', package='wget')
        nc = LinuxPackage(command='nc', package='netcat')
        ip = LinuxPackage(command='ip', package='iproute2')
        curl = LinuxPackage(command='curl', package='curl')

        for package in (wget, nc, ip, curl, keepalived):
            package_exists = self.instance.self_node.execute(f'command {package.command} -h; echo $?', hide=True)
            exit_code = package_exists.stdout.split()[-1].strip()
            if exit_code != '0':
                logging.warning(crayons.yellow(f'Package: {package.package} not found.'))
                print(crayons.cyan(f'Installing {package.package}'))
                self.instance.self_node_sudo.execute(f'apt-get install -y {package.package}')


class CentosKubeProvisioner(KubeProvisioner):
    def check_install_prerequisites(self):
        keepalived = LinuxPackage(command='keepalived', package='keepalived')
        wget = LinuxPackage(command='wget', package='wget')
        nc = LinuxPackage(command='nc', package='nmap-ncat')
        ip = LinuxPackage(command='ip', package='iproute2')
        curl = LinuxPackage(command='curl', package='curl')

        for package in (wget, nc, ip, curl, keepalived):
            package_exists = self.instance.self_node.execute(f'command {package.command} -h; echo $?', hide=True)
            exit_code = package_exists.stdout.split()[-1].strip()
            if exit_code != '0':
                logging.warning(crayons.yellow(f'Package: {package.package} not found.'))
                print(crayons.cyan(f'Installing {package.package}'))
                self.instance.self_node_sudo.execute(f'yum install -y {package.package}')


class KubeConfig:
    def __init__(
        self,
        config_filename: str,
        custom_cluster_name=None,
        custom_context=None,
        custom_user_name=None,
        set_current_context=True
    ):
        self.config_filename = config_filename
        self.custom_cluster_name = custom_cluster_name
        self.custom_context = custom_context
        self.custom_user_name = custom_user_name
        self.set_current_context = set_current_context
        self.config_yaml = self.serialize_config()

    @property
    def clusters(self):
        return self.config_yaml.get('clusters') if self.config_yaml else []

    @property
    def cluster_first(self):
        return self.clusters[0] if self.clusters else None

    @property
    def users(self):
        return self.config_yaml.get('users') if self.config_yaml else []

    @property
    def user_first(self):
        return self.users[0] if self.users else None

    @property
    def contexts(self):
        return self.config_yaml.get('contexts') if self.config_yaml else []

    @property
    def context_first(self):
        return self.contexts[0] if self.contexts else None

    @property
    def current_context(self):
        return self.config_yaml.get('current-context')

    def serialize_config(self):
        with open(self.config_filename, mode='r') as local_dump_file:
            try:
                return yaml.safe_load(local_dump_file)
            except yaml.YAMLError as yaml_error:
                print(crayons.red(f'Error: failed to load from {local_dump_file}'))
                print(crayons.red(f'{yaml_error}'))
                return None

    def cluster_exists(self):
        if not self.clusters:
            return False

        terms = []
        if self.custom_cluster_name:
            cluster = self.custom_cluster_name in [cluster.get('name') for cluster in self.clusters]
            terms.append(cluster)
        if self.custom_user_name:
            user = self.custom_user_name in [user.get('name') for user in self.users]
            terms.append(user)
        if self.custom_context:
            context = self.custom_context in [context.get('name') for context in self.contexts]
            terms.append(context)
        return all(terms) if terms else False

    def update_current_context(self, new_context):
        if not self.current_context:
            self.config_yaml['current-context'] = new_context
        else:
            self.config_yaml['current-context'] = (
                new_context
                if self.set_current_context else
                self.current_context
            )
        return self.config_yaml

    def get_or_create_custom_cluster_user_values(self, new_cluster_name, new_user_name):
        cluster_uid = str(uuid.uuid4())[:8]
        if not self.custom_cluster_name:
            self.custom_cluster_name = f'{new_cluster_name}-{cluster_uid}'
        if not self.custom_user_name:
            self.custom_user_name = f'{new_user_name}-{cluster_uid}'

    @staticmethod
    def get_cluster_data(cluster: dict):
        if not cluster:
            return None, None, None
        name = cluster.get('name')
        cluster_obj = cluster.get('cluster')
        server = cluster_obj.get('server')
        certificate_authority_data = cluster_obj.get('certificate-authority-data')
        print(crayons.blue('=' * len('Cluster')))
        print(crayons.blue('Cluster'))
        print(crayons.blue('=' * len('Cluster')))
        print(crayons.cyan('Name: ') + f'{name}')
        print(crayons.cyan('Server: ') + f'{server}')
        print('')
        return name, server, certificate_authority_data

    @staticmethod
    def get_user_data(user: dict):
        if not user:
            return None, None, None
        name = user.get('name')
        user_obj = user.get('user')
        client_certificate_data = user_obj.get('client-certificate-data')
        client_key_data = user_obj.get('client-key-data')
        print(crayons.blue('=' * len('User')))
        print(crayons.blue('User'))
        print(crayons.blue('=' * len('User')))
        print(crayons.cyan('Name: ') + f'{name}')
        print('')
        return name, client_certificate_data, client_key_data

    @staticmethod
    def get_context_data(context: dict):
        if not context:
            return None, None, None
        name = context.get('name')
        context_obj = context.get('context')
        user = context_obj.get('user')
        cluster = context_obj.get('cluster')
        print(crayons.blue('=' * len('Context')))
        print(crayons.blue('Context'))
        print(crayons.blue('=' * len('Context')))
        print(crayons.cyan('Name: ') + f'{name}')
        print(crayons.cyan('Cluster: ') + f'{cluster}')
        print(crayons.cyan('User: ') + f'{user}')
        print('')
        return name, cluster, user


class KubeExecutor:
    def __init__(self, wrapper: FabricWrapper = None):
        self.wrapper = wrapper
        self.local = LOCAL
        self.dashboard_user = os.path.join(BASE_PATH, 'dashboard-adminuser.yaml')
        self.host = self.wrapper.connection.original_host if self.wrapper else None
        self.home = os.path.expanduser('~')
        self.remote = self.wrapper.execute('echo $HOME', hide=True).stdout.strip() if self.wrapper else None

    def get_current_context(self):
        print(crayons.cyan('Verify that the cluster and context are the correct ones'))
        current_context = self.local.run(f'HOME={self.home} kubectl config current-context').stdout.strip()
        self.local.run(f'HOME={self.home} kubectl config view')
        print(crayons.cyan('Are you in the correct cluster/context ? (y/N)'))
        context_correct = input()
        if context_correct not in ('Y', 'y'):
            print(crayons.yellow('Aborting Operation'))
            return None
        return current_context

    def add_local_cluster_config(
        self,
        custom_cluster_name=None,
        custom_context=None,
        custom_user_name=None,
        set_current_context=True
    ):
        # TODO: Needs further refactoring.
        local_kube = os.path.join(self.home, '.kube')
        remote_kube = os.path.join(self.remote, '.kube')
        local_config_base = os.path.join(local_kube, 'config')
        remote_config_base = os.path.join(remote_kube, 'config')
        local_dump_folder = os.path.join(WORKDIR, 'dump')
        local_dump = os.path.join(local_dump_folder, self.host, 'config.yaml')

        self.local.run(f'mkdir -p {local_dump_folder} && mkdir -p {os.path.join(local_dump_folder, self.host)}')
        self.local.run(f'scp {self.host}:{remote_config_base} {local_dump}')

        remote_kube_config = KubeConfig(
            config_filename=local_dump,
            custom_cluster_name=custom_cluster_name,
            custom_context=custom_context,
            custom_user_name=custom_user_name,
            set_current_context=set_current_context
        )
        remote_config_yaml = remote_kube_config.serialize_config()
        self.local.run(f'rm -rf {local_dump_folder}')

        current_context = remote_kube_config.current_context
        print(crayons.cyan('Current Context: ') + f'{current_context}')
        remote_cluster = remote_kube_config.cluster_first
        remote_user = remote_kube_config.user_first
        remote_context = remote_kube_config.context_first
        remote_cluster_name, _, _ = KubeConfig.get_cluster_data(remote_cluster)
        remote_user_name, _, _ = KubeConfig.get_user_data(remote_user)

        self.local.run(f'cp {local_config_base} {local_config_base}.bak')
        local_kube_config = KubeConfig(
            config_filename=local_config_base,
            custom_cluster_name=custom_cluster_name,
            custom_context=custom_context,
            custom_user_name=custom_user_name,
            set_current_context=set_current_context
        )
        local_config_yaml = local_kube_config.serialize_config()
        local_kube_config.update_current_context(current_context)

        custom_cluster_name_used = True if custom_cluster_name else False
        custom_user_name_used = True if custom_user_name else False
        local_kube_config.get_or_create_custom_cluster_user_values(
            new_cluster_name=remote_cluster_name,
            new_user_name=remote_user_name
        )

        local_cluster_entries = local_kube_config.clusters
        local_context_entries = local_kube_config.contexts
        local_user_entries = local_kube_config.users
        for cluster_entry in local_cluster_entries:
            if cluster_entry.get('name') == remote_cluster_name or custom_cluster_name_used:
                remote_cluster['name'] = custom_cluster_name
        for user_entry in local_user_entries:
            if user_entry.get('name') == remote_user_name or custom_user_name_used:
                remote_user['name'] = custom_user_name
        for context_entry in local_context_entries:
            if context_entry.get('context').get('cluster') == remote_cluster_name or custom_cluster_name_used:
                remote_context['context']['cluster'] = custom_cluster_name
            if context_entry.get('context').get('user') == remote_user_name or custom_user_name_used:
                remote_context['context']['user'] = custom_user_name
            remote_context['name'] = (
                custom_context
                if custom_context else
                f'{remote_user["name"]}@{remote_cluster["name"]}'
            )

        if not local_kube_config.clusters:
            local_config_yaml['clusters'] = remote_config_yaml.get('clusters')
        else:
            local_config_yaml['clusters'].append(remote_cluster)

        if not local_kube_config.users:
            local_config_yaml['users'] = remote_config_yaml.get('users')
        else:
            local_config_yaml['users'].append(remote_user)

        if not local_kube_config.contexts:
            local_config_yaml['contexts'] = remote_config_yaml.get('contexts')
        else:
            local_config_yaml['contexts'].append(remote_context)

        local_config_yaml['current-context'] = (
            custom_context
            if set_current_context and custom_context else
            local_kube_config.current_context
        )

        try:
            with open(local_config_base, mode='w') as local_config_file_mutated:
                try:
                    yaml.safe_dump(local_config_yaml, stream=local_config_file_mutated)
                except yaml.YAMLError as yaml_error:
                    logging.error(crayons.red(f'Error: failed to load from {local_config_base}'))
                    logging.error(crayons.red(f'{yaml_error}'))
                    print(crayons.blue(f'Performing rollback of {local_config_base}'))
                    self.local.run(f'mv {local_config_base}.bak {local_config_base}')
                    print(crayons.green('Rollback complete'))
                    return
        except Exception as generic:
            logging.error(crayons.red(f'Error during writing to kube config {local_config_base}: {generic}'))
            print(crayons.blue(f'Performing rollback of {local_config_base}'))
            self.local.run(f'mv {local_config_base}.bak {local_config_base}')
            print(crayons.green('Rollback complete'))

    # Use str type annotation for kube_cluster, to avoid cyclic import.
    def unset_local_cluster_config(self, kube_cluster: 'KubeCluster'):
        if not self.cluster_exists(kube_cluster):
            logging.warning(crayons.yellow(f'Cluster: {kube_cluster.cluster_attributes.name} not found in config.'))
            return
        cluster_name = kube_cluster.cluster_attributes.name
        user = kube_cluster.cluster_attributes.user
        context = kube_cluster.cluster_attributes.context
        self.local.run(f'HOME={self.home} kubectl config use-context {context}')
        self.local.run(f'HOME={self.home} kubectl config delete-cluster {cluster_name}')
        self.local.run(f'HOME={self.home} kubectl config delete-context {context}')
        self.local.run(f'HOME={self.home} kubectl config unset users.{user}')

    def cluster_exists(self, kube_cluster: 'KubeCluster'):
        local_kube = os.path.join(self.home, '.kube')
        config_file = os.path.join(local_kube, 'config')
        cluster_name = kube_cluster.cluster_attributes.name
        kube_config = KubeConfig(config_filename=config_file, custom_cluster_name=cluster_name)
        if kube_cluster.cluster_attributes.user:
            kube_config.custom_user_name = kube_cluster.cluster_attributes.user
        if kube_cluster.cluster_attributes.context:
            kube_config.custom_context = kube_cluster.cluster_attributes.context
        return kube_config.cluster_exists()

    def wait_for_running_system_status(self, namespace='kube-system', remote=False, poll_interval=1):
        runner = LOCAL.run if not remote else self.wrapper.execute
        prepend = f'HOME={self.home} ' if not remote else ''

        awk_table_1 = 'awk \'{print $1}\''
        awk_table_2 = 'awk \'{print $2}\''
        non_running_command = f'kubectl get pods -n {namespace} --field-selector=status.phase!=Running'
        running_command = f'kubectl get pods -n {namespace} --field-selector=status.phase=Running | {awk_table_1}'
        running_command_current_desired = f'kubectl get pods -n {namespace} --field-selector=status.phase=Running | {awk_table_2}'

        pods_not_ready = 'initial'
        while pods_not_ready:
            print(crayons.white(f'Wait for all {namespace} pods to enter "Running" phase'))
            pods_not_ready = runner(command=f'{prepend}{non_running_command}').stdout.strip()
            time.sleep(poll_interval)
        print(crayons.green(f'All {namespace} pods entered "Running" phase.'))

        all_complete = False
        while not all_complete:
            print(crayons.white(f'Wait for all {namespace} pods to reach "Desired" state'))
            names_table = runner(command=f'{prepend}{running_command}', hide=True).stdout.strip()
            current_to_desired_table = runner(command=f'{prepend}{running_command_current_desired}', hide=True).stdout.strip()
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

    def deploy_dashboard(self, remote_path='/opt/kube', local=True):
        """
        Argument remote_path exists on hosts with the file by previously running install_kube() method.
        """
        prepend = f'HOME={self.home} ' if local else ''
        run = self.local.run if local else self.wrapper.execute
        bootstrap_path = os.path.join(BASE_PATH, 'bootstrap') if local else os.path.join(remote_path, 'bootstrap')
        user_creation = f'{bootstrap_path}/dashboard-adminuser.yaml'

        print(crayons.cyan('Deploying Dashboard'))
        dashboard = run(command=f'{prepend}kubectl apply -f {KUBE_DASHBOARD_URL}')
        if dashboard.ok:
            print(crayons.green(f'Kubernetes Dashboard deployed successfully.'))
            print(crayons.cyan('Deploying User admin-user with role-binding: cluster-admin'))
            time.sleep(30)

            user_role = run(command=f'{prepend}kubectl apply -f {user_creation}')
            if user_role.ok:
                print(crayons.green(f'User admin-user created successfully.'))
            else:
                logging.error(crayons.red('User admin-user was not created correctly.'))
        else:
            logging.error(crayons.red('Dashboard was not deployed correctly.'))

    def get_dashboard_token(self, user='admin-user', local=True):
        prepend = f'HOME={self.home} ' if local else ''
        run = self.local.run if local else self.wrapper.execute
        awk_routine = "'{print $1}'"
        command = f"{prepend}kubectl -n kubernetes-dashboard describe secret $({prepend}kubectl -n kubernetes-dashboard get secret | grep {user} | awk {awk_routine})"
        print(crayons.white(command))
        token = run(command=command)
        return token.stdout.strip() if token.ok else None

    def apply_label_node(self, role, instance_name):
        prepend = f'HOME={self.home}'
        label_node = f'node-role.kubernetes.io/{role}='
        labeled = self.local.run(f'{prepend} kubectl label nodes {instance_name} {label_node}')
        if labeled.ok:
            print(crayons.green(f'Added label {label_node} to {instance_name}'))

    def helm_install_v2(self, patch=True, helm=True, tiller=True):
        prepend = f'HOME={self.home}'
        helm_script = 'https://git.io/get_helm.sh'

        current_context = self.get_current_context()
        if not current_context:
            return

        if helm:
            print(crayons.cyan('Installing Helm locally'))
            install = self.local.run(f'{prepend} curl -L {helm_script} | bash')
            if not install.ok:
                logging.error(crayons.red(f'Helm installation failed'))
                return
            self.local.run(f'echo "source <(helm completion bash)" >> {self.home}/.bashrc')
            print(crayons.green('Helm installed locally'))

        if tiller:
            if not patch:
                logging.warning(crayons.yellow('No-Patch (K8s versions > 1.16.*) installation is not implemented.'))
                return

            print(crayons.cyan('Bootstrapping Tiller with patch for K8s versions > 1.16.*'))
            bootstrap = self.tiller_install_v2_patch()
            if not bootstrap.ok:
                logging.error(crayons.red(f'Helm initialization with Tiller failed'))
                logging.warning(crayons.yellow('Rolling back installation'))
                rollback = self.local.run(f'{prepend} helm reset --force --remove-helm-home')
                if rollback.ok:
                    print(crayons.green('Rollback completed'))
                return

            tiller_ready = ''
            while not tiller_ready:
                print(crayons.white('Ping for tiller ready'))
                tiller_ready = self.local.run(f'{prepend} kubectl get pod --namespace kube-system -l app=helm,name=tiller --field-selector=status.phase=Running').stdout.strip()
                time.sleep(1)
            print(crayons.green(f'Helm initialized with Tiller for context: {current_context}'))
            self.wait_for_running_system_status()
            time.sleep(10)
            print(crayons.magenta('You might need to run "helm init --client-only to initialize repos"'))

    def tiller_install_v2_patch(self):
        prepend = f'HOME={self.home}'
        self.local.run(f'{prepend} kubectl --namespace kube-system create sa tiller')
        self.local.run(
            f'{prepend} kubectl create clusterrolebinding tiller ' +
            '--clusterrole cluster-admin ' +
            '--serviceaccount=kube-system:tiller'
        )
        return self.local.run(
            f"{prepend} helm init --service-account tiller " +
            f"--override spec.selector.matchLabels.'name'='tiller',spec.selector.matchLabels.'app'='helm' " +
            f"--output yaml | sed 's@apiVersion: extensions/v1beta1@apiVersion: apps/v1@' | {prepend} kubectl apply -f -"
        )

    @staticmethod
    def get_bridge_common_interface(interface='vmbr0'):
        map_nodes_to_ifaces = {}
        nodes = pve_cluster_config_client.get_nodes()
        for node in nodes:
            interfaces = vm_client.get_cluster_node_bridge_interfaces(node=node.name)
            for iface in interfaces:
                candidate = iface.get('name')
                if interface in candidate:
                    map_nodes_to_ifaces[node.name] = candidate
        common = set.intersection(set(map_nodes_to_ifaces.values()))
        return common.pop() if common else None

    def metallb_install(self, file='', version='0.12.0', interface='vmbr0'):
        prepend = f'HOME={self.home}'
        if not file:
            values_file = 'values.yaml'
            local_workdir = os.path.join(WORKDIR, '.metallb')
            local_values_path = os.path.join(local_workdir, values_file)

            metallb_range = pve_cluster_config_client.loadbalancer_ip_range_to_string_or_list()
            if not metallb_range:
                logging.error(crayons.red('Could not deploy MetalLB with given cluster values.'))
                return
            common_iface = self.get_bridge_common_interface(interface)
            if not common_iface:
                logging.error(crayons.red(f'Interface {interface} not found as common bridge in PVE Cluster nodes.'))
                return

            template_values = (
                'configInline:',
                '  address-pools:',
                f'  - name: {common_iface}',
                '    protocol: layer2',
                '    addresses:',
                f'    - {metallb_range}',
                'controller:',
                '  tolerations:',
                '  - effect: NoExecute',
                '    key: node.kubernetes.io/not-ready',
                '    operator: Exists',
                '    tolerationSeconds: 60',
                '  - effect: NoExecute',
                '    key: node.kubernetes.io/unreachable',
                '    operator: Exists',
                '    tolerationSeconds: 60',
            )

            self.local.run(f'mkdir -p {local_workdir}')
            _, file, error = KubeProvisioner.write_config_to_file(
                file=values_file,
                local_file_path=local_values_path,
                script_body=template_values
            )
            if error:
                # Logging executes in write_config_to_file
                return

        if not self.helm_exists(prepend):
            return

        print(crayons.cyan(f'Deploying MetalLB'))
        metal_install = self.local.run(f'{prepend} helm install --name metallb -f {file} stable/metallb --version={version}')
        if metal_install.failed:
            logging.error(crayons.red('MetalLB installation failed.Rolling Back'))
            rollback = self.local.run('helm delete metallb --purge')
            if rollback.ok:
                print(crayons.green('Rollback completed'))
                return
        print(crayons.green('MetalLB installed'))

    def helm_exists(self, command_prefix):
        exit_code = self.local.run(f'{command_prefix} helm version ; echo $?').stdout.split()[-1].strip()
        if exit_code != '0':
            logging.warning(crayons.yellow('"helm" not found on your system. Please run helm-install first'))
        return exit_code == '0'

    # TODO: Storage feature.