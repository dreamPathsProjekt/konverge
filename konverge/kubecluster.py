from typing import NamedTuple
from konverge.utils import KubeStorage, HelmVersion
from konverge.kube import ControlPlaneDefinitions


class HelmAtrributes(NamedTuple):
    version: HelmVersion = HelmVersion.v2
    local: bool = False
    tiller: bool = True


class ClusterAttributes(NamedTuple):
    name: str
    pool: str
    user: str = None
    context: str = None
    storage: KubeStorage = None
    loadbalancer: bool = True
    helm: HelmAtrributes = HelmAtrributes()


class KubeCluster:
    def __init__(self, cluster_config: dict):
        self.cluster_config = cluster_config
        self.name = self.cluster_config.get('name')
        self.control_plane = self._serialize_control_plane()
        self.cluster_attributes =self._serialize_cluster_attributes()

    def _serialize_cluster_attributes(self):
        user = self.cluster_config.get('user')
        context = self.cluster_config.get('context')
        storage = KubeStorage.return_value(self.cluster_config.get('storage'))
        loadbalancer = self.cluster_config.get('loadbalancer') or True
        helm_attributes = self.cluster_config.get('helm')
        if not helm_attributes:
            helm = HelmAtrributes()
        else:
            version = HelmVersion.return_value(helm_attributes.get('version')) or HelmVersion.v2
            local = helm_attributes.get('local') or False
            tiller = helm_attributes.get('tiller') or True
            helm = HelmAtrributes(
                version=version,
                local=local,
                tiller=tiller
            )
        return ClusterAttributes(
            name=self.cluster_config.get('name'),
            pool=self.cluster_config.get('pool'),
            user=user,
            context=context,
            storage=storage,
            loadbalancer=loadbalancer,
            helm=helm
        )

    def _serialize_control_plane(self):
        control_plane_definitions = ControlPlaneDefinitions()
        control_plane = self.cluster_config.get('control_plane')
        if not control_plane:
            return control_plane_definitions

        for key, value in control_plane.items():
            if key != 'apiserver':
                setattr(control_plane_definitions, key, value)
        apiserver = control_plane.get('apiserver')
        if not apiserver:
            return control_plane_definitions
        for key, value in apiserver.items():
            setattr(control_plane_definitions, f'apiserver_{key}', value)
        return control_plane_definitions





