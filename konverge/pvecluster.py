"""
Classes and functions for proxmox cluster-wide config.
"""
import logging
import crayons

from konverge.files import ProxmoxClusterConfigFile, ConfigSerializer
from konverge.utils import FabricWrapper


class ClusterConfig:
    def __init__(self, cluster_config: ProxmoxClusterConfigFile):
        self.cluster = cluster_config.serialize()

    @property
    def name(self):
        return self.cluster.name

    @property
    def gateway(self):
        if hasattr(self.cluster.network, 'gateway'):
            return self.cluster.network.gateway
        return ''

    @staticmethod
    def get_existing_node_attributes(node: ConfigSerializer):
        attributes = (
            'host',
            'user',
            'password',
            'ip',
            'key_filename',
            'key_passphrase',
            'port',
            'sudo'
        )
        return [attribute for attribute in attributes if hasattr(node, attribute)]

    @staticmethod
    def _host_and_ip_missing(node: ConfigSerializer, attributes_exist: list):
        predicate = not 'ip' in attributes_exist and not 'host' in attributes_exist
        if predicate:
            logging.error(crayons.red(f'Invalid entry for node {node.name}. At least a value of "host", "ip" is required.'))
        return predicate

    def get_nodes(self, namefilter=None):
        filtered_nodes = [node for node in self.cluster.nodes if namefilter and namefilter in node.name]
        nodes = filtered_nodes if namefilter else self.cluster.nodes

        if namefilter and not filtered_nodes:
            return []
        return nodes

    def get_node_ips(self, namefilter=None):
        node_ips = []
        for node in self.get_nodes(namefilter):
            attributes_exist = self.get_existing_node_attributes(node=node)
            if 'ip' in attributes_exist:
                node_ips.append(node.ip)
        return node_ips

    def get_network_base(self):
        if hasattr(self.cluster.network, 'base'):
            return self.cluster.network.base
        return None

    def get_allocated_ips_from_config(self, namefilter=None):
        allocated = set(self.get_node_ips(namefilter))
        network = self.get_network_base()
        if network:
            [allocated.add(f'{network}.{i}') for i in range(6)]
            allocated.add(f'{network}.255')
        if hasattr(self.cluster.network, 'gateway'):
            allocated.add(self.cluster.network.gateway)
        if hasattr(self.cluster.network, 'allocated'):
            [allocated.add(item) for item in self.cluster.network.allocated]
        return allocated

    def get_allowed_range(self):
        if hasattr(self.cluster.network, 'allowed_range'):
            return self.cluster.network.allowed_range.start, self.cluster.network.allowed_range.end
        return 6, 254

    def get_loadbalancer_range(self):
        if hasattr(self.cluster.network, 'loadbalancer_range'):
            return self.cluster.network.loadbalancer_range.start, self.cluster.network.loadbalancer_range.end
        return 6, 254

    def get_proxmox_ssh_connection_objects(self, namefilter=None):
        connections = []
        for node in self.get_nodes(namefilter):
            attributes_exist = self.get_existing_node_attributes(node=node)
            if 'host' in attributes_exist:
                connections.append(
                    FabricWrapper(host=node.host)
                )
                continue
            elif 'user' and 'password' in attributes_exist:
                if self._host_and_ip_missing(node, attributes_exist):
                    continue
                connections.append(
                    FabricWrapper(
                        host=node.host if 'host' in attributes_exist else node.ip,
                        user=node.user,
                        password=node.password,
                        port=node.port if 'port' in attributes_exist else 22,
                        sudo=node.sudo if 'sudo' in attributes_exist else False
                    )
                )
            elif 'user' and 'key_filename' in attributes_exist:
                if self._host_and_ip_missing(node, attributes_exist):
                    continue
                connections.append(
                    FabricWrapper(
                        host=node.host if 'host' in attributes_exist else node.ip,
                        user=node.user,
                        key_filename=node.key_filename,
                        key_passphrase=node.key_passphrase if 'key_passphrase' in attributes_exist else None,
                        port=node.port if 'port' in attributes_exist else 22,
                        sudo=node.sudo if 'sudo' in attributes_exist else False
                    )
                )
        return connections


