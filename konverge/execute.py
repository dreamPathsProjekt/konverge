import pprint

# Pass Custom file
# from konverge.utils import set_pve_config_filename
# set_pve_config_filename('test.yml')

from konverge.kubecluster import KubeCluster, KubeClusterStages
from konverge import settings


def execute():
    cluster = KubeCluster(config=settings.kube_config)
    pprint.pprint(cluster.masters.state)
    pprint.pprint(cluster.templates.state)
    pprint.pprint([worker.state for worker in cluster.workers])
    pprint.pprint([vars(instance.vm_attributes) for instance in cluster.masters.instances])
    cluster.execute(wait_period=240, stage=KubeClusterStages.create)