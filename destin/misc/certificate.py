"""
Summaries of the X.509 certificates embedded in other files.

This wraps :py:mod:`cryptography.x509` into a flat, JSON-ready summary and a block of report lines.
It describes a certificate; it does not validate one. No signature is checked, no chain is built,
and no trust decision is made or implied, so an expired or self-signed certificate is summarised as
readily as any other.

:func:`find_certificates` scans a buffer for embedded DER, which is how the Apple FairPlay
certificate is recovered from an ``SC_Info`` supplement file.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed448, ed25519, rsa
from cryptography.hazmat.primitives.serialization import Encoding
from typing_extensions import override

if TYPE_CHECKING:
    from datetime import datetime

__all__ = ('CertificateSummary', 'ExtensionInfo', 'PublicKeyInfo', 'certificate_lines',
           'certificate_to_json', 'find_certificates', 'load_certificate')

_DER_SEQUENCE = 0x30
_LONG_FORM = 0x80
_LENGTH_MASK = 0x7F
_MAX_LENGTH_BYTES = 4


class PublicKeyInfo(NamedTuple):
    """What a certificate's public key is, without the key material."""

    algorithm: str
    """The key's algorithm, such as ``RSA`` or ``EC``."""
    size: int | None
    """The key's size in bits, where the algorithm has a variable one."""
    detail: str | None
    """Algorithm-specific detail: the public exponent for RSA, the curve name for EC."""
    @override
    def __str__(self) -> str:
        """
        Render the key on one line.

        Returns
        -------
        str
            The algorithm, its size, and its detail, omitting whichever are absent.
        """
        parts = [self.algorithm]
        if self.size is not None:
            parts.append(f'{self.size} bits')
        if self.detail is not None:
            parts.append(self.detail)
        return ', '.join(parts)


class ExtensionInfo(NamedTuple):
    """One X.509 extension, broken into its fields."""

    name: str
    """The extension's registered name, falling back to its object identifier."""
    oid: str
    """The extension's object identifier, in dotted-decimal form."""
    critical: bool
    """Whether a reader that does not understand it must reject the certificate."""
    fields: tuple[tuple[str, Any], ...]
    """The extension's own fields, in order, for the types broken out here."""
    summary: str
    """A one-line rendering, which is all there is for a type not broken out here."""


class CertificateSummary(NamedTuple):
    """The parts of an X.509 certificate worth showing a reader."""

    version: str
    """The certificate's version, such as ``v3``."""
    serial_number: int
    """The serial number as an integer."""
    subject: str
    """Who the certificate was issued to, in RFC 4514 form."""
    issuer: str
    """Who issued it, in RFC 4514 form."""
    not_valid_before: datetime
    """Start of the validity window, in UTC."""
    not_valid_after: datetime
    """End of the validity window, in UTC."""
    signature_algorithm: str
    """The signature algorithm's name, falling back to its object identifier."""
    signature_algorithm_oid: str
    """The signature algorithm's object identifier, in dotted-decimal form."""
    public_key: PublicKeyInfo
    """What the public key is."""
    fingerprint_sha256: str
    """SHA-256 over the DER encoding, which is the fingerprint tools print."""
    extensions: tuple[ExtensionInfo, ...]
    """Every extension, in the order the certificate lists them."""
    der: bytes
    """The certificate itself, DER-encoded, so callers can re-export it."""
    @property
    def pem(self) -> str:
        """
        The certificate in PEM form.

        Returns
        -------
        str
            The PEM text, ending in a newline.
        """
        return x509.load_der_x509_certificate(self.der).public_bytes(Encoding.PEM).decode()

    @property
    def serial_hex(self) -> str:
        """
        The serial number in the uppercase hexadecimal form tools print.

        Returns
        -------
        str
            The serial number, padded to an even number of digits.
        """
        digits = f'{self.serial_number:X}'
        return digits.zfill(len(digits) + len(digits) % 2)


def _public_key_info(certificate: x509.Certificate) -> PublicKeyInfo:
    """
    Describe a certificate's public key.

    Parameters
    ----------
    certificate : cryptography.x509.Certificate
        The certificate.

    Returns
    -------
    PublicKeyInfo
        The key's algorithm, size, and algorithm-specific detail.
    """
    key = certificate.public_key()
    if isinstance(key, rsa.RSAPublicKey):
        return PublicKeyInfo('RSA', key.key_size, f'exponent {key.public_numbers().e}')
    if isinstance(key, ec.EllipticCurvePublicKey):
        return PublicKeyInfo('EC', key.key_size, key.curve.name)
    if isinstance(key, dsa.DSAPublicKey):
        return PublicKeyInfo('DSA', key.key_size, None)
    if isinstance(key, ed25519.Ed25519PublicKey):
        return PublicKeyInfo('Ed25519', None, None)
    if isinstance(key, ed448.Ed448PublicKey):
        return PublicKeyInfo('Ed448', None, None)
    return PublicKeyInfo(type(key).__name__, getattr(key, 'key_size', None), None)


