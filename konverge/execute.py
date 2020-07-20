import pprint

# Pass Custom file
# from konverge.utils import set_pve_config_filename
# set_pve_config_filename('test.yml')

from konverge.kubecluster import KubeCluster, KubeClusterStages
from konverge import settings


def execute():
    cluster = KubeCluster(config=settings.kube_config)
    # cluster.execute(wait_period=240, destroy=True, stage=KubeClusterStages.create)
    # cluster.execute(dry_run=False, destroy=True, destroy_template=False)
    # cluster.execute(wait_period=120, stage=KubeClusterStages.post_installs)
    # cluster.execute(wait_period=240)
    from konverge.kube import KubeExecutor
    executor = KubeExecutor()
    print(executor.get_node_names(cluster=cluster.cluster))

    # cluster.execute(wait_period=240)
    # cluster.execute(wait_period=240, stage=KubeClusterStages.join)

    # Note: zfspool is much faster boot than NFS.