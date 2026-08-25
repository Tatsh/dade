"""Tests for :py:mod:`dade.misc.coredata`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import plistlib

import pytest

from dade.misc import build_sql, convert, load_mom_column_types

from .conftest import ArchiveBuilder

if TYPE_CHECKING:
    from pathlib import Path


def _constant(builder: ArchiveBuilder, value: plistlib.UID) -> plistlib.UID:
    return builder.add({
        '$class': builder.add_class('NSConstantValueExpression', 'NSExpression'),
        'NSExpressionType': 0,
        'NSConstantValue': value,
    })


def _copy_mapping_model(builder: ArchiveBuilder, fields: dict[str, object]) -> plistlib.UID:
    mapping = builder.add({
        '$class': builder.add_class('NSEntityMapping'),
        'NSMappingName': builder.add('M'),
        'NSMappingType': 4,
        'NSDestinationEntityName': builder.add('Score'),
        'NSAttributeMappings': builder.add_array([]),
        'NSRelationshipMappings': builder.add_array([]),
        **fields,
    })
    return builder.add({
        '$class': builder.add_class('NSMappingModel'),
        'NSEntityMappings': builder.add_array([mapping]),
    })


def test_convert_mapping_model(mapping_model: Path) -> None:
    mappings = convert(mapping_model)['entityMappings']
    assert [m['name'] for m in mappings] == ['ScoreToScore', 'RemoveLegacy']
    copy_mapping, remove_mapping = mappings
    assert copy_mapping['mappingType'] == 'copy'
    assert copy_mapping['sourceEntityVersionHash'] == '01020304'
    assert copy_mapping['destinationEntityVersionHash'] == '05060708'
    assert copy_mapping['entityMigrationPolicyClassName'] == 'ScorePolicy'
    assert copy_mapping['sourceExpression'] == (
        'FETCH(FUNCTION($manager, "fetchRequestForSourceEntityNamed:predicateString:", '
        '"Score", "TRUEPREDICATE"), $manager.sourceContext)')
    assert [(a['name'], a['valueExpression'])
            for a in copy_mapping['attributeMappings']] == [('title', '$source.title'),
                                                            ('rating', '"0"')]
    assert copy_mapping['userInfo'] == {'note': 'shared'}
    assert remove_mapping['mappingType'] == 'remove'
    assert remove_mapping['destinationEntityName'] is None


def test_convert_managed_object_model(managed_object_model: Path) -> None:
    entities = convert(managed_object_model)['entities']
    assert list(entities) == ['Score']
    score = entities['Score']
    assert score['className'] == 'Score'
    assert score['attributes']['title']['type'] == 'string'
    assert score['attributes']['title']['optional'] is True
    assert score['attributes']['title']['validationPredicates'] == ['SELF >= "0"']
    assert score['attributes']['plays']['type'] == 'integer32'
    assert score['attributes']['plays']['optional'] is False
    assert score['relationships']['owner'] == {
        'destinationEntity': 'Player',
        'inverseRelationship': 'scores',
        'minCount': 0,
        'maxCount': 1,
        'deleteRule': 'cascade',
        'optional': False,
        'ordered': False,
        'renamingIdentifier': None,
        'userInfo': None,
    }


def test_convert_archive_mode_shares_objects(mapping_model: Path) -> None:
    top = convert(mapping_model, archive_mode=True)
    assert top['$archiver'] == 'NSKeyedArchiver'
    mappings = top['$top']['root']['NSEntityMappings']['items']
    assert mappings[0]['$mappingType'] == 'copy'
    assert '$id' in mappings[0]['NSUserInfo']
    assert mappings[1]['NSUserInfo'] == {'$ref': mappings[0]['NSUserInfo']['$id']}


def test_convert_archive_mode_annotates_expression_types(mapping_model: Path) -> None:
    root = convert(mapping_model, archive_mode=True)['$top']['root']
    assert root['NSEntityMappings']['items'][0]['NSSourceExpression'][
        '$expressionType'] == 'fetchRequest'


def test_convert_rejects_a_foreign_root(tmp_path: Path) -> None:
    path = tmp_path / 'Other.archive'
    path.write_bytes(
        plistlib.dumps(
            {
                '$archiver':
                    'NSKeyedArchiver',
                '$version':
                    100000,
                '$top': {
                    'root': plistlib.UID(1)
                },
                '$objects': [
                    '$null', {
                        '$class': plistlib.UID(2)
                    }, {
                        '$classname': 'NSDate',
                        '$classes': ['NSDate']
                    }
                ],
            },
            fmt=plistlib.FMT_BINARY))
    with pytest.raises(ValueError, match="Unsupported root object 'NSDate'"):
        convert(path)


def test_convert_rejects_a_plist_that_is_not_an_archive(tmp_path: Path) -> None:
    path = tmp_path / 'Plain.plist'
    path.write_bytes(plistlib.dumps({'a': 1}, fmt=plistlib.FMT_BINARY))
    with pytest.raises(ValueError, match='Not an NSKeyedArchiver archive'):
        convert(path)


def test_load_mom_column_types(managed_object_model: Path) -> None:
    assert load_mom_column_types(managed_object_model) == {
        'Score': {
            'title': 'VARCHAR',
            'plays': 'INTEGER'
        }
    }


def test_load_mom_column_types_rejects_a_mapping_model(mapping_model: Path) -> None:
    with pytest.raises(ValueError, match='not NSManagedObjectModel'):
        load_mom_column_types(mapping_model)


def test_build_sql_without_column_types(mapping_model: Path) -> None:
    script = build_sql(convert(mapping_model), None)
    assert 'CREATE TABLE ZSCORE (' in script
    assert '  ZRATING,' in script
    assert 'INSERT INTO ZSCORE (Z_PK, Z_ENT, Z_OPT, ZRATING, ZTITLE)' in script
    assert '  SELECT Z_PK, 1 AS Z_ENT, Z_OPT, NULL /* "0" */, ZTITLE' in script
    assert '  FROM src.ZSCORE;' in script
    assert '-- RemoveLegacy: remove mapping with no destination entity; nothing to emit.' in script
    assert script.endswith('DETACH DATABASE src;\n')


def test_build_sql_with_column_types(mapping_model: Path, managed_object_model: Path) -> None:
    script = build_sql(convert(mapping_model), load_mom_column_types(managed_object_model))
    assert '  ZPLAYS INTEGER,' in script
    assert '  ZTITLE VARCHAR' in script


def test_build_sql_rejects_an_unrelated_model(mapping_model: Path) -> None:
    with pytest.raises(ValueError, match='Destination entities Score are absent'):
        build_sql(convert(mapping_model), {'Unrelated': {'x': 'INTEGER'}})


def test_archive_mode_decodes_edge_cases(tmp_path: Path) -> None:
    builder = ArchiveBuilder()
    root = builder.add({
        '$class':
            builder.add_class('NSFoo'),
        'null':
            plistlib.UID(0),
        'classDescriptor':
            builder.add_class('NSBar'),
        'intKeyedDictionary':
            builder.add({
                '$class': builder.add_class('NSDictionary'),
                'NS.keys': [builder.add(1), builder.add(2)],
                'NS.objects': [builder.add('a'), builder.add('b')],
            }),
        'string':
            builder.add({
                '$class': builder.add_class('NSMutableString', 'NSString'),
                'NS.string': builder.add('hi'),
            }),
        'rawList': [builder.add('x'), builder.add('y')],
        'rawDictionary': {
            '$class': builder.add_class('NSBaz'),
            'k': builder.add('v')
        },
    })
    path = tmp_path / 'edge.archive'
    path.write_bytes(builder.build(root))
    top = convert(path, archive_mode=True)['$top']['root']
    assert top['null'] is None
    assert top['classDescriptor']['$classname'] == 'NSBar'
    assert top['intKeyedDictionary']['entries'] == [[1, 'a'], [2, 'b']]
    assert top['string']['string'] == 'hi'
    assert top['rawList'] == ['x', 'y']
    assert top['rawDictionary']['$class'] == 'NSBaz'


def test_render_constant_value_types(tmp_path: Path) -> None:
    builder = ArchiveBuilder()

    def attribute(name: str, value: plistlib.UID) -> plistlib.UID:
        return builder.add({
            '$class': builder.add_class('NSPropertyMapping'),
            'NSDestinationPropertyName': builder.add(name),
            'NSValueExpression': _constant(builder, value),
        })

    mapping = builder.add({
        '$class':
            builder.add_class('NSEntityMapping'),
        'NSMappingName':
            builder.add('M'),
        'NSMappingType':
            4,
        'NSDestinationEntityName':
            builder.add('Score'),
        'NSAttributeMappings':
            builder.add_array([
                attribute('nil', plistlib.UID(0)),
                attribute('flag', builder.add(obj=True)),
                attribute('blob', builder.add(b'\x01\x02')),
                attribute('number', builder.add(5)),
            ]),
        'NSRelationshipMappings':
            builder.add_array([]),
    })
    root = builder.add({
        '$class': builder.add_class('NSMappingModel'),
        'NSEntityMappings': builder.add_array([mapping]),
    })
    path = tmp_path / 'constants.cdm'
    path.write_bytes(builder.build(root))
    expressions = {
        pm['name']: pm['valueExpression']
        for pm in convert(path)['entityMappings'][0]['attributeMappings']
    }
    assert expressions == {'nil': 'nil', 'flag': 'YES', 'blob': '<0102>', 'number': '5'}


def test_managed_object_model_covers_property_and_predicate_variants(tmp_path: Path) -> None:
    builder = ArchiveBuilder()
    true_predicate = builder.add({'$class': builder.add_class('NSTruePredicate', 'NSPredicate')})
    compound = builder.add({
        '$class': builder.add_class('NSCompoundPredicate', 'NSPredicate'),
        'NSCompoundPredicateType': 0,
        'NSSubpredicates': builder.add_array([true_predicate]),
    })
    false_predicate = builder.add({'$class': builder.add_class('NSFalsePredicate', 'NSPredicate')})
    unknown_predicate = builder.add(
        {'$class': builder.add_class('NSMysteryPredicate', 'NSPredicate')})
    unknown_expression = builder.add({
        '$class': builder.add_class('NSMysteryExpression', 'NSExpression'),
        'NSExpressionType': 99,
    })
    comparison = builder.add({
        '$class':
            builder.add_class('NSComparisonPredicate', 'NSPredicate'),
        'NSPredicateOperator':
            builder.add({
                '$class': builder.add_class('NSPredicateOperator'),
                'NSOperatorType': 0,
            }),
        'NSLeftExpression':
            unknown_expression,
        'NSRightExpression':
            _constant(builder, builder.add('0')),
    })
    user_info = builder.add_dictionary({
        'data':
            builder.add(b'\xde\xad'),
        'array':
            builder.add_array([builder.add('one')]),
        'intKeyed':
            builder.add({
                '$class': builder.add_class('NSDictionary'),
                'NS.keys': [builder.add(1)],
                'NS.objects': [builder.add('a')],
            }),
        'instance':
            builder.add({
                '$class': builder.add_class('NSThing'),
                'x': builder.add('y')
            }),
    })
    described = builder.add({
        '$class':
            builder.add_class('NSAttributeDescription', 'NSPropertyDescription'),
        'NSAttributeType':
            700,
        'NSValidationPredicates':
            builder.add_array([
                compound, false_predicate, unknown_predicate, comparison,
                builder.add('a bare string predicate')
            ]),
        'NSUserInfo':
            user_info,
    })
    with_list = builder.add({
        '$class': builder.add_class('NSAttributeDescription', 'NSPropertyDescription'),
        'NSAttributeType': 700,
        'NSUserInfo': [builder.add('loose')],
    })
    relationship = builder.add({
        '$class':
            builder.add_class('NSRelationshipDescription', 'NSPropertyDescription'),
        'NSDestinationEntity':
            builder.add({
                '$class': builder.add_class('NSEntityDescription'),
                'NSEntityName': builder.add('Other'),
            }),
    })
    fetched = builder.add({
        '$class': builder.add_class('NSFetchedPropertyDescription', 'NSPropertyDescription'),
        'NSPropertyName': builder.add('fp'),
    })
    entity = builder.add({
        '$class':
            builder.add_class('NSEntityDescription'),
        'NSClassNameForEntity':
            builder.add('Widget'),
        'NSProperties':
            builder.add_dictionary({
                'described': described,
                'withList': with_list,
                'relationship': relationship,
                'bare': builder.add('a bare property'),
                'fetched': fetched,
            }),
    })
    root = builder.add({
        '$class': builder.add_class('NSManagedObjectModel'),
        'NSEntities': builder.add_dictionary({'Widget': entity}),
    })
    path = tmp_path / 'variants.mom'
    path.write_bytes(builder.build(root))
    widget = convert(path)['entities']['Widget']
    predicates = widget['attributes']['described']['validationPredicates']
    assert '(TRUEPREDICATE)' in predicates
    assert 'FALSEPREDICATE' in predicates
    assert widget['relationships']['relationship']['inverseRelationship'] is None
    assert widget['otherProperties'] is not None
    assert 'bare' in widget['otherProperties']
    assert 'fetched' in widget['otherProperties']
    user = widget['attributes']['described']['userInfo']
    assert user['data'] == 'dead'
    assert user['array'] == ['one']
    assert user['intKeyed'] == [[1, 'a']]
    assert user['instance'] == {'x': 'y'}
    assert widget['attributes']['withList']['userInfo'] == ['loose']


def test_sql_notes_relationship_mappings(tmp_path: Path) -> None:
    builder = ArchiveBuilder()
    relationship = builder.add({
        '$class': builder.add_class('NSPropertyMapping'),
        'NSDestinationPropertyName': builder.add('owner'),
    })
    root = _copy_mapping_model(
        builder, {
            'NSRelationshipMappings': builder.add_array([relationship]),
            'NSSourceExpression': builder.add_fetch('Score', 'TRUEPREDICATE'),
        })
    path = tmp_path / 'rel.cdm'
    path.write_bytes(builder.build(root))
    assert 'Relationship mappings are present but not translated here.' in build_sql(
        convert(path), None)


def test_sql_mapping_without_a_source_expression(tmp_path: Path) -> None:
    builder = ArchiveBuilder()
    root = _copy_mapping_model(builder, {})
    path = tmp_path / 'empty_source.cdm'
    path.write_bytes(builder.build(root))
    assert 'the table starts empty.' in build_sql(convert(path), None)


def test_sql_mapping_with_an_untranslatable_source(tmp_path: Path) -> None:
    builder = ArchiveBuilder()
    root = _copy_mapping_model(builder,
                               {'NSSourceExpression': _constant(builder, builder.add('0'))})
    path = tmp_path / 'other_source.cdm'
    path.write_bytes(builder.build(root))
    assert 'Source expression not translated:' in build_sql(convert(path), None)


def test_sql_mapping_with_a_non_true_predicate(tmp_path: Path) -> None:
    builder = ArchiveBuilder()
    root = _copy_mapping_model(builder,
                               {'NSSourceExpression': builder.add_fetch('Score', 'title > 0')})
    path = tmp_path / 'predicate_source.cdm'
    path.write_bytes(builder.build(root))
    assert 'Source predicate not translated: title > 0' in build_sql(convert(path), None)


def test_sql_attribute_without_a_value_expression(tmp_path: Path) -> None:
    builder = ArchiveBuilder()
    attribute = builder.add({
        '$class': builder.add_class('NSPropertyMapping'),
        'NSDestinationPropertyName': builder.add('rating'),
    })
    root = _copy_mapping_model(
        builder, {
            'NSSourceExpression': builder.add_fetch('Score', 'TRUEPREDICATE'),
            'NSAttributeMappings': builder.add_array([attribute]),
        })
    path = tmp_path / 'no_value.cdm'
    path.write_bytes(builder.build(root))
    script = build_sql(convert(path), None)
    assert any(line.rstrip().endswith('NULL') for line in script.splitlines() if 'SELECT' in line)
