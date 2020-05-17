import logging
import os
import math
from enum import Enum
from functools import singledispatch
from typing import Union

import crayons
from fabric2 import Connection, Config
from fabric2.util import get_local_user
from invoke import Context

from konverge.files import ConfigSerializer


LOCAL = Context(Config())

KUBE_VERSION_MAP_DOCKER_CE = {
    '1.15': '18.06',
    '1.16': '18.09',
    '1.17': '19.03'
}

KUBE_VERSION_MAP_DOCKER_IO = {
    '1.15': '18.09',
    '1.16': '18.09',
    '1.17': '18.09'
}


def colorize_yes_or_no(msg, yes=True):
    return crayons.green(msg) if yes else crayons.red(msg)


def get_kube_versions(os_type='ubuntu', kube_major='1.16', docker_ce=False):
    from konverge.settings import BASE_PATH

    bootstrap = os.path.join(BASE_PATH, 'bootstrap')
    if os_type == 'ubuntu':
        filename = os.path.join(bootstrap, 'kube_versions_ubuntu.sh')
    else:
        filename = os.path.join(bootstrap, 'kube_versions_centos.sh')
    docker_major = KUBE_VERSION_MAP_DOCKER_CE.get(kube_major) if docker_ce else KUBE_VERSION_MAP_DOCKER_IO.get(kube_major)
    local = LOCAL
    return local.run(
        f'chmod +x {filename} && KUBE_MAJOR_VERSION={kube_major} DOCKER_MAJOR_VERSION={docker_major} {filename}',
        hide=True
    ).stdout


@singledispatch
def get_attributes_exist(attributes, resource: ConfigSerializer):
    return [attribute for attribute in attributes if hasattr(resource, attribute)]


@get_attributes_exist.register
def _(attributes: str, resource: ConfigSerializer):
    return [attributes] if hasattr(resource, attributes) else []


@get_attributes_exist.register
def _(attributes: Union[tuple, list], resource: ConfigSerializer):
    return [attribute for attribute in attributes if hasattr(resource, attribute)]


class EnumCommon(Enum):
    @classmethod
    def has_value(cls, value):
        return value in cls._value2member_map_

    @classmethod
    def return_value(cls, value):
        if cls.has_value(value):
            return getattr(cls, value)


class Storage(EnumCommon):
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


class BootMedia(Enum):
    floppy = 'a'
    hard_disk = 'c'
    cdrom = 'd'
    network = 'n'


class BackupMode(Enum):
    stop = 'stop'
    snapshot = 'snapshot'
    suspend = 'suspend'


class KubeStorage(EnumCommon):
    rook = 'rook'
    glusterfs = 'glusterfs'
    nfs = 'nfs'


class HelmVersion(EnumCommon):
    v2 = 'v2'
    v3 = 'v3'


class VMCategory(EnumCommon):
    template = 'template'
    masters = 'masters'
    workers = 'workers'


class KubeClusterAction(EnumCommon):
    create = 'create'
    update = 'update'
    delete = 'delete'
    recreate = 'recreate'
    nothing = 'nothing'


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
            image_storage_type: Storage = None,
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
        self.image_storage_type = image_storage_type
        self.ssh_keyname = ssh_keyname
        self.gateway = gateway

    @property
    def description_os_type(self):
        if self.description and 'Ubuntu' in  self.description:
            return 'ubuntu'
        elif self.description and 'CentOS' in self.description:
            return 'centos'
        return self.os_type

    @property
    def public_ssh_key(self):
        return f'{self.ssh_keyname}.pub'

    @property
    def private_pem_ssh_key(self):
        return f'{self.ssh_keyname}.pem'

    @property
    def private_ssh_key(self):
        return self.ssh_keyname if 'id_rsa' in self.ssh_keyname else f'{self.ssh_keyname}.key'

    @property
    def public_key_exists(self):
        return os.path.exists(self.public_ssh_key)

    @property
    def private_key_exists(self):
        return os.path.exists(self.private_ssh_key)

    @property
    def private_pem_ssh_key_exists(self):
        return os.path.exists(self.private_pem_ssh_key)

    def read_public_key(self):
        if not self.public_key_exists:
            return None
        with open(self.public_ssh_key, mode='r') as pub_file:
            key_content = pub_file.read().strip()
        return key_content


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


