import os
import time
import logging

import crayons

from konverge.pve import VMAPIClient
from konverge.mixins import CommonVMMixin
from konverge.utils import (
    VMAttributes,
    FabricWrapper
)


class CloudinitTemplate(CommonVMMixin):
    cls_cloud_image = ''
    full_url = ''
    filename = ''

    def __init__(
            self,
            vm_attributes: VMAttributes,
            client: VMAPIClient,
            proxmox_node: FabricWrapper = None,
            unused_driver = 'unused0',
            preinstall = True
    ):
        self.vm_attributes = vm_attributes
        self.client = client
        self.proxmox_node = proxmox_node if proxmox_node else FabricWrapper(host=vm_attributes.node)
        self.unused_driver = unused_driver
        self.preinstall = preinstall

        self.vmid, self.username = self.get_vmid_and_username()
        self.pool = self.client.get_or_create_pool(name=self.vm_attributes.pool)
        self.volume_type, self.driver = ('--scsi0', 'scsi0') if self.vm_attributes.scsi else ('--virtio0', 'virtio0')

        self._update_description()
        (
            self.storage,
            self.storage_details,
            self.location
        ) = self._get_storage_details()
        (
            self.cloudinit_storage,
            self.cloudinit_storage_details,
            self.cloudinit_location
        ) = self._get_storage_details(image=True)
        self.allowed_ip = ''

    @property
    def cloud_image(self):
        return self.cls_cloud_image

    @property
    def full_image_url(self):
        return self.full_url

    @staticmethod
    def os_type_factory(os_type='ubuntu'):
        options = {
            'ubuntu': UbuntuCloudInitTemplate,
            'centos': CentosCloudInitTemplate
        }
        return options.get(os_type)

    def _update_description(self):
        self.vm_attributes.description = '"Generic Linux base template VM created by CloudImage."'

    def generate_vmid(self, id_prefix):
        raise NotImplementedError

    def download_cloudinit_image(self):
        items = self.client.get_storage_content_items(node=self.vm_attributes.node, storage_type=self.vm_attributes.image_storage_type)
        image_items = list(filter(lambda item: self.cloud_image in item.get('name'), items))
        if image_items:
            print(crayons.green(f'Cloud image: {self.cloud_image} already exists.'))
            return image_items

        logging.warning(crayons.yellow(f'Cloud image: {self.cloud_image} not found. Searching in {self.location}.'))
        image_filename = os.path.join(self.cloudinit_location, self.cloud_image)
        output = self.proxmox_node.execute(f'ls -l {image_filename}', hide=True).stdout.strip()
        if image_filename in output:
            print(crayons.green(f'Cloud image: {self.cloud_image} already exists in {self.cloudinit_location}.'))
            return image_filename

        logging.warning(crayons.yellow(f'Cloud image: {self.cloud_image} not found in {self.cloudinit_location}. Downloading {self.full_image_url}'))
        get_image_command = f'rm -f {self.cloud_image}; wget {self.full_image_url} && mv {self.cloud_image} {self.cloudinit_location}'
        downloaded = self.proxmox_node.execute(get_image_command)
        if downloaded.ok:
            print(crayons.green(f'Image {self.cloud_image} downloaded to {self.cloudinit_location}. Filename: {image_filename}'))
        else:
            logging.error(crayons.red(f'Error downloading image {self.cloud_image}'))
            return None
        return image_filename

    def import_cloudinit_image(self, image_filename):
        if not image_filename:
            logging.error(crayons.red(f'Cannot import image: {self.cloud_image}. Filename: {image_filename}'))
            return
        print(crayons.cyan(f'Importing Image: {self.cloud_image}'))
        imported = self.proxmox_node.execute(f'qm importdisk {self.vmid} {image_filename} {self.storage}')
        if imported.ok:
            print(crayons.green(f'Image {self.cloud_image} imported successfully.'))

    def install_storageos_requirements(self):
        raise NotImplementedError

    def execute(
            self,
            kubernetes_version='1.16.3-00',
            docker_version='18.09.7',
            storageos_requirements=False
    ):
        print(crayons.cyan(f'Stage: Download image: {self.cloud_image}'))
        image_filename = self.download_cloudinit_image()
        print(crayons.cyan(f'Stage: Create Base VM {self.vm_attributes.name} {self.vmid} on node {self.vm_attributes.node}'))
        logging.warning(crayons.yellow(self.create_vm()))
        print(crayons.cyan('Stage: Import image and get unused storage'))
        self.import_cloudinit_image(image_filename)
        volume = self.get_storage(unused=True)

        print(crayons.cyan(f'Stage: Attach volume to VM {self.vm_attributes.name} {self.vmid} on node {self.vm_attributes.node}'))
        logging.warning(crayons.yellow(self.attach_volume_to_vm(volume)))
        print(crayons.cyan(f'Stage: Add cloudinit drive'))
        logging.warning(crayons.yellow(self.add_cloudinit_drive()))
        print(crayons.cyan(f'Stage: Set boot disk'))
        logging.warning(crayons.yellow(self.set_boot_disk()))
        print(crayons.cyan(f'Stage: Resize disk'))
        self.resize_disk()
        print(crayons.cyan(f'Stage: Set VGA serial drive'))
        self.set_vga_display()

        if self.preinstall:
            print(crayons.cyan(f'Stage: Start VM {self.vm_attributes.name} {self.vmid} on node {self.vm_attributes.node}'))
            self.inject_cloudinit_values()
            started = self.start_vm()
            if started:
                print(crayons.green(f'Start VM {self.vm_attributes.name} {self.vmid}: Success'))
            else:
                logging.error(crayons.red(f'VM {self.vm_attributes.name} {self.vmid} failed to start'))
                return
            print(crayons.cyan(f'Stage: Waiting 2 min. for VM {self.vm_attributes.name} {self.vmid} on node {self.vm_attributes.node} to initialize.'))
            time.sleep(120)
            print(crayons.green(f'VM {self.vm_attributes.name} {self.vmid} on node {self.vm_attributes.node} initialized.'))
            print(crayons.cyan(f'Stage: Install kubernetes pre-requisites from file {self.filename}'))
            self.install_kube(
                filename=self.filename,
                kubernetes_version=kubernetes_version,
                docker_version=docker_version,
                storageos_requirements=storageos_requirements
            )
            time.sleep(5)
            print(crayons.cyan(f'Stage: Stop VM {self.vm_attributes.name} {self.vmid} on node {self.vm_attributes.node}'))
            stopped = self.stop_vm()
            if stopped:
                print(crayons.green(f'Stop VM {self.vm_attributes.name} {self.vmid}: Success'))
            else:
                logging.error(crayons.red(f'VM {self.vm_attributes.name} {self.vmid} failed to stop'))
                return
            print(crayons.cyan(f'Remove ssh config entry for {self.vm_attributes.name}'))
            self.remove_ssh_config_entry()

        print(crayons.cyan(f'Stage: exporting template from VM {self.vm_attributes.name} {self.vmid} on node {self.vm_attributes.node}'))
        self.export_template()
        print(crayons.green(f'Template exported: {self.vm_attributes.name} {self.vmid} on node {self.vm_attributes.node}'))
        return self.vmid


