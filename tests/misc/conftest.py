"""Shared pytest configuration for the ``destin.misc`` suite."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
import plistlib
import struct
import zipfile

from click.testing import CliRunner
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID
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


def _atom(kind: bytes, body: bytes) -> bytes:
    """
    Build one QuickTime-style atom.

    Parameters
    ----------
    kind : bytes
        The four-byte type.
    body : bytes
        The payload.

    Returns
    -------
    bytes
        The atom, header included.
    """
    return struct.pack('>I4s', len(body) + 8, kind) + body


def _self_signed(key: Any, common_name: str) -> bytes:
    """
    Build a self-signed certificate for the tests.

    Parameters
    ----------
    key : Any
        The private key to sign with and publish.
    common_name : str
        The subject and issuer common name.

    Returns
    -------
    bytes
        The certificate, DER-encoded.
    """
    name = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, 'US'),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'Example Inc.'),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])
    builder = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(
        key.public_key()).serial_number(CERTIFICATE_SERIAL).not_valid_before(
            datetime(2020, 1, 1, tzinfo=timezone.utc)).not_valid_after(
                datetime(2030, 1, 1, tzinfo=timezone.utc)).add_extension(x509.BasicConstraints(
                    ca=False, path_length=None),
                                                                         critical=True))
    return builder.sign(key, hashes.SHA256()).public_bytes(Encoding.DER)


CERTIFICATE_SERIAL = 0x1234567890ABCDEF
"""Serial number the test certificates carry."""
SC_INFO_ACCOUNT_ID = 0x765AF8F2
"""Apple account identifier the sample purchase record carries."""
SC_INFO_ACCOUNT_NAME = 'Example Buyer'
"""Account name the sample purchase record carries."""
SC_INFO_PURCHASED = 3789925910
"""Purchase time the sample record carries, in seconds since 1904-01-01 UTC."""
SC_INFO_IV = bytes(range(16))
"""Initialisation vector the sample purchase record carries."""
SC_INFO_IDENTIFIER = bytes(range(20))
"""The 20-byte identifier the sample supplements share."""
SUPP_RECORD_COUNT = 3
"""How many 32-byte records the sample ``.supp`` carries."""
SC_INFO_MANIFEST = {
    'SinfPaths': ['SC_Info/Example.sinf'],
    'SinfReplicationPaths': ['SC_Info/Example.sinf'],
}
"""The manifest both the unpacked and the archived sample bundles carry."""


@pytest.fixture(scope='session')
def ec_certificate_der() -> bytes:
    """
    Build a self-signed elliptic-curve certificate once for the whole suite.

    Returns
    -------
    bytes
        The certificate, DER-encoded.
    """
    return _self_signed(ec.generate_private_key(ec.SECP256R1()), 'Example EC Leaf')


@pytest.fixture(scope='session')
def rsa_certificate_der() -> bytes:
    """
    Build a self-signed RSA certificate once for the whole suite.

    Returns
    -------
    bytes
        The certificate, DER-encoded.
    """
    return _self_signed(rsa.generate_private_key(public_exponent=65537, key_size=2048),
                        'Example RSA Leaf')


@pytest.fixture
def sinf_bytes() -> bytes:
    """
    Build a purchase record carrying every atom the reader surfaces.

    Returns
    -------
    bytes
        The ``.sinf`` contents.
    """
    rights = b''.join((
        b'veID' + bytes.fromhex('000036f3'),
        b'plat' + bytes.fromhex('00000005'),
        b'aver' + bytes.fromhex('01010100'),
        b'tran' + struct.pack('>I', SC_INFO_PURCHASED - 1),
        b'song' + bytes.fromhex('1c244a91'),
        b'tool' + b'P609',
        b'medi' + bytes.fromhex('00000080'),
        b'mode' + bytes.fromhex('00002000'),
    )) + bytes.fromhex('8a34795bffffffee')
    schi = b''.join((
        _atom(b'user', struct.pack('>I', SC_INFO_ACCOUNT_ID)),
        _atom(b'crdt', struct.pack('>I', SC_INFO_PURCHASED)),
        _atom(b'asdt', struct.pack('>I', 0)),
        _atom(b'key ', struct.pack('>I', 6)),
        _atom(b'iviv', SC_INFO_IV),
        _atom(b'righ', rights),
        _atom(b'name',
              SC_INFO_ACCOUNT_NAME.encode().ljust(256, b'\0')),
        _atom(b'priv',
              bytes(range(256)) * 2),
    ))
    return _atom(
        b'sinf', b''.join((
            _atom(b'frma', b'game'),
            _atom(b'schm', b'\0\0\0\0itun\0\0\0\0'),
            _atom(b'schi', schi),
            _atom(b'sign', bytes(128)),
        )))


@pytest.fixture
def supf_bytes(ec_certificate_der: bytes) -> bytes:
    """
    Build a ``.supf`` supplement in the real length-prefixed layout.

    Returns
    -------
    bytes
        The ``.supf`` contents.
    """
    body = (struct.pack('>4I', 1, 64, 0x0100000C, 0) + SC_INFO_IDENTIFIER + struct.pack('>I', 1) +
            bytes(range(32)))
    assert len(body) == 72
    return (b'\x03507' + struct.pack('>I', len(body)) + body +
            struct.pack('>I', len(ec_certificate_der)) + ec_certificate_der +
            struct.pack('>I', 128) + bytes(range(128)))


@pytest.fixture
def supp_bytes(rsa_certificate_der: bytes) -> bytes:
    """
    Build a ``.supp`` supplement holding a counted record table and its own certificate.

    Returns
    -------
    bytes
        The ``.supp`` contents.
    """
    records = b''.join(bytes([index]) * 32 for index in range(SUPP_RECORD_COUNT))
    return (b'\x01507' + SC_INFO_IDENTIFIER + struct.pack('>I', SUPP_RECORD_COUNT) + records +
            struct.pack('>I', len(rsa_certificate_der)) + rsa_certificate_der + bytes(128))


@pytest.fixture
def supx_bytes() -> bytes:
    """
    Build a ``.supx`` supplement holding two tagged entries.

    Returns
    -------
    bytes
        The ``.supx`` contents.
    """
    body = (struct.pack('>II', 1, 16) + bytes(range(16)) + struct.pack('>II', 2, 16) +
            bytes(range(16, 32)) + struct.pack('>II', 0, 0))
    return struct.pack('>II', 1, len(body)) + body + b'\xcc' * 8


@pytest.fixture
def sc_info_dir(tmp_path: Path, sinf_bytes: bytes, supf_bytes: bytes, supp_bytes: bytes,
                supx_bytes: bytes) -> Path:
    """
    Write a complete ``SC_Info`` directory inside a bundle inside a payload directory.

    Returns
    -------
    pathlib.Path
        The ``Payload`` directory holding the bundle, so the search is exercised too.
    """
    directory = tmp_path / 'Payload' / 'Example.app' / 'SC_Info'
    directory.mkdir(parents=True)
    (directory / 'Manifest.plist').write_bytes(plistlib.dumps(SC_INFO_MANIFEST))
    (directory / 'Example.sinf').write_bytes(sinf_bytes)
    (directory / 'Example.supf').write_bytes(supf_bytes)
    (directory / 'Example.supp').write_bytes(supp_bytes)
    (directory / 'Example.supx').write_bytes(supx_bytes)
    return tmp_path / 'Payload'


@pytest.fixture
def sc_info_ipa(tmp_path: Path, sinf_bytes: bytes, supf_bytes: bytes, supp_bytes: bytes,
                supx_bytes: bytes) -> Path:
    """
    Write an ``.ipa`` holding one bundle and its metadata, without unpacking anything.

    Returns
    -------
    pathlib.Path
        The written ``.ipa``.
    """
    path = tmp_path / 'Example.ipa'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('iTunesMetadata.plist', plistlib.dumps({'s': 143462}))
        archive.writestr('Payload/Example.app/Info.plist', plistlib.dumps({'CFBundleName': 'X'}))
        for name, data in (('Example.sinf', sinf_bytes), ('Example.supf', supf_bytes),
                           ('Example.supp', supp_bytes), ('Example.supx', supx_bytes)):
            archive.writestr(f'Payload/Example.app/SC_Info/{name}', data)
        archive.writestr('Payload/Example.app/SC_Info/Manifest.plist',
                         plistlib.dumps(SC_INFO_MANIFEST))
    return path


@pytest.fixture
def nested_ipa(tmp_path: Path, sinf_bytes: bytes, supf_bytes: bytes, supp_bytes: bytes) -> Path:
    """
    Write an ``.ipa`` holding an application and an app extension beside it.

    The extension is written first, so that anything relying on the application coming first has
    to sort for it rather than take the archive's own order.

    Returns
    -------
    pathlib.Path
        The written ``.ipa``.
    """
    path = tmp_path / 'Nested.ipa'
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in (('Widget.sinf', sinf_bytes), ('Widget.supf', supf_bytes)):
            archive.writestr(f'Payload/Example.app/PlugIns/Widget.appex/SC_Info/{name}', data)
        for name, data in (('Example.sinf', sinf_bytes), ('Example.supf', supf_bytes),
                           ('Example.supp', supp_bytes)):
            archive.writestr(f'Payload/Example.app/SC_Info/{name}', data)
    return path
