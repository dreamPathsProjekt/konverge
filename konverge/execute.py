import pprint

# Pass Custom file
# from konverge.utils import set_pve_config_filename
# set_pve_config_filename('test.yml')

from konverge.kubecluster import KubeCluster, KubeClusterStages
from konverge import settings


def execute():
    cluster = KubeCluster(config=settings.kube_config)
    # pprint.pprint(cluster.masters.state)
    # pprint.pprint(cluster.templates.state)
    # pprint.pprint([worker.state for worker in cluster.workers])
    # pprint.pprint([vars(instance.vm_attributes) for instance in cluster.masters.instances])

    # Debug issue with workers execute element 0
    pprint.pprint([[instance.vm_attributes.name for instance in worker.instances] for worker in cluster.workers])
    pprint.pprint([[instance.vm_attributes.name for instance in runner.serializer.instances] for runner in cluster.runners.get('workers')])
    # cluster.execute(wait_period=240, stage=KubeClusterStages.create)
    cluster.execute(dry_run=True)
    [pprint.pprint(worker.state) for worker in cluster.workers]
    pprint.pprint(cluster.masters.state)