import crayons
from typing import TYPE_CHECKING, List

# Avoid cyclic import
if TYPE_CHECKING:
    from konverge.instance import InstanceClone

from konverge.utils import KubeClusterAction, VMAttributes, colorize_yes_or_no


def create_update_or_delete(msg: str, action: KubeClusterAction = KubeClusterAction.create):
    if action == KubeClusterAction.create:
        return crayons.green(msg)
    if action == KubeClusterAction.update:
        return crayons.yellow(msg)
    if action == KubeClusterAction.delete or action == KubeClusterAction.recreate:
        return crayons.red(msg)
    return crayons.white(msg)


def get_action_symbol(action: KubeClusterAction):
    if action == KubeClusterAction.create:
        return '+++'
    if action == KubeClusterAction.delete:
        return '---'
    if action == KubeClusterAction.update:
        return '~'
    if action == KubeClusterAction.recreate:
        return '--++'
    return ''


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


def output_tools_settings(kube_cluster: 'KubeCluster'):
    settings_title = 'Kubernetes Tools'
    print(crayons.cyan(settings_title))
    print(crayons.cyan('=' * len(settings_title)))

    output_helm_options(kube_cluster)
    print(
        crayons.white('Deploy MetalLB Loadbalancer: ') +
        colorize_yes_or_no(
            msg='Yes' if kube_cluster.cluster_attributes.loadbalancer else 'No',
            yes=kube_cluster.cluster_attributes.loadbalancer
        )
    )
    if kube_cluster.cluster_attributes.loadbalancer:
        print(crayons.white('Loadbalancer Range: ') + crayons.yellow(kube_cluster.metallb_range))
        print(
            crayons.white(f'Storage Class Implementation: ') +
            crayons.yellow(f'{kube_cluster.cluster_attributes.storage.value}')
        )
        print('')


def output_helm_options(kube_cluster: 'KubeCluster'):
    print(crayons.white(f'Helm Version: {kube_cluster.cluster_attributes.helm.version.value}'))
    print(
        crayons.white('Initially Install Helm Locally: ') +
        colorize_yes_or_no(
            msg='Yes' if kube_cluster.cluster_attributes.helm.local else 'No',
            yes=kube_cluster.cluster_attributes.helm.local
        )
    )
    print(
        crayons.white('Initially Deploy Tiller: ') +
        colorize_yes_or_no(
            msg='Yes' if kube_cluster.cluster_attributes.helm.tiller else 'No',
            yes=kube_cluster.cluster_attributes.helm.tiller
        )
    )
    print('')


def output_templates(kube_cluster: 'KubeCluster', action: KubeClusterAction = KubeClusterAction.create):
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
    symbol = get_action_symbol(action)

    for node, template in kube_cluster.template.items():
        print(create_update_or_delete(msg=symbol, action=action))
        print(create_update_or_delete(f'*** {template.vm_attributes.name} ***', action=action))
        print(create_update_or_delete('Proxmox Node: ', action=action) + crayons.yellow(node))
        print(create_update_or_delete('VMID: ', action=action) + crayons.yellow(template.vmid))
        print(create_update_or_delete(f'Username: ', action=action) + crayons.yellow(f'{template.username}'))

        print(crayons.blue('PVE Storage'))
        print(create_update_or_delete(
            create_update_or_delete(f'Cloudinit Image Storage: {template.cloudinit_storage}, '
            f'Type: {template.vm_attributes.image_storage_type.value}'), action=action
        ))
        print(create_update_or_delete(f'Disk Storage: {template.storage}, Type: {template.vm_attributes.storage_type.value}', action=action))

        vm_output_helper(template.vm_attributes, action=action)
        print('')
        # print(crayons.white(f'  Allowed IP: {template.allowed_ip}'))


def output_masters(
        kube_cluster: 'KubeCluster',
        action: KubeClusterAction = KubeClusterAction.create,
        vmid_placeholder=9999
):
    masters_title = f'Cluster {kube_cluster.cluster_attributes.name} Master VMs'
    print(crayons.cyan(masters_title))
    print(crayons.cyan('=' * len(masters_title)))
    print('')
    common_instance_clones(kube_cluster.masters, action=action, role='master', vmid_placeholder=vmid_placeholder)


def output_worker_groups(
        kube_cluster: 'KubeCluster',
        action: KubeClusterAction = KubeClusterAction.create,
        vmid_placeholder=9999
):
    workers_title = f'Cluster {kube_cluster.cluster_attributes.name} Worker Groups VMs'
    print(crayons.cyan(workers_title))
    print(crayons.cyan('=' * len(workers_title)))
    print('')

    for role, workers in kube_cluster.workers.items():
        group_title = f'Group {role}'
        print(crayons.cyan(group_title))
        print(crayons.cyan('-' * len(group_title)))
        print('')
        common_instance_clones(workers, action=action, role=role, vmid_placeholder=vmid_placeholder)


def common_instance_clones(
        instances: List['InstanceClone'],
        action: KubeClusterAction = KubeClusterAction.create,
        role='master',
        vmid_placeholder=9999
):
    symbol = get_action_symbol(action)
    for instance in instances:
        if instance.vmid == vmid_placeholder:
            vmid = crayons.magenta('[Known after apply]')
        else:
            vmid = crayons.yellow(instance.vmid)
        print(create_update_or_delete(msg=symbol, action=action))
        print(create_update_or_delete(f'*** {instance.vm_attributes.name} ***', action=action))
        print(crayons.blue('Role: ') + crayons.yellow(role))
        print(create_update_or_delete('Proxmox Node: ', action=action) + crayons.yellow(instance.vm_attributes.node))
        print(create_update_or_delete(f'Username: ', action=action) + crayons.yellow(f'{instance.username}'))
        print(create_update_or_delete('VMID: ', action=action) + vmid)
        vm_output_helper(instance.vm_attributes, action=action)
        vm_output_hotplug_helper(instance, action=action)
        print('')


def vm_output_helper(vm: VMAttributes, action: KubeClusterAction = KubeClusterAction.create):
    print(crayons.blue('VM Attributes'))
    print(create_update_or_delete(f'Description: {vm.description}', action=action))
    print(create_update_or_delete(f'CPUs: {vm.cpus}', action=action))
    print(create_update_or_delete(f'Memory: {vm.memory} MB', action=action))
    print(create_update_or_delete(f'Root Disk Size: {vm.disk_size} GB', action=action))
    print(create_update_or_delete(f'Storage Driver: {"SCSI" if vm.scsi else "VirtIO"}', action=action))
    print(create_update_or_delete(f'Gateway: {vm.gateway}', action=action))
    print(create_update_or_delete(f'SSH KeyPair: ', action=action) + crayons.yellow(f'{vm.private_pem_ssh_key}, {vm.public_ssh_key}'))


def vm_output_hotplug_helper(vm: 'InstanceClone', action: KubeClusterAction = KubeClusterAction.create):
    hotplug = 'Yes' if vm.hotplug_disk_size else 'No'
    print(
        create_update_or_delete(msg='Hotplug: ', action=action) +
        colorize_yes_or_no(msg=hotplug, yes=(hotplug == 'Yes'))
    )
    if vm.hotplug_disk_size:
        print(create_update_or_delete(f'Hotplug Disk Size: {vm.hotplug_disk_size}', action=action))