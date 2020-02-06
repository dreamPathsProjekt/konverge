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

        self.vmid, _ = self.get_vmid_and_username()
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

    def install_kube(self):
        raise NotImplementedError

    def execute(self):
        image_filename = self.download_cloudinit_image()
        print()
        logging.warning(crayons.yellow(self.create_vm()))

        self.import_cloudinit_image(image_filename)
        volume = self.get_storage(unused=True)

        print()
        logging.warning(crayons.yellow(self.attach_volume_to_vm(volume)))
        print()
        logging.warning(crayons.yellow(self.add_cloudinit_drive()))
        print()
        logging.warning(crayons.yellow(self.set_boot_disk()))
        print()
        self.resize_disk()
        print()
        self.set_vga_display()

        if self.preinstall:
            self.inject_cloudinit_values()
            self.start_vm()
            time.sleep(15)
            self.install_kube()
            self.stop_vm()

        print()
        self.export_template()
        return self.vmid


class UbuntuCloudInitTemplate(CloudinitTemplate):
    cls_cloud_image = 'bionic-server-cloudimg-amd64.img'
    full_url = f'https://cloud-images.ubuntu.com/bionic/current/{cls_cloud_image}'

    def _update_description(self):
        self.vm_attributes.description = f'"Ubuntu 18.04.3 base template VM created by CloudImage."'

    def generate_vmid(self, id_prefix, preinstall=True):
        template_vmid = int(f'{id_prefix}000') if self.preinstall else int(f'{id_prefix}100')
        username = 'ubuntu'
        return template_vmid, username

    def install_kube(self):
        filename = 'bootstrap/req_ubuntu.sh'


class CentosCloudInitTemplate(CloudinitTemplate):
    cls_cloud_image = 'CentOS-7-x86_64-GenericCloud.qcow2'
    full_url = f'https://cloud.centos.org/centos/7/images/{cls_cloud_image}'

    def _update_description(self):
        self.vm_attributes.description = f'"CentOS 7 base template VM created by CloudImage."'

    def generate_vmid(self, id_prefix):
        template_vmid = int(f'{id_prefix}001') if self.preinstall else int(f'{id_prefix}101')
        username = 'centos'
        return template_vmid, username

    def install_kube(self):
        filename = 'bootstrap/req_redhat.sh'


