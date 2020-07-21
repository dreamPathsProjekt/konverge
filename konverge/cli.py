import os
import logging
import click
import crayons

from shutil import copyfile

from konverge import VERSION
from konverge.kubecluster import KubeCluster
from konverge import settings


@click.group()
def cli():
    pass


@cli.command(help='Print the version of the CLI')
def version():
    click.echo(VERSION)


@cli.command(help='Initializes the workspace.')
@click.option('--file', '-f', type=click.STRING, help='Custom K8s cluster manifest file.')
@click.option('--pve-file', '-p', type=click.STRING, help='Custom Proxmox cluster manifest file.')
def init(file: str, pve_file: str):
    try:
        pve_init = _prepare_file(pve_file, pve=True) if pve_file else True
        cluster_init = _prepare_file(file, pve=False) if file else True
    except Exception as os_error:
        logging.error(crayons.red(os_error))
        logging.error(crayons.red('Workspace was not initialized.'))
        return
    if not pve_init or not cluster_init:
        logging.error(crayons.red('Error initializing files. Workspace was not initialized.'))
        return
    if not _manifests_exist():
        logging.error(crayons.red('Workspace was not initialized.'))
        return
    print(crayons.green('Workspace initialized'))


def _manifests_exist():
    cluster = os.path.join(settings.WORKDIR, '.cluster.yml')
    pve = os.path.join(settings.WORKDIR, '.pve.yml')
    if not os.path.exists(cluster):
        logging.error(crayons.red(f'K8s Cluster manifest {cluster} does not exist.'))
        return False
    if not os.path.exists(pve):
        logging.error(crayons.red(f'Proxmox Cluster manifest {pve} does not exist.'))
        return False
    return True


def _prepare_file(file, pve=True):
    source = os.path.join(settings.WORKDIR, file)
    target = os.path.join(settings.WORKDIR, '.pve.yml' if pve else '.cluster.yml')
    if not os.path.exists(source):
        logging.error(crayons.red(f'File: {file} does not exist.'))
        return False
    if os.path.exists(target):
        copyfile(target, f'{target}.bak')
    copyfile(source, target)
    return True


def _get_cluster():
    return KubeCluster(config=settings.kube_config)


@cli.command(help='Create K8s Cluster. To override .cluster.yml, run \'konverge init\'')
@click.option('--timeout', '-t', type=click.INT, help='Wait period between create and bootstrap phase in seconds. Default: 120 sec.')
def create(timeout):
    cluster = _get_cluster()
    cluster.execute(wait_period=timeout) if timeout else cluster.execute()
