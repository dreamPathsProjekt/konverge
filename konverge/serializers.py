import logging
from typing import NamedTuple, Union

import crayons

from konverge import settings
from konverge.cloudinit import CloudinitTemplate
from konverge.instance import InstanceClone
from konverge.kube import ControlPlaneDefinitions, KubeExecutor
from konverge.queries import VMQuery
from konverge.utils import HelmVersion, KubeStorage, infer_full_versions_from_major, Storage, VMAttributes


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

    @property
    def exists(self):
        """
        Checks local ~/.kube/config from KubeExecutor.cluster_exists(cluster),
        to determine, if cluster has been already created.
        """
        kube_executor = KubeExecutor()
        if kube_executor.cluster_exists(self):
            logging.warning(crayons.yellow(f'Cluster {self.cluster.name} exists.'))
            return True
        return False

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

    def serialize_versions(self):
        defaults = (None, None, False)
        versions = self.config.get('versions')
        if not versions:
            return defaults

        version = versions.get('kubernetes')
        docker_ce = versions.get('docker_ce', False)
        if not version:
            return defaults

        version, docker = infer_full_versions_from_major(kubernetes=version, docker_ce=docker_ce)
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

        version, docker, docker_ce = self.serialize_versions()
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


class ClusterInstanceSerializer:
    def __init__(
        self,
        config: dict,
        cluster_attributes: ClusterAttributes
    ):
        self.config = config
        self.cluster_attributes = cluster_attributes
        self.templates: 'Union[ClusterTemplateSerializer, None]' = None

        self.gateway = settings.pve_cluster_config_client.gateway
        self.name = self.config.get('name')
        self.scale = self.config.get('scale')
        self.node = self.config.get('node')
        self.nodes = self.node.split(',')
        self.username = self.config.get('username')
        self.cpus = self.config.get('cpus')
        self.memory = self.config.get('memory')
        self.disk = self.config.get('disk')
        self.scsi = self.config.get('scsi') or False
        self.secondary_iface = self.config.get('secondary_iface') or False
        self.disk_size = self.disk.get('size') if self.disk else None
        self.hotplug = self.disk.get('hotplug') if self.disk else None
        self.hotplug_size = self.disk.get('hotplug_size') if self.disk else None
        self.storage_type, self.image_storage_type = self.get_pve_storage()

        self.instances = []
        self.state = {node: [] for node in self.nodes}

    @property
    def hotplug_valid(self):
        if self.hotplug and not self.hotplug_size:
            logging.error(crayons.red(f'Hotplug disk enabled for VM group: {self.name}, but no "hotplug_size" is provided.'))
            return False
        return True

    def get_template(self, node):
        for template in self.templates.instances:
            template: CloudinitTemplate
            if template.vm_attributes.node == node:
                return template

    def get_pve_storage(self):
        pve_storage = self.config.get('pve_storage')

        try:
            storage_type = Storage.return_value(pve_storage.get('type'))
        except AttributeError as attr_error:
            storage_type = None
            logging.warning(crayons.yellow(attr_error))
        return storage_type, None

    def serialize(self):
        """
        Spread vms round-robin on available nodes.
        """
        for i in range(self.scale):
            node = self.nodes[i % len(self.nodes)]
            vm_attributes = VMAttributes(
                name=f'{self.name}-{i}',
                node=node,
                pool=self.cluster_attributes.pool,
                os_type=self.cluster_attributes.os_type,
                cpus=self.cpus,
                memory=self.memory,
                disk_size=self.disk_size,
                scsi=self.scsi,
                ssh_keyname=self.cluster_attributes.ssh_key,
                gateway=self.gateway
            )

            # Inherit template instance storage type and username.
            # Use VMID_PLACEHOLDER, to calculate vmid dynamically later.
            template = self.get_template(node)
            if self.storage_type:
                vm_attributes.storage_type = self.storage_type
            else:
                vm_attributes.storage_type = template.vm_attributes.storage_type

            clone = InstanceClone(
                vm_attributes=vm_attributes,
                client=settings.vm_client,
                template=template,
                vmid=settings.VMID_PLACEHOLDER,
                username=self.username,
                hotplug_disk_size=self.hotplug_size if self.hotplug and self.hotplug_valid else None,
                secondary_iface=self.secondary_iface
            )
            self.instances.append(clone)
            self.state[clone.vm_attributes.node].append(
                {
                    'name': clone.vm_attributes.name,
                    'vmid': clone.vmid,
                    'exists': False
                }
            )

    def query(self):
        if not self.instances:
            return False
        for instance in self.instances:
            instance: InstanceClone
            query = VMQuery(
                client=settings.vm_client,
                name=instance.vm_attributes.name,
                pool=instance.vm_attributes.pool,
                node=instance.vm_attributes.node
            )
            answer = query.execute()
            answermsg = f'VMID: {answer[0].vmid}, Name: {answer[0].vm_attributes.name}' if answer else 'Not Found'
            print(
                crayons.white(
                    f'Query instance {instance.vm_attributes.name}: {answermsg}'
                )
            )
            created_instance = answer[0] if answer else answer
            if created_instance:
                vms_state = self.state[instance.vm_attributes.node]
                match = lambda vm: vm.get('name') and vm.get('name') == created_instance.vm_attributes.name
                member = list(filter(match, vms_state))[0]
                index = vms_state.index(member) if member else None
                self.instances[self.instances.index(instance)] = created_instance
                if index is not None:
                    self.state[instance.vm_attributes.node][index] = {
                        'name': created_instance.vm_attributes.name,
                        'vmid': created_instance.vmid,
                        'exists': True
                    }

        for node in self.nodes:
            if any(item['exists'] for item in self.state[node]):
                return True
        return False


class ClusterTemplateSerializer(ClusterInstanceSerializer):
    def __init__(
        self,
        config: dict,
        cluster_attributes: ClusterAttributes
    ):
        super().__init__(
            config=config,
            cluster_attributes=cluster_attributes
        )
        self.state = {
            node: {
                'name': f'{node}-{self.name}' if self.name else None,
                'vmid': None,
                'exists': False
            }
            for node in self.nodes
        }

    def template_exists(self, node):
        if node in self.nodes:
            return self.state.get(node).get('exists')
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
        # TODO: Support preinstall option as argument, during generation. Methods cover it.
        for node in self.nodes:
            vm_attributes = VMAttributes(
                name=self.state.get(node).get('name'),
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
            self.state[node]['vmid'] = template.vmid

    def query(self):
        if not self.instances:
            return False
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
                self.state[instance.vm_attributes.node]['exists'] = True
                self.state[instance.vm_attributes.node]['vmid'] = created_instance.vmid
        return any([self.state[node]['exists'] for node in self.nodes])


class ClusterMasterSerializer(ClusterInstanceSerializer):
    def __init__(
        self,
        config: dict,
        cluster_attributes: ClusterAttributes,
        templates: ClusterTemplateSerializer
    ):
        super().__init__(
            config=config,
            cluster_attributes=cluster_attributes,
        )
        self.templates = templates


class ClusterWorkerSerializer(ClusterInstanceSerializer):
    roles = []

    def __init__(
        self,
        config: dict,
        cluster_attributes: ClusterAttributes,
        templates: ClusterTemplateSerializer
    ):
        super().__init__(
            config=config,
            cluster_attributes=cluster_attributes,
        )
        self.templates = templates
        self.role = self.config.get('role') or 'default'
        self.roles.append(self.role)

    @classmethod
    def is_valid(cls):
        default_role = list(filter(lambda role: role == 'default', cls.roles))
        return len(default_role) <= 1
