import os
import crayons
import logging

from konverge.pve import VMAPIClient
from konverge.utils import (
    VMAttributes,
    FabricWrapper,
    Storage,
    BootMedia,
    get_id_prefix,
    add_ssh_config_entry,
    remove_ssh_config_entry,
    clear_server_entry,
    sleep_intervals,
    LOCAL
)
from konverge import settings


class CommonVMMixin:
    """
    Mixin class attributes only declared as types.
    No instantiation of attributes on class level.
    """
    vm_attributes: VMAttributes
    client: VMAPIClient
    proxmox_node: FabricWrapper
    vmid: str
    driver: str
    unused_driver: str
    storage: str
    username: str
    allowed_ip: str

    def _update_description(self):
        self.vm_attributes.description = ''

    def _get_storage_details(self, image=False):
        storage_type = self.vm_attributes.image_storage_type if image else self.vm_attributes.storage_type
        storage_details = self.client.get_storage_detail_path_content(storage_type=storage_type)
        directory = 'images' if 'images' in storage_details.get('content') else ''
        path = storage_details.get('path')
        location = os.path.join(path if path else '', directory)
        storage = storage_details.get('name')
        return storage, storage_details, location

    @property
    def running(self):
        vms = self.client.get_cluster_vms(node=self.vm_attributes.node)
        if not vms:
            return False
        return list(filter(lambda vm: int(self.vmid) == int(vm.get('vmid')), vms))[0].get('status') == 'running'

    def generate_vmid_and_username(self, id_prefix, preinstall=True, external: set = None):
        raise NotImplementedError

    def get_vmid_and_username(self, external: set = None):
        id_prefix = get_id_prefix(proxmox_node_scale=settings.node_scale, node=self.vm_attributes.node)
        return self.generate_vmid_and_username(id_prefix=id_prefix, external=external)

    def get_vm_config(self):
        return self.client.get_vm_config(node=self.vm_attributes.node, vmid=self.vmid)

    def get_storage_from_config(self, driver):
        config = self.get_vm_config()
        volume = config.get(driver) if config else None
        return volume.split(',')[0].strip() if volume else None

    def get_storage(self, unused=False):
        driver = self.unused_driver if unused else self.driver
        return self.get_storage_from_config(driver)

    def get_storage_from_cluster_type(self, storage: Storage = None):
        storages = self.client.get_cluster_storage(verbose=True)
        for storage_result in storages:
            if storage and storage_result.get('type') == storage.value:
                return storage_result.get('storage')
            elif storage_result.get('type') == self.vm_attributes.storage_type.value:
                return storage_result.get('storage')

    def generate_allowed_ip(self):
        network = settings.pve_cluster_config_client.get_network_base()
        loadbalancer = settings.pve_cluster_config_client.loadbalancer_ip_range_to_string_or_list(dash=False)
        start, end = settings.pve_cluster_config_client.get_allowed_range()
        allocated = settings.pve_cluster_config_client.get_allocated_ips_from_config(namefilter=self.vm_attributes.node)
        # Arp-scan
        allocated.update(self.get_allocated_ips_per_node_interface())
        # Cloudinit allocated, includes stopped vms.
        allocated.update(self.client.get_all_vm_allocated_ips_all_nodes())
        # Include lb range if exists.
        allocated.update(loadbalancer)
        print(crayons.white(f'All allocated ips: {allocated}'))

        for subnet_ip in range(start, end):
            generated_ip = f'{network}.{subnet_ip}'
            if generated_ip in allocated and subnet_ip == end:
                logging.error(crayons.red(f'Cannot create any more IP addresses in range: {network}.{start} - {network}.{end}'))
                return None
            if generated_ip in allocated:
                logging.warning(crayons.yellow(f'Exists: {generated_ip}'))
            if generated_ip not in allocated:
                print(crayons.green(f'Generated IP: {generated_ip}'))
                return generated_ip

    def get_allocated_ips_per_node_interface(self):
        interfaces = self.client.get_cluster_node_bridge_interfaces(self.vm_attributes.node)
        bridges = [
            (
                interface.get('name'),
                interface.get('cidr')
            )
            for interface in interfaces
            if interface.get('cidr') and interface.get('address')
        ]
        allocated_set = set()
        for bridge in bridges:
            interface, cidr = bridge
            arp_scan_exists = self.proxmox_node.execute('command arp-scan --help; echo $?', hide=True)
            exit_code = arp_scan_exists.stdout.split()[-1].strip()
            if exit_code != '0':
                print(crayons.cyan('arp-scan not found. Installing.'))
                self.proxmox_node.execute('apt-get install -y arp-scan')
            awk_routine = "'{print $1}'"
            ips = self.proxmox_node.execute(
                f'arp-scan --interface={interface} {cidr} | awk {awk_routine}', hide=False
            ).stdout.split()[2:-2]
            [allocated_set.add(ip) for ip in ips]
        print(crayons.white(f'Allocated running: {allocated_set}'))
        return allocated_set

    def create_vm(self):
        pool = self.client.get_or_create_pool(self.vm_attributes.pool)
        print(crayons.cyan(f'Resource pool: {pool}'))
        created = self.client.create_vm(
            vm_attributes=self.vm_attributes,
            vmid=self.vmid
        )
        if not self.log_create_delete(created):
            return created
        self.add_ssh_config_entry()
        return created

    def destroy_vm(self):
        self.remove_ssh_config_entry()
        deleted = self.client.destroy_vm(
            node=self.vm_attributes.node,
            vmid=self.vmid
        )

        if not self.log_create_delete(deleted, destroy=True):
            return deleted
        return deleted

    def log_create_delete(self, response, destroy=False):
        prefix = 'Create' if not destroy else 'Destroy'
        if not response:
            logging.error(crayons.red(f'Failed to {prefix} VM: {self.vm_attributes.name} {self.vmid} on node {self.vm_attributes.node}'))
        else:
            print(crayons.green(f'{prefix} VM {self.vm_attributes.name} {self.vmid} on node {self.vm_attributes.node}: Success'))
        return response

    def attach_volume_to_vm(self, volume, root_volume=True, disk_size=5, drive_slot='0'):
        return self.client.attach_volume_to_vm(
            node=self.vm_attributes.node,
            vmid=self.vmid,
            scsi=self.vm_attributes.scsi,
            volume=volume,
            disk_size=self.vm_attributes.disk_size if root_volume else disk_size,
            drive_slot=drive_slot
        )

    def enable_hotplug(self, hotplug='1'):
        return self.client.enable_hotplug(
            node=self.vm_attributes.node,
            vmid=self.vmid,
            hotplug=hotplug
        )

    def disable_hotplug(self):
        return self.client.enable_hotplug(
            node=self.vm_attributes.node,
            vmid=self.vmid,
            disable=True
        )

    def get_unallocated_disk_slots(self):
        max_drives = 20
        slots = [i for i in range(max_drives)]
        for slot in slots:
            driver = f'scsi{slot}' if self.vm_attributes.scsi else f'virtio{slot}'
            volume = self.get_storage_from_config(driver)
            if volume:
                logging.warning(crayons.yellow(f'Found allocated volume: {driver}'))
            else:
                print(crayons.green(f'Using Unallocated volume: {driver}'))
                return slot, driver

    def attach_hotplug_drive(self, disk_size=20):
        slot, driver = self.get_unallocated_disk_slots()
        print(crayons.cyan(f'Attaching new volume volume type: {self.storage} on driver: {driver}'))
        attach = self.proxmox_node.execute(f'qm set {self.vmid} --{driver} {self.storage}:{disk_size}')
        if attach.failed:
            logging.error(crayons.red(f'Failed to attach {driver} for VM: {self.vmid}'))
            return
        print(crayons.green(f'Attached {driver} for VM: {self.vmid}'))

    def add_cloudinit_drive(self, drive_slot='2'):
        return self.client.add_cloudinit_drive(
            node=self.vm_attributes.node,
            vmid=self.vmid,
            storage_name=f'{self.storage}:cloudinit',
            drive_slot=drive_slot
        )

    def set_boot_disk(self):
        return self.client.set_boot_disk(
            node=self.vm_attributes.node,
            vmid=self.vmid,
            boot=BootMedia.hard_disk,
            driver=self.driver
        )

    def resize_disk(self):
        self.client.resize_disk(
            node=self.vm_attributes.node,
            vmid=self.vmid,
            driver=self.driver,
            disk_size=self.vm_attributes.disk_size
        )

    def set_vga_display(self):
        """
        Set VGA display. Many Cloud-Init images rely on this, as it is an requirement for OpenStack images.
        """
        self.client.update_vm_config(
            node=self.vm_attributes.node,
            vmid=self.vmid,
            storage_operation=False,
            serial0='socket',
            vga='serial0'
        )

    def start_vm(self):
        if self.running:
            print(crayons.green(f'VM {self.vmid} is already running'))
            return self.vmid
        return self.client.start_vm(
            node=self.vm_attributes.node,
            vmid=self.vmid
        )

    def stop_vm(self):
        if not self.running:
            print(crayons.green(f'VM {self.vmid} is already stopped'))
            return self.vmid
        return self.client.stop_vm(
            node=self.vm_attributes.node,
            vmid=self.vmid
        )

    def export_template(self):
        self.client.export_vm_template(
            node=self.vm_attributes.node,
            vmid=self.vmid
        )

    def inject_cloudinit_values(self, invalidate=False):
        if invalidate:
            self.client.inject_vm_cloudinit(
                node=self.vm_attributes.node,
                vmid=self.vmid,
                ssh_key_content=None,
                vm_ip=None,
                gateway=None
            )
            return
        if not self.vm_attributes.public_key_exists:
            logging.error(crayons.red(f'Public key: {self.vm_attributes.public_ssh_key} does not exist. Abort'))
            return
        if not self.vm_attributes.private_pem_ssh_key_exists:
            logging.warning(
                crayons.yellow(
                    f'Private key {self.vm_attributes.private_pem_ssh_key} does not exist in the same location as: {self.vm_attributes.public_ssh_key}.'
                )
            )
        self.create_allowed_ip_if_not_exists()
        gateway = self.vm_attributes.gateway if self.vm_attributes.gateway else settings.pve_cluster_config_client.gateway

        print(crayons.blue(f'Inject cloudinit values ipconfig: ip={self.allowed_ip}, gateway={gateway}, sshkeys: {self.vm_attributes.public_ssh_key}'))
        self.client.inject_vm_cloudinit(
            node=self.vm_attributes.node,
            vmid=self.vmid,
            ssh_key_content=self.vm_attributes.read_public_key(),
            vm_ip=self.allowed_ip,
            gateway=gateway
        )

    def create_allowed_ip_if_not_exists(self):
        if not self.allowed_ip:
            logging.warning(crayons.yellow(f'Allowed ip does not exist.'))
            self.allowed_ip = self.generate_allowed_ip()

    def add_ssh_config_entry(self):
        self.create_allowed_ip_if_not_exists()
        add_ssh_config_entry(
            host=self.vm_attributes.name,
            user=self.username,
            identity=self.vm_attributes.private_pem_ssh_key,
            ip=self.allowed_ip
        )
        clear_server_entry(self.allowed_ip)

    def remove_ssh_config_entry(self):
        ip_address, netmask, gateway = self.client.get_ip_config_from_vm_cloudinit(
            node=self.vm_attributes.node,
            vmid=self.vmid
        )
        remove_ssh_config_entry(
            host=self.vm_attributes.name,
            user=self.username,
            ip=ip_address
        )
        clear_server_entry(ip_address)

    def install_kube(
            self,
            filename='req_ubuntu.sh',
            kubernetes_version='1.16.3-00',
            docker_version='18.09.7',
            docker_ce=False,
            storageos_requirements=False
    ):
        local = LOCAL
        host = self.vm_attributes.name
        template_host = FabricWrapper(host=host)
        template_host_sudo = FabricWrapper(host=host, sudo=True)

        file = filename
        dashboard_file = 'dashboard-adminuser.yaml'
        daemon_file = 'daemon.json'

        local_path = os.path.join(settings.BASE_PATH, f'bootstrap/{file}')
        local_dashboard_path = os.path.join(settings.BASE_PATH, f'bootstrap/{dashboard_file}')
        local_daemon_path = os.path.join(settings.BASE_PATH, f'bootstrap/{daemon_file}')
        remote_path = f'/opt/kube/bootstrap'
        docker_flavour = 'DOCKER_CE=1' if docker_ce else ''

        print(crayons.white(f'Current workdir: {settings.BASE_PATH}'))

        print(crayons.cyan(f'Copying files {file}, {dashboard_file}, {daemon_file}'))
        template_host_sudo.execute(f'mkdir -p {remote_path}')
        template_host_sudo.execute(f'chown -R $USER:$USER {remote_path}')
        sent1 = local.run(f'scp {local_path} {host}:{remote_path}')
        sent2 = local.run(f'scp {local_dashboard_path} {host}:{remote_path}')
        sent3 = local.run(f'scp {local_daemon_path} {host}:{remote_path}')
        if not sent1.ok or not sent2.ok or not sent3.ok:
            logging.error(crayons.red(f'Failed to sent files {file}, {dashboard_file}, {daemon_file}'))
            return

        print(crayons.blue(f'Installing kubectl, kubeadm, kubelet & docker CR on {host}.'))
        print(crayons.cyan(f'Kubernetes Version: {kubernetes_version}. Docker Version: {docker_version}'))
        template_host.execute(f'chmod +x {remote_path}/{file}')
        installed = template_host.execute(
            f'DAEMON_JSON_LOCATION={remote_path} KUBE_VERSION={kubernetes_version} DOCKER_VERSION={docker_version} {docker_flavour} {remote_path}/{file}',
            warn=True
        )
        if installed.ok:
            print(crayons.green(f'Installed pre-requisites on {host}'))
        else:
            logging.error(crayons.red(f'Pre-requisites on {host} failed to install.'))
            return

        if storageos_requirements:
            self.install_storageos_requirements()

    def install_storageos_requirements(self):
        pass

    def dry_run(self, destroy=False, instance=True):
        color = crayons.red if destroy else crayons.green
        prefix = 'Destroy' if destroy else 'Create'
        title = f'{prefix} VM {self.vm_attributes.name}'
        horizontal_sep = '=' * len(title)

        print()
        print(color(title))
        print(color(horizontal_sep))
        print()
        print(color(f'VMID: ') + crayons.yellow(self.vmid))
        if instance:
            print(color('Template'))
            print(color(f'  VMID: ') + crayons.yellow(self.template.vmid))
            print(color(f'  Name: {self.template.vm_attributes.name}'))
            print(color('Instance'))
        print(color(f'  Node: {self.vm_attributes.node}'))
        print(color(f'  Pool: {self.vm_attributes.pool}'))
        print(color(f'  Description: {self.vm_attributes.description}'))
        print(color(f'  OS: {self.vm_attributes.os_type}'))
        print(color(f'  CPUs: {self.vm_attributes.cpus}'))
        print(color(f'  Memory: {self.vm_attributes.memory}'))
        print(color(f'  DiskSize GB: {self.vm_attributes.disk_size}'))
        print(color(f'  Scsi driver: {self.vm_attributes.scsi}'))
        print(color(f'  Storage: {self.vm_attributes.storage_type}'))
        print(color(f'  SSH keyname: {self.vm_attributes.ssh_keyname}'))
        print(color(f'  Gateway: {self.vm_attributes.gateway}'))
        print()
        print()


