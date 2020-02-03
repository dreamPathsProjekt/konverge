import crayons

from fabric2 import task


@task
def get_allocated_ips_per_node_interface(client, interface='', cidr=''):
    allocated_set = set()
    arp_scan_exists = client.run('command arp-scan --help; echo $?', hide=True)
    exit_code = arp_scan_exists.stdout.split()[-1].strip()
    if exit_code != '0':
        print(crayons.cyan('arp-scan not found. Installing.'))
        client.run('apt-get install -y arp-scan')
    awk_routine = "'{print $1}'"
    ips = client.run(f'arp-scan --interface={interface} {cidr} | awk {awk_routine}', hide=False).stdout.split()[2:-2]
    [allocated_set.add(ip) for ip in ips]
    print(crayons.white(f'Allocated: {allocated_set}'))
    return allocated_set
