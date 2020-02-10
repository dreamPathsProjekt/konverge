import logging
import urllib.parse

import crayons

from proxmoxer import ProxmoxAPI
from proxmoxer.core import ResourceException

from konverge.utils import (
    Storage,
    VMAttributes,
    BootMedia
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

    @staticmethod
    def api_client_factory(instance_type='vm'):
        types = {
            'vm': VMAPIClient,
            'lxc': LXCAPIClient
        }
        return types.get(instance_type)

    def get_resource_pools(self, name=None):
        if name:
            return [pool.get('poolid') for pool in self.client.pools.get() if pool.get('poolid') == name][0]
        return [pool.get('poolid') for pool in self.client.pools.get()]

    def get_or_create_pool(self, name):
        if not name or (name in self.get_resource_pools()):
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

    def _get_single_node_resource(self, node):
        return self.get_cluster_nodes(node)[0]

    def get_cluster_vms(self, node=None, verbose=False):
        if node:
            node_resource = self._get_single_node_resource(node)
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
            node_resource = self._get_single_node_resource(node)
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

    def _get_all_cluster_storage_verbose(self, storage_type: Storage = None):
        if not storage_type:
            return self.client.storage.get()
        return self.client.storage.get(type=storage_type.value)

    def get_cluster_storage(self, storage_type: Storage = None, verbose=False):
        storages = self._get_all_cluster_storage_verbose(storage_type=storage_type)
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

    def get_storage_detail_path_content(self, storage_type: Storage = None):
        storage_details = self.get_cluster_storage(storage_type=storage_type, verbose=True)[0]
        path = storage_details.get('path')
        content = storage_details.get('content').split(',')
        if storage_type == Storage.zfspool:
            path = storage_details.get('pool')
        return {
            'name': storage_details.get('storage'),
            'path': path,
            'content': content
        }

    def get_storage_content_items(self, node, storage_type: Storage = None, verbose=False):
        node_resource = self.get_cluster_nodes(node)[0]
        storage_details = self.get_cluster_storage(storage_type=storage_type, verbose=True)[0]
        items = self.client.nodes(node_resource['name']).storage(storage_details['storage']).content.get()
        if verbose:
            return items
        return [
            {
                'name': item.get('volid').split('/')[-1] if storage_type == Storage.nfs else item.get('name'),
                'volume': item.get('content'),
                'volid': item.get('volid')
            }
            for item in items
        ]


class VMAPIClient(ProxmoxAPIClient):
    def create_vm(self, vm_attributes: VMAttributes, vmid):
        node_resource = self._get_single_node_resource(vm_attributes.node)
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
            balloon=vm_attributes.memory,
            sockets=1,
            cores=vm_attributes.cpus,
            storage=self.get_cluster_storage(storage_type=vm_attributes.storage_type)[0].get('name'),
            net0=f'model=virtio,bridge=vmbr0,firewall=1'
        )

    def start_vm(self, node, vmid):
        node_resource = self._get_single_node_resource(node)
        return self.client.nodes(node_resource['name']).qemu(vmid).status.start.post()

    def shutdown_vm(self, node, vmid, timeout=20):
        node_resource = self._get_single_node_resource(node)
        return self.client.nodes(node_resource['name']).qemu(vmid).status.shutdown.post(timeout=timeout)

    def stop_vm(self, node, vmid, timeout=20):
        node_resource = self._get_single_node_resource(node)
        return self.client.nodes(node_resource['name']).qemu(vmid).status.stop.post(timeout=timeout)

    def destroy_vm(self, node, vmid):
        node_resource = self._get_single_node_resource(node)
        return self.client.nodes(node_resource['name']).qemu(vmid).delete()

    def export_vm_template(self, node, vmid):
        node_resource = self._get_single_node_resource(node)
        self.client.nodes(node_resource['name']).qemu(vmid).template.post()

    def clone_vm_from_template(self, node, source_vmid, target_vmid, name='', description=''):
        """
        Parameter full creates a full disk clone of VM. For templates default is False: creates a linked clone.
        """
        node_resource = self._get_single_node_resource(node)
        qemu_instance = self.client.nodes(node_resource['name']).qemu(source_vmid)
        return qemu_instance.clone.create(
            newid=target_vmid,
            name=name,
            description=description
        )

    def get_vm_config(self, node, vmid, current=True):
        current_values = int(current)
        node_resource = self._get_single_node_resource(node)
        return self.client.nodes(node_resource['name']).qemu(vmid).config.get(current=current_values)

    def update_vm_config(self, node, vmid, storage_operation=False, **vm_kwargs):
        node_resource = self._get_single_node_resource(node)
        operation = (
            self.client.nodes(node_resource['name']).qemu(vmid).config.post
        ) if storage_operation else (
            self.client.nodes(node_resource['name']).qemu(vmid).config.put
        )
        return operation(**vm_kwargs)

    def enable_hotplug(self, node, vmid, hotplug='1', disable=False):
        try:
            return self.update_vm_config(
                node=node,
                vmid=vmid,
                storage_operation=True,
                hotplug='0' if disable else hotplug
            )
        except ResourceException as invalid:
            logging.error(invalid)
            return None

    def attach_volume_to_vm(self, node, vmid, volume, scsihw='virtio-scsi-pci', scsi=False, disk_size=5, drive_slot='0'):
        volume_details = f'file={volume},size={disk_size}G'
        return self.update_vm_config(
            node=node,
            vmid=vmid,
            storage_operation=True,
            scsihw=scsihw,
            **{f'scsi{drive_slot}': volume_details}
        ) if scsi else self.update_vm_config(
            node=node,
            vmid=vmid,
            storage_operation=True,
            scsihw=scsihw,
            **{f'virtio{drive_slot}': volume_details}
        )

    def add_cloudinit_drive(self, node, vmid, storage_name, drive_slot=2):
        return self.update_vm_config(
            node=node,
            vmid=vmid,
            storage_operation=True,
            **{f'ide{drive_slot}': storage_name}
        )

    def set_boot_disk(self, node, vmid, driver, boot: BootMedia = BootMedia.hard_disk):
        return self.update_vm_config(
            node=node,
            vmid=vmid,
            storage_operation=True,
            boot=boot.value,
            bootdisk=driver
        )

    def resize_disk(self, node, vmid, driver='virtio0', disk_size=5):
        node_resource = self._get_single_node_resource(node)
        self.client.nodes(node_resource['name']).qemu(vmid).resize.put(
            disk=driver,
            size=f'{disk_size}G'
        )

    def inject_vm_cloudinit(self, node, vmid, ssh_key_content, vm_ip, gateway, netmask='24'):
        if ssh_key_content and vm_ip and gateway:
            return self.update_vm_config(
                node=node,
                vmid=vmid,
                sshkeys=urllib.parse.quote(ssh_key_content, safe=''),
                ipconfig0=f'ip={vm_ip}/{netmask},gw={gateway}'
            )
        elif ssh_key_content and (not vm_ip or not gateway):
            self.update_vm_config(
                node=node,
                vmid=vmid,
                sshkeys=urllib.parse.quote(ssh_key_content, safe=''),
                delete='ipconfig0'
            )
        return self.update_vm_config(
            node=node,
            vmid=vmid,
            delete='sshkeys,ipconfig0'
        )

    def get_ip_config_from_vm_cloudinit(self, node, vmid, ipconfig_slot=0):
        config = self.get_vm_config(node, vmid, current=False)
        ip_config = config.get(f'ipconfig{ipconfig_slot}')

        if not ip_config or not ip_config.strip():
            return None, None, None

        ip, gw = ip_config.split(',')
        ip_address, netmask = ip.split('/')
        ip_address = ip_address.split('=')[-1]
        gateway = gw.split('=')[-1]
        return ip_address, netmask, gateway

    def agent_get_interfaces(self, node, vmid, verbose=False, filter_lo=True):
        node_resource = self._get_single_node_resource(node)
        try:
            response = self.client.nodes(node_resource['name']).qemu(vmid).agent.get('network-get-interfaces')
        except ResourceException as agent_not_running:
            logging.error(crayons.red(f'Qemu guest agent is not running in {vmid}'))
            logging.error(crayons.red(agent_not_running))
            return None
        if verbose:
            return response

        stripped = [
            {
                'name': result.get('name'),
                'ip_addresses': [address.get('ip-address') for address in result.get('ip-addresses') if
                                 address.get('ip-address-type') == 'ipv4']
            }
            for result in response.get('result')
        ]
        filtered = list(filter(lambda iface: iface.get('name') != 'lo', stripped))
        return filtered if filter_lo else stripped


class LXCAPIClient(ProxmoxAPIClient):
    pass