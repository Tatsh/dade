"""Tests for :py:mod:`destin.misc.coredata`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import plistlib

from destin.misc import build_sql, convert, load_mom_column_types
import pytest

if TYPE_CHECKING:
    from pathlib import Path


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
