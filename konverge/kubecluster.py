from konverge.kube import ControlPlaneDefinitions


class KubeCluster:
    def __init__(self, cluster_config: dict):
        self.cluster_config = cluster_config
        self.name = self.cluster_config.get('name')
        self.control_plane = self._serialize_control_plane()

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