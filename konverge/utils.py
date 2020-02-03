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