def get_id_prefix(id_prefix=1, proxmox_node_scale=3, node=None):
    """
    Default prefix if node name has no number, is 1.
    """
    if not node:
        return id_prefix
    for i in range(1, proxmox_node_scale + 1):
        if str(i) in node:
            return i
    return id_prefix


def add_ssh_config_entry(host, user, identity, ip):
    """
    Add host configuration locally on ~/.ssh/config
    """
    local = LOCAL
    home = get_local_user()
    config_file = f'/home/{home}/.ssh/config'
    if not os.path.exists(config_file):
        logging.warning(crayons.yellow(f'Did not find config file: {config_file}. Creating now.'))
        local.run(f'mkdir -p ~/.ssh')
    try:
        local.run(f'echo "" >> {config_file}')
        local.run(f'echo "Host {host}" >> {config_file}')
        local.run(f'echo "Hostname {ip}" >> {config_file}')
        local.run(f'echo "User {user}" >> {config_file}')
        local.run(f'echo "Port 22" >> {config_file}')
        local.run(f'echo "IdentityFile {identity}" >> {config_file}')
        local.run(f'echo "StrictHostKeyChecking no" >> {config_file}')
        print(crayons.green(f'Host: {host} added to ~/.ssh/config'))
    except Exception as generic:
        logging.error(crayons.red(f'Error during adding host to config: {generic}'))


def remove_ssh_config_entry(host, ip, user='ubuntu'):
    local = LOCAL
    home = get_local_user()
    config_file = f'/home/{home}/.ssh/config'
    local.run(f'cp {config_file} {config_file}.bak')
    found = False

    if not os.path.exists(config_file):
        logging.error(crayons.red(f'Did not find config file: {config_file}. Exit.'))
        return

    with open(config_file, mode='r') as ssh_config:
        lines = ssh_config.readlines()
        for line in lines:
            index = lines.index(line)
            try:
                if (
                        f'Host {host}' == line.strip().replace('\n', '') and
                        f'Hostname {ip}' == lines[index + 1].strip().replace('\n', '') and
                        f'User {user}' == lines[index + 2].strip().replace('\n', '') and
                        'Port 22' == lines[index + 3].strip().replace('\n', '')
                ):
                    print(crayons.magenta('Lines to remove:'))
                    print(crayons.yellow(line.strip().replace('\n', '')))
                    print(crayons.yellow(lines[index + 1].strip().replace('\n', '')))
                    print(crayons.yellow(lines[index + 2].strip().replace('\n', '')))
                    print(crayons.yellow(lines[index + 3].strip().replace('\n', '')))
                    print(crayons.yellow(lines[index + 4].strip().replace('\n', '')))
                    print(crayons.yellow(lines[index + 5].strip().replace('\n', '')))
                    found = True
                    for i in range(6):
                        lines[index + i] = ''
            except IndexError as index_error:
                logging.error(crayons.red(f'Error during removing host from config: {index_error}'))
                print(crayons.blue('Performing rollback of ~/.ssh/config'))
                local.run(f'mv {config_file}.bak {config_file}')
                print(crayons.green('Rollback complete'))
                return
        try:
            if lines and found:
                with open(config_file, 'w') as ssh_config_write:
                    ssh_config_write.writelines(lines)
                    print(crayons.green('Entry removed from ~/.ssh/config'))
            else:
                print(crayons.green('Entry not found'))
        except Exception as generic:
            logging.error(crayons.red(f'Error during removing host from config: {generic}'))
            print(crayons.blue('Performing rollback of ~/.ssh/config'))
            local.run(f'mv {config_file}.bak {config_file}')
            print(crayons.green('Rollback complete'))


def clear_server_entry(ip):
    try:
        local = LOCAL
        home = get_local_user()
        local.run(f'ssh-keygen -f "/home/{home}/.ssh/known_hosts" -R "{ip}"')
    except Exception as warning:
        logging.warning(crayons.yellow(f'{ip} not found on ~/.ssh/known_hosts'))
        logging.warning(crayons.white(warning))


def human_readable_disk_size(size):
   if size == 0:
       return '0B'
   size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
   index = int(math.floor(math.log(size, 1024)))
   power = math.pow(1024, index)
   result = round(size/power, 2)
   return int(result), size_name[index]


def set_pve_config_filename(filename: str):
    if filename:
        os.environ['PVE_FILENAME'] = filename


def set_kube_config_filename(filename: str):
    if filename:
        os.environ['KUBE_FILENAME'] = filename