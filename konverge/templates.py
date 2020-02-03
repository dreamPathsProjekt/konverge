import os
import logging

import crayons

from fabric2 import Connection

from konverge.operations import ProxmoxAPIClient
from konverge.utils import VMAttributes, get_template_id_prefix, get_template_vmid_from_os_type


class CloudinitTemplate:
    cloud_image = ''
    full_url = ''

    def __init__(self, vm_attributes: VMAttributes, client: ProxmoxAPIClient):
        self.vm_attributes = vm_attributes
        self.client = client
        id_prefix = get_template_id_prefix(scale=1, node=self.vm_attributes.node)
        self.vmid, _ = get_template_vmid_from_os_type(id_prefix=id_prefix, os_type=self.vm_attributes.os_type)
        self.pool = self.client.get_or_create_pool(name=self.vm_attributes.pool)
        self.volume_type, self.driver = ('--scsi0', 'scsi0') if self.vm_attributes.scsi else ('--virtio0', 'virtio0')

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

    def download_cloudinit_image(self, proxmox_ssh_node):
        storage_details = self.client.get_storage_detail_path_content(type=self.vm_attributes.storage)
        directory = 'images' if 'images' in storage_details.get('content') else ''

        cloud_image = self.os_type_factory(os_type=self.vm_attributes.os_type).cloud_image
        items = self.client.get_storage_content_items(node=self.vm_attributes.node, type=self.vm_attributes.storage)
        image_items = list(filter(lambda item: cloud_image in item.get('name'), items))
        if image_items:
            print(crayons.green(f'Cloud image: {cloud_image} already exists.'))
            return image_items

        location = os.path.join(storage_details.get('path'), directory)
        logging.warning(crayons.yellow(f'Cloud image: {cloud_image} not found. Searching in {location}.'))
        image_filename = os.path.join(location, cloud_image)
        proxmox_host = Connection(proxmox_ssh_node)
        output = proxmox_host.run(f'ls -l {image_filename}', hide=True).stdout.strip()
        if image_filename in output:
            print(crayons.green(f'Cloud image: {cloud_image} already exists in {location}.'))
            return image_filename

        full_url = self.os_type_factory(os_type=self.vm_attributes.os_type).full_url
        logging.warning(crayons.yellow(f'Cloud image: {cloud_image} not found in {location}. Downloading {full_url}'))
        get_image_command = f'rm -f {cloud_image}; wget {full_url} && mv {cloud_image} {location}'
        proxmox_host.run(get_image_command)
        return image_filename

    def create_base_vm(self):
        return self.client.create_vm(
            vm_attributes=self.vm_attributes,
            vmid=self.vmid
        )

    def import_cloudinit_image(self):
        pass


class UbuntuCloudInitTemplate(CloudinitTemplate):
    cloud_image = 'bionic-server-cloudimg-amd64.img'
    full_url = f'https://cloud-images.ubuntu.com/bionic/current/{cloud_image}'

    def _update_description(self):
        self.vm_attributes.description = '"Ubuntu 18.04.3 base template VM created by CloudImage."'


class CentosCloudInitTemplate(CloudinitTemplate):
    cloud_image = 'CentOS-7-x86_64-GenericCloud.qcow2'
    full_url = f'https://cloud.centos.org/centos/7/images/{cloud_image}'

    def _update_description(self):
        self.vm_attributes.description = '"CentOS 7 base template VM created by CloudImage."'