def _oid_name(oid: x509.ObjectIdentifier) -> str:
    """
    Read an object identifier's registered name.

    Parameters
    ----------
    oid : cryptography.x509.ObjectIdentifier
        The identifier.

    Returns
    -------
    str
        The registered name, or the dotted-decimal form when the identifier is not one
        :py:mod:`cryptography` has a name for.
    """
    # cryptography exposes the registered name only as a private attribute, and its own repr is
    # built from it. Falling back to the dotted form keeps this working whatever it does next.
    return getattr(oid, '_name', None) or oid.dotted_string


def _key_usage_fields(value: x509.KeyUsage) -> tuple[tuple[str, Any], ...]:
    """
    Break a ``keyUsage`` extension into its flags.

    Parameters
    ----------
    value : cryptography.x509.KeyUsage
        The extension's value.

    Returns
    -------
    tuple[tuple[str, Any], ...]
        One pair per flag. The last two are only meaningful with key agreement set, and
        :py:mod:`cryptography` refuses to read them otherwise, so they are omitted then.
    """
    fields: list[tuple[str, Any]] = [
        ('digitalSignature', value.digital_signature),
        ('contentCommitment', value.content_commitment),
        ('keyEncipherment', value.key_encipherment),
        ('dataEncipherment', value.data_encipherment),
        ('keyAgreement', value.key_agreement),
        ('keyCertSign', value.key_cert_sign),
        ('crlSign', value.crl_sign),
    ]
    if value.key_agreement:
        fields += [('encipherOnly', value.encipher_only), ('decipherOnly', value.decipher_only)]
    return tuple(fields)


def _extension_fields(value: x509.ExtensionType) -> tuple[tuple[str, Any], ...]:
    """
    Break an extension into its own fields, for the types worth breaking out.

    Parameters
    ----------
    value : cryptography.x509.ExtensionType
        The extension's value.

    Returns
    -------
    tuple[tuple[str, Any], ...]
        The fields in order, or empty for a type this does not break out, whose one-line summary
        then carries everything.
    """
    if isinstance(value, x509.KeyUsage):
        return _key_usage_fields(value)
    if isinstance(value, x509.BasicConstraints):
        return (('ca', value.ca), ('pathLength', value.path_length))
    if isinstance(value, x509.SubjectKeyIdentifier):
        return (('digest', value.digest.hex()),)
    if isinstance(value, x509.AuthorityKeyIdentifier):
        return (('keyIdentifier',
                 value.key_identifier.hex() if value.key_identifier is not None else None),
                ('authorityCertSerialNumber', value.authority_cert_serial_number))
    if isinstance(value, x509.ExtendedKeyUsage):
        return (('usages', [_oid_name(oid) for oid in value]),)
    if isinstance(value, x509.SubjectAlternativeName):
        return (('names', [str(name.value) for name in value]),)
    return ()


def load_certificate(der: bytes) -> CertificateSummary:
    """
    Summarise a DER-encoded X.509 certificate.

    Parameters
    ----------
    der : bytes
        The certificate, DER-encoded.

    Returns
    -------
    CertificateSummary
        The summary.

    Notes
    -----
    Bytes that are not a DER certificate raise the :py:class:`ValueError`
    :py:func:`cryptography.x509.load_der_x509_certificate` raises.
    """
    certificate = x509.load_der_x509_certificate(der)
    extensions = tuple(
        ExtensionInfo(_oid_name(extension.oid), extension.oid.dotted_string, extension.critical,
                      _extension_fields(extension.value),
                      str(extension.value).strip('<>')) for extension in certificate.extensions)
    return CertificateSummary(certificate.version.name, certificate.serial_number,
                              certificate.subject.rfc4514_string(),
                              certificate.issuer.rfc4514_string(), certificate.not_valid_before_utc,
                              certificate.not_valid_after_utc,
                              _oid_name(certificate.signature_algorithm_oid),
                              certificate.signature_algorithm_oid.dotted_string,
                              _public_key_info(certificate),
                              certificate.fingerprint(hashes.SHA256()).hex(), extensions, der)


