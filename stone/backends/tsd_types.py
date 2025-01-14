from __future__ import absolute_import, division, print_function, unicode_literals

import json
import os
import re
import six
import sys

_MYPY = False
if _MYPY:
    import typing  # noqa: F401 # pylint: disable=import-error,unused-import,useless-suppression

# Hack to get around some of Python 2's standard library modules that
# accept ascii-encodable unicode literals in lieu of strs, but where
# actually passing such literals results in errors with mypy --py2. See
# <https://github.com/python/typeshed/issues/756> and
# <https://github.com/python/mypy/issues/2536>.
import importlib
argparse = importlib.import_module(str('argparse'))  # type: typing.Any

from stone.ir import ApiNamespace
from stone.ir import (
    is_alias,
    is_struct_type,
    is_union_type,
    is_user_defined_type,
    is_void_type,
    unwrap_nullable,
)
from stone.backend import CodeBackend
from stone.backends.helpers import (
    fmt_pascal,
)
from stone.backends.tsd_helpers import (
    fmt_polymorphic_type_reference,
    fmt_tag,
    fmt_type,
    fmt_type_name,
    fmt_union,
    generate_imports_for_referenced_namespaces,
    get_data_types_for_namespace,
)


_cmdline_parser = argparse.ArgumentParser(prog='tsd-types-backend')
_cmdline_parser.add_argument(
    'template',
    help=('A template to use when generating the TypeScript definition file. '
          'Replaces the string /*TYPES*/ with stone type definitions.')
)
_cmdline_parser.add_argument(
    'filename',
    nargs='?',
    help=('The name of the generated typeScript definition file that contains '
          'all of the emitted types.'),
)
_cmdline_parser.add_argument(
    '--exclude_error_types',
    default=False,
    action='store_true',
    help='If true, the output will exclude the interface for Error type.',
)
_cmdline_parser.add_argument(
    '-e',
    '--extra-arg',
    action='append',
    type=str,
    default=[],
    help=("Additional argument to add to a route's argument based "
          "on if the route has a certain attribute set. Format (JSON): "
          '{"match": ["ROUTE_ATTR", ROUTE_VALUE_TO_MATCH], '
          '"arg_name": "ARG_NAME", "arg_type": "ARG_TYPE", '
          '"arg_docstring": "ARG_DOCSTRING"}'),
)
_cmdline_parser.add_argument(
    '-i',
    '--indent-level',
    type=int,
    default=1,
    help=('Indentation level to emit types at. Routes are automatically '
          'indented one level further than this.')
)
_cmdline_parser.add_argument(
    '-s',
    '--spaces-per-indent',
    type=int,
    default=2,
    help=('Number of spaces to use per indentation level.')
)
_cmdline_parser.add_argument(
    '-p',
    '--module-name-prefix',
    type=str,
    default='',
    help=('Prefix for data type module names. '
         'This is useful for repo which requires absolute path as '
         'module name')
)
_cmdline_parser.add_argument(
    '--export-namespaces',
    default=False,
    action='store_true',
    help=('Adds the export tag to each namespace.'
          'This is useful is you are not placing each namespace '
          'inside of a module and want to export each namespace individually')
)


_header = """\
// Auto-generated by Stone, do not modify.
"""

_types_header = """\
/**
 * An Error object returned from a route.
 */
interface Error<T> {
\t// Text summary of the error.
\terror_summary: string;
\t// The error object.
\terror: T;
\t// User-friendly error message.
\tuser_message: UserMessage;
}

/**
 * User-friendly error message.
 */
interface UserMessage {
\t// The message.
\ttext: string;
\t// The locale of the message.
\tlocale: string;
}

"""

_timestamp_definition = "type Timestamp = string;"


