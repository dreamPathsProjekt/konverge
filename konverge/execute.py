import pprint

# Pass Custom file
# from konverge.utils import set_pve_config_filename
# set_pve_config_filename('test.yml')

from konverge.kubecluster import KubeCluster, KubeClusterStages
from konverge import settings


def execute():
    cluster = KubeCluster(config=settings.kube_config)
    # cluster.execute(wait_period=240, destroy=True, stage=KubeClusterStages.create)
    # cluster.execute(dry_run=True, destroy=True, destroy_template=True)
    cluster.execute(wait_period=120, stage=KubeClusterStages.post_installs)
    # cluster.execute(wait_period=480)