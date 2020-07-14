from konverge.kuberunner import serializers, kube_runner_factory
from konverge.files import KubeClusterConfigFile
from konverge.utils import VMCategory, sleep_intervals


class KubeOrchestrator:
    def __init__(self, config: KubeClusterConfigFile):
        self.config = config.serialize()
        self.cluster = serializers.ClusterAttributesSerializer(self.config)
        self.control_plane = serializers.ControlPlaneSerializer(self.config)

        self.cluster.serialize()
        self.control_plane.serialize()

        self.templates = serializers.ClusterTemplateSerializer(
            config=self.config.get(VMCategory.template.value),
            cluster_attributes=self.cluster.cluster
        )
        self.templates.serialize()

        self.masters = serializers.ClusterMasterSerializer(
            config=self.config.get(VMCategory.masters.value),
            cluster_attributes=self.cluster.cluster,
            templates=self.templates
        )
        self.masters.serialize()

        self.workers = [
            serializers.ClusterWorkerSerializer(
                config=group,
                cluster_attributes=self.cluster.cluster,
                templates=self.templates
            )
            for group in self.config.get(VMCategory.workers.value)
        ]
        [worker.serialize() for worker in self.workers]

        self.runners = {
            VMCategory.template.value: kube_runner_factory(self.templates),
            VMCategory.masters.value: kube_runner_factory(self.masters),
            VMCategory.workers.value: [kube_runner_factory(worker) for worker in self.workers]
        }

    def wait(self, wait_period=120):
        sleep_intervals(wait_period)

    def create(self):
        for category, runners in self.runners:
            if category == VMCategory.workers.value:
                [runner.create() for runner in runners]
            else:
                runners.create()

    def destroy(self, template=False):
        for category, runners in self.runners:
            if template and category == VMCategory.template.value:
                runners.destroy()
            elif category == VMCategory.workers.value:
                [runner.destroy() for runner in runners]
            else:
                runners.destroy()

    def execute(self, destroy=False, template=False, wait_period=120):
        if not destroy:
            self.create()
            self.wait(wait_period)
        else:
            self.destroy(template=template)

