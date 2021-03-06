import os
import logging
from functools import singledispatch

import crayons
import yaml
from jsonschema import ValidationError, validate, FormatChecker

from konverge.schema import PROXMOX_CLUSTER_SCHEMA, KUBE_CLUSTER_SCHEMA


class GenericConfigFile:
    schema = None
    filenames = tuple()

    def __init__(self, filename: str = None):
        self.filename = filename
        self.config = self.read_yaml_file()

    @property
    def exists(self):
        return os.path.exists(self.filename)

    def read_yaml_file(self):
        if not self.filename or not self.exists:
            self.filename = self._get_default_filename()
        return self._read_yaml_file_from_input()

    def _get_default_filename(self):
        for file in self.filenames:
            if os.path.exists(file):
                return file
        logging.error(crayons.red(f'There is no file named: {self.filenames} in the current folder.'))
        return None

    def _read_yaml_file_from_input(self):
        if not self.filename:
            logging.error(crayons.red(f'Cannot read filename: {self.filename}'))
            return None
        try:
            with open(self.filename, mode='r') as stream:
                config = yaml.safe_load(stream)
        except yaml.YAMLError as yaml_error:
            logging.error(crayons.red(f'Error: failed to load from {self.filename}'))
            logging.error(crayons.red(f'{yaml_error}'))
            return
        if not config:
            logging.error(crayons.red(f'File {self.filename} is empty'))
            return
        return config

    def validate(self):
        if not self.schema:
            return self.config
        if not self.config:
            logging.error(crayons.red(f'No serialized object generated from {self.filename}'))
            return None
        try:
            validate(instance=self.config, schema=self.schema, format_checker=FormatChecker())
        except ValidationError as validation_failed:
            logging.error(crayons.red(f'{self.filename} invalid: {validation_failed}'))
            return None
        return self.config

    def serialize(self):
        if not self.config:
            logging.error(crayons.red(f'No serialized object generated from {self.filename}'))
            return None
        validated = self.validate()
        return ConfigSerializer(validated)


class ProxmoxClusterConfigFile(GenericConfigFile):
    schema = PROXMOX_CLUSTER_SCHEMA
    filenames = '.pve.yaml', '.pve.yml', '.proxmox.yaml', '.proxmox.yml'


class KubeClusterConfigFile(GenericConfigFile):
    schema = KUBE_CLUSTER_SCHEMA
    filenames = '.cluster.yaml', '.cluster.yml'

    def serialize(self):
        if not self.config:
            logging.error(crayons.red(f'No serialized object generated from {self.filename}'))
            return None
        return self.validate()


class ConfigSerializer:
    name: str

    def __init__(self, config: dict):
        self._serialize_values = singledispatch(self._serialize_values)
        self._serialize_values.register(dict, self._serialize_values_dict)
        self._serialize_values.register(list, self._serialize_values_list)
        if config:
            for key, value in config.items():
                self._serialize_values(value, key)

    def _serialize_values(self, value, key):
        setattr(self, key, value)

    def _serialize_values_dict(self, value, key):
        setattr(self, key, ConfigSerializer(value))

    def _serialize_values_list(self, value, key):
        dispatch = lambda entry: ConfigSerializer(entry) if isinstance(entry, dict) else entry
        setattr(self, key, [dispatch(unpacked) for unpacked in value])

    def __repr__(self):
        """
        Remove private and dunder methods from repr.
        """
        attrs = str([attribute for attribute in dir(self) if '__' not in attribute and not attribute.startswith('_')])
        return f'<{type(self).__name__}: {attrs}>'
