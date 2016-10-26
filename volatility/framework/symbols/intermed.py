import copy
import json
import logging
import urllib.parse

from volatility.framework import constants, exceptions, interfaces, objects

vollog = logging.getLogger(__name__)


class IntermediateSymbolTable(interfaces.symbols.SymbolTableInterface):
    """Class for storing intermediate debugging data as objects and classes"""

    def __init__(self, name, idd_filepath, native_types = None):
        super().__init__(name, native_types)
        url = urllib.parse.urlparse(idd_filepath)
        if url.scheme != 'file':
            raise NotImplementedError("The {0} scheme is not yet implement for the Intermediate Symbol Format.")
        with open(url.path, "r") as fp:
            self._json = json.load(fp)
        self._validate_json()
        self._overrides = {}

    def _validate_json(self):
        if (not 'user_types' in self._json or
                not 'base_types' in self._json or
                not 'metadata' in self._json or
                not 'symbols' in self._json or
                not 'enums' in self._json):
            raise exceptions.SymbolSpaceError("Malformed JSON file provided")

    def get_type_class(self, name):
        return self._overrides.get(name, objects.Struct)

    def set_type_class(self, name, clazz):
        if name not in self.types:
            raise ValueError("Symbol type " + name + " not in " + self.name + " SymbolTable")
        self._overrides[name] = clazz

    def del_type_class(self, name):
        if name in self._overrides:
            del self._overrides[name]

    @property
    def types(self):
        """Returns an iterator of the symbol names"""
        return self._json.get('user_types', {})

    def _interdict_to_template(self, dictionary):
        """Converts an intermediate format dict into an object template"""
        if not dictionary:
            raise exceptions.SymbolSpaceError("Invalid intermediate dictionary: " + repr(dictionary))

        type_name = dictionary['kind']
        if type_name == 'base':
            type_name = dictionary['name']

        if type_name in self.natives.types:
            # The symbol is a native type
            native_template = self.natives.get_type(type_name)

            # Add specific additional parameters, etc
            update = {}
            if type_name == 'array':
                update['count'] = dictionary['count']
                update['target'] = self._interdict_to_template(dictionary['subtype'])
            elif type_name == 'pointer':
                update["target"] = self._interdict_to_template(dictionary['subtype'])
            elif type_name == 'enum':
                update = self._lookup_enum(dictionary['name'])
            elif type_name == 'bitfield':
                update = {'start_bit': dictionary['bit_position'], 'end_bit': dictionary['bit_length']}
                update['target'] = self._interdict_to_template(dictionary['type'])
            native_template.update_vol(**update)  # pylint: disable=W0142
            return native_template

        # Otherwise
        if dictionary['kind'] not in ['struct', 'union']:
            raise exceptions.SymbolSpaceError("Unknown Intermediate format: " + repr(dictionary))

        return objects.templates.ReferenceTemplate(type_name = self.name + constants.BANG + dictionary['name'])

    def _lookup_enum(self, name):
        """Looks up an enumeration and returns a dictionary of __init__ parameters for an Enum"""
        lookup = self._json['enums'].get(name, None)
        if not lookup:
            raise exceptions.SymbolSpaceError("Unknown enumeration found: " + repr(name))
        result = {"choices": copy.deepcopy(lookup['constants']),
                  "target": self.natives.get_type(lookup['base'])}
        return result

    def get_type(self, type_name):
        """Resolves an individual symbol"""
        if type_name not in self._json['user_types']:
            raise exceptions.SymbolError("Unknown symbol:" + repr(type_name))
        curdict = self._json['user_types'][type_name]
        members = {}
        for member_name in curdict['fields']:
            interdict = curdict['fields'][member_name]
            member = (interdict['offset'], self._interdict_to_template(interdict['type']))
            members[member_name] = member
        object_class = self.get_type_class(type_name)
        return objects.templates.ObjectTemplate(type_name = self.name + constants.BANG + type_name,
                                                object_class = object_class,
                                                size = curdict['length'],
                                                members = members)