class TSDTypesBackend(CodeBackend):
    """
    Generates a single TypeScript definition file with all of the types defined, organized
    as namespaces, if a filename is provided in input arguments. Otherwise generates one
    declaration file for each namespace with the corresponding typescript definitions.

    If a single output file is generated, a top level type definition will be added for the
    Timestamp data type. Otherwise, each namespace will have the type definition for Timestamp.

    Also, note that namespace definitions are emitted as declaration files. Hence any template
    provided as argument must not have a top level declare statement. If namespaces are emitted
    into a single file, the template file can be used to wrap them around a declare statement.
    """

    cmdline_parser = _cmdline_parser

    preserve_aliases = True

    # Instance var of the current namespace being generated
    cur_namespace = None  # type: typing.Optional[ApiNamespace]

    # Instance var to denote if one file is output for each namespace.
    split_by_namespace = False

    def generate(self, api):
        extra_args = self._parse_extra_args(api, self.args.extra_arg)
        template = self._read_template()
        if self.args.filename:
            self._generate_base_namespace_module(api.namespaces.values(), self.args.filename,
                                                 template, extra_args,
                                                 exclude_error_types=self.args.exclude_error_types)
        else:
            self.split_by_namespace = True
            for namespace in api.namespaces.values():
                filename = '{}.d.ts'.format(namespace.name)
                self._generate_base_namespace_module(
                    [namespace], filename, template,
                    extra_args,
                    exclude_error_types=self.args.exclude_error_types)

    def _read_template(self):
        template_path = os.path.join(self.target_folder_path, self.args.template)

        if os.path.isfile(template_path):
            with open(template_path, 'r', encoding='utf-8') as template_file:
                return template_file.read()
        else:
            raise AssertionError('TypeScript template file does not exist.')

    def _generate_base_namespace_module(self, namespace_list, filename,
                                        template, extra_args,
                                        exclude_error_types=False):

        # Skip namespaces that do not contain types.
        if all([len(get_data_types_for_namespace(ns)) == 0 for ns in namespace_list]):
            return

        spaces_per_indent = self.args.spaces_per_indent
        indent_level = self.args.indent_level

        with self.output_to_relative_path(filename):

            # /*TYPES*/
            t_match = re.search("/\\*TYPES\\*/", template)
            if not t_match:
                raise AssertionError('Missing /*TYPES*/ in TypeScript template file.')

            t_start = t_match.start()
            t_end = t_match.end()
            t_ends_with_newline = template[t_end - 1] == '\n'
            temp_end = len(template)
            temp_ends_with_newline = template[temp_end - 1] == '\n'

            self.emit_raw(template[0:t_start] + ("\n" if not t_ends_with_newline else ''))

            indent = spaces_per_indent * indent_level
            indent_spaces = (' ' * indent)
            with self.indent(dent=indent):
                if not exclude_error_types:
                    indented_types_header = indent_spaces + (
                        ('\n' + indent_spaces)
                        .join(_types_header.split('\n'))
                        .replace('\t', ' ' * spaces_per_indent)
                    )
                    self.emit_raw(indented_types_header + '\n')

                if not self.split_by_namespace:
                    self.emit(_timestamp_definition)
                    self.emit()

                for namespace in namespace_list:
                    self._generate_types(namespace, spaces_per_indent, extra_args)
            self.emit_raw(template[t_end + 1:temp_end] +
                          ("\n" if not temp_ends_with_newline else ''))

    def _generate_types(self, namespace, spaces_per_indent, extra_args):
        self.cur_namespace = namespace
        # Count aliases as data types too!
        data_types = get_data_types_for_namespace(namespace)
        # Skip namespaces that do not contain types.
        if len(data_types) == 0:
            return

        if self.split_by_namespace:
            generate_imports_for_referenced_namespaces(
                backend=self, namespace=namespace, module_name_prefix=self.args.module_name_prefix
            )

        if namespace.doc:
            self._emit_tsdoc_header(namespace.doc)

        self.emit(self._get_top_level_declaration(namespace.name))

        with self.indent(dent=spaces_per_indent):
            for data_type in data_types:
                self._generate_type(data_type, spaces_per_indent,
                                    extra_args.get(data_type, []))

        if self.split_by_namespace:
            with self.indent(dent=spaces_per_indent):
                # TODO(Pranay): May avoid adding an unused definition if needed.
                self.emit(_timestamp_definition)

        self.emit('}')
        self.emit()

    def _get_top_level_declaration(self, name):
        if self.split_by_namespace:
            # Use module for when emitting declaration files.
            return "declare module '%s%s' {" % (self.args.module_name_prefix, name)
        else:
            if self.args.export_namespaces:
                return "export namespace %s {" % name
            else:
                # Use namespace for organizing code with-in the file.
                return "namespace %s {" % name

    def _parse_extra_args(self, api, extra_args_raw):
        """
        Parses extra arguments into a map keyed on particular data types.
        """
        extra_args = {}

        def invalid(msg, extra_arg_raw):
            print('Invalid --extra-arg:%s: %s' % (msg, extra_arg_raw),
                  file=sys.stderr)
            sys.exit(1)

        for extra_arg_raw in extra_args_raw:
            try:
                extra_arg = json.loads(extra_arg_raw)
            except ValueError as e:
                invalid(str(e), extra_arg_raw)

            # Validate extra_arg JSON blob
            if 'match' not in extra_arg:
                invalid('No match key', extra_arg_raw)
            elif (not isinstance(extra_arg['match'], list) or
                  len(extra_arg['match']) != 2):
                invalid('match key is not a list of two strings', extra_arg_raw)
            elif (not isinstance(extra_arg['match'][0], six.text_type) or
                  not isinstance(extra_arg['match'][1], six.text_type)):
                print(type(extra_arg['match'][0]))
                invalid('match values are not strings', extra_arg_raw)
            elif 'arg_name' not in extra_arg:
                invalid('No arg_name key', extra_arg_raw)
            elif not isinstance(extra_arg['arg_name'], six.text_type):
                invalid('arg_name is not a string', extra_arg_raw)
            elif 'arg_type' not in extra_arg:
                invalid('No arg_type key', extra_arg_raw)
            elif not isinstance(extra_arg['arg_type'], six.text_type):
                invalid('arg_type is not a string', extra_arg_raw)
            elif ('arg_docstring' in extra_arg and
                  not isinstance(extra_arg['arg_docstring'], six.text_type)):
                invalid('arg_docstring is not a string', extra_arg_raw)

            attr_key, attr_val = extra_arg['match'][0], extra_arg['match'][1]
            extra_args.setdefault(attr_key, {})[attr_val] = \
                (extra_arg['arg_name'], extra_arg['arg_type'],
                 extra_arg.get('arg_docstring'))

        # Extra arguments, keyed on data type objects.
        extra_args_for_types = {}
        # Locate data types that contain extra arguments
        for namespace in api.namespaces.values():
            for route in namespace.routes:
                extra_parameters = []
                if is_user_defined_type(route.arg_data_type):
                    for attr_key in route.attrs:
                        if attr_key not in extra_args:
                            continue
                        attr_val = route.attrs[attr_key]
                        if attr_val in extra_args[attr_key]:
                            extra_parameters.append(extra_args[attr_key][attr_val])
                if len(extra_parameters) > 0:
                    extra_args_for_types[route.arg_data_type] = extra_parameters

        return extra_args_for_types

    def _emit_tsdoc_header(self, docstring):
        self.emit('/**')
        self.emit_wrapped_text(self.process_doc(docstring, self._docf), prefix=' * ')
        self.emit(' */')

    def _generate_type(self, data_type, indent_spaces, extra_args):
        """
        Generates a TypeScript type for the given type.
        """
        if is_alias(data_type):
            self._generate_alias_type(data_type)
        elif is_struct_type(data_type):
            self._generate_struct_type(data_type, indent_spaces, extra_args)
        elif is_union_type(data_type):
            self._generate_union_type(data_type, indent_spaces)

    def _generate_alias_type(self, alias_type):
        """
        Generates a TypeScript type for a stone alias.
        """
        namespace = alias_type.namespace
        self.emit('export type %s = %s;' % (fmt_type_name(alias_type, namespace),
                                     fmt_type_name(alias_type.data_type, namespace)))
        self.emit()

    def _generate_struct_type(self, struct_type, indent_spaces, extra_parameters):
        """
        Generates a TypeScript interface for a stone struct.
        """
        namespace = struct_type.namespace
        if struct_type.doc:
            self._emit_tsdoc_header(struct_type.doc)
        parent_type = struct_type.parent_type
        extends_line = ' extends %s' % fmt_type_name(parent_type, namespace) if parent_type else ''
        self.emit('export interface %s%s {' % (fmt_type_name(struct_type, namespace), extends_line))
        with self.indent(dent=indent_spaces):

            for param_name, param_type, param_docstring in extra_parameters:
                if param_docstring:
                    self._emit_tsdoc_header(param_docstring)
                # Making all extra args optional parameters
                self.emit('%s?: %s;' % (param_name, param_type))

            for field in struct_type.fields:
                doc = field.doc
                field_type, nullable = unwrap_nullable(field.data_type)
                field_ts_type = fmt_type(field_type, namespace)
                optional = nullable or field.has_default
                if field.has_default:
                    # doc may be None. If it is not empty, add newlines
                    # before appending to it.
                    doc = doc + '\n\n' if doc else ''
                    doc = "Defaults to %s." % field.default

                if doc:
                    self._emit_tsdoc_header(doc)
                # Translate nullable types into optional properties.
                field_name = '%s?' % field.name if optional else field.name
                self.emit('%s: %s;' % (field_name, field_ts_type))

        self.emit('}')
        self.emit()

        # Some structs can explicitly list their subtypes. These structs have a .tag field that
        # indicate which subtype they are, which is only present when a type reference is
        # ambiguous.
        # Emit a special interface that contains this extra field, and refer to it whenever we
        # encounter a reference to a type with enumerated subtypes.
        if struct_type.is_member_of_enumerated_subtypes_tree():
            if struct_type.has_enumerated_subtypes():
                # This struct is the parent to multiple subtypes. Determine all of the possible
                # values of the .tag property.
                tag_values = []
                for tags, _ in struct_type.get_all_subtypes_with_tags():
                    for tag in tags:
                        tag_values.append('"%s"' % tag)

                tag_union = fmt_union(tag_values)
                self._emit_tsdoc_header('Reference to the %s polymorphic type. Contains a .tag '
                                        'property to let you discriminate between possible '
                                        'subtypes.' % fmt_type_name(struct_type, namespace))
                self.emit('export interface %s extends %s {' %
                          (fmt_polymorphic_type_reference(struct_type, namespace),
                           fmt_type_name(struct_type, namespace)))

                with self.indent(dent=indent_spaces):
                    self._emit_tsdoc_header('Tag identifying the subtype variant.')
                    self.emit('\'.tag\': %s;' % tag_union)

                self.emit('}')
                self.emit()
            else:
                # This struct is a particular subtype. Find the applicable .tag value from the
                # parent type, which may be an arbitrary number of steps up the inheritance
                # hierarchy.
                parent = struct_type.parent_type
                while not parent.has_enumerated_subtypes():
                    parent = parent.parent_type
                # parent now contains the closest parent type in the inheritance hierarchy that has
                # enumerated subtypes. Determine which subtype this is.
                for subtype in parent.get_enumerated_subtypes():
                    if subtype.data_type == struct_type:
                        self._emit_tsdoc_header('Reference to the %s type, identified by the '
                                                'value of the .tag property.' %
                                                fmt_type_name(struct_type, namespace))
                        self.emit('export interface %s extends %s {' %
                                  (fmt_polymorphic_type_reference(struct_type, namespace),
                                   fmt_type_name(struct_type, namespace)))

                        with self.indent(dent=indent_spaces):
                            self._emit_tsdoc_header('Tag identifying this subtype variant. This '
                                                    'field is only present when needed to '
                                                    'discriminate between multiple possible '
                                                    'subtypes.')
                            self.emit_wrapped_text('\'.tag\': \'%s\';' % subtype.name)

                        self.emit('}')
                        self.emit()
                        break

    def _generate_union_type(self, union_type, indent_spaces):
        """
        Generates a TypeScript interface for a stone union.
        """
        # Emit an interface for each variant. TypeScript 2.0 supports these tagged unions.
        # https://github.com/Microsoft/TypeScript/wiki/What%27s-new-in-TypeScript#tagged-union-types
        parent_type = union_type.parent_type
        namespace = union_type.namespace
        union_type_name = fmt_type_name(union_type, namespace)
        variant_type_names = []
        if parent_type:
            variant_type_names.append(fmt_type_name(parent_type, namespace))

        def _is_struct_without_enumerated_subtypes(data_type):
            """
            :param data_type: any data type.
            :return: True if the given data type is a struct which has no enumerated subtypes.
            """
            return is_struct_type(data_type) and (
                not data_type.has_enumerated_subtypes())

        for variant in union_type.fields:
            if variant.doc:
                self._emit_tsdoc_header(variant.doc)
            variant_name = '%s%s' % (union_type_name, fmt_pascal(variant.name))
            variant_type_names.append(variant_name)

            is_struct_without_enumerated_subtypes = _is_struct_without_enumerated_subtypes(
                variant.data_type)

            if is_struct_without_enumerated_subtypes:
                self.emit('export interface %s extends %s {' % (
                    variant_name, fmt_type(variant.data_type, namespace)))
            else:
                self.emit('export interface %s {' % variant_name)

            with self.indent(dent=indent_spaces):
                # Since field contains non-alphanumeric character, we need to enclose
                # it in quotation marks.
                self.emit("'.tag': '%s';" % variant.name)
                if is_void_type(variant.data_type) is False and (
                    not is_struct_without_enumerated_subtypes
                ):
                    self.emit("%s: %s;" % (variant.name, fmt_type(variant.data_type, namespace)))
            self.emit('}')
            self.emit()

        if union_type.doc:
            self._emit_tsdoc_header(union_type.doc)
        self.emit('export type %s = %s;' % (union_type_name, ' | '.join(variant_type_names)))
        self.emit()

    def _docf(self, tag, val):
        """
        Callback to process documentation references.
        """
        return fmt_tag(self.cur_namespace, tag, val)
