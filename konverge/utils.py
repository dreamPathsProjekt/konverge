from enum import Enum
from typing import Union


def get_template_id_prefix(id_prefix=1, scale=3, node=None):
    if not node:
        return id_prefix
    for i in range(1, scale + 1):
        if str(i) in node:
            return str(i)
    return id_prefix


def get_template_vmid_from_os_type(id_prefix, os_type='ubuntu'):
    if os_type == 'ubuntu':
        template_vmid = int(f'{id_prefix}000')
        username = 'ubuntu'
    elif os_type == 'centos':
        template_vmid = int(f'{id_prefix}001')
        username = 'centos'
    else:
        template_vmid = int(f'{id_prefix}000')
        username = 'ubuntu'
    return template_vmid, username


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
            storage_type: Union[Storage, str] = None
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
        self.storage = storage_type