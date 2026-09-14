"""Shared pytest configuration for the ``dade.misc`` suite."""
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
    from collections.abc import Callable, Sequence
    from pathlib import Path


class ArchiveBuilder:
    """
    Assemble an ``NSKeyedArchiver`` plist object graph for the tests.

    Objects are appended to the archive's ``$objects`` table and referred to by the
    :py:class:`plistlib.UID` each ``add`` returns, the way a real archive is arranged.
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
    Write a compiled mapping model with one copy mapping and one remove mapping.

    The copy mapping includes the fetch source expression, two attribute mappings, and version
    hashes; the remove mapping has no destination entity. Both share one user-info dictionary, and
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
    Write a compiled managed object model with one entity, an attribute, and a relationship.

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
    Write a compiled ``.strings`` table, a flat binary plist.

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
"""Serial number the test certificates have."""
SC_INFO_ACCOUNT_ID = 0x765AF8F2
"""Apple account identifier in the sample purchase record."""
SC_INFO_ACCOUNT_NAME = 'Example Buyer'
"""Account name in the sample purchase record."""
SC_INFO_PURCHASED = 3789925910
"""Purchase time in the sample record, in seconds since 1904-01-01 UTC."""
SC_INFO_IV = bytes(range(16))
"""Initialisation vector in the sample purchase record."""
SC_INFO_IDENTIFIER = bytes(range(20))
"""The 20-byte identifier the sample supplements share."""
SUPP_RECORD_COUNT = 3
"""How many 32-byte records the sample ``.supp`` has."""
SC_INFO_MANIFEST = {
    'SinfPaths': ['SC_Info/Example.sinf'],
    'SinfReplicationPaths': ['SC_Info/Example.sinf'],
}
"""The manifest in both the unpacked and the archived sample bundles."""


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
    Build a purchase record with every atom the reader surfaces.

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
    Build a ``.supp`` supplement with a counted record table and its certificate.

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
    Build a ``.supx`` supplement with two tagged entries.

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
        The ``Payload`` directory with the bundle, exercising the search too.
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
def sc_info_dir_with_two_records(tmp_path: Path, sinf_bytes: bytes, supf_bytes: bytes,
                                 supp_bytes: bytes) -> Path:
    """
    Write an ``SC_Info`` directory with two sets of protection files.

    The second set is named after another architecture and does not include a ``.supf``. A real
    download takes this shape when one set remains beside the main record.

    Returns
    -------
    pathlib.Path
        The ``Payload`` directory with the bundle.
    """
    directory = tmp_path / 'Payload' / 'Example.app' / 'SC_Info'
    directory.mkdir(parents=True)
    (directory / 'Manifest.plist').write_bytes(plistlib.dumps(SC_INFO_MANIFEST))
    (directory / 'Example.sinf').write_bytes(sinf_bytes)
    (directory / 'Example.supf').write_bytes(supf_bytes)
    (directory / 'Example.supp').write_bytes(supp_bytes)
    # Sorts before 'Example'; name order alone would pick the wrong record.
    (directory / 'AExample_armv7.sinf').write_bytes(sinf_bytes)
    (directory / 'AExample_armv7.supp').write_bytes(supp_bytes)
    return tmp_path / 'Payload'


@pytest.fixture
def sc_info_ipa(tmp_path: Path, sinf_bytes: bytes, supf_bytes: bytes, supp_bytes: bytes,
                supx_bytes: bytes) -> Path:
    """
    Write an ``.ipa`` with one bundle and its metadata, without unpacking anything.

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
    Write an ``.ipa`` with an application and an app extension beside it.

    The extension is written first. Anything relying on the application coming first therefore has
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


