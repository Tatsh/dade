r"""
Convert compiled Core Data model artefacts (``.cdm``, ``.mom``) to JSON.

Both formats are ``NSKeyedArchiver`` binary plists: a ``.cdm`` is a compiled ``.xcmappingmodel``
whose root is an ``NSMappingModel``, and a ``.mom`` is a compiled ``.xcdatamodel`` whose root is an
``NSManagedObjectModel``. The ``.omo`` beside the current-version ``.mom`` is deliberately
unsupported: it is Core Data's undocumented load-time cache of that same model (``momv2$<digest>``
magic, custom offset-table binary) and carries no information the ``.mom`` lacks.

**Default (deserialised object):** replicates what ``NSKeyedUnarchiver`` plus Core Data would
materialise, dispatching on the archive's root class.

For an ``NSMappingModel`` (``.cdm``):

* each ``NSEntityMapping`` becomes an object with plain ``name``, ``mappingType``
  (add/remove/copy/transform/custom), source/destination entity names, hex version hashes,
  migration policy class, and its attribute and relationship mappings;
* every archived ``NSExpression`` tree is rendered back into its canonical source-string form,
  mirroring Foundation's ``description`` conventions: ``$source.category`` for ``valueForKeyPath:``
  function expressions, ``FUNCTION(operand, "selector:", args...)`` for other functions, and
  ``FETCH(request, context)`` for the private ``NSFetchRequestExpression`` - the same strings the
  Xcode mapping-model editor shows;
* ``NSDictionary``/``NSArray`` values (user info, property transforms) are flattened to plain JSON
  objects and arrays.

For an ``NSManagedObjectModel`` (``.mom``):

* each ``NSEntityDescription`` becomes an object with its class name, super/sub-entities, renaming
  identifier, and properties;
* each ``NSAttributeDescription`` carries its readable type (integer32, string, date, ...), value
  class name, optionality, indexed flag, default value, and validation predicates rendered as
  readable strings (``SELF >= 0``); relationships carry destination, inverse, count bounds, and
  delete rule.

**Archive mode (lossless keyed-archive dump):** decodes the raw archive object graph instead (of
any ``NSKeyedArchiver`` plist, whatever its root class), as close to lossless as JSON allows:

* every archived instance becomes an object carrying its ``$class`` name and all archived fields,
  with ``UID`` references resolved in place;
* objects referenced more than once are emitted in full on first use with an ``$id`` marker, and as
  ``{"$ref": id}`` afterwards, so shared structure and cycles survive the conversion;
* ``NSArray``/``NSSet`` variants become ``{"$class": ..., "items": [...]}`` and ``NSDictionary``
  variants ``{"$class": ..., "entries": {...}}``;
* binary data (the entity version hashes) is hex-encoded under ``$data``;
* ``NSMappingType`` and ``NSExpressionType`` gain readable ``$mappingType`` / ``$expressionType``
  annotations alongside the raw values (no loss).

**SQL mode (effective migration SQL, ``.cdm`` only):** :func:`build_sql` emits the SQLite
statements the migration amounts to, using Core Data's ``Z`` conventions (table ``Z<ENTITY>``,
columns ``Z<ATTRIBUTE>`` plus ``Z_PK``/``Z_ENT``/``Z_OPT``, and the ``Z_PRIMARYKEY`` bookkeeping
table). Each copy mapping becomes the single-statement ``INSERT INTO ... SELECT`` equivalent
against an ``ATTACH``\ ed old store; add mappings contribute only their ``CREATE TABLE``. Core Data
really routes every row through ``NSMigrationManager`` in memory, so this is the net effect, not a
transcript. Passing the column types of the compiled *destination* model (see
:func:`load_mom_column_types`) gives columns their real types and numbers ``Z_ENT`` from the full
entity list; without them, columns are emitted untyped (valid in SQLite) from the mapping alone.
Anything untranslatable (a predicate other than ``TRUEPREDICATE``, a value expression that is not
``$source.<key>``) is surfaced as an SQL comment rather than silently dropped.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
import json
import plistlib
import re

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = ('ATTRIBUTE_SQL_TYPES', 'ATTRIBUTE_TYPE_NAMES', 'COLLECTION_CLASSES',
           'COMPOUND_PREDICATE_JOINERS', 'DELETE_RULES', 'ENTITY_MAPPING_TYPES', 'EXPRESSION_TYPES',
           'PREDICATE_OPERATORS', 'build_sql', 'convert', 'load_mom_column_types')

ENTITY_MAPPING_TYPES: Mapping[int, str] = {
    0: 'undefined',
    1: 'custom',
    2: 'add',
    3: 'remove',
    4: 'copy',
    5: 'transform',
}
"""``NSEntityMappingType`` (``CoreData/NSEntityMapping.h``) to its readable name.

