"""
Classes and functions for proxmox cluster-wide config.
"""
import logging
import crayons
import ipaddress

from konverge.files import ProxmoxClusterConfigFile, ConfigSerializer
from konverge.utils import FabricWrapper


class PVEClusterConfig:
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
                try:
                    ip = ipaddress.ip_address(node.ip)
                except ValueError as not_address:
                    logging.error(crayons.red(not_address))
                    continue
                node_ips.append(str(ip))
        return node_ips

    def get_network_base(self):
        if hasattr(self.cluster.network, 'base'):
            base = self.cluster.network.base
            network = None
            address = None
            try:
                network = ipaddress.ip_network(base)
            except ValueError as not_network:
                logging.warning(crayons.yellow(not_network))
                try:
                    address = ipaddress.ip_address(base)
                except ValueError as not_address:
                    logging.error(crayons.red(not_address))
                    return None
            if network:
                address = network.network_address
            if address:
                addr_list = str(address).split('.')
                addr_list.pop(-1)
                return '.'.join(addr_list)
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

    def loadbalancer_ip_range_to_string_or_list(self, dash=True):
        start, end = self.get_loadbalancer_range()
        base = self.get_network_base()
        if not base:
            logging.error(crayons.red('Base Network not found'))
            return None
        if dash:
            return f'{base}.{start}-{base}.{end}'
        ip_addresses = []
        for suffix in range(start, end + 1):
            ip_addresses.append(str(ipaddress.ip_address(f'{base}.{suffix}')))
        return  ip_addresses

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


