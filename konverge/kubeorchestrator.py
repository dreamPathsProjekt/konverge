import logging
import crayons
from typing import NamedTuple
from functools import singledispatch

from konverge import settings
from konverge.utils import (
    KubeClusterAction,
    KubeStorage,
    HelmVersion,
    VMCategory,
    VMAttributes,
    Storage,
    get_kube_versions
)
from konverge.kube import ControlPlaneDefinitions, KubeExecutor, KubeProvisioner
from konverge.cloudinit import CloudinitTemplate
from konverge.instance import InstanceClone
from konverge.queries import VMQuery


class HelmAtrributes(NamedTuple):
    version: HelmVersion = HelmVersion.v2
    local: bool = False
    tiller: bool = True


class ClusterAttributes(NamedTuple):
    name: str
    pool: str
    os_type: str = 'ubuntu'
    user: str = None
    context: str = None
    dashboard: bool = True
    storage: KubeStorage = None
    loadbalancer: bool = True
    version: str = None
    docker: str = None
    docker_ce: bool = False
    ssh_key: str = None
    helm: HelmAtrributes = HelmAtrributes()


class ControlPlaneSerializer:
    def __init__(
        self,
        config: dict,
        control_plane: ControlPlaneDefinitions = ControlPlaneDefinitions()
    ):
        self.config = config
        self.control_plane = control_plane

    def serialize(self):
        cp_config = self.config.get('control_plane')
        if not cp_config:
            return

        for key, value in cp_config.items():
            if key != 'apiserver':
                setattr(self.control_plane, key, value)
        apiserver = cp_config.get('apiserver')
        if not apiserver:
            return
        for key, value in apiserver.items():
            setattr(self.control_plane, f'apiserver_{key}', value)


class ClusterAttributesSerializer:
    def __init__(
        self,
        config: dict,
        helm: HelmAtrributes = HelmAtrributes(),
        cluster: ClusterAttributes = None
    ):
        self.config = config
        self.helm = helm
        self.cluster = cluster

    @staticmethod
    def infer_full_versions_from_major(kubernetes='1.17', docker_ce=False):
        versions = get_kube_versions(kube_major=kubernetes, docker_ce=docker_ce)
        lines = versions.splitlines()
        start = 0
        end = len(lines)
        docker_ce_start = 0
        docker_ce_end = len(lines)
        docker_io_start = 0
        docker_io_end = len(lines)
        for line in lines:
            if '=== kubelet ===' in line:
                start = lines.index(line)
            if '=== kubectl ===' in line:
                end = lines.index(line)
            if '=== docker.io ===' in line:
                docker_io_start = lines.index(line)
            if '=== docker-ce ===' in line:
                docker_io_end = lines.index(line)
            if '=== docker-ce ===' in line and docker_ce:
                docker_ce_start = lines.index(line)
            if docker_ce:
                docker_ce_end = -1
        version_list = [entry for entry in lines[start + 1:end] if entry]
        docker_ce_list = [entry for entry in lines[docker_ce_start + 1:docker_ce_end] if entry] if docker_ce else []
        docker_io_list = [entry for entry in lines[docker_io_start + 1:docker_io_end] if entry]
        minor_versions = []
        docker_ce_versions = []
        docker_io_versions = []
        for entry in version_list:
            title, version, url = entry.split('|')
            minor_versions.append(version.strip())
        if docker_ce:
            for entry in docker_ce_list:
                title, version, url = entry.split('|')
                docker_ce_versions.append(version.strip())
        for entry in docker_io_list:
            title, version, url = entry.split('|')
            docker_io_versions.append(version.strip())
        latest = minor_versions[0]
        if docker_ce:
            return latest, docker_ce_versions[0]
        return latest, docker_io_versions[0]

    def serialize_helm(self):
        helm_attributes = self.config.get('helm')
        if not helm_attributes:
            return
        helm_version = HelmVersion.return_value(helm_attributes.get('version')) or HelmVersion.v2
        local = helm_attributes.get('local') or False
        tiller = helm_attributes.get('tiller') or True
        self.helm = HelmAtrributes(
            version=helm_version,
            local=local,
            tiller=tiller
        )

    def serialize_versions(self, versions: dict):
        defaults = (None, None, False)
        if not versions:
            return defaults
        version = versions.get('kubernetes')
        docker_ce = versions.get('docker_ce', False)
        if not version:
            return defaults
        version, docker = self.infer_full_versions_from_major(kubernetes=version, docker_ce=docker_ce)
        print(crayons.green(f'Kubernetes version: {version}'))
        ce='Docker CE'
        io='docker.io'
        print(crayons.green(f'{ce if docker_ce else io} version: {docker}'))
        return version, docker, docker_ce

    def serialize(self):
        name = self.config.get('name')
        pool = self.config.get('pool')
        os_type = self.config.get('os_type') or 'ubuntu'
        user = self.config.get('user')
        context = self.config.get('context')
        dashboard = self.config.get('dashboard', True) or True
        storage = KubeStorage.return_value(self.config.get('storage'))
        loadbalancer = self.config.get('loadbalancer') or True
        ssh_key = self.config.get('ssh_key')

        versions = self.config.get('versions')
        version, docker, docker_ce = self.serialize_versions(versions)

        self.serialize_helm()
        self.cluster = ClusterAttributes(
            name=name,
            pool=pool,
            os_type=os_type,
            user=user,
            context=context,
            dashboard=dashboard,
            storage=storage,
            loadbalancer=loadbalancer,
            version=version,
            docker=docker,
            docker_ce=docker_ce,
            ssh_key=ssh_key,
            helm=self.helm
        )


