import os
import logging
from functools import singledispatch

import crayons
import yaml
from jsonschema import ValidationError, validate


class GenericConfigFile:
    schema = None

    def __init__(self, filename: str = None):
        self.filename = filename
        self.config = self.read_yaml_file()

    @property
    def exists(self):
        return os.path.exists(self.filename)

    def read_yaml_file(self):
        if not self.filename:
            logging.error(crayons.red(f'There is no filename declared'))
            return None
        if not self.exists:
            logging.error(crayons.red(f'File {self.filename} does not exist'))
            return None
        return self._read_yaml_file_from_input()

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
        raise NotImplementedError

    def serialize(self):
        raise NotImplementedError


class ProxmoxClusterConfigFile(GenericConfigFile):
    schema = {
        'type': 'object',
        'properties': {
            'name': {'type': 'string'},
            'nodes': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'name': {'type': 'string'},
                        'ip': {'type': 'string'}
                    },
                    'required': ['name']
                },
                'minItems': 1,
                'uniqueItems': True
            }
        },
        'required': ['name', 'nodes']
    }

    def read_yaml_file(self):
        if not self.filename or not self.exists:
            self.filename = self._get_default_filename()
        return self._read_yaml_file_from_input()

    @staticmethod
    def _get_default_filename():
        filenames = '.cluster.yaml', '.cluster.yml'
        for file in filenames:
            if os.path.exists(file):
                return file
        logging.error(crayons.red(f'There is no file named: {filenames[0]} or {filenames[1]} in the current folder.'))
        return None

    def validate(self):
        if not self.schema:
            return self.config
        if not self.config:
            logging.error(crayons.red(f'No serialized object generated from {self.filename}'))
            return None
        try:
            validate(instance=self.config, schema=self.schema)
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


class ConfigSerializer:
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
        setattr(self, key, [ConfigSerializer(unpacked) for unpacked in value])

    def __repr__(self):
        """
        Remove private and dunder methods from repr.
        """
        attrs = str([attribute for attribute in dir(self) if '__' not in attribute and not attribute.startswith('_')])
        return f'<{type(self).__name__}: {attrs}>'
