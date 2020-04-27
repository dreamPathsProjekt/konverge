import crayons
from typing import TYPE_CHECKING

# Avoid cyclic import
if TYPE_CHECKING:
    from konverge.kubecluster import KubeCluster
    from konverge.instance import InstanceClone

from konverge.utils import VMAttributes, colorize_yes_or_no


def output_cluster(kube_cluster: 'KubeCluster'):
    title = f'Cluster: {kube_cluster.cluster_attributes.name}'
    print(crayons.cyan(title))
    print(crayons.cyan('=' * len(title)))
    attributes = (
        f'Kubernetes Version: {kube_cluster.cluster_attributes.version}',
        f'Docker Version: {kube_cluster.cluster_attributes.docker}',
        f'Proxmox Node Pool: {kube_cluster.cluster_attributes.pool}',
        f'OS Type: {kube_cluster.cluster_attributes.os_type}',
    )
    print(crayons.white('\n'.join(attributes)))
    print('')


def output_config(kube_cluster: 'KubeCluster'):
    cluster_config_title = f'Cluster Config'
    print(crayons.cyan(cluster_config_title))
    print(crayons.cyan('=' * len(cluster_config_title)))
    cluster_config = (
        f'Context: {kube_cluster.cluster_attributes.context}',
        f'User: {kube_cluster.cluster_attributes.user}'
    )
    print(crayons.white('\n'.join(cluster_config)))
    print('')


def output_control_plane(kube_cluster: 'KubeCluster'):
    control_plane_title = f'Control Plane Settings'
    print(crayons.cyan(control_plane_title))
    print(crayons.cyan('=' * len(control_plane_title)))
    print(
        crayons.white('High Availability: ') +
        colorize_yes_or_no(
            msg='Yes' if kube_cluster.control_plane.ha_masters else 'No',
            yes=kube_cluster.control_plane.ha_masters)
    )
    print(crayons.white(f'Networking: {kube_cluster.control_plane.networking}'))
    if not kube_cluster.control_plane.apiserver_ip:
        ip = crayons.magenta('[Known after apply]')
    else:
        ip = kube_cluster.control_plane.apiserver_ip
    print(crayons.white(f'Api Server: {ip}:{kube_cluster.control_plane.apiserver_port}'))
    print('')


def output_templates(kube_cluster: 'KubeCluster'):
    template_title = f'Cluster {kube_cluster.cluster_attributes.name} VM Templates'
    print(crayons.cyan(template_title))
    print(crayons.cyan('=' * len(template_title)))
    print(
        crayons.white('Generate: ') +
        colorize_yes_or_no(
            msg='Yes' if kube_cluster.template_creation else 'No',
            yes=kube_cluster.template_creation
        )
    )
    print(crayons.cyan('-' * len(template_title)))
    print('')

    for node, template in kube_cluster.template.items():
        print(crayons.green(f'*** {template.vm_attributes.name} ***'))
        print(crayons.white('Proxmox Node: ') + crayons.yellow(node))
        print(crayons.white('VMID: ') + crayons.yellow(template.vmid))
        print(crayons.white(f'Username: ') + crayons.yellow(f'{template.username}'))

        print(crayons.blue('PVE Storage'))
        print(crayons.white(
            f'Cloudinit Image Storage: {template.cloudinit_storage}, '
            f'Type: {template.vm_attributes.image_storage_type.value}'
        ))
        print(crayons.white(f'Disk Storage: {template.storage}, Type: {template.vm_attributes.storage_type.value}'))

        vm_output_helper(template.vm_attributes)
        print('')
        # print(crayons.white(f'  Allowed IP: {template.allowed_ip}'))


def vm_output_helper(vm: VMAttributes):
    print(crayons.blue('VM Attributes'))
    print(crayons.white(f'Description: {vm.description}'))
    print(crayons.white(f'CPUs: {vm.cpus}'))
    print(crayons.white(f'Memory: {vm.memory} MB'))
    print(crayons.white(f'Root Disk Size: {vm.disk_size} GB'))
    print(crayons.white(f'Storage Driver: {"SCSI" if vm.scsi else "VirtIO"}'))
    print(crayons.white(f'Gateway: {vm.gateway}'))
    print(crayons.white(f'SSH KeyPair: ') + crayons.yellow(f'{vm.private_pem_ssh_key}, {vm.public_ssh_key}'))


def vm_output_hotplug_helper(vm: 'InstanceClone'):
    hotplug = 'Yes' if vm.hotplug_disk_size else 'No'
    print(
        crayons.white('Hotplug: ') +
        colorize_yes_or_no(msg=hotplug, yes=(hotplug == 'Yes'))
    )
    if vm.hotplug_disk_size:
        print(crayons.white(f'Hotplug Disk Size: {vm.hotplug_disk_size}'))