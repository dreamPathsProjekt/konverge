import time

from konverge.settings import vm_client
from konverge.utils import VMAttributes, Storage, FabricWrapper
from konverge.cloudinit import CloudinitTemplate
from konverge.instance import InstanceClone
from konverge.queries import VMQuery
from konverge.kube import KubeProvisioner, ControlPlaneDefinitions, KubeExecutor

def execute():
    proxmox_node = FabricWrapper(host='vhost3.proxmox')
    template_attributes = VMAttributes(
        name='ubuntu18-kubernetes-template',
        node='vhost3',
        pool='development',
        os_type='ubuntu',
        storage_type=Storage.nfs,
        image_storage_type=Storage.nfs,
        ssh_keyname='/home/dritsas/.ssh/vhost3-vms',
        gateway='10.0.100.105'
    )
    ubuntu_template_factory = CloudinitTemplate.os_type_factory(template_attributes.os_type)
    ubuntu_template = ubuntu_template_factory(vm_attributes=template_attributes, client=vm_client, proxmox_node=proxmox_node)

    # Create Template with preinstall
    # ubuntu_template.execute()
    # ubuntu_template.execute(destroy=True)
    # Tested add and remove ssh config entries with local fabric object.

    # query = VMQuery(client=vm_client, name='po')
    # for instance in query.execute(node='vhost2'):
    #     print(vars(instance))
        # print(instance.generate_allowed_ip())

        # Needs agent installed
        # print(instance.client.agent_get_interfaces(node=instance.vm_attributes.node, vmid=instance.vmid))

        # print(vars(instance.vm_attributes))
        # print(instance.execute(destroy=True))
        # print(instance.backup_export(storage=Storage.nfs))

    # Create clones
    instances = []
    for i in range(3):
        query = VMQuery(client=vm_client, name=f'test-cluster-{i}')
        instance_clone = query.execute(node='vhost3')[0]

        # clone_attributes = VMAttributes(
        #     name=f'test-cluster-{i}',
        #     node='vhost3',
        #     pool='development',
        #     os_type='ubuntu',
        #     storage_type=Storage.nfs,
        #     disk_size=20,
        #     cpus=4,
        #     memory=16384,
        #     ssh_keyname='/home/dritsas/.ssh/vhost3-vms',
        #     gateway='10.0.100.105'
        # )
        #
        # instance_clone = InstanceClone(
        #     vm_attributes=clone_attributes,
        #     client=vm_client,
        #     proxmox_node=proxmox_node,
        #     template=ubuntu_template,
        #     # hotplug_disk_size=10
        # )
        # instance_clone.execute(start=True)
        # instances.append(instance_clone)

        instance_clone.execute(destroy=True)

    # Needs more time to initialize
    # time.sleep(120)

    # Single master flow
    # control_plane = ControlPlaneDefinitions()
    #
    # provisioner = KubeProvisioner.kube_provisioner_factory(os_type=instances[0].vm_attributes.os_type)(
    #     instance=instances[0],
    #     control_plane=control_plane
    # )
    # # provisioner.bootstrap_control_plane()
    #
    # joiner_1 = KubeProvisioner.kube_provisioner_factory(os_type=instances[1].vm_attributes.os_type)(
    #     instance=instances[1],
    #     control_plane=control_plane
    # )
    #
    # joiner_2 = KubeProvisioner.kube_provisioner_factory(os_type=instances[2].vm_attributes.os_type)(
    #     instance=instances[2],
    #     control_plane=control_plane
    # )
    #
    # joiner_1.join_node(leader=instances[0])
    # joiner_2.join_node(leader=instances[0])


    # HA masters flow
    # control_plane = ControlPlaneDefinitions(
    #     ha_masters=True
    # )
    # provisioner_leader = KubeProvisioner.kube_provisioner_factory(os_type=instances[0].vm_attributes.os_type)(
    #     instance=instances[0],
    #     control_plane=control_plane
    # )
    # virtual_ip = provisioner_leader.install_control_plane_loadbalancer(is_leader=True)
    #
    # if virtual_ip:
    #     # Following line is not needed
    #     control_plane.apiserver_ip = virtual_ip
    #     print(control_plane.apiserver_ip)
    #     provisioner_masters_1 = KubeProvisioner.kube_provisioner_factory(os_type=instances[1].vm_attributes.os_type)(
    #         instance=instances[1],
    #         control_plane=control_plane
    #     )
    #     provisioner_masters_2 = KubeProvisioner.kube_provisioner_factory(os_type=instances[2].vm_attributes.os_type)(
    #         instance=instances[2],
    #         control_plane=control_plane
    #     )
    #     provisioner_masters_1.install_control_plane_loadbalancer(is_leader=False)
    #     provisioner_masters_2.install_control_plane_loadbalancer(is_leader=False)
    #
    #     certificate_key = provisioner_leader.bootstrap_control_plane()
    #     provisioner_masters_1.join_node(leader=instances[0], control_plane_node=True, certificate_key=certificate_key)
    #     provisioner_masters_2.join_node(leader=instances[0], control_plane_node=True, certificate_key=certificate_key)

    # kube_executor = KubeExecutor(wrapper=instances[0].self_node)
    # kube_executor.add_local_cluster_config(
    #     custom_user_name='admin-test',
    #     custom_cluster_name='test-cluster',
    #     custom_context='test-context',
    #     set_current_context=True
    # )
    # kube_executor.deploy_dashboard(local=False)

