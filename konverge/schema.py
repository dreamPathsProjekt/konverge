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

KUBE_CLUSTER_SCHEMA = {
    'type': 'object',
    'properties': {
        'name': {'type': 'string'},
        'user': {'type': 'string'},
        'context': {'type': 'string'},
        'pool': {'type': 'string'},
        'os_type': {
            'type': 'string',
            'pattern': '^(ubuntu|centos)$'
        },
        'ssh_key': {'type': 'string'},
        'template': {
            'type': 'object',
            'properties': {
                'create': {'type': 'boolean'},
                'pve_storage': {
                    'type': 'object',
                    'properties': {
                        'instance': {
                            'type': 'object',
                            'properties': {
                                'type': {
                                    'type': 'string',
                                    'pattern': '^(cephfs|cifs|dir|drbd|fake|glusterfs|iscsi|iscsidirect|lvm|lvmthin|nfs|rbd|sheepdog|zfs|zfspool)$'
                                }
                            },
                            'required': ['type']
                        },
                        'image': {
                            'type': 'object',
                            'properties': {
                                'type': {
                                    'type': 'string',
                                    'pattern': '^(cephfs|cifs|dir|drbd|fake|glusterfs|iscsi|iscsidirect|lvm|lvmthin|nfs|rbd|sheepdog|zfs|zfspool)$'
                                }
                            },
                            'required': ['type']
                        }
                    },
                    'required': ['instance', 'image']
                },
                'name': {'type': 'string'},
                'node': {'type': 'string'},
                'cpus': {
                    'type': 'integer',
                    'minimum': 1
                },
                'memory': {
                    'type': 'integer',
                    'minimum': 1
                },
                'disk': {
                    'type': 'object',
                    'properties': {
                        'size': {
                            'type': 'integer',
                            'minimum': 1
                        },
                        'hotplug': {'type': 'boolean'},
                        'hotplug_size': {
                            'type': 'integer',
                            'minimum': 1
                        }
                    },
                    'required': ['size']
                },
                'scsi': {'type': 'boolean'}
            },
            'required': ['pve_storage', 'name', 'node']
        },
        'control_plane': {
            'type': 'object',
            'properties': {
                'ha_masters': {'type': 'boolean'},
                'networking': {
                    'type': 'string',
                    'pattern': '^(calico|weave)$'
                },
                'apiserver': {
                    'type': 'object',
                    'properties': {
                        'ip': {
                            'type': ['string', 'null'],
                            'format': 'ipv4'
                        },
                        'port': {'type': ['integer', 'string']}
                    },
                    'required': []
                }
            },
            'required': []
        },
        'storage': {
            'type': ['string', 'null'],
            'pattern': '^(rook|nfs|glusterfs)$'
        },
        'loadbalancer': {'type': 'boolean'},
        'helm': {
            'type': 'object',
            'properties': {
                'version': {
                    'type': 'string',
                    'pattern': '^(v2|v3)$'
                },
                'local': {'type': 'boolean'},
                'tiller': {'type': 'boolean'}
            },
            'required': []
        },
        'masters': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'node': {'type': 'string'},
                'scale': {
                    'type': 'integer',
                    'minimum': 1
                },
                'cpus': {
                    'type': 'integer',
                    'minimum': 1
                },
                'memory': {
                    'type': 'integer',
                    'minimum': 1
                },
                'disk': {
                    'type': 'object',
                    'properties': {
                        'size': {
                            'type': 'integer',
                            'minimum': 1
                        },
                        'hotplug': {'type': 'boolean'},
                        'hotplug_size': {
                            'type': 'integer',
                            'minimum': 1
                        }
                    },
                    'required': ['size']
                },
                'scsi': {'type': 'boolean'}
            },
            'required': ['name', 'node', 'scale', 'cpus', 'memory', 'disk']
        },
        'workers': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'node': {'type': 'string'},
                    'role': {'type': 'string'},
                    'scale': {
                        'type': 'integer',
                        'minimum': 1
                    },
                    'cpus': {
                        'type': 'integer',
                        'minimum': 1
                    },
                    'memory': {
                        'type': 'integer',
                        'minimum': 1
                    },
                    'disk': {
                        'type': 'object',
                        'properties': {
                            'size': {
                                'type': 'integer',
                                'minimum': 1
                            },
                            'hotplug': {'type': 'boolean'},
                            'hotplug_size': {
                                'type': 'integer',
                                'minimum': 1
                            }
                        },
                        'required': ['size']
                    },
                    'scsi': {'type': 'boolean'}
                },
                'required': ['name', 'node', 'scale', 'cpus', 'memory', 'disk'],
                'uniqueItems': True
            }
        }
    },
    'required': ['name', 'pool', 'os_type', 'ssh_key', 'template', 'masters', 'workers']
}