class MachOBuilder:
    """
    Assemble a little-endian Mach-O image for the tests.

    Load commands are appended in order and the header is written last, once their total size is
    known. The linker itself has to work in that order.
    """
    def __init__(self,
                 *,
                 wide: bool = True,
                 cpu_type: int = 0x0100_000C,
                 cpu_subtype: int = 0,
                 file_type: int = 2,
                 flags: int = 0x0020_0085) -> None:
        self.commands: list[bytes] = []
        self.cpu_subtype = cpu_subtype
        self.cpu_type = cpu_type
        self.file_type = file_type
        self.flags = flags
        self.wide = wide

    def add(self, command: int, body: bytes) -> None:
        """
        Append one load command, padded to a four-byte boundary.

        Parameters
        ----------
        command : int
            The ``LC_*`` value.
        body : bytes
            The command's payload, excluding the eight-byte command header.
        """
        size = (len(body) + 8 + 3) & ~3
        self.commands.append(struct.pack('<II', command, size) + body.ljust(size - 8, b'\0'))

    def add_raw(self, blob: bytes) -> None:
        """
        Append an already-assembled load command, header included and unpadded.

        Parameters
        ----------
        blob : bytes
            The whole command.
        """
        self.commands.append(blob)

    def add_segment(self, name: str, sections: Sequence[str] = ()) -> None:
        """
        Append an ``LC_SEGMENT`` or ``LC_SEGMENT_64`` naming zero or more sections.

        Parameters
        ----------
        name : str
            The segment name.
        sections : collections.abc.Sequence[str]
            The section names within the segment.
        """
        padded = name.encode().ljust(16, b'\0')
        if self.wide:
            body = padded + struct.pack('<QQQQiiII', 0x1000, 0x2000, 0x3000, 0x4000, 7, 5,
                                        len(sections), 0)
            for section in sections:
                body += (section.encode().ljust(16, b'\0') + padded +
                         struct.pack('<QQIIIIIIII', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
            self.add(0x19, body)
            return
        body = padded + struct.pack('<IIIIiiII', 0x1000, 0x2000, 0x3000, 0x4000, 7, 5,
                                    len(sections), 0)
        for section in sections:
            body += (section.encode().ljust(16, b'\0') + padded +
                     struct.pack('<IIIIIIIII', 0, 0, 0, 0, 0, 0, 0, 0, 0))
        self.add(0x1, body)

    def add_string_command(self, command: int, text: str) -> None:
        """
        Append a load command whose only payload is an offset-addressed C string.

        Parameters
        ----------
        command : int
            The ``LC_*`` value.
        text : str
            The string to store.
        """
        self.add(command, struct.pack('<I', 12) + text.encode() + b'\0')

    def build(self) -> bytes:
        """
        Assemble the whole image.

        Returns
        -------
        bytes
            The Mach-O image.
        """
        body = b''.join(self.commands)
        if self.wide:
            header = struct.pack('<IIIIIIII', 0xFEED_FACF, self.cpu_type, self.cpu_subtype,
                                 self.file_type, len(self.commands), len(body), self.flags, 0)
        else:
            header = struct.pack('<IIIIIII', 0xFEED_FACE, self.cpu_type, self.cpu_subtype,
                                 self.file_type, len(self.commands), len(body), self.flags)
        return header + body


def _entitlements_signature(plist: bytes) -> bytes:
    """Wrap an entitlements plist in the code-signature super-blob that includes it."""
    blob = struct.pack('>II', 0xFADE_7171, len(plist) + 8) + plist
    # One requirements blob ahead of the entitlements; the reader has to skip a foreign one.
    other = struct.pack('>II', 0xFADE_0C00, 8)
    start = 12 + 8 * 2
    header = struct.pack('>III', 0xFADE_0CC0, start + len(other) + len(blob), 2)
    index = struct.pack('>II', 2, start) + struct.pack('>II', 5, start + len(other))
    return header + index + other + blob


@pytest.fixture
def macho_arm64(tmp_path: Path) -> Path:
    """
    Write a thin 64-bit ``arm64`` image exercising every load command the reader names.

    Returns
    -------
    pathlib.Path
        The written image.
    """
    builder = MachOBuilder()
    builder.add_segment('__PAGEZERO')
    builder.add_segment('__TEXT', ('__text', '__cstring'))
    builder.add_string_command(0xC, '/usr/lib/libSystem.B.dylib')
    builder.add_string_command(0x18 | 0x8000_0000,
                               '/System/Library/Frameworks/WebKit.framework/WebKit')
    builder.add_string_command(0x1C | 0x8000_0000, '@executable_path/Frameworks')
    builder.add(0x1B, bytes(range(16)))
    builder.add(0x2A, struct.pack('<Q', (1 << 40) | (2 << 30) | (3 << 20)))
    builder.add(0x32, struct.pack('<III', 2, 0x0009_0000, 0x000A_0300))
    builder.add(0x2C, struct.pack('<IIII', 0x4000, 0x1000, 1, 0))
    signature = _entitlements_signature(
        plistlib.dumps({'application-identifier': 'ABCDE12345.com.example.app'}))
    # The signature is appended after every load command; its offset is only known once the
    # command that points at it is itself in place. A placeholder sizes the image, then the real
    # offset replaces it.
    builder.add(0x1D, struct.pack('<II', 0, len(signature)))
    offset = len(builder.build())
    builder.commands[-1] = struct.pack('<IIII', 0x1D, 16, offset, len(signature))
    path = tmp_path / 'Example'
    path.write_bytes(builder.build() + signature)
    return path


@pytest.fixture
def macho_armv7(tmp_path: Path) -> Path:
    """
    Write a thin 32-bit ``armv7`` image using the older minimum-OS command.

    Returns
    -------
    pathlib.Path
        The written image.
    """
    builder = MachOBuilder(wide=False, cpu_type=12, cpu_subtype=9)
    builder.add_segment('__TEXT', ('__text',))
    builder.add(0x25, struct.pack('<II', 0x0006_0000, 0x0007_0100))
    path = tmp_path / 'Legacy'
    path.write_bytes(builder.build())
    return path


@pytest.fixture
def macho_universal(tmp_path: Path, macho_arm64: Path, macho_armv7: Path) -> Path:
    """
    Write a universal image with the 32-bit and 64-bit slices side by side.

    Returns
    -------
    pathlib.Path
        The written image.
    """
    slices = (macho_armv7.read_bytes(), macho_arm64.read_bytes())
    header = struct.pack('>II', 0xCAFE_BABE, len(slices))
    offset = (len(header) + 20 * len(slices) + 0xFFF) & ~0xFFF
    entries, body, cursor = b'', b'', offset
    for index, data in enumerate(slices):
        entries += struct.pack('>iiIII', 12 if index == 0 else 0x0100_000C, 0, cursor, len(data),
                               12)
        body += data
        cursor += len(data)
    path = tmp_path / 'Fat'
    path.write_bytes(header + entries + b'\0' * (offset - len(header) - len(entries)) + body)
    return path


@pytest.fixture
def macho_builder() -> type[MachOBuilder]:
    """
    Hand the tests the Mach-O assembler itself, for images no fixture covers.

    Returns
    -------
    type[MachOBuilder]
        The builder class.
    """
    return MachOBuilder


@pytest.fixture
def make_signature() -> Callable[[bytes], bytes]:
    """
    Build a code-signature super-blob with an entitlements plist.

    Returns
    -------
    collections.abc.Callable[[bytes], bytes]
        A callable taking the plist bytes and returning the whole signature.
    """
    return _entitlements_signature


@pytest.fixture
def make_signed_macho(tmp_path: Path) -> Callable[[bytes], Path]:
    """
    Write a minimal image whose code signature is the bytes given.

    Returns
    -------
    collections.abc.Callable[[bytes], pathlib.Path]
        A callable taking the signature bytes and returning the written image.
    """
    def build(signature: bytes) -> Path:
        builder = MachOBuilder()
        builder.add(0x1D, struct.pack('<II', 0, len(signature)))
        offset = len(builder.build())
        builder.commands[-1] = struct.pack('<IIII', 0x1D, 16, offset, len(signature))
        path = tmp_path / 'Signed'
        path.write_bytes(builder.build() + signature)
        return path

    return build


class DSStoreBuilder:
    """
    Assemble a Buddy allocator file for the tests.

    Blocks are appended in the order they are given and addressed by their position, the way the
    allocator's own table addresses them. Each is padded out to the next power of two, and the
    header, the block table, and the 32 empty free lists are filled in by :py:meth:`build`.
    """
    header_size = 36
    """The bytes the header occupies before the first block."""
    page_size = 0x1000
    """The node size a master block reports."""
    def __init__(self) -> None:
        self.blocks: list[bytes] = []

    def add(self, payload: bytes) -> int:
        """
        Append one block.

        Parameters
        ----------
        payload : bytes
            The block's body.

        Returns
        -------
        int
            The block's number.
        """
        self.blocks.append(payload)
        return len(self.blocks) - 1

    @staticmethod
    def branch(pairs: Sequence[tuple[int, bytes]], last: int) -> bytes:
        """
        Build an internal node, alternating child block numbers with records.

        Parameters
        ----------
        pairs : collections.abc.Sequence[tuple[int, bytes]]
            Each child block number and the record that follows it.
        last : int
            The block number of the child after the final record. The node opens with it.

        Returns
        -------
        bytes
            The node's body.
        """
        body = b''.join(struct.pack('>I', child) + record for child, record in pairs)
        return struct.pack('>II', last, len(pairs)) + body

    def build(self, directories: Sequence[tuple[str, int]]) -> bytes:
        """
        Write the whole file.

        Parameters
        ----------
        directories : collections.abc.Sequence[tuple[str, int]]
            Each directory name and the master block it points at.

        Returns
        -------
        bytes
            The file, header first and allocator last.
        """
        data = bytearray(self.header_size)
        addresses = []
        for payload in self.blocks:
            while (len(data) - 4) % 32:
                data.append(0)
            exponent = max(5, (len(payload) - 1).bit_length())
            addresses.append((len(data) - 4) | exponent)
            data += payload + bytes((1 << exponent) - len(payload))
        while (len(data) - 4) % 32:
            data.append(0)
        offset = len(data) - 4
        padded = -(-len(addresses) // 256) * 256
        allocator = bytearray(struct.pack('>II', len(addresses), 0))
        allocator += struct.pack(f'>{padded}I', *addresses, *((0,) * (padded - len(addresses))))
        allocator += struct.pack('>I', len(directories))
        for name, block in directories:
            allocator += struct.pack('>B', len(name)) + name.encode() + struct.pack('>I', block)
        allocator += struct.pack('>I', 0) * 32
        data += allocator
        data[:20] = struct.pack('>I4sIII', 1, b'Bud1', offset, len(allocator), offset)
        return bytes(data)

    @staticmethod
    def leaf(records: Sequence[bytes]) -> bytes:
        """
        Build a leaf node.

        Parameters
        ----------
        records : collections.abc.Sequence[bytes]
            The records the node stores, in order.

        Returns
        -------
        bytes
            The node's body.
        """
        return struct.pack('>II', 0, len(records)) + b''.join(records)

    @classmethod
    def master(cls, root: int, *, levels: int = 1, records: int = 0, nodes: int = 1) -> bytes:
        """
        Build a master block.

        Parameters
        ----------
        root : int
            The block number of the tree's root node.
        levels : int
            The tree's depth.
        records : int
            The number of records the tree stores.
        nodes : int
            The number of nodes the tree occupies.

        Returns
        -------
        bytes
            The block's body.
        """
        return struct.pack('>IIIII', root, levels, records, nodes, cls.page_size)

    @staticmethod
    def record(name: str, code: str, kind: str, value: bytes) -> bytes:
        """
        Build one record.

        Parameters
        ----------
        name : str
            The file name the record belongs to.
        code : str
            The four-character structure identifier.
        kind : str
            The four-character data type.
        value : bytes
            The value, already encoded as the data type stores it.

        Returns
        -------
        bytes
            The record.
        """
        return (struct.pack('>I', len(name)) + name.encode('utf-16-be') + code.encode() +
                kind.encode() + value)


@pytest.fixture
def ds_store_builder() -> type[DSStoreBuilder]:
    """
    Hand the tests the Buddy allocator assembler itself, for files no fixture covers.

    Returns
    -------
    type[DSStoreBuilder]
        The builder class.
    """
    return DSStoreBuilder


@pytest.fixture
def ds_store_path(tmp_path: Path) -> Path:
    """
    Write a database whose tree is one leaf, with a record of every data type.

    Returns
    -------
    pathlib.Path
        The written database.
    """
    builder = DSStoreBuilder()
    # Finder's own allocator occupies the first block, and a node therefore never sits there.
    builder.add(bytes(8))
    window = plistlib.dumps({
        'ShowSidebar': True,
        'WindowBounds': '{{0, 0}, {770, 435}}'
    },
                            fmt=plistlib.FMT_BINARY)
    records = (DSStoreBuilder.record('.', 'bwsp', 'blob',
                                     struct.pack('>I', len(window)) + window),
               DSStoreBuilder.record(
                   '.', 'fwi0', 'blob',
                   struct.pack('>I', 16) + struct.pack('>4h', 36, 0, 471, 770) + b'icnv' +
                   bytes(4)), DSStoreBuilder.record('.', 'vSrn', 'long', struct.pack('>i', 1)),
               DSStoreBuilder.record(
                   'Photos', 'Iloc', 'blob',
                   struct.pack('>I', 16) + struct.pack('>II', 132, 64) +
                   bytes.fromhex('ffffffffffff0000')),
               DSStoreBuilder.record('Photos', 'dscl', 'bool', b'\x01'),
               DSStoreBuilder.record('Photos', 'icsp', 'shor', struct.pack('>i', 16)),
               DSStoreBuilder.record('Readme.txt', 'cmmt', 'ustr',
                                     struct.pack('>I', 2) + 'メモ'.encode('utf-16-be')),
               DSStoreBuilder.record('Readme.txt', 'logS', 'comp', struct.pack('>q', 8192)),
               DSStoreBuilder.record('Readme.txt', 'modD', 'dutc', struct.pack(
                   '>q',
                   241978834944000)), DSStoreBuilder.record('Readme.txt', 'ptbL', 'type', b'icnv'),
               DSStoreBuilder.record('Readme.txt', 'pBBk', 'blob',
                                     struct.pack('>I', 4) + b'book'))
    node = builder.add(DSStoreBuilder.leaf(records))
    master = builder.add(DSStoreBuilder.master(node, levels=0, records=len(records)))
    path = tmp_path / '.DS_Store'
    path.write_bytes(builder.build((('DSDB', master),)))
    return path


@pytest.fixture
def ds_store_branching(tmp_path: Path) -> Path:
    """
    Write a database whose root node is internal, with a leaf on either side of its record.

    Returns
    -------
    pathlib.Path
        The written database.
    """
    builder = DSStoreBuilder()
    # Finder's own allocator occupies the first block, and a node therefore never sits there.
    builder.add(bytes(8))
    left = builder.add(
        DSStoreBuilder.leaf((DSStoreBuilder.record('Alpha', 'vSrn', 'long', struct.pack(
            '>i', 1)), DSStoreBuilder.record('Beta', 'vSrn', 'long', struct.pack('>i', 2)))))
    right = builder.add(
        DSStoreBuilder.leaf((
            DSStoreBuilder.record('Delta', 'vSrn', 'long', struct.pack('>i', 4)),
            DSStoreBuilder.record('Echo', 'vSrn', 'long', struct.pack('>i', 5)),
        )))
    root = builder.add(
        DSStoreBuilder.branch(
            ((left, DSStoreBuilder.record('Gamma', 'vSrn', 'long', struct.pack('>i', 3))),), right))
    master = builder.add(DSStoreBuilder.master(root, levels=1, nodes=3, records=5))
    path = tmp_path / '.DS_Store'
    path.write_bytes(builder.build((('DSDB', master),)))
    return path
