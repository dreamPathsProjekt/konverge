import os
import logging

import crayons

from konverge.pve import ProxmoxAPIClient
from konverge.utils import VMAttributes, FabricWrapper, get_template_id_prefix, get_template_vmid_from_os_type


class CloudinitTemplate:
    cls_cloud_image = ''
    full_url = ''

    def __init__(
            self,
            vm_attributes: VMAttributes,
            client: ProxmoxAPIClient,
            proxmox_node: FabricWrapper = None
    ):
        self.vm_attributes = vm_attributes
        self.client = client
        self.proxmox_node = proxmox_node if proxmox_node else FabricWrapper(host=vm_attributes.node)

        id_prefix = get_template_id_prefix(scale=1, node=self.vm_attributes.node)
        self.vmid, _ = get_template_vmid_from_os_type(id_prefix=id_prefix, os_type=self.vm_attributes.os_type)
        self.pool = self.client.get_or_create_pool(name=self.vm_attributes.pool)
        self.volume_type, self.driver = ('--scsi0', 'scsi0') if self.vm_attributes.scsi else ('--virtio0', 'virtio0')

        self._update_description()
        self.storage_details, self.location = self.get_storage_details()

    @property
    def cloud_image(self):
        cls = self.os_type_factory(os_type=self.vm_attributes.os_type)
        return cls.cls_cloud_image

    @property
    def full_image_url(self):
        cls = self.os_type_factory(os_type=self.vm_attributes.os_type)
        return cls.full_url

    @classmethod
    def os_type_factory(cls, os_type='ubuntu'):
        if os_type == 'ubuntu':
            return UbuntuCloudInitTemplate
        elif os_type == 'centos':
            return CentosCloudInitTemplate
        else:
            return CloudinitTemplate

    def _update_description(self):
        self.vm_attributes.description = '"Generic Linux base template VM created by CloudImage."'

    def get_storage_details(self):
        storage_details = self.client.get_storage_detail_path_content(storage_type=self.vm_attributes.storage)
        directory = 'images' if 'images' in storage_details.get('content') else ''
        location = os.path.join(storage_details.get('path'), directory)
        return storage_details, location

    def download_cloudinit_image(self):
        items = self.client.get_storage_content_items(node=self.vm_attributes.node, storage_type=self.vm_attributes.storage)
        image_items = list(filter(lambda item: self.cloud_image in item.get('name'), items))
        if image_items:
            print(crayons.green(f'Cloud image: {self.cloud_image} already exists.'))
            return image_items

        logging.warning(crayons.yellow(f'Cloud image: {self.cloud_image} not found. Searching in {self.location}.'))
        image_filename = os.path.join(self.location, self.cloud_image)
        output = self.proxmox_node.execute(f'ls -l {image_filename}', hide=True).stdout.strip()
        if image_filename in output:
            print(crayons.green(f'Cloud image: {self.cloud_image} already exists in {self.location}.'))
            return image_filename

        logging.warning(crayons.yellow(f'Cloud image: {self.cloud_image} not found in {self.location}. Downloading {self.full_image_url}'))
        get_image_command = f'rm -f {self.cloud_image}; wget {self.full_image_url} && mv {self.cloud_image} {self.location}'
        self.proxmox_node.execute(get_image_command)
        return image_filename

    def create_base_vm(self):
        return self.client.create_vm(
            vm_attributes=self.vm_attributes,
            vmid=self.vmid
        )

    def get_vm_config(self, vmid):
        return self.client.get_vm_config(node=self.vm_attributes.node, vmid=vmid)

    def get_storage_from_config(self, vmid):
        config = self.get_vm_config(vmid)
        volume = config.get(self.driver) if config else None
        return volume.split(',')[0].strip() if volume else None

    def import_cloudinit_image(self):
        pass


class UbuntuCloudInitTemplate(CloudinitTemplate):
    cls_cloud_image = 'bionic-server-cloudimg-amd64.img'
    full_url = f'https://cloud-images.ubuntu.com/bionic/current/{cls_cloud_image}'

    def _update_description(self):
        self.vm_attributes.description = '"Ubuntu 18.04.3 base template VM created by CloudImage."'


class CentosCloudInitTemplate(CloudinitTemplate):
    cls_cloud_image = 'CentOS-7-x86_64-GenericCloud.qcow2'
    full_url = f'https://cloud.centos.org/centos/7/images/{cls_cloud_image}'

    def _update_description(self):
        self.vm_attributes.description = '"CentOS 7 base template VM created by CloudImage."'