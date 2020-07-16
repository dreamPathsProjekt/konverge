import pprint

# Pass Custom file
# from konverge.utils import set_pve_config_filename
# set_pve_config_filename('test.yml')

from konverge.kubecluster import KubeCluster, KubeClusterStages
from konverge import settings


def execute():
    cluster = KubeCluster(config=settings.kube_config)
    # cluster.execute(wait_period=240, stage=KubeClusterStages.create)
    # cluster.execute(dry_run=True, destroy=True, stage=KubeClusterStages.create)
    cluster.execute(dry_run=True, stage=KubeClusterStages.create)