class ExecuteStagesMixin:
    vm_attributes: VMAttributes
    vmid: str
    start_vm: callable
    stop_vm: callable
    inject_cloudinit_values: callable
    remove_ssh_config_entry: callable

    def start_stage(self, cloudinit=False, wait_minutes=4):
        wait_period = wait_minutes * 60
        sleep_interval = 5

        print(crayons.cyan(f'Stage: Start VM {self.vm_attributes.name} {self.vmid} on node {self.vm_attributes.node}'))
        if cloudinit:
            self.inject_cloudinit_values()

        started = self.start_vm()
        if started:
            print(crayons.green(f'Start VM {self.vm_attributes.name} {self.vmid}: Success'))
        else:
            logging.error(crayons.red(f'VM {self.vm_attributes.name} {self.vmid} failed to start'))
            return

        print(crayons.cyan(f'Stage: Waiting {wait_period / 60} minutes, for VM {self.vm_attributes.name} {self.vmid} on node {self.vm_attributes.node} to initialize.'))
        sleep_intervals(wait_period=wait_period, sleep_interval=sleep_interval)
        print(crayons.green(f'VM {self.vm_attributes.name} {self.vmid} on node {self.vm_attributes.node} initialized.'))

    def stop_stage(self, cloudinit=False):
        print(crayons.cyan(f'Stage: Stop VM {self.vm_attributes.name} {self.vmid} on node {self.vm_attributes.node}'))
        stopped = self.stop_vm()
        if stopped:
            print(crayons.green(f'Stop VM {self.vm_attributes.name} {self.vmid}: Success'))
        else:
            logging.error(crayons.red(f'VM {self.vm_attributes.name} {self.vmid} failed to stop'))
            return
        print(crayons.cyan(f'Remove ssh config entry for {self.vm_attributes.name}'))
        self.remove_ssh_config_entry()
        if cloudinit:
            self.inject_cloudinit_values(invalidate=True)
