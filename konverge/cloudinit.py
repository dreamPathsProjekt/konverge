import os
import time

from konverge.pve import logging, crayons, VMAPIClient, BootMedia
from konverge.utils import (
    VMAttributes,
    FabricWrapper,
    get_id_prefix
)


class CloudinitTemplate:
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

    def _get_storage_details(self):
        storage_details = self.client.get_storage_detail_path_content(storage_type=self.vm_attributes.storage_type)
        directory = 'images' if 'images' in storage_details.get('content') else ''
        location = os.path.join(storage_details.get('path'), directory)
        storage = storage_details.get('name')
        return storage, storage_details, location

    def generate_vmid(self, id_prefix):
        raise NotImplementedError

    def get_vmid_and_username(self):
        id_prefix = get_id_prefix(scale=1, node=self.vm_attributes.node)
        return self.generate_vmid(id_prefix=id_prefix)

    def download_cloudinit_image(self):
        items = self.client.get_storage_content_items(node=self.vm_attributes.node, storage_type=self.vm_attributes.storage_type)
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
        created = self.proxmox_node.execute(get_image_command)
        if created.ok:
            print(crayons.green(f'Vm: {self.vm_attributes.name} id: {self.vmid} created successfully.'))
        else:
            logging.error(crayons.red(f'Error during creation of Vm: {self.vm_attributes.name} id: {self.vmid}'))
            return None
        return image_filename

    def create_base_vm(self):
        return self.client.create_vm(
            vm_attributes=self.vm_attributes,
            vmid=self.vmid
        )

    def get_vm_config(self):
        return self.client.get_vm_config(node=self.vm_attributes.node, vmid=self.vmid)

    def get_storage_from_config(self, driver):
        config = self.get_vm_config()
        volume = config.get(driver) if config else None
        return volume.split(',')[0].strip() if volume else None

    def get_storage(self, unused=True):
        driver = self.unused_driver if unused else self.driver
        return self.get_storage_from_config(driver)

    def import_cloudinit_image(self, image_filename):
        if not image_filename:
            logging.error(crayons.red(f'Cannot import image: {self.cloud_image}. Filename: {image_filename}'))
            return
        print(crayons.cyan(f'Importing Image: {self.cloud_image}'))
        imported = self.proxmox_node.execute(f'qm importdisk {self.vmid} {image_filename} {self.storage}')
        if imported.ok:
            print(crayons.green(f'Image {self.cloud_image} imported successfully.'))

    def attach_volume_to_vm(self, volume):
        return self.client.attach_volume_to_vm(
            node=self.vm_attributes.node,
            vmid=self.vmid,
            scsi=self.vm_attributes.scsi,
            volume=volume,
            disk_size=self.vm_attributes.disk_size
        )

    def add_cloudinit_drive(self, drive_slot='2'):
        return self.client.add_cloudinit_drive(
            node=self.vm_attributes.node,
            vmid=self.vmid,
            storage_name=self.storage,
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
        response = self.client.start_vm(
            node=self.vm_attributes.node,
            vmid=self.vmid
        )
        time.sleep(5)
        return response

    def stop_vm(self):
        response = self.client.stop_vm(
            node=self.vm_attributes.node,
            vmid=self.vmid
        )
        time.sleep(5)
        return response

    def export_template(self):
        self.client.export_vm_template(
            node=self.vm_attributes.node,
            vmid=self.vmid
        )

    def install_kube(self):
        raise NotImplementedError

    def execute(self):
        image_filename = self.download_cloudinit_image()
        print()
        logging.warning(crayons.yellow(self.create_base_vm()))

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
            # TODO: Add step to inject cloudinit variables, before start.
            self.start_vm()
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
        pass


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
        pass


