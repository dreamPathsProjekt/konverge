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
    helm: HelmAtrributes = HelmAtrributes()


class ClusterInstance:
    def __init__(
        self,
        config: dict,
        category: VMCategory,
        control_plane: ControlPlaneDefinitions,
        cluster_attributes: ClusterAttributes
    ):
        self.config = config
        self.group = self.config.get(category)
        self.control_plane = control_plane
        self.cluster_attributes = cluster_attributes
        self.cluster_ssh_key = self.config.get('ssh_key')
        self.instances = []

        self.gateway = settings.pve_cluster_config_client.gateway
        self.name = self.group.get('name')
        self.scale = self.group.get('scale')
        self.node = self.group.get('node')
        self.cpus = self.group.get('cpus')
        self.memory = self.group.get('memory')
        self.disk = self.group.get('disk')
        self.scsi = self.group.get('scsi') or False
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
            category=VMCategory.template.value,
            control_plane=control_plane,
            cluster_attributes=cluster_attributes
        )
        self.nodes = self.node.split(',')
        self.storage_type, self.image_storage_type = self.get_pve_storage()
        self.names = {node: f'{node}-{self.name}' if self.name else None for node in self.nodes}

    @property
    def create(self):
        create = self.group.get('create')
        if create is not None:
            return create
        return True

    def template_exists(self):
        pass

    def get_pve_storage(self):
        pve_storage = self.group.get('pve_storage')
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
                name=self.names.get(node),
                node=node,
                pool=self.cluster_attributes.pool,
                os_type=self.cluster_attributes.os_type,
                storage_type=self.storage_type,
                image_storage_type=self.image_storage_type,
                scsi=self.scsi,
                ssh_keyname=self.cluster_ssh_key,
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

class ClusterMaster(ClusterInstance):
    def __init__(
        self,
        config: dict,
        control_plane: ControlPlaneDefinitions,
        cluster_attributes: ClusterAttributes
    ):
        super().__init__(
            config=config,
            category=VMCategory.masters.value,
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
            category=VMCategory.workers.value,
            control_plane=control_plane,
            cluster_attributes=cluster_attributes
        )

    def serialize(self):
        pass