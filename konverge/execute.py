import pprint

# Pass Custom file
# from konverge.utils import set_pve_config_filename
# set_pve_config_filename('test.yml')

from konverge.kubecluster import KubeCluster, KubeClusterStages
from konverge import settings


def execute():
    # cluster = KubeCluster(config=settings.kube_config)
    # cluster.execute(wait_period=240, destroy=True, stage=KubeClusterStages.create)
    # cluster.execute(dry_run=True, destroy=True, destroy_template=True)
    # cluster.execute(wait_period=120, stage=KubeClusterStages.post_installs)
    # cluster.execute(wait_period=480)

    from konverge.settings import vm_client
    from konverge.utils import StorageFormat, Storage

    resp = vm_client.clone_vm_from_template(
        name='full-clone-0',
        node='vhost3',
        source_vmid=3100,
        target_vmid=304,
        pool='development',
        full=True,
        storage=Storage.zfspool,
        format=StorageFormat.raw
    )
    print(resp)
    # TODO: pve client command works. Support option on schema and InstanceClone.
    # Note: zfspool is much faster boot than NFS.