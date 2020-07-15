import pprint

# Pass Custom file
from konverge.utils import set_pve_config_filename
set_pve_config_filename('test.yml')

from konverge.kubecluster import KubeCluster
from konverge.files import KubeClusterConfigFile


def execute():
    cluster = KubeCluster(config=KubeClusterConfigFile())
    pprint.pprint(vars(cluster))
    # cluster.execute(wait_period=240)