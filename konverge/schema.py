PROXMOX_CLUSTER_SCHEMA = {
    'type': 'object',
    'properties': {
        'name': {'type': 'string'},
        'nodes': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'ip': {'type': 'string'},
                    'host': {'type': 'string'},
                    'user': {'type': 'string'},
                    'password': {'type': 'string'},
                    'key_filename': {'type': 'string'},
                    'key_passphrase': {'type': 'string'},
                    'port': {'type': 'integer'},
                    'sudo': {'type': 'boolean'}
                },
                'required': ['name']
            },
            'minItems': 1,
            'uniqueItems': True
        },
        'network': {
            'type': 'object',
            'properties': {
                'base': {'type': 'string'},
                'gateway': {'type': 'string'},
                'allocated': {
                    'type': 'array',
                    'items': {
                        'type': 'string',
                        'uniqueItems': True
                    }
                },
                'allowed_range': {
                    'type': 'object',
                    'properties': {
                        'start': {
                            'type': 'integer',
                            'minimum': 6,
                            'maximum': 254
                        },
                        'end': {
                            'type': 'integer',
                            'minimum': 6,
                            'maximum': 254
                        }
                    },
                    'required': ['start', 'end']
                },
                'loadbalancer_range': {
                    'type': 'object',
                    'properties': {
                        'start': {
                            'type': 'integer',
                            'minimum': 6,
                            'maximum': 254
                        },
                        'end': {
                            'type': 'integer',
                            'minimum': 6,
                            'maximum': 254
                        }
                    },
                    'required': ['start', 'end']
                }
            },
            'required': ['base', 'gateway', 'allowed_range']
        }
    },
    'required': ['name', 'nodes', 'network']
}


KUBE_CLUSTER_SCHEMA = {}