from konverge import serializers


class KubeRunner:
    # TODO: Refactor dry-run blocks if possible.
    allocated_vmids: set = set()

    def __init__(self, serializer: serializers.ClusterInstanceSerializer):
        self.serializer = serializer

    def query(self):
        return self.serializer.query()

    @property
    def is_valid(self):
        return self.serializer.hotplug_valid

    @classmethod
    def set_allocated(cls, vmid):
        cls.allocated_vmids.add(int(vmid))

    @classmethod
    def unset_allocated(cls, vmid):
        cls.allocated_vmids.remove(int(vmid))

    def create(self, disable_backups=False, dry_run=False):
        if not self.is_valid:
            return
        exist = self.query()

        for instance in self.serializer.instances:
            state: list = self.serializer.state[instance.vm_attributes.node]

            print(serializers.crayons.cyan(f'Node: {instance.vm_attributes.node} - State: {state}'))
            match = lambda vm: vm.get('name') and vm.get('name') == instance.vm_attributes.name
            member = list(filter(match, state))[0]
            index = state.index(member) if member else None

            # Fix: do not use: ```if not index``` - ```index == 0``` is considered falsy.
            if index is None:
                serializers.logging.warning(
                    serializers.crayons.yellow(f'{instance.vm_attributes.name} not found in state. Skip create: {member}')
                )
                continue
            if exist and member.get('exists'):
                serializers.logging.warning(
                    serializers.crayons.yellow(f'{instance.vm_attributes.name} exists. Skip create: {member}')
                )
                continue
            instance.vmid, _ = instance.get_vmid_and_username(external=self.allocated_vmids)
            vmid = instance.execute(start=True, dry_run=dry_run)
            self.set_allocated(vmid)
            if disable_backups:
                instance.disable_backups()
            state[index] = {
                'name': instance.vm_attributes.name,
                'vmid': vmid,
                'exists': True
            }

    def destroy(self, dry_run=False):
        if not self.query():
            serializers.logging.warning(
                serializers.crayons.yellow(f'No {self.serializer.name} instances exist. Skip destroy.')
            )
            return

        for instance in self.serializer.instances:
            state: list = self.serializer.state[instance.vm_attributes.node]

            print(serializers.crayons.cyan(f'Node: {instance.vm_attributes.node} - State: {state}'))
            match = lambda vm: vm.get('vmid') == instance.vmid or vm.get('name') == instance.vm_attributes.name
            member = list(filter(match, state))[0]
            index = state.index(member) if member else None

            if index is None:
                serializers.logging.warning(
                    serializers.crayons.yellow(
                        f'{instance.vm_attributes.name} not found in state. Skip destroy: {member}')
                )
                continue
            if not member.get('exists'):
                serializers.logging.warning(
                    serializers.crayons.yellow(f'{instance.vm_attributes.name} does not exist. Skip destroy: {member}')
                )
                continue
            instance.execute(destroy=True, dry_run=dry_run)
            self.unset_allocated(instance.vmid)
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

    def create(self, disable_backups=False, dry_run=False):
        self.serializer: serializers.ClusterTemplateSerializer
        if not self.is_valid:
            return

        exist = self.query()
        for instance in self.serializer.instances:
            instance: serializers.CloudinitTemplate
            if exist and self.serializer.template_exists(instance.vm_attributes.node):
                serializers.logging.warning(
                    serializers.crayons.yellow(
                        f'{instance.vm_attributes.name} exists. Skip create: {self.serializer.state[instance.vm_attributes.node]}'
                    )
                )
                continue
            vmid = instance.execute(
                kubernetes_version=self.serializer.cluster_attributes.version,
                docker_version=self.serializer.cluster_attributes.docker,
                docker_ce=self.serializer.cluster_attributes.docker_ce,
                dry_run=dry_run
            )
            self.serializer.state[instance.vm_attributes.node]['exists'] = True
            self.serializer.state[instance.vm_attributes.node]['vmid'] = vmid

    def destroy(self, dry_run=False):
        self.serializer: serializers.ClusterTemplateSerializer
        if not self.query():
            return

        for instance in self.serializer.instances:
            instance: serializers.CloudinitTemplate
            if not self.serializer.template_exists(instance.vm_attributes.node):
                serializers.logging.warning(
                    serializers.crayons.yellow(
                        f'{instance.vm_attributes.name} does not exist. Skip destroy: {self.serializer.state[instance.vm_attributes.node]}'
                    )
                )
                continue
            # TODO: Template execute(destroy=True) does not remove templates. Uses destroy vm.
            instance.execute(
                kubernetes_version=self.serializer.cluster_attributes.version,
                docker_version=self.serializer.cluster_attributes.docker,
                docker_ce=self.serializer.cluster_attributes.docker_ce,
                dry_run=dry_run,
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