class UbuntuCloudInitTemplate(CloudinitTemplate):
    cls_cloud_image = 'bionic-server-cloudimg-amd64.img'
    full_url = f'https://cloud-images.ubuntu.com/bionic/current/{cls_cloud_image}'
    filename = 'req_ubuntu.sh'

    def _update_description(self):
        self.vm_attributes.description = f'"Ubuntu 18.04.3 base template VM created by CloudImage."'

    def generate_vmid(self, id_prefix, preinstall=True):
        template_vmid = int(f'{id_prefix}100') if self.preinstall else int(f'{id_prefix}000')
        username = 'ubuntu'
        return template_vmid, username

    def execute(
            self,
            kubernetes_version='1.16.3-00',
            docker_version='18.09.7',
            storageos_requirements=False
    ):
        suffix = '-0ubuntu1~18.04.4'
        super().execute(
            kubernetes_version=kubernetes_version,
            docker_version=f'{docker_version}{suffix}',
            storageos_requirements=storageos_requirements
        )

    def install_storageos_requirements(self):
        host = self.vm_attributes.name
        template_host_sudo = FabricWrapper(host=host, sudo=True)
        print(crayons.cyan('Installing Storage OS pre-requisites on nodes'))
        if 'master' in host:
            logging.warning(crayons.yellow(f'Client {host} is tagged master node. Skipping.'))
            return
        install_prereqs = template_host_sudo.execute('apt-get -y update && apt-get -y install linux-modules-extra-$(uname -r)')
        if install_prereqs.ok:
            print(crayons.green('Pre-requisistes for Storage OS Operator installed successfully'))
        else:
            logging.error(crayons.red('Pre-requisistes for Storage OS Operator failed to install.'))
            return


class CentosCloudInitTemplate(CloudinitTemplate):
    cls_cloud_image = 'CentOS-7-x86_64-GenericCloud.qcow2'
    full_url = f'https://cloud.centos.org/centos/7/images/{cls_cloud_image}'
    filename = 'req_centos.sh'

    def _update_description(self):
        self.vm_attributes.description = f'"CentOS 7 base template VM created by CloudImage."'

    def generate_vmid(self, id_prefix):
        template_vmid = int(f'{id_prefix}101') if self.preinstall else int(f'{id_prefix}001')
        username = 'centos'
        return template_vmid, username

    def execute(
            self,
            kubernetes_version='1.16.3-00',
            docker_version='18.09.7',
            storageos_requirements=False
    ):
        super().execute(
            kubernetes_version=kubernetes_version,
            docker_version=docker_version,
            storageos_requirements=storageos_requirements
        )

    def install_storageos_requirements(self):
        logging.warning('Install StorageOS requirements not implemented for CentOS')