:meta hide-value:
"""
EXPRESSION_TYPES: Mapping[int, str] = {
    0: 'constantValue',
    1: 'evaluatedObject',
    2: 'variable',
    3: 'keyPath',
    4: 'function',
    5: 'unionSet',
    6: 'intersectSet',
    7: 'minusSet',
    10: 'keyPathSpecifier',
    13: 'subquery',
    14: 'aggregate',
    15: 'anyKey',
    19: 'block',
    20: 'conditional',
    50: 'fetchRequest',
}
"""``NSExpressionType`` (``Foundation/NSExpression.h``) to its readable name.

The private values 10 and 50, which appear in compiled mapping models, are included.

:meta hide-value:
"""
COLLECTION_CLASSES = ('NSArray', 'NSMutableArray', 'NSOrderedSet', 'NSMutableOrderedSet', 'NSSet',
                      'NSMutableSet')
"""Archived class names decoded as an ordered list of items rather than a keyed object.

:meta hide-value:
"""
ATTRIBUTE_TYPE_NAMES: Mapping[int, str] = {
    0: 'undefined',
    100: 'integer16',
    200: 'integer32',
    300: 'integer64',
    400: 'decimal',
    500: 'double',
    600: 'float',
    700: 'string',
    800: 'boolean',
    900: 'date',
    1000: 'binaryData',
    1800: 'UUID',
    1900: 'URI',
    2000: 'transformable',
    2100: 'objectID',
}
"""``NSAttributeType`` (``CoreData/NSAttributeDescription.h``) to its readable name.

:meta hide-value:
"""
PREDICATE_OPERATORS: Mapping[int, str] = {
    0: '<',
    1: '<=',
    2: '>',
    3: '>=',
    4: '==',
    5: '!=',
    6: 'MATCHES',
    7: 'LIKE',
    8: 'BEGINSWITH',
    9: 'ENDSWITH',
    10: 'IN',
    99: 'CONTAINS',
    100: 'BETWEEN',
}
"""``NSPredicateOperatorType`` (``Foundation/NSComparisonPredicate.h``) to its symbol.

:meta hide-value:
"""
COMPOUND_PREDICATE_JOINERS: Mapping[int, str] = {
    0: ' AND NOT ',
    1: ' AND ',
    2: ' OR ',
}
"""``NSCompoundPredicateType`` to the text that joins its subpredicates.

A NOT predicate has only one subpredicate, so its joiner never appears.

:meta hide-value:
"""
DELETE_RULES: Mapping[int, str] = {
    0: 'noAction',
    1: 'nullify',
    2: 'cascade',
    3: 'deny',
}
"""``NSDeleteRule`` (``CoreData/NSRelationshipDescription.h``) to its readable name.

:meta hide-value:
"""
ATTRIBUTE_SQL_TYPES: Mapping[int, str] = {
    100: 'INTEGER',
    200: 'INTEGER',
    300: 'INTEGER',
    400: 'DECIMAL',
    500: 'FLOAT',
    600: 'FLOAT',
    700: 'VARCHAR',
    800: 'INTEGER',
    900: 'TIMESTAMP',
    1000: 'BLOB',
    2000: 'BLOB',
}
"""``NSAttributeType`` to the column type the SQLite store emits for it.

