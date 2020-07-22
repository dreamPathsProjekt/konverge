import os
import logging
import click
import crayons

from shutil import copyfile

from konverge import VERSION
from konverge.kubecluster import KubeCluster, KubeClusterStages
from konverge import settings


def _hide_password(ctx, param, value):
    if not value or value == '********':
      return  os.getenv('PROXMOX_PASSWORD')
    return value


def _settings_valid():
    if not settings.vm_client:
        logging.warning(crayons.yellow('Not authenticated. Please login using \'konverge login\''))
        return False
    if not isinstance(settings.vm_client, settings.ProxmoxAPIClient):
        logging.error(crayons.red('Proxmox API Client Invalid.'))
        return False
    return True


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


@click.group()
def cli():
    pass


@cli.command(help='Print the version of the CLI')
def version():
    click.echo(VERSION)


@cli.command(help='Login to Proxmox API Server.')
@click.option('--host', '-h', prompt=True, default=lambda: os.getenv('PROXMOX_HOST'), type=click.STRING, help='Proxmox Host.')
@click.option('--user', '-u', prompt=True, default=lambda: os.getenv('PROXMOX_USER'), type=click.STRING, help='Proxmox Username. Use either @pam or @pve domains.')
@click.option(
    '--password',
    '-p',
    prompt=True,
    callback=_hide_password,
    default='********' if os.getenv('PROXMOX_PASSWORD') is not None else '',
    type=click.STRING,
    help='Proxmox Password.',
    hide_input=True
)
@click.option('--insecure', '-i', is_flag=True, default=False, type=click.BOOL, help='Insecure: Do not verify SSL.')
def login(host, user, password, insecure):
    if not host or not user or not password:
        logging.error(crayons.red('Please fill out all the necessary values.'))
        return

    verify_ssl = False if insecure else True
    try:
        settings.VMAPIClientFactory(
            host=host,
            user=user,
            password=password,
            backend='https',
            verify_ssl=verify_ssl
        )
        settings.write_pve_credentials(
            host=host,
            user=user,
            password=password,
            verify_ssl=verify_ssl
        )
        print(crayons.green(f'User {user} authenticated successfully.'))
    except settings.https.AuthenticationError as auth:
        logging.error(crayons.red(auth))
        logging.warning(crayons.yellow(f'Unauthorized. Authentication failed for {host}'))
    except settings.SSLError as ssl:
        logging.error(crayons.red(ssl))
        logging.warning(crayons.yellow(f'Verify SSL Failed for {host}'))
    except Exception as unknown:
        logging.error(crayons.red(unknown))
        logging.error(crayons.red(f'Could not authenticate to {host}'))


@cli.command(help='Initializes the workspace.')
@click.option('--file', '-f', type=click.STRING, help='Custom K8s cluster manifest file.')
@click.option('--pve-file', '-p', type=click.STRING, help='Custom Proxmox cluster manifest file.')
def init(file, pve_file):
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


@cli.command(help='Create K8s Cluster.')
@click.option('--timeout', '-t', type=click.INT, help='Wait period between phases in seconds. Default: 120 sec.')
@click.option('--dry-run', '-d', is_flag=True, default=False, type=click.BOOL, help='Dry-run (preview) this operation.')
@click.option(
    '--stage',
    '-s',
    default='all',
    type=click.Choice(
        [
            'all',
            'create',
            'bootstrap',
            'join',
            'post_installs',
        ]
    ),
    help='Creation Stage.')
def create(timeout, dry_run, stage):
    if not _settings_valid():
        return

    execute_stage = None
    if stage != 'all':
        execute_stage = KubeClusterStages.return_value(stage)

    cluster = _get_cluster()

    if execute_stage:
        cluster.execute(
            wait_period=timeout,
            dry_run=dry_run,
            stage=execute_stage
        ) if timeout else cluster.execute(
            dry_run=dry_run,
            stage=execute_stage
        )
        return

    cluster.execute(
        wait_period=timeout,
        dry_run=dry_run
    ) if timeout else cluster.execute(dry_run=dry_run)


@cli.command(help='Destroy K8s Cluster.')
@click.option('--timeout', '-t', type=click.INT, help='Wait period between phases in seconds. Default: 120 sec.')
@click.option('--dry-run', '-d', is_flag=True, default=False, type=click.BOOL, help='Dry-run (preview) this operation.')
@click.option('--templates', '-T', is_flag=True, default=False, type=click.BOOL, help='Destroy Cloudinit Templates.')
@click.option(
    '--stage',
    '-s',
    default='all',
    type=click.Choice(
        [
            'all',
            'workers',
            'masters',
            'remove',
            'post_destroy',
        ]
    ),
    help='Destroy Stage.')
def destroy(timeout, dry_run, stage, templates):
    if not _settings_valid():
        return

    execute_stage = None
    if stage == 'workers':
        execute_stage = KubeClusterStages.join
    elif stage == 'masters':
        execute_stage = KubeClusterStages.bootstrap
    elif stage == 'remove':
        execute_stage = KubeClusterStages.create
    elif stage == 'post_destroy':
        execute_stage = KubeClusterStages.post_installs

    cluster = _get_cluster()

    if execute_stage:
        cluster.execute(
            destroy=True,
            wait_period=timeout,
            dry_run=dry_run,
            stage=execute_stage,
            destroy_template=templates
        ) if timeout else cluster.execute(
            destroy=True,
            dry_run=dry_run,
            stage=execute_stage,
            destroy_template=templates
        )
        return

    cluster.execute(
        destroy=True,
        wait_period=timeout,
        dry_run=dry_run,
        destroy_template=templates
    ) if timeout else cluster.execute(
        destroy=True,
        dry_run=dry_run,
        destroy_template=templates
    )


@cli.command(help='Apply K8s Cluster (declarative).')
@click.option('--timeout', '-t', type=click.INT, help='Wait period between phases in seconds. Default: 120 sec.')
@click.option('--dry-run', '-d', is_flag=True, default=False, type=click.BOOL, help='Dry-run (preview) this operation.')
def apply(timeout, dry_run):
    if not _settings_valid():
        return

    cluster = _get_cluster()
    cluster.execute(
        wait_period=timeout,
        dry_run=dry_run,
        apply=True
    ) if timeout else cluster.execute(dry_run=dry_run, apply=True)