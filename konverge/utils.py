import logging
from enum import Enum

import crayons

from fabric2 import Connection


class Storage(Enum):
    cephfs = 'cephfs'
    cifs = 'cifs'
    dir = 'dir'
    drbd = 'drbd'
    fake = 'fake'
    glusterfs = 'glusterfs'
    iscsi = 'iscsi'
    iscsidirect = 'iscsidirect'
    lvm = 'lvm'
    lvmthin = 'lvmthin'
    nfs = 'nfs'
    rbd = 'rbd'
    sheepdog = 'sheepdog'
    zfs = 'zfs'
    zfspool = 'zfspool'

    @classmethod
    def has_value(cls, value):
        return value in cls._value2member_map_


class BootMedia(Enum):
    floppy = 'a'
    hard_disk = 'c'
    cdrom = 'd'
    network = 'n'


class VMAttributes:
    def __init__(
            self,
            name,
            node,
            pool,
            description='',
            os_type='ubuntu',
            cpus=1,
            memory=1024,
            disk_size=5,
            scsi=False,
            storage_type: Storage = None,
            ssh_keyname='',
            gateway=''
    ):
        self.name = name
        self.node = node
        self.pool = pool
        self.description = description
        self.os_type = os_type
        self.cpus = cpus
        self.memory = memory
        self.disk_size = disk_size
        self.scsi = scsi
        self.storage_type = storage_type
        self.ssh_keyname = ssh_keyname
        self.gateway = gateway

    @property
    def public_ssh_key(self):
        return f'{self.ssh_keyname}.pub'

    @property
    def private_pem_ssh_key(self):
        return f'{self.ssh_keyname}.pem'

    @property
    def private_ssh_key(self):
        return self.ssh_keyname if 'id_rsa' in self.ssh_keyname else f'{self.ssh_keyname}.key'


class FabricWrapper:
    def __init__(
            self,
            host,
            user=None,
            password=None,
            key_filename=None,
            key_passphrase=None,
            port=22,
            sudo=False
    ):
        self.sudo = sudo
        if not user and not password and not key_filename:
            # Get details from ~/.ssh/config
            self.connection = Connection(host)
        elif key_filename and not password:
            self.connection = Connection(
                host=host,
                user=user,
                port=port,
                connect_kwargs={
                    'key_filename': key_filename,
                    'passphrase': key_passphrase
                }
            )
        elif not key_filename and password:
            self.connection = Connection(
                host=host,
                user=user,
                port=port,
                connect_kwargs={
                    'password': password
                }
            )
        elif key_filename and password:
            self.connection = Connection(
                host=host,
                user=user,
                port=port,
                connect_kwargs={
                    'key_filename': key_filename,
                    'passphrase': key_passphrase if key_passphrase else password
                }
            )
        else:
            logging.error(
                crayons.red(f'You need to provide either a private key_filename or password to connect to {host} with user: {user}')
            )
            self.connection = None

    def execute(self, command, **kwargs):
        if not self.connection:
            logging.error(crayons.red('No connection object instantiated.'))
            return None
        return self.connection.sudo(command, **kwargs) if self.sudo else self.connection.run(command, **kwargs)


def get_id_prefix(id_prefix=1, scale=3, node=None):
    if not node:
        return id_prefix
    for i in range(1, scale + 1):
        if str(i) in node:
            return str(i)
    return id_prefix