class ClusterInstance:
    def __init__(
        self,
        config: dict,
        control_plane: ControlPlaneDefinitions,
        cluster_attributes: ClusterAttributes
    ):
        self.config = config
        self.control_plane = control_plane
        self.cluster_attributes = cluster_attributes
        self.instances = []

        self.gateway = settings.pve_cluster_config_client.gateway
        self.name = self.config.get('name')
        self.scale = self.config.get('scale')
        self.node = self.config.get('node')
        self.cpus = self.config.get('cpus')
        self.memory = self.config.get('memory')
        self.disk = self.config.get('disk')
        self.scsi = self.config.get('scsi') or False
        self.disk_size = self.disk.get('size') if self.disk else None

    def serialize(self):
        raise NotImplementedError


class ClusterTemplate(ClusterInstance):
    def __init__(
        self,
        config: dict,
        control_plane: ControlPlaneDefinitions,
        cluster_attributes: ClusterAttributes
    ):
        super().__init__(
            config=config,
            control_plane=control_plane,
            cluster_attributes=cluster_attributes
        )
        self.nodes = self.node.split(',')
        self.storage_type, self.image_storage_type = self.get_pve_storage()
        self.details = {
            node: {
                'name': f'{node}-{self.name}' if self.name else None,
                'vmid': None,
                'exists': False
            }
            for node in self.nodes
        }

    @property
    def create(self):
        create = self.config.get('create')
        if create is not None:
            return create
        return True

    def template_exists(self, node):
        if node in self.nodes:
            return self.details.get(node).get('exists')
        logging.warning(crayons.yellow(f'Node {node} does not exist.'))
        return False

    def get_pve_storage(self):
        pve_storage = self.config.get('pve_storage')
        storage_type = None
        image_storage_type = None

        try:
            storage_type = Storage.return_value(pve_storage.get('instance').get('type'))
            image_storage_type = Storage.return_value(pve_storage.get('image').get('type'))
        except AttributeError as attr_error:
            logging.error(crayons.red(attr_error))
        if not storage_type:
            logging.error(crayons.red(f'Template {self.name} has invalid instance storage type: {storage_type}'))
        if not image_storage_type:
            logging.error(crayons.red(f'Template {self.name} has invalid imagestorage type: {storage_type}'))
        return storage_type, image_storage_type

    @staticmethod
    def generate_template(vm_attributes: VMAttributes, preinstall=True):
        factory = CloudinitTemplate.os_type_factory(vm_attributes.os_type)
        return factory(vm_attributes=vm_attributes, client=settings.vm_client, preinstall=preinstall)

    def serialize(self):
        for node in self.nodes:
            vm_attributes = VMAttributes(
                name=self.details.get(node).get('name'),
                node=node,
                pool=self.cluster_attributes.pool,
                os_type=self.cluster_attributes.os_type,
                storage_type=self.storage_type,
                image_storage_type=self.image_storage_type,
                scsi=self.scsi,
                ssh_keyname=self.cluster_attributes.ssh_key,
                gateway=self.gateway
            )
            if self.cpus:
                vm_attributes.cpus = self.cpus
            if self.memory:
                vm_attributes.memory = self.memory
            if self.disk_size:
                vm_attributes.disk_size = self.disk_size

            template = self.generate_template(vm_attributes)
            self.instances.append(template)
            self.details[node]['vmid'] = template.vmid

    def query(self):
        if not self.instances:
            return
        for instance in self.instances:
            instance: CloudinitTemplate
            query = VMQuery(
                client=settings.vm_client,
                name=instance.vm_attributes.name,
                pool=instance.vm_attributes.pool,
                node=instance.vm_attributes.node,
                vmid=instance.vmid
            )
            created_instance = query.execute(template=isinstance(instance, CloudinitTemplate))
            if created_instance:
                self.instances[self.instances.index(instance)] = created_instance
                self.details[instance.vm_attributes.node]['exists'] = True
                self.details[instance.vm_attributes.node]['vmid'] = created_instance.vmid


class ClusterMaster(ClusterInstance):
    def __init__(
        self,
        config: dict,
        control_plane: ControlPlaneDefinitions,
        cluster_attributes: ClusterAttributes
    ):
        super().__init__(
            config=config,
            control_plane=control_plane,
            cluster_attributes=cluster_attributes
        )

    def serialize(self):
        pass


class ClusterWorker(ClusterInstance):
    def __init__(
        self,
        config: dict,
        control_plane: ControlPlaneDefinitions,
        cluster_attributes: ClusterAttributes
    ):
        super().__init__(
            config=config,
            control_plane=control_plane,
            cluster_attributes=cluster_attributes
        )

    def serialize(self):
        pass