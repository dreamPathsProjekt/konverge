import logging
import crayons

from typing import Union

from proxmoxer import ProxmoxAPI

from konverge.utils import (
    Storage,
    VMAttributes
)


class ProxmoxAPIClient:
    def __init__(self, host, user, password, backend='https', verify_ssl=False):
        self.client = ProxmoxAPI(
            host=host,
            user=user,
            password=password,
            backend=backend,
            verify_ssl=verify_ssl
        )

    def get_resource_pools(self, name=None):
        if name:
            return [pool.get('poolid') for pool in self.client.pools.get() if pool.get('poolid') == name][0]
        return [pool.get('poolid') for pool in self.client.pools.get()]

    def get_or_create_pool(self, name):
        if name in self.get_resource_pools():
            return name
        self.client.pools.create(poolid=name)
        return self.get_resource_pools(name)

    def get_cluster_nodes(self, node=None, verbose=False):
        nodes = self.client.cluster.resources.get(type='node')
        if verbose:
            return nodes

        if node:
            nodes = [
                node_resource
                for node_resource in nodes
                if node_resource.get('node') == node
            ]

        return [
            {
                'name': node.get('node'),
                'status': node.get('status')
            }
            for node in nodes
        ]

    def get_cluster_vms(self, node=None, verbose=False):
        if node:
            node_resource = self.get_cluster_nodes(node)[0]
            vms = [vm for vm in self.client.nodes(node_resource['name']).qemu.get()]
        else:
            vms = self.client.cluster.resources.get(type='vm')

        if verbose:
            return vms
        return [
            {
                'vmid': vm.get('vmid'),
                'name': vm.get('name'),
                'status': vm.get('status')
            }
            for vm in vms
        ]

    def get_cluster_lxc(self, node=None, verbose=False):
        if node:
            node_resource = self.get_cluster_nodes(node)[0]
            lxcs = [lxc for lxc in self.client.nodes(node_resource['name']).lxc.get()]
        else:
            lxcs = self.client.cluster.resources.get(type='lxc')

        if verbose:
            return lxcs
        return [
            {
                'vmid': lxc.get('vmid'),
                'name': lxc.get('name'),
                'status': lxc.get('status')
            }
            for lxc in lxcs
        ]

    def _get_all_cluster_node_bridge_interfaces_verbose(self, node=None):
        if node:
            node_resource = self.get_cluster_nodes(node=node)[0]
            return self.client.nodes(node_resource['name']).network.get(type='bridge')
        return [
            self.client.nodes(node_resource['name']).network.get(type='bridge')
            for node_resource in self.get_cluster_nodes(node=node)
        ]

    def get_cluster_node_bridge_interfaces(self, node=None, verbose=False):
        def get_keys_from_iface(interface):
            return {
                'name': interface.get('iface'),
                'cidr': interface.get('cidr'),
                'gateway': interface.get('gateway'),
                'address': interface.get('address')
            }

        interfaces = self._get_all_cluster_node_bridge_interfaces_verbose(node=node)
        if verbose:
            return interfaces
        if node:
            return [get_keys_from_iface(interface) for interface in interfaces]
        return [[
            get_keys_from_iface(interface)
            for interface in interface_list] for interface_list in interfaces
        ]

    def _get_all_cluster_storage_verbose(self, type: Union[Storage, str] = None):
        if not type:
            return self.client.storage.get()
        if isinstance(type, str) and not Storage.has_value(type):
            logging.error(crayons.red(f'Invalid storage type: {type}'))
            return []
        return (
            self.client.storage.get(type=type)
        ) if isinstance(type, str) else (
            self.client.storage.get(type=type.value)
        )

    def get_cluster_storage(self, type: Union[Storage, str] = None, verbose=False):
        storages = self._get_all_cluster_storage_verbose(type=type)
        if verbose:
            return storages
        if storages:
            return [
                {
                    'name': storage.get('storage'),
                    'content': storage.get('content')
                }
                for storage in storages
            ]
        return []

    def get_storage_detail_path_content(self, type: Union[Storage, str] = None):
        storage_details = self.get_cluster_storage(type=type, verbose=True)[0]
        path = storage_details.get('path')
        content = storage_details.get('content').split(',')
        if type == Storage.zfspool.value or type == Storage.zfspool:
            path = storage_details.get('pool')
        return {
            'name': storage_details.get('storage'),
            'path': path,
            'content': content
        }

    def get_storage_content_items(self, node, type: Union[Storage, str] = None, verbose=False):
        node_resource = self.get_cluster_nodes(node)[0]
        storage_details = self.get_cluster_storage(type=type, verbose=True)[0]
        items = self.client.nodes(node_resource['name']).storage(storage_details['storage']).content.get()
        if verbose:
            return items
        return [
            {
                'name': item.get('volid').split('/')[-1] if type == Storage.nfs.value or type == Storage.nfs else item.get('name'),
                'volume': item.get('content'),
                'volid': item.get('volid')
            }
            for item in items
        ]

    def create_vm(self, vm_attributes: VMAttributes, vmid):
        node_resource = self.get_cluster_nodes(vm_attributes.node)[0]
        return self.client.nodes(node_resource['name']).qemu.create(
            vmid=vmid,
            acpi=1,
            agent=1,
            kvm=1,
            name=vm_attributes.name,
            description=vm_attributes.description,
            ostype='l26',
            pool=vm_attributes.pool,
            memory=vm_attributes.memory,
            ballon=vm_attributes.memory,
            sockets=1,
            cores=vm_attributes.cpus,
            storage=self.client.get_cluster_storage(type=vm_attributes.storage)[0].get('name'),
            net0=f'model=virtio,bridge=vmbr0,firewall=1'
        )
