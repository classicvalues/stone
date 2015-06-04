from __future__ import absolute_import, division, print_function, unicode_literals

import os
import shutil
import six

from contextlib import contextmanager

from babelapi.data_type import (
    DataType,
    Float32,
    Float64,
    Int32,
    Int64,
    UInt32,
    UInt64,
    is_boolean_type,
    is_binary_type,
    is_composite_type,
    is_list_type,
    is_string_type,
    is_struct_type,
    is_timestamp_type,
    is_union_type,
    is_numeric_type,
    is_nullable_type,
    is_void_type,
)

from babelapi.generator import CodeGeneratorMonolingual
from babelapi.lang.swift import SwiftTargetLanguage

base = """
/* Autogenerated. Do not edit. */

import Foundation
"""
class SwiftGenerator(CodeGeneratorMonolingual):
    lang = SwiftTargetLanguage()

    def _docf(self, tag, val):
        return '`{}`'.format(val)

    def generate(self, api):
        cur_folder = os.path.dirname(__file__)
        self.logger.info('Copying BabelSerializers.swift to output folder')
        shutil.copy(os.path.join(cur_folder, 'BabelSerializers.swift'),
                    self.target_folder_path)

        self.logger.info('Copying BabelValidators.swift to output folder')
        shutil.copy(os.path.join(cur_folder, 'BabelValidators.swift'),
                    self.target_folder_path)

        self.logger.info('Copying Client.swift to output folder')
        shutil.copy(os.path.join(cur_folder, 'Client.swift'),
                    self.target_folder_path)

        for namespace in api.namespaces.values():
            path = '{}.swift'.format(self.lang.format_class(namespace.name))
            with self.output_to_relative_path(path):
                self._generate_base_namespace_module(namespace)

    def _generate_base_namespace_module(self, namespace):
        self.emit_raw(base)

        with self.block('public class {}'.format(self.lang.format_class(namespace.name))):
            for data_type in namespace.linearize_data_types():
                if is_struct_type(data_type):
                    self._generate_struct_class(namespace, data_type)
                elif is_union_type(data_type):
                    self._generate_union_type(namespace, data_type)
