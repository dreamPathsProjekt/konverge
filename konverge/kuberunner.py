from konverge import serializers


class KubeRunner:
    def __init__(self, serializer: serializers.ClusterInstanceSerializer):
        self.serializer = serializer

    def query(self):
        return self.serializer.query()

    @property
    def is_valid(self):
        return self.serializer.hotplug_valid

    def create(self, disable_backups=False):
        if not self.is_valid:
            return

        exist = self.query()
        for instance in self.serializer.instances:
            state: list = self.serializer.state[instance.vm_attributes.node]

            for member in state:
                match = member.get('name') == instance.vm_attributes.name
                if not match:
                    continue
                if exist and member.get('exists'):
                    continue
                index = state.index(member)
                instance.vmid, _ = instance.get_vmid_and_username()
                vmid = instance.execute(start=True)
                if disable_backups:
                    instance.disable_backups()
                state[index] = {
                    'name': instance.vm_attributes.name,
                    'vmid': vmid,
                    'exists': True
                }

    def destroy(self):
        if not self.query():
            return

        for instance in self.serializer.instances:
            state: list = self.serializer.state[instance.vm_attributes.node]

            for member in state:
                match = member.get('vmid') == instance.vmid or member.get('name') == instance.vm_attributes.name
                if not match:
                    continue
                if not member.get('exists'):
                    continue
                index = state.index(member)
                instance.execute(destroy=True)
                state[index] = {
                    'name': instance.vm_attributes.name,
                    'vmid': serializers.settings.VMID_PLACEHOLDER,
                    'exists': False
                }


class KubeTemplateRunner(KubeRunner):
    def __init__(self, serializer: serializers.ClusterInstanceSerializer):
        super().__init__(serializer)

    @property
    def is_valid(self):
        self.serializer: serializers.ClusterTemplateSerializer
        return not all(
            [self.serializer.template_exists(node) for node in self.serializer.nodes]
        ) and self.serializer.hotplug_valid

    def create(self, disable_backups=False):
        self.serializer: serializers.ClusterTemplateSerializer
        if not self.is_valid:
            return

        exist = self.query()
        for instance in self.serializer.instances:
            instance: serializers.CloudinitTemplate
            if exist and self.serializer.template_exists(instance.vm_attributes.node):
                continue
            vmid = instance.execute(
                kubernetes_version=self.serializer.cluster_attributes.version,
                docker_version=self.serializer.cluster_attributes.docker,
                docker_ce=self.serializer.cluster_attributes.docker_ce
            )
            self.serializer.state[instance.vm_attributes.node]['exists'] = True
            self.serializer.state[instance.vm_attributes.node]['vmid'] = vmid

    def destroy(self):
        self.serializer: serializers.ClusterTemplateSerializer
        if not self.query():
            return

        for instance in self.serializer.instances:
            instance: serializers.CloudinitTemplate
            if not self.serializer.template_exists(instance.vm_attributes.node):
                continue
            instance.execute(
                kubernetes_version=self.serializer.cluster_attributes.version,
                docker_version=self.serializer.cluster_attributes.docker,
                docker_ce=self.serializer.cluster_attributes.docker_ce,
                destroy=True
            )
            self.serializer.state[instance.vm_attributes.node]['exists'] = False


class KubeMasterRunner(KubeRunner):
    def __init__(self, serializer: serializers.ClusterInstanceSerializer):
        super().__init__(serializer)


class KubeWorkerRunner(KubeRunner):
    def __init__(self, serializer: serializers.ClusterInstanceSerializer):
        super().__init__(serializer)

    @property
    def is_valid(self):
        return serializers.ClusterWorkerSerializer.is_valid() and self.serializer.hotplug_valid


def kube_runner_factory(serializer):
    types = {
        serializers.ClusterTemplateSerializer: KubeTemplateRunner(serializer),
        serializers.ClusterMasterSerializer: KubeMasterRunner(serializer),
        serializers.ClusterWorkerSerializer: KubeWorkerRunner(serializer)
    }
    return types.get(type(serializer))