def _der_size(data: bytes, offset: int) -> int | None:
    """
    Read how many bytes the DER value at an offset occupies.

    Parameters
    ----------
    data : bytes
        The buffer.
    offset : int
        Where the value starts.

    Returns
    -------
    int | None
        The total size, header included, or ``None`` when there is no readable definite-length
        header there.
    """
    # The sole caller only scans for the long-form marker ``\x30\x82``, so the tag and short-form
    # guards below cannot be reached through it; they keep the reader correct for any other caller.
    if offset + 2 > len(data) or data[offset] != _DER_SEQUENCE:  # pragma: no cover
        return None
    first = data[offset + 1]
    if first < _LONG_FORM:  # pragma: no cover
        return 2 + first
    count = first & _LENGTH_MASK
    if count == 0 or count > _MAX_LENGTH_BYTES or offset + 2 + count > len(data):
        return None
    return 2 + count + int.from_bytes(data[offset + 2:offset + 2 + count], 'big')


def find_certificates(data: bytes) -> tuple[tuple[int, bytes], ...]:
    """
    Find every DER certificate embedded in a buffer.

    Each candidate sequence is parsed before being accepted, so unrelated bytes that happen to
    start like one are not reported.

    Parameters
    ----------
    data : bytes
        The buffer to scan.

    Returns
    -------
    tuple[tuple[int, bytes], ...]
        The offset and bytes of each certificate, in the order they appear.
    """
    found: list[tuple[int, bytes]] = []
    offset = 0
    while (offset := data.find(b'\x30\x82', offset)) >= 0:
        size = _der_size(data, offset)
        if size is None or offset + size > len(data):
            offset += 1
            continue
        candidate = data[offset:offset + size]
        try:
            x509.load_der_x509_certificate(candidate)
        except ValueError:
            offset += 1
            continue
        found.append((offset, candidate))
        offset += size
    return tuple(found)


def _extension_to_json(extension: ExtensionInfo) -> dict[str, Any]:
    """
    Render one extension as JSON-ready values.

    A type broken into fields carries those and nothing else; only a type this does not break down
    falls back to the one-line summary, so no rendered object repeats itself.

    Parameters
    ----------
    extension : ExtensionInfo
        The extension to render.

    Returns
    -------
    dict[str, Any]
        The rendered extension.
    """
    rendered: dict[str, Any] = {
        'name': extension.name,
        'oid': extension.oid,
        'critical': extension.critical,
    }
    if extension.fields:
        rendered['fields'] = dict(extension.fields)
    else:
        rendered['summary'] = extension.summary
    return rendered


def certificate_to_json(summary: CertificateSummary) -> dict[str, Any]:
    """
    Render a certificate summary as JSON-ready values.

    Parameters
    ----------
    summary : CertificateSummary
        The summary to render.

    Returns
    -------
    dict[str, Any]
        The rendered summary, the DER and PEM encodings included.
    """
    return {
        'version': summary.version,
        'serialNumber': summary.serial_hex,
        'serialNumberDecimal': str(summary.serial_number),
        'subject': summary.subject,
        'issuer': summary.issuer,
        'notValidBefore': summary.not_valid_before.isoformat(),
        'notValidAfter': summary.not_valid_after.isoformat(),
        'signatureAlgorithm': summary.signature_algorithm,
        'signatureAlgorithmOid': summary.signature_algorithm_oid,
        'publicKey': {
            'algorithm': summary.public_key.algorithm,
            'size': summary.public_key.size,
            'detail': summary.public_key.detail,
        },
        'fingerprintSha256': summary.fingerprint_sha256,
        'extensions': [_extension_to_json(extension) for extension in summary.extensions],
        'der': summary.der.hex(),
        'pem': summary.pem,
    }


def certificate_lines(summary: CertificateSummary, indent: str = '    ') -> list[str]:
    """
    Render a certificate summary as aligned report lines.

    Parameters
    ----------
    summary : CertificateSummary
        The summary to render.
    indent : str
        Text put before each label.

    Returns
    -------
    list[str]
        One line per field, plus one per extension.
    """
    pairs = [
        ('Subject', summary.subject),
        ('Issuer', summary.issuer),
        ('Serial', summary.serial_hex),
        ('Version', summary.version),
        ('Valid from', summary.not_valid_before.isoformat()),
        ('Valid to', summary.not_valid_after.isoformat()),
        ('Signature', f'{summary.signature_algorithm} ({summary.signature_algorithm_oid})'),
        ('Public key', str(summary.public_key)),
        ('SHA-256', summary.fingerprint_sha256),
    ]
    width = max(len(label) for label, _ in pairs)
    lines = [f'{indent}{label.ljust(width)}  {value}' for label, value in pairs]
    if summary.extensions:
        lines.append(f'{indent}Extensions')
    for extension in summary.extensions:
        critical = ' (critical)' if extension.critical else ''
        lines.append(f'{indent}  {extension.name}{critical}  ({extension.oid})')
        if not extension.fields:
            lines.append(f'{indent}    {extension.summary}')
            continue
        field_width = max(len(name) for name, _ in extension.fields)
        lines += [
            f'{indent}    {name.ljust(field_width)}  {field}' for name, field in extension.fields
        ]
    return lines
