from proxmoxer import ProxmoxAPI


class ProxmoxAPIClient:
    def __init__(self, host, user, password, backend='https', verify_ssl=False):
        self.client = ProxmoxAPI(
            host=host,
            user=user,
            password=password,
            backend=backend,
            verify_ssl=verify_ssl
        )

    def get_all_cluster_nodes_verbose(self):
        return self.client.cluster.resources.get(type='node')

    def get_all_cluster_vms_verbose(self):
        return self.client.cluster.resources.get(type='vm')

    def get_all_cluster_lxc_verbose(self):
        return self.client.cluster.resources.get(type='lxc')

    def get_cluster_vms_by_node_verbose(self, node):
        node_resource = self.get_cluster_nodes(node)[0]
        return [vm for vm in self.client.nodes(node_resource['name']).qemu.get()]

    def get_cluster_lxc_by_node_verbose(self, node):
        node_resource = self.get_cluster_nodes(node)[0]
        return [lxc for lxc in self.client.nodes(node_resource['name']).lxc.get()]

    def get_all_cluster_node_interfaces_verbose(self, node=None):
        return [
            self.client.nodes(node_resource['name']).network.get()
            for node_resource in self.get_cluster_nodes(node=node)
        ]

    def get_cluster_nodes(self, node=None):
        if node:
            nodes = [
                node_resource
                for node_resource in self.get_all_cluster_nodes_verbose()
                if node_resource.get('node') == node
            ]
        else:
            nodes = self.get_all_cluster_nodes_verbose()
        return [
            {
                'name': node.get('node'),
                'status': node.get('status')
            }
            for node in nodes
        ]

    def get_cluster_vms(self, node=None):
        if node:
            vms = self.get_cluster_vms_by_node_verbose(node)
        else:
            vms = self.get_all_cluster_vms_verbose()
        return [
            {
                'vmid': vm.get('vmid'),
                'name': vm.get('name'),
                'status': vm.get('status')
            }
            for vm in vms
        ]

    def get_cluster_lxc(self, node=None):
        if node:
            lxcs = self.get_cluster_lxc_by_node_verbose(node)
        else:
            lxcs = self.get_all_cluster_lxc_verbose()
        return [
            {
                'vmid': lxc.get('vmid'),
                'name': lxc.get('name'),
                'status': lxc.get('status')
            }
            for lxc in lxcs
        ]