:meta hide-value:
"""

# The ``NSExpressionType`` values rendered specially. The rest fall through to a description naming
# the type, since they carry no canonical source-string form worth reproducing.
_EXPRESSION_CONSTANT = 0
_EXPRESSION_SELF = 1
_EXPRESSION_VARIABLE = 2
_EXPRESSION_KEY_PATHS = (3, 10)
_EXPRESSION_FUNCTION = 4
_EXPRESSION_FETCH_REQUEST = 50

_FETCH_PATTERN = re.compile(
    r'FETCH\(FUNCTION\(\$manager, "fetchRequestForSourceEntityNamed:predicateString:", '
    r'"([^"]+)", "([^"]*)"\), \$manager\.sourceContext\)')
_SOURCE_KEY_PATTERN = re.compile(r'^\$source\.(\w+)$')


class _ArchiveDecoder:
    """
    Resolve an ``NSKeyedArchiver`` object graph into JSON-compatible values.

    With ``share_refs`` (the archive dump), objects referenced more than once are emitted once with
    ``$id`` and thereafter as ``{"$ref": id}``. Without it (the deserialised model), shared objects
    are expanded at every use, as a real unarchive would hand out the same instance in both places.

    Parameters
    ----------
    archive : Mapping[str, Any]
        The whole keyed archive, as :py:func:`plistlib.loads` returns it.
    share_refs : bool
        Emit shared objects once with an ``$id`` marker and refer back to them afterwards.

    Raises
    ------
    ValueError
        When the plist was not written by ``NSKeyedArchiver``.
    """
    def __init__(self, archive: Mapping[str, Any], *, share_refs: bool = True) -> None:
        if archive.get('$archiver') != 'NSKeyedArchiver':
            msg = f'Not an NSKeyedArchiver archive: {archive.get("$archiver")!r}.'
            raise ValueError(msg)
        self.objects: list[Any] = archive['$objects']
        self.share_refs = share_refs
        self.refcounts = self._count_references(archive)
        self.emitted: set[int] = set()
        self.in_progress: set[int] = set()

    def class_name(self, instance: Mapping[str, Any]) -> str:
        """
        Read the archived class name of an instance.

        Parameters
        ----------
        instance : Mapping[str, Any]
            An archived instance carrying a ``$class`` reference.

        Returns
        -------
        str
            The class name, or ``'?'`` when the descriptor holds none.
        """
        descriptor = self.objects[instance['$class'].data]
        return str(descriptor.get('$classname', '?'))

    def decode_uid(self, uid: int) -> Any:
        """
        Decode the object a ``UID`` refers to, applying the sharing policy.

        Parameters
        ----------
        uid : int
            Index into the archive's ``$objects`` table.

        Returns
        -------
        Any
            The decoded value, a ``{'$ref': uid}`` back-reference, or ``None`` for the null object.
        """
        obj = self.objects[uid]
        if uid == 0 and obj == '$null':
            return None
        if not isinstance(obj, dict):
            return self.decode_value(obj)
        # Instances only: share and cycle handling applies to the object graph.
        if (self.share_refs and uid in self.emitted) or uid in self.in_progress:
            return {'$ref': uid}
        self.in_progress.add(uid)
        try:
            decoded = self.decode_instance(obj)
        finally:
            self.in_progress.discard(uid)
        if self.share_refs and self.refcounts.get(uid, 0) > 1:
            decoded = {'$id': uid, **decoded}
            self.emitted.add(uid)
        return decoded

    def decode_instance(self, instance: Mapping[str, Any]) -> dict[str, Any]:
        """
        Decode one archived instance into a plain object.

        Parameters
        ----------
        instance : Mapping[str, Any]
            The archived instance.

        Returns
        -------
        dict[str, Any]
            The decoded object, carrying its ``$class`` name alongside its fields.
        """
        if '$classname' in instance:
            # A class descriptor reached directly (unusual); emit verbatim.
            return dict(instance)
        name = self.class_name(instance)
        if name in COLLECTION_CLASSES:
            return {
                '$class': name,
                'items': [self.decode_value(v) for v in instance.get('NS.objects', [])]
            }
        if 'NS.keys' in instance:
            keys = [self.decode_value(k) for k in instance['NS.keys']]
            values = [self.decode_value(v) for v in instance.get('NS.objects', [])]
            pairs = list(zip(keys, values, strict=True))
            if all(isinstance(k, str) for k in keys):
                return {'$class': name, 'entries': dict(pairs)}
            return {'$class': name, 'entries': [list(pair) for pair in pairs]}
        if 'NS.string' in instance:
            return {'$class': name, 'string': self.decode_value(instance['NS.string'])}
        # Decode fields in sorted key order so that, with the key-sorted JSON output, shared
        # objects are expanded at the first position a reader encounters and later positions carry
        # the ``$ref``.
        decoded: dict[str, Any] = {'$class': name}
        for key, value in sorted(instance.items()):
            if key == '$class':
                continue
            decoded[key] = self.decode_value(value)
        if isinstance(decoded.get('NSMappingType'), int):
            decoded['$mappingType'] = ENTITY_MAPPING_TYPES.get(
                decoded['NSMappingType'], f'unknown ({decoded["NSMappingType"]})')
        if isinstance(decoded.get('NSExpressionType'), int):
            decoded['$expressionType'] = EXPRESSION_TYPES.get(
                decoded['NSExpressionType'], f'unknown ({decoded["NSExpressionType"]})')
        return decoded

    def decode_value(self, value: Any) -> Any:
        """
        Decode any archived value, following references and wrapping binary data.

        Parameters
        ----------
        value : Any
            A value taken straight out of the archive.

        Returns
        -------
        Any
            The decoded value. Binary data becomes ``{'$data': '<hex>'}``.
        """
        if isinstance(value, plistlib.UID):
            return self.decode_uid(value.data)
        if isinstance(value, bytes):
            return {'$data': value.hex()}
        if isinstance(value, list):
            return [self.decode_value(v) for v in value]
        if isinstance(value, dict):
            return self.decode_instance(value)
        return value

    def decode_top(self, archive: Mapping[str, Any]) -> dict[str, Any]:
        """
        Decode the archive's ``$top`` mapping and the header around it.

        Parameters
        ----------
        archive : Mapping[str, Any]
            The whole keyed archive.

        Returns
        -------
        dict[str, Any]
            The archiver name, version, and the decoded ``$top`` mapping.
        """
        return {
            '$archiver': archive['$archiver'],
            '$version': archive.get('$version'),
            '$top': {
                key: self.decode_value(value)
                for key, value in archive['$top'].items()
            },
        }

    def _count_references(self, archive: Mapping[str, Any]) -> dict[int, int]:
        """
        Count how many times each UID is referenced, excluding ``$class`` references.

        A UID referenced once can be inlined where it is used; one referenced more than once is
        shared, and inlining it would duplicate the object rather than represent the graph.

        Parameters
        ----------
        archive : Mapping[str, Any]
            The whole keyed archive.

        Returns
        -------
        dict[int, int]
            UID to the number of times it is referenced.
        """
        counts: dict[int, int] = {}

        def visit(value: Any) -> None:
            if isinstance(value, plistlib.UID):
                counts[value.data] = counts.get(value.data, 0) + 1
            elif isinstance(value, list):
                for item in value:
                    visit(item)
            elif isinstance(value, dict):
                for key, item in value.items():
                    if key != '$class':
                        visit(item)

        visit(archive['$top'])
        for obj in self.objects:
            visit(obj)
        return counts


def _render_constant(value: Any) -> str:
    if value is None:
        return 'nil'
    if isinstance(value, bool):
        return 'YES' if value else 'NO'
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, dict) and '$data' in value:
        return f'<{value["$data"]}>'
    return str(value)


def _render_expression(exp: Mapping[str, Any] | None) -> str | None:
    """
    Render a decoded ``NSExpression`` tree as its canonical source string.

    This mirrors the ``description`` conventions of Foundation's expression classes, which are also
    the strings the Xcode mapping-model editor shows (``$source.category``, ``FUNCTION(...)``,
    ``FETCH(...)``).

    Parameters
    ----------
    exp : Mapping[str, Any] | None
        The decoded expression, or ``None`` where the archive holds no expression at all.

    Returns
    -------
    str | None
        The source string, or ``None`` when there was no expression. An expression type with no
        canonical form yields a description naming the type rather than being dropped.
    """
    if exp is None:
        return None
    expression_type = exp.get('NSExpressionType')
    if expression_type == _EXPRESSION_CONSTANT:
        return _render_constant(exp.get('NSConstantValue'))
    if expression_type == _EXPRESSION_SELF:
        return 'SELF'
    if expression_type == _EXPRESSION_VARIABLE:
        return '$' + str(exp['NSVariable'])
    if expression_type in _EXPRESSION_KEY_PATHS:
        return str(exp['NSKeyPath'])
    if expression_type == _EXPRESSION_FUNCTION:
        operand = _render_expression(exp.get('NSOperand'))
        selector = exp['NSSelectorName']
        items = (exp.get('NSArguments') or {}).get('items', [])
        if selector == 'valueForKeyPath:' and len(items) == 1:
            return f'{operand}.{_render_expression(items[0])}'
        rendered = ', '.join(_render_expression(a) or 'nil' for a in items)
        suffix = f', {rendered}' if rendered else ''
        return f'FUNCTION({operand}, {json.dumps(selector)}{suffix})'
    if expression_type == _EXPRESSION_FETCH_REQUEST:
        request = _render_expression(exp.get('NSFRExpression'))
        context = _render_expression(exp.get('NSMOCExpression'))
        count = ', COUNT' if exp.get('NSCountOnlyFlag') else ''
        return f'FETCH({request}, {context}{count})'
    kind = EXPRESSION_TYPES.get(expression_type, 'unknown') if isinstance(expression_type,
                                                                          int) else 'unknown'
    return f'<expression type {expression_type} ({kind})>'


def _render_predicate(predicate: Any) -> Any:
    """
    Render a decoded ``NSPredicate`` as a readable string, as far as it can be read.

    Parameters
    ----------
    predicate : Any
        The decoded predicate.

    Returns
    -------
    Any
        The rendered string. Anything unrecognised falls back to the simplified raw structure
        rather than being dropped, so nothing is lost by a gap in the rendering.
    """
    if not isinstance(predicate, dict):
        return _simplify_value(predicate)
    match predicate.get('$class'):
        case 'NSComparisonPredicate':
            operator_type = (predicate.get('NSPredicateOperator') or {}).get('NSOperatorType')
            symbol = (PREDICATE_OPERATORS.get(operator_type, f'<operator {operator_type}>')
                      if isinstance(operator_type, int) else f'<operator {operator_type}>')
            left = _render_expression(predicate.get('NSLeftExpression'))
            right = _render_expression(predicate.get('NSRightExpression'))
            return f'{left} {symbol} {right}'
        case 'NSCompoundPredicate':
            compound_type = predicate.get('NSCompoundPredicateType')
            joiner = (COMPOUND_PREDICATE_JOINERS.get(compound_type, ' ?? ') if isinstance(
                compound_type, int) else ' ?? ')
            group = predicate.get('NSSubpredicates') or {}
            return '(' + joiner.join(str(_render_predicate(p))
                                     for p in group.get('items', [])) + ')'
        case 'NSTruePredicate':
            return 'TRUEPREDICATE'
        case 'NSFalsePredicate':
            return 'FALSEPREDICATE'
        case _:
            return _simplify_value(predicate)


def _simplify_value(value: Any) -> Any:
    """
    Flatten decoded container wrappers to plain JSON values.

    Parameters
    ----------
    value : Any
        A decoded value, which may be a wrapper around a container.

    Returns
    -------
    Any
        The value with its wrappers removed, recursively.
    """
    if isinstance(value, dict):
        if '$data' in value:
            return value['$data']
        if 'items' in value and '$class' in value:
            return [_simplify_value(v) for v in value['items']]
        if 'entries' in value and '$class' in value:
            entries = value['entries']
            if isinstance(entries, dict):
                return {k: _simplify_value(v) for k, v in entries.items()}
            return [[_simplify_value(k), _simplify_value(v)] for k, v in entries]
        return {k: _simplify_value(v) for k, v in value.items() if k != '$class'}
    if isinstance(value, list):
        return [_simplify_value(v) for v in value]
    return value


def _build_property_mapping(pm: Mapping[str, Any]) -> dict[str, Any]:
    return {
        'name': pm.get('NSDestinationPropertyName'),
        'valueExpression': _render_expression(pm.get('NSValueExpression')),
        'propertyTransforms': _simplify_value(pm.get('NSPropertyTransforms')),
        'userInfo': _simplify_value(pm.get('NSUserInfo')),
    }


def _build_entity_mapping(em: Mapping[str, Any]) -> dict[str, Any]:
    def mappings(key: str) -> list[dict[str, Any]]:
        group = em.get(key)
        items = group.get('items', []) if isinstance(group, dict) else []
        return [_build_property_mapping(pm) for pm in items]

    def hash_hex(key: str) -> str | None:
        value = em.get(key)
        return value.get('$data') if isinstance(value, dict) else None

    mapping_type = em.get('NSMappingType')
    return {
        'name': em.get('NSMappingName'),
        'mappingType': (ENTITY_MAPPING_TYPES.get(mapping_type, f'unknown ({mapping_type})')
                        if isinstance(mapping_type, int) else f'unknown ({mapping_type})'),
        'sourceEntityName': em.get('NSSourceEntityName'),
        'destinationEntityName': em.get('NSDestinationEntityName'),
        'sourceEntityVersionHash': hash_hex('NSSourceEntityVersionHash'),
        'destinationEntityVersionHash': hash_hex('NSDestinationEntityVersionHash'),
        'sourceExpression': _render_expression(em.get('NSSourceExpression')),
        'entityMigrationPolicyClassName': em.get('NSEntityMigrationPolicyClassName'),
        'attributeMappings': mappings('NSAttributeMappings'),
        'relationshipMappings': mappings('NSRelationshipMappings'),
        'userInfo': _simplify_value(em.get('NSUserInfo')),
    }


def _build_model(root: Mapping[str, Any]) -> dict[str, Any]:
    # NSEntityMappingsByName is derived (keyed by mapping name), so it is not repeated here.
    group = root.get('NSEntityMappings') or {}
    return {'entityMappings': [_build_entity_mapping(em) for em in group.get('items', [])]}


def _build_attribute(prop: Mapping[str, Any]) -> dict[str, Any]:
    attribute_type = prop.get('NSAttributeType')
    validation = prop.get('NSValidationPredicates')
    predicates = validation.get('items', []) if isinstance(validation, dict) else []
    return {
        'type': (ATTRIBUTE_TYPE_NAMES.get(attribute_type, f'unknown ({attribute_type})')
                 if isinstance(attribute_type, int) else f'unknown ({attribute_type})'),
        'valueClassName': prop.get('NSAttributeValueClassName'),
        'optional': bool(prop.get('NSIsOptional')),
        'indexed': bool(prop.get('NSIsIndexed')),
        'defaultValue': _simplify_value(prop.get('NSDefaultValue')),
        'renamingIdentifier': prop.get('NSRenamingIdentifier'),
        'valueTransformerName': prop.get('NSValueTransformerName'),
        'validationPredicates': [_render_predicate(p) for p in predicates] or None,
        'userInfo': _simplify_value(prop.get('NSUserInfo')),
    }


def _build_relationship(prop: Mapping[str, Any]) -> dict[str, Any]:
    def related_name(key: str, name_key: str) -> Any:
        value = prop.get(key)
        if isinstance(value, dict):
            return value.get(name_key, value)
        return value

    delete_rule = prop.get('NSDeleteRule')
    return {
        'destinationEntity': related_name('NSDestinationEntity', 'NSEntityName'),
        'inverseRelationship': related_name('NSInverseRelationship', 'NSPropertyName'),
        'minCount': prop.get('NSMinCount'),
        'maxCount': prop.get('NSMaxCount'),
        'deleteRule': DELETE_RULES.get(delete_rule) if isinstance(delete_rule, int) else None,
        'optional': bool(prop.get('NSIsOptional')),
        'ordered': bool(prop.get('NSIsOrdered')),
        'renamingIdentifier': prop.get('NSRenamingIdentifier'),
        'userInfo': _simplify_value(prop.get('NSUserInfo')),
    }


def _build_entity(entity: Mapping[str, Any]) -> dict[str, Any]:
    properties = (entity.get('NSProperties') or {}).get('entries', {})
    attributes: dict[str, Any] = {}
    relationships: dict[str, Any] = {}
    other_properties: dict[str, Any] = {}
    for name, prop in sorted(properties.items()):
        if not isinstance(prop, dict):
            other_properties[name] = prop
        elif 'NSAttributeType' in prop:
            attributes[name] = _build_attribute(prop)
        elif 'NSDestinationEntity' in prop:
            relationships[name] = _build_relationship(prop)
        else:
            other_properties[name] = _simplify_value(prop)
    subentities = entity.get('NSSubentities')
    superentity = entity.get('NSSuperentity')
    return {
        'className': entity.get('NSClassNameForEntity'),
        'superentity': (superentity.get('NSEntityName', superentity) if isinstance(
            superentity, dict) else superentity),
        'subentities': (sorted(subentities['entries'])
                        if isinstance(subentities, dict) and 'entries' in subentities else []),
        'renamingIdentifier': entity.get('NSRenamingIdentifier'),
        'versionHashModifier': entity.get('NSVersionHashModifier'),
        'attributes': attributes,
        'relationships': relationships,
        'otherProperties': other_properties or None,
        'userInfo': _simplify_value(entity.get('NSUserInfo')),
    }


def _build_managed_object_model(root: Mapping[str, Any]) -> dict[str, Any]:
    entities = (root.get('NSEntities') or {}).get('entries', {})
    return {
        'entities': {
            name: _build_entity(entity)
            for name, entity in sorted(entities.items())
        },
        'versionIdentifiers': _simplify_value(root.get('NSVersionIdentifiers')),
        'fetchRequestTemplates': _simplify_value(root.get('NSFetchRequestTemplates')),
    }


def load_mom_column_types(path: Path) -> dict[str, dict[str, str]]:
    """
    Read a compiled model and recover the SQL column type of every attribute.

    Parameters
    ----------
    path : pathlib.Path
        The ``.mom`` to read.

    Returns
    -------
    dict[str, dict[str, str]]
        Entity name to attribute name to SQL type.

    Raises
    ------
    ValueError
        When the archive's root is not an ``NSManagedObjectModel``, so the file is not a compiled
        model.
    """
    archive = plistlib.loads(path.read_bytes())
    root = _ArchiveDecoder(archive, share_refs=False).decode_value(archive['$top']['root'])
    if root.get('$class') != 'NSManagedObjectModel':
        msg = f'Root object of {path} is {root.get("$class")!r}, not NSManagedObjectModel.'
        raise ValueError(msg)
    types: dict[str, dict[str, str]] = {}
    for entity_name, entity in (root.get('NSEntities') or {}).get('entries', {}).items():
        properties = (entity.get('NSProperties') or {}).get('entries', {})
        types[entity_name] = {
            property_name: ATTRIBUTE_SQL_TYPES.get(prop['NSAttributeType'], 'BLOB')
            for property_name, prop in properties.items()
            if isinstance(prop, dict) and 'NSAttributeType' in prop
        }
    return types


def _sql_for_entity_mapping(em: Mapping[str, Any], ordinals: Mapping[str, int],
                            mom_types: Mapping[str, Mapping[str, str]] | None) -> list[str]:
    """
    Emit the statements one entity mapping amounts to.

    Parameters
    ----------
    em : Mapping[str, Any]
        One deserialised entity mapping.
    ordinals : Mapping[str, int]
        Destination entity name to its ``Z_ENT`` ordinal.
    mom_types : Mapping[str, Mapping[str, str]] | None
        Column types from the destination model, or ``None`` to infer them from the mapping.

    Returns
    -------
    list[str]
        The lines for this mapping, ending in a blank line.
    """
    destination = em['destinationEntityName']
    name = em['name']
    if destination is None:
        return [
            f'-- {name}: {em["mappingType"]} mapping with no destination entity; nothing to emit.',
            ''
        ]
    table = 'Z' + destination.upper()
    attribute_mappings = sorted(em['attributeMappings'], key=lambda pm: pm['name'] or '')
    if mom_types and destination in mom_types:
        destination_types = mom_types[destination]
        columns = {attr: destination_types[attr] for attr in sorted(destination_types)}
    else:
        columns = {pm['name']: '' for pm in attribute_mappings}
    lines = [f'-- {name} ({em["mappingType"]})', f'CREATE TABLE {table} (']
    declarations = ['Z_PK INTEGER PRIMARY KEY', 'Z_ENT INTEGER', 'Z_OPT INTEGER']
    declarations += [f'Z{attr.upper()} {sql_type}'.rstrip() for attr, sql_type in columns.items()]
    lines += [f'  {decl},' for decl in declarations[:-1]]
    lines += [f'  {declarations[-1]}', ');']
    if em['relationshipMappings']:
        lines.append('-- Relationship mappings are present but not translated here.')
    source_expression = em['sourceExpression']
    if source_expression is None:
        lines += [f'-- {em["mappingType"]} mapping: the table starts empty.', '']
        return lines
    if (match := _FETCH_PATTERN.fullmatch(source_expression)) is None:
        lines += [f'-- Source expression not translated: {source_expression}', '']
        return lines
    source_entity, predicate = match.groups()
    if predicate != 'TRUEPREDICATE':
        lines.append(f'-- Source predicate not translated: {predicate}')
    select_terms = ['Z_PK', f'{ordinals[destination]} AS Z_ENT', 'Z_OPT']
    insert_columns = ['Z_PK', 'Z_ENT', 'Z_OPT']
    for pm in attribute_mappings:
        insert_columns.append('Z' + pm['name'].upper())
        expression = pm['valueExpression']
        key = _SOURCE_KEY_PATTERN.match(expression) if expression else None
        if key is not None:
            select_terms.append('Z' + key.group(1).upper())
        elif expression is None:
            select_terms.append('NULL')
        else:
            select_terms.append(f'NULL /* {expression} */')
    lines += [
        f'INSERT INTO {table} ({", ".join(insert_columns)})', f'  SELECT {", ".join(select_terms)}',
        f'  FROM src.Z{source_entity.upper()};', ''
    ]
    return lines


def build_sql(model: Mapping[str, Any], mom_types: Mapping[str, Mapping[str, str]] | None) -> str:
    """
    Emit the effective SQLite script for a deserialised mapping model.

    ``Z_ENT`` ordinals follow Core Data's own assignment, which is a position in the model's
    name-sorted entity list. Given the destination model they come from its full entity list;
    without it they come from the mapped entities alone, which agrees only when the mapping covers
    every entity.

    Parameters
    ----------
    model : Mapping[str, Any]
        A deserialised mapping model, as :func:`convert` returns.
    mom_types : Mapping[str, Mapping[str, str]] | None
        Column types from the destination model, or ``None`` to infer them from the mapping.

    Returns
    -------
    str
        The script, ending in a newline.

    Raises
    ------
    ValueError
        When ``mom_types`` comes from a model that does not describe the entities the mapping
        targets.
    """
    mappings = model['entityMappings']
    destinations = sorted(
        em['destinationEntityName'] for em in mappings if em['destinationEntityName'])
    ordinal_names = sorted(mom_types) if mom_types else destinations
    ordinals = {name: index + 1 for index, name in enumerate(ordinal_names)}
    if missing := [name for name in destinations if name not in ordinals]:
        msg = (f'Destination entities {", ".join(sorted(set(missing)))} are absent from the '
               'compiled model supplying column types; the two models do not describe the same '
               'store.')
        raise ValueError(msg)
    lines = [
        '-- Effective SQLite statements for this mapping model. Core Data performs a',
        '-- heavyweight migration by rebuilding the store and pumping every row through',
        '-- NSMigrationManager in memory; each copy mapping below is shown as its',
        '-- single-statement INSERT ... SELECT equivalent.',
        "ATTACH DATABASE 'old_store.sqlite' AS src;",
        'BEGIN EXCLUSIVE;',
        '',
    ]
    for em in sorted(mappings, key=lambda m: m['destinationEntityName'] or ''):
        lines += _sql_for_entity_mapping(em, ordinals, mom_types)
    lines += [
        'CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER PRIMARY KEY, Z_NAME VARCHAR,',
        '                           Z_SUPER INTEGER, Z_MAX INTEGER);',
    ]
    for destination in destinations:
        lines.append('INSERT INTO Z_PRIMARYKEY (Z_ENT, Z_NAME, Z_SUPER, Z_MAX)')
        # This builds a script as text and never executes it, so the injection rule does not apply;
        # the names interpolated come from the model being converted in any case.
        lines.append(f"  SELECT {ordinals[destination]}, '{destination}', 0, "  # noqa: S608
                     f'COALESCE(MAX(Z_PK), 0) FROM Z{destination.upper()};')
    lines += [
        '-- Z_METADATA (Z_VERSION, Z_UUID, Z_PLIST) is written by Core Data with the new',
        "-- model's version-hash plist; the blob is not reproducible here.",
        'COMMIT;',
        'DETACH DATABASE src;',
    ]
    return '\n'.join(lines) + '\n'


def convert(path: Path, *, archive_mode: bool = False) -> dict[str, Any]:
    """
    Read a compiled Core Data artefact and return it as plain JSON-ready values.

    Parameters
    ----------
    path : pathlib.Path
        The ``.cdm`` or ``.mom`` to read.
    archive_mode : bool
        Decode the raw keyed-archive object graph rather than dispatching on the root class. This
        works on any ``NSKeyedArchiver`` plist whatever its root, and is as close to lossless as
        JSON allows, at the cost of being the archive's shape rather than the model's.

    Returns
    -------
    dict[str, Any]
        The converted model.

    Raises
    ------
    ValueError
        When the archive's root is neither an ``NSMappingModel`` nor an ``NSManagedObjectModel``,
        so there is no model to build.
    """
    archive = plistlib.loads(path.read_bytes())
    if archive_mode:
        return _ArchiveDecoder(archive).decode_top(archive)
    root = _ArchiveDecoder(archive, share_refs=False).decode_value(archive['$top']['root'])
    match root.get('$class') if isinstance(root, dict) else None:
        case 'NSMappingModel':
            return _build_model(root)
        case 'NSManagedObjectModel':
            return _build_managed_object_model(root)
        case root_class:
            msg = f'Unsupported root object {root_class!r}; use archive mode for a raw dump.'
            raise ValueError(msg)
