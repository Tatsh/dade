"""Shared pytest configuration for the ``destin.misc`` suite."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
import plistlib

from click.testing import CliRunner
import pytest

if TYPE_CHECKING:
    from pathlib import Path


class ArchiveBuilder:
    """
    Assemble an ``NSKeyedArchiver`` plist object graph for the tests.

    Objects are appended to the archive's ``$objects`` table and referred to by the
    :py:class:`plistlib.UID` each ``add`` returns, which is how a real archive is laid out.
    """
    def __init__(self) -> None:
        self.objects: list[Any] = ['$null']

    def add(self, obj: Any) -> plistlib.UID:
        """
        Append one object to the archive.

        Parameters
        ----------
        obj : Any
            The object to append.

        Returns
        -------
        plistlib.UID
            A reference to the appended object.
        """
        self.objects.append(obj)
        return plistlib.UID(len(self.objects) - 1)

    def add_class(self, name: str, *hierarchy: str) -> plistlib.UID:
        """
        Append a class descriptor.

        Parameters
        ----------
        name : str
            The archived class name.
        hierarchy : str
            Superclass names, from the nearest upwards, excluding ``NSObject``.

        Returns
        -------
        plistlib.UID
            A reference to the descriptor.
        """
        return self.add({'$classname': name, '$classes': [name, *hierarchy, 'NSObject']})

    def add_array(self, items: list[plistlib.UID]) -> plistlib.UID:
        """
        Append an ``NSArray``.

        Parameters
        ----------
        items : list[plistlib.UID]
            References to the array's elements.

        Returns
        -------
        plistlib.UID
            A reference to the array.
        """
        return self.add({'$class': self.add_class('NSArray'), 'NS.objects': items})

    def add_dictionary(self, entries: dict[str, plistlib.UID]) -> plistlib.UID:
        """
        Append an ``NSDictionary`` keyed by strings.

        Parameters
        ----------
        entries : dict[str, plistlib.UID]
            Keys to references to their values.

        Returns
        -------
        plistlib.UID
            A reference to the dictionary.
        """
        return self.add({
            '$class': self.add_class('NSDictionary'),
            'NS.keys': [self.add(key) for key in entries],
            'NS.objects': list(entries.values()),
        })

    def add_key_path(self, key_path: str) -> plistlib.UID:
        """
        Append a key-path ``NSExpression``.

        Parameters
        ----------
        key_path : str
            The key path the expression evaluates.

        Returns
        -------
        plistlib.UID
            A reference to the expression.
        """
        return self.add({
            '$class': self.add_class('NSKeyPathExpression', 'NSExpression'),
            'NSExpressionType': 3,
            'NSKeyPath': self.add(key_path),
        })

    def add_value_for_key_path(self, variable: str, key_path: str) -> plistlib.UID:
        """
        Append the ``valueForKeyPath:`` function expression that renders as ``$variable.keyPath``.

        Parameters
        ----------
        variable : str
            The expression variable's name, without its leading ``$``.
        key_path : str
            The key path read from the variable.

        Returns
        -------
        plistlib.UID
            A reference to the expression.
        """
        return self.add({
            '$class': self.add_class('NSFunctionExpression', 'NSExpression'),
            'NSExpressionType': 4,
            'NSOperand': self.add_variable(variable),
            'NSSelectorName': self.add('valueForKeyPath:'),
            'NSArguments': self.add_array([self.add_key_path(key_path)]),
        })

    def add_variable(self, name: str) -> plistlib.UID:
        """
        Append a variable ``NSExpression``.

        Parameters
        ----------
        name : str
            The variable's name, without its leading ``$``.

        Returns
        -------
        plistlib.UID
            A reference to the expression.
        """
        return self.add({
            '$class': self.add_class('NSVariableExpression', 'NSExpression'),
            'NSExpressionType': 2,
            'NSVariable': self.add(name),
        })

    def add_constant(self, value: str) -> plistlib.UID:
        """
        Append a constant ``NSExpression``.

        Parameters
        ----------
        value : str
            The constant's value.

        Returns
        -------
        plistlib.UID
            A reference to the expression.
        """
        return self.add({
            '$class': self.add_class('NSConstantValueExpression', 'NSExpression'),
            'NSExpressionType': 0,
            'NSConstantValue': self.add(value),
        })

    def add_fetch(self, entity: str, predicate: str) -> plistlib.UID:
        """
        Append the source expression Core Data compiles for a copy mapping.

        Parameters
        ----------
        entity : str
            The source entity fetched from.
        predicate : str
            The predicate string, usually ``TRUEPREDICATE``.

        Returns
        -------
        plistlib.UID
            A reference to the expression.
        """
        request = self.add({
            '$class':
                self.add_class('NSFunctionExpression', 'NSExpression'),
            'NSExpressionType':
                4,
            'NSOperand':
                self.add_variable('manager'),
            'NSSelectorName':
                self.add('fetchRequestForSourceEntityNamed:predicateString:'),
            'NSArguments':
                self.add_array([self.add_constant(entity),
                                self.add_constant(predicate)]),
        })
        return self.add({
            '$class': self.add_class('NSFetchRequestExpression', 'NSExpression'),
            'NSExpressionType': 50,
            'NSFRExpression': request,
            'NSMOCExpression': self.add_value_for_key_path('manager', 'sourceContext'),
        })

    def build(self, root: plistlib.UID) -> bytes:
        """
        Serialise the archive as a binary plist.

        Parameters
        ----------
        root : plistlib.UID
            Reference to the archive's root object.

        Returns
        -------
        bytes
            The archive.
        """
        return plistlib.dumps(
            {
                '$archiver': 'NSKeyedArchiver',
                '$version': 100000,
                '$top': {
                    'root': root
                },
                '$objects': self.objects,
            },
            fmt=plistlib.FMT_BINARY)


@pytest.fixture
def runner() -> CliRunner:
    """
    Provide a Click :py:class:`~click.testing.CliRunner` for command tests.

    Returns
    -------
    click.testing.CliRunner
        A fresh runner for invoking commands.
    """
    return CliRunner()


@pytest.fixture
def mapping_model(tmp_path: Path) -> Path:
    """
    Write a compiled mapping model holding one copy mapping and one remove mapping.

    The copy mapping carries the fetch source expression, two attribute mappings, and version
    hashes; the remove mapping has no destination entity. Both share one user-info dictionary, so
    the archive dump has a shared object to emit as ``$id`` and ``$ref``.

    Returns
    -------
    pathlib.Path
        The written ``.cdm``.
    """
    builder = ArchiveBuilder()
    user_info = builder.add_dictionary({'note': builder.add('shared')})
    copy_mapping = builder.add({
        '$class':
            builder.add_class('NSEntityMapping'),
        'NSMappingName':
            builder.add('ScoreToScore'),
        'NSMappingType':
            4,
        'NSSourceEntityName':
            builder.add('Score'),
        'NSDestinationEntityName':
            builder.add('Score'),
        'NSSourceEntityVersionHash':
            builder.add(b'\x01\x02\x03\x04'),
        'NSDestinationEntityVersionHash':
            builder.add(b'\x05\x06\x07\x08'),
        'NSSourceExpression':
            builder.add_fetch('Score', 'TRUEPREDICATE'),
        'NSEntityMigrationPolicyClassName':
            builder.add('ScorePolicy'),
        'NSAttributeMappings':
            builder.add_array([
                builder.add({
                    '$class': builder.add_class('NSPropertyMapping'),
                    'NSDestinationPropertyName': builder.add('title'),
                    'NSValueExpression': builder.add_value_for_key_path('source', 'title'),
                }),
                builder.add({
                    '$class': builder.add_class('NSPropertyMapping'),
                    'NSDestinationPropertyName': builder.add('rating'),
                    'NSValueExpression': builder.add_constant('0'),
                }),
            ]),
        'NSRelationshipMappings':
            builder.add_array([]),
        'NSUserInfo':
            user_info,
    })
    remove_mapping = builder.add({
        '$class': builder.add_class('NSEntityMapping'),
        'NSMappingName': builder.add('RemoveLegacy'),
        'NSMappingType': 3,
        'NSSourceEntityName': builder.add('Legacy'),
        'NSAttributeMappings': builder.add_array([]),
        'NSRelationshipMappings': builder.add_array([]),
        'NSUserInfo': user_info,
    })
    root = builder.add({
        '$class': builder.add_class('NSMappingModel'),
        'NSEntityMappings': builder.add_array([copy_mapping, remove_mapping]),
    })
    path = tmp_path / 'v1_to_v2.cdm'
    path.write_bytes(builder.build(root))
    return path


@pytest.fixture
def managed_object_model(tmp_path: Path) -> Path:
    """
    Write a compiled managed object model holding one entity with an attribute and a relationship.

    Returns
    -------
    pathlib.Path
        The written ``.mom``.
    """
    builder = ArchiveBuilder()
    predicate = builder.add({
        '$class':
            builder.add_class('NSComparisonPredicate', 'NSPredicate'),
        'NSPredicateOperator':
            builder.add({
                '$class': builder.add_class('NSPredicateOperator'),
                'NSOperatorType': 3,
            }),
        'NSLeftExpression':
            builder.add({
                '$class': builder.add_class('NSSelfExpression', 'NSExpression'),
                'NSExpressionType': 1,
            }),
        'NSRightExpression':
            builder.add_constant('0'),
    })
    title = builder.add({
        '$class': builder.add_class('NSAttributeDescription', 'NSPropertyDescription'),
        'NSAttributeType': 700,
        'NSAttributeValueClassName': builder.add('NSString'),
        'NSIsOptional': True,
        'NSValidationPredicates': builder.add_array([predicate]),
    })
    plays = builder.add({
        '$class': builder.add_class('NSAttributeDescription', 'NSPropertyDescription'),
        'NSAttributeType': 200,
        'NSAttributeValueClassName': builder.add('NSNumber'),
    })
    owner = builder.add({
        '$class':
            builder.add_class('NSRelationshipDescription', 'NSPropertyDescription'),
        'NSDestinationEntity':
            builder.add({
                '$class': builder.add_class('NSEntityDescription'),
                'NSEntityName': builder.add('Player'),
            }),
        'NSInverseRelationship':
            builder.add({
                '$class': builder.add_class('NSRelationshipDescription', 'NSPropertyDescription'),
                'NSPropertyName': builder.add('scores'),
            }),
        'NSMinCount':
            0,
        'NSMaxCount':
            1,
        'NSDeleteRule':
            2,
    })
    score = builder.add({
        '$class': builder.add_class('NSEntityDescription'),
        'NSClassNameForEntity': builder.add('Score'),
        'NSProperties': builder.add_dictionary({
            'title': title,
            'plays': plays,
            'owner': owner
        }),
    })
    root = builder.add({
        '$class': builder.add_class('NSManagedObjectModel'),
        'NSEntities': builder.add_dictionary({'Score': score}),
    })
    path = tmp_path / 'ScoreData_v2.mom'
    path.write_bytes(builder.build(root))
    return path


@pytest.fixture
def compiled_strings(tmp_path: Path) -> Path:
    """
    Write a compiled ``.strings`` table, which is a flat binary plist.

    Returns
    -------
    pathlib.Path
        The written table.
    """
    path = tmp_path / 'Localizable.strings'
    path.write_bytes(plistlib.dumps({'ok': 'OK', 'cancel': 'キャンセル'}, fmt=plistlib.FMT_BINARY))
    return path


@pytest.fixture
def text_strings(tmp_path: Path) -> Path:
    """
    Write an uncompiled ``.strings`` table in the old-style text form.

    Returns
    -------
    pathlib.Path
        The written table.
    """
    path = tmp_path / 'Text.strings'
    path.write_text(
        '/* a leading comment */\n'
        '"ok" = "OK";\n'
        '// a line comment\n'
        '"quote" = "say \\"hi\\"";\n'
        '"lines" = "one\\ntwo";\n'
        '"odd\\ key" = "kept";\n',
        encoding='utf-8')
    return path