#            else:
#                raise TypeError('Cannot handle type %r' % type(data_type))
        self._generate_routes(namespace)

    # generation helper methods

    @contextmanager
    def function_block(self, func, args, return_type=None):
        signature = '{}({})'.format(func, args)
        if return_type:
            signature += ' -> {}'.format(return_type)
        with self.block(signature):
            yield

    def _func_args(self, args_list, newlines=False, force_first=False):
        out = []
        first = True
        for k, v in args_list:
            if first and force_first and '=' not in v:
                k = "#"+k
            if v is not None:
                out.append('{}: {}'.format(k, v))
            first = False
        sep = ', '
        if newlines:
            sep += '\n' + self.make_indent()
        return sep.join(out)

    @contextmanager
    def class_block(self, thing, protocols=None):
        protocols = protocols or []
        extensions = []

        if isinstance(thing, DataType):
            name = self.class_data_type(thing)
            if thing.parent_type:
                extensions.append(self.class_data_type(thing.parent_type))
        elif isinstance(thing, six.text_type):
            name = thing
        else:
            raise TypeError("trying to generate class block for unknown type %r" % thing)

        extensions.extend(protocols)

        extend_suffix = ': {}'.format(', '.join(extensions)) if extensions else ''

        with self.block('public class {}{}'.format(name, extend_suffix)):
            yield

    @contextmanager
    def serializer_block(self, data_type):
        with self.class_block(self.class_data_type(data_type)+'Serializer',
                              protocols=['JSONSerializer']):
            self.emit("public init() { }")
            yield

    @contextmanager
    def serializer_func(self, data_type):
        with self.function_block('public func serialize',
                                 args=self._func_args([('value', self.class_data_type(data_type))]),
                                 return_type='JSON'):
            yield

    @contextmanager
    def deserializer_func(self, data_type):
        with self.function_block('public func deserialize',
                                 args=self._func_args([('json', 'JSON')]),
                                 return_type=self.class_data_type(data_type)):
            yield

    def class_data_type(self, data_type):
        return self.lang.format_class(data_type.name)

    def _serializer_obj(self, data_type, namespace=None):
        if is_nullable_type(data_type):
            data_type = data_type.data_type
            nullable = True
        else:
            nullable = False
        if is_list_type(data_type):
            ret = 'ArraySerializer({})'.format(
                self._serializer_obj(data_type.data_type, namespace=namespace))
        elif is_string_type(data_type):
            ret = 'Serialization._StringSerializer'
        elif is_timestamp_type(data_type):
            ret = 'NSDateSerializer("{}")'.format(data_type.format)
        elif is_boolean_type(data_type):
            ret = 'Serialization._BoolSerializer'
        elif is_binary_type(data_type):
            ret = 'Serialization._NSDataSerializer'
        elif is_void_type(data_type):
            ret = 'Serialization._VoidSerializer'
        elif isinstance(data_type, Int32):
            ret = 'Serialization._Int32Serializer'
        elif isinstance(data_type, Int64):
            ret = 'Serialization._Int64Serializer'
        elif isinstance(data_type, UInt32):
            ret = 'Serialization._UInt32Serializer'
        elif isinstance(data_type, UInt64):
            ret = 'Serialization._UInt64Serializer'
        elif isinstance(data_type, Float32):
            ret = 'Serialization._FloatSerializer'
        elif isinstance(data_type, Float64):
            ret = 'Serialization._DoubleSerializer'
        elif is_composite_type(data_type):
            ret = self.lang.format_class(namespace.name) + '.' if namespace else ''
            ret += self.class_data_type(data_type) + 'Serializer()'

        if nullable:
            ret = 'NullableSerializer({})'.format(ret)

        return ret

    def _swift_type_mapping(self, data_type, namespace=None, serializer=False):
        suffix = 'Serializer' if serializer else ''
        if is_nullable_type(data_type):
            data_type = data_type.data_type
            nullable = True
        else:
            nullable = False
        if is_list_type(data_type):
            ret = 'Array{}<{}>'.format(
                suffix,
                self._swift_type_mapping(data_type.data_type, namespace, serializer)
            )
            suffix = ''
        elif is_string_type(data_type):
            ret = 'String'
        elif is_timestamp_type(data_type):
            ret = 'NSDate'
        elif is_boolean_type(data_type):
            ret = 'Bool'
        elif is_binary_type(data_type):
            ret = 'NSData'
        elif is_void_type(data_type):
            ret = 'Void'
        elif isinstance(data_type, Int32):
            ret = 'Int32'
        elif isinstance(data_type, Int64):
            ret = 'Int64'
        elif isinstance(data_type, UInt32):
            ret = 'UInt32'
        elif isinstance(data_type, UInt64):
            ret = 'UInt64'
        elif isinstance(data_type, Float32):
            ret = 'Float'
        elif isinstance(data_type, Float64):
            ret = 'Double'
        elif is_composite_type(data_type):
            ret = self.lang.format_class(namespace.name) + "." if namespace else ""
            ret += self.class_data_type(data_type)
        ret += suffix
        if nullable:
            if serializer:
                ret = 'NullableSerializer<{}>'.format(ret)
            else:
                ret += '?'

        return ret

    def _determine_validator_type(self, data_type):
        if is_nullable_type(data_type):
            data_type = data_type.data_type
            nullable = True
        else:
            nullable = False
        if is_list_type(data_type):
            item_validator = self._determine_validator_type(data_type.data_type)
            if item_validator:
                v = "arrayValidator({})".format(
                    self._func_args([
                        ("minItems", data_type.min_items),
                        ("maxItems", data_type.max_items),
                        ("itemValidator", item_validator),
                    ])
                )
            else:
                return None
        elif is_numeric_type(data_type):
            v = "comparableValidator({})".format(
                self._func_args([
                    ("minValue", data_type.min_value),
                    ("maxValue", data_type.max_value),
                ])
            )
        elif is_string_type(data_type):
            pat = data_type.pattern.encode('ascii') if data_type.pattern else None
            v = "stringValidator({})".format(
                self._func_args([
                    ("minLength", data_type.min_length),
                    ("maxLength", data_type.max_length),
                    ("pattern", '"{}"'.format(pat.encode('string-escape')) if pat else None),
                ])
            )
        else:
            return None

        if nullable:
            v = "nullableValidator({})".format(v)
        return v

    def _generate_struct_class(self, namespace, data_type):
        if data_type.doc:
            self.emit_wrapped_text(self.process_doc(data_type.doc, self._docf), prefix='/// ')
        else:
            self.emit('/// The {} struct'.format(self.class_data_type(data_type)))
        self.emit('///')
        for f in data_type.fields:
            self.emit('/// :param: {}'.format(self.lang.format_variable(f.name)))
            if f.doc:
                self.emit_wrapped_text(self.process_doc(f.doc, self._docf), prefix='///        ')

        with self.class_block(data_type, protocols=['Printable']):
            for field in data_type.fields:
                self.emit('public let {} : {}'.format(
                    self.lang.format_variable(field.name),
                    self._swift_type_mapping(field.data_type),
                ))
            self._generate_struct_init(namespace, data_type)

            decl = 'public var' if not data_type.parent_type else 'public override var'

            with self.block('{} description : String'.format(decl)):
                cls = self.class_data_type(data_type)+'Serializer'
                self.emit(
                    'return "\(prepareJSONForSerialization({}().serialize(self)))"'.format(cls)
                )

        self._generate_struct_class_serializer(namespace, data_type)

    def _struct_init_args(self, data_type, namespace=None):
        args = []
        for field in data_type.all_fields:
            name = self.lang.format_variable(field.name)
            value = self._swift_type_mapping(field.data_type, namespace=namespace)
            field_type = field.data_type
            if is_nullable_type(field_type):
                field_type = field_type.data_type
                nullable = True
            else:
                nullable = False

            if field.has_default:
                if is_union_type(field_type):
                    default = '.{}'.format(self.lang.format_class(field.default.tag_name))
                else:
                    default = self.lang.format_obj(field.default)
                value += ' = {}'.format(default)
            elif nullable:
                value += ' = nil'
            arg = (name, value)
            args.append(arg)
        return args

    def _generate_struct_init(self, namespace, data_type):
        # init method
        args = self._struct_init_args(data_type)
        if data_type.parent_type and not data_type.fields:
            return
        with self.function_block('public init', self._func_args(args)):
            for field in data_type.fields:
                v = self.lang.format_variable(field.name)
                validator = self._determine_validator_type(field.data_type)
                if validator:
                    self.emit('{}(value: {})'.format(validator, v))
                self.emit('self.{} = {}'.format(v, v))
            if data_type.parent_type:
                func_args = [(self.lang.format_variable(f.name),
                              self.lang.format_variable(f.name))
                             for f in data_type.parent_type.all_fields]
                self.emit('super.init({})'.format(self._func_args(func_args)))

    def _generate_enumerated_subtype_serializer(self, namespace, data_type):
        with self.block('switch value'):
            for tags, subtype in data_type.get_all_subtypes_with_tags():
                assert len(tags) == 1, tags
                tag = tags[0]
                tagvar = self.lang.format_variable(tag)
                self.emit('case let {} as {}:'.format(
                    tagvar,
                    self._swift_type_mapping(subtype, namespace=namespace)
                ))

                with self.indent():
                    with self.block('for (k,v) in Serialization.getFields({}.serialize({}))'.format(
                        self._serializer_obj(subtype), tagvar
                    )):
                        self.emit('output[k] = v')
                    self.emit('output[".tag"] = .Str("{}")'.format(tag))
            self.emit('default: fatalError("Tried to serialize unexpected subtype")')

    def _generate_struct_base_class_deserializer(self, namespace, data_type):
            args = []
            for field in data_type.all_fields:
                var = self.lang.format_variable(field.name)
                self.emit('let {} = {}.deserialize(dict["{}"] ?? .Null)'.format(
                    var,
                    self._serializer_obj(field.data_type),
                    field.name,
                ))

                args.append((var, var))
            self.emit('return {}({})'.format(
                self.class_data_type(data_type),
                self._func_args(args)
            ))

    def _generate_enumerated_subtype_deserializer(self, namespace, data_type):
        self.emit('let tag = Serialization.getTag(dict)')
        with self.block('switch tag'):
            for tags, subtype in data_type.get_all_subtypes_with_tags():
                assert len(tags) == 1, tags
                tag = tags[0]
                self.emit('case "{}":'.format(tag))
                with self.indent():
                    self.emit('return {}.deserialize(json)'.format(self._serializer_obj(subtype)))
            self.emit('default:')
            with self.indent():
                if data_type.is_catch_all():
                    self._generate_struct_base_class_deserializer(namespace, data_type)
                else:
                    self.emit('fatalError("Unknown tag \\(tag)")')

    def _generate_struct_class_serializer(self, namespace, data_type):
        with self.serializer_block(data_type):
            with self.serializer_func(data_type):
                if not data_type.all_fields:
                    self.emit('var output = [String : JSON]()')
                else:
                    self.emit("var output = [ ")
                    for field in data_type.all_fields:
                        self.emit('"{}": {}.serialize(value.{}),'.format(
                            field.name,
                            self._serializer_obj(field.data_type),
                            self.lang.format_variable(field.name)
                        ))
                    self.emit(']')

                    if data_type.has_enumerated_subtypes():
                        self._generate_enumerated_subtype_serializer(namespace, data_type)
                self.emit('return .Dictionary(output)')
            with self.deserializer_func(data_type):
                with self.block("switch json"):
                    self.emit("case .Dictionary(let dict):")
                    with self.indent():
                        if data_type.has_enumerated_subtypes():
                            self._generate_enumerated_subtype_deserializer(namespace, data_type)
                        else:
                            self._generate_struct_base_class_deserializer(namespace, data_type)
                    self.emit("default:")
                    with self.indent():
                        self.emit('assert(false, "Type error deserializing")')

    def _format_tag_type(self, namespace, data_type):
        if is_void_type(data_type):
            return ''
        else:
            return '({})'.format(self._swift_type_mapping(data_type, namespace))

    def _generate_union_type(self, namespace, data_type):
        if data_type.doc:
            self.emit_wrapped_text(self.process_doc(data_type.doc, self._docf), prefix='/// ')
        else:
            self.emit('/// The {} union'.format(self.class_data_type(data_type)))
        self.emit('///')
        for f in data_type.fields:
            self.emit('/// - {}{}'.format(self.lang.format_class(f.name), ':' if f.doc else ''))
            if f.doc:
                self.emit_wrapped_text(self.process_doc(f.doc, self._docf), prefix='///   ')
        with self.block('public enum {} : Printable'.format(self.class_data_type(data_type))):
            for field in data_type.fields:
                typ = self._format_tag_type(namespace, field.data_type)
                self.emit('case {}{}'.format(self.lang.format_class(field.name),
                                                  typ))
            with self.block('public var description : String'):
                cls = self.class_data_type(data_type)+'Serializer'
                self.emit(
                    'return "\(prepareJSONForSerialization({}().serialize(self)))"'.format(cls)
                )

        self._generate_union_serializer(data_type)

    def _tag_type(self, data_type, field):
        return "{}.{}".format(
            self.class_data_type(data_type),
            self.lang.format_class(field.name)
        )

    def _generate_union_serializer(self, data_type):
        with self.serializer_block(data_type):
            with self.serializer_func(data_type), self.block('switch value'):
                for field in data_type.fields:
                    field_type = field.data_type
                    if is_nullable_type(field_type):
                        field_type = field_type.data_type
                    case = '.{}'.format(self.lang.format_class(field.name))
                    d = ['".tag": .Str("{}")'.format(field.name)]
                    if not is_void_type(field_type):
                        case += '(let arg)'
                        d.append('"{}": {}.serialize(arg)'.format(
                            field.name,
                            self._serializer_obj(field.data_type)
                        ))

                    ret = ".Dictionary([{}])".format(", ".join(d))
                    self.emit('case {}:'.format(case))
                    with self.indent():
                        self.emit('return {}'.format(ret))
            with self.deserializer_func(data_type):
                with self.block("switch json"):
                    self.emit("case .Dictionary(let d):")
                    with self.indent():
                        self.emit('let tag = Serialization.getTag(d)')
                        with self.block('switch tag'):
                            for field in data_type.fields:
                                field_type = field.data_type
                                if is_nullable_type(field_type):
                                    field_type = field_type.data_type

                                self.emit('case "{}":'.format(field.name))

                                tag_type = self._tag_type(data_type, field)
                                with self.indent():
                                    if is_void_type(field_type):
                                        self.emit('return {}'.format(tag_type))
                                    else:
                                        self.emit('let v = {}.deserialize(d["{}"] ?? .Null)'.format(
                                            self._serializer_obj(field_type), field.name
                                        ))
                                        self.emit('return {}(v)'.format(tag_type))
                            self.emit('default:')
                            with self.indent():
                                if data_type.catch_all_field:
                                    self.emit('return {}'.format(
                                        self._tag_type(data_type, data_type.catch_all_field)
                                    ))
                                else:
                                    self.emit('fatalError("Unknown tag \(tag)")')
                    self.emit("default:")
                    with self.indent():

                        self.emit('assert(false, "Failed to deserialize")')
    def _generate_routes(self, namespace):
        if not len(namespace.routes):
            return
        with self.block('extension BabelClient'):
            for route in namespace.routes:
                self._generate_route(namespace, route)

    STYLE_MAPPING = {
        None: 'Rpc',
        'upload': 'Upload',
        'download': 'Download',
    }

    def _generate_route(self, namespace, route):
        host_ident = route.attrs.get('host', 'meta')
        request_type = self._swift_type_mapping(route.request_data_type, namespace=namespace)
        route_style = route.attrs.get('style')

        if is_struct_type(route.request_data_type):
            arg_list = self._struct_init_args(route.request_data_type, namespace=namespace)
            doc_list = [(self.lang.format_variable(f.name), self.process_doc(f.doc, self._docf))
                        for f in route.request_data_type.fields if f.doc]
        else:
            arg_list = [] if is_void_type(route.request_data_type) else [('request', request_type)]
            doc_list = []

        if route_style == 'upload':
            arg_list.append(('body', 'NSData'))
            doc_list.append(('body', 'The binary payload to upload'))

        func_name = self.lang.format_method('{}_{}'.format(namespace.name, route.name))
        if route.doc:
            self.emit_wrapped_text(route.doc, prefix='/// ')
        else:
            self.emit_wrapped_text('/// The {} route'.format(func_name))
        self.emit('///')
        for name, doc in doc_list:
            self.emit('/// :param: {}'.format(name))
            if doc:
                self.emit_wrapped_text(doc, prefix='///        ')

        route_type = self.STYLE_MAPPING[route.attrs.get('style')]

        rtype = self._swift_type_mapping(route.response_data_type,
                                         namespace=namespace, serializer=True)
        etype = self._swift_type_mapping(route.error_data_type,
                                         namespace=namespace, serializer=True)

        with self.function_block('public func {}'.format(func_name),
                                 args=self._func_args(arg_list, force_first=True),
                                 return_type='Babel{}Request<{}, {}>'.format(route_type,
                                                                               rtype,
                                                                               etype)):

            if is_struct_type(route.request_data_type):
                args = [(name, name) for name, _ in self._struct_init_args(route.request_data_type)]
                self.emit('let request = {}({})'.format(request_type, self._func_args(args)))

            func_args = [
                ('client', 'self'),
                ('host', '"'+host_ident+'"'),
                ('route', '"/{}/{}"'.format(namespace.name, route.name)),
                ('params', '{}.serialize({})'.format(
                    self._serializer_obj(route.request_data_type, namespace=namespace),
                    '' if is_void_type(route.request_data_type) else 'request'))
            ]
            if route_style == 'upload':
                func_args.append(('body', 'body'))

            func_args.extend([
                ('responseSerializer', self._serializer_obj(route.response_data_type,
                                                              namespace=namespace)),
                ('errorSerializer', self._serializer_obj(route.error_data_type,
                                                           namespace=namespace)),
            ])

            self.emit('return Babel{}Request({})'.format(route_type, self._func_args(func_args)))