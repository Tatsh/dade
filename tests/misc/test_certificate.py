"""Tests for :py:mod:`destin.misc.certificate`."""
from __future__ import annotations

from destin.misc.certificate import (
    certificate_lines,
    certificate_to_json,
    find_certificates,
    load_certificate,
)
import pytest

from .conftest import CERTIFICATE_SERIAL


def test_load_rsa_certificate(rsa_certificate_der: bytes) -> None:
    summary = load_certificate(rsa_certificate_der)
    assert summary.version == 'v3'
    assert summary.serial_number == CERTIFICATE_SERIAL
    assert 'CN=Example RSA Leaf' in summary.subject
    assert summary.subject == summary.issuer
    assert summary.public_key.algorithm == 'RSA'
    assert summary.public_key.size == 2048
    assert summary.public_key.detail == 'exponent 65537'
    assert summary.signature_algorithm == 'sha256WithRSAEncryption'
    assert summary.not_valid_before.year == 2020
    assert summary.not_valid_after.year == 2030
    assert len(summary.fingerprint_sha256) == 64


def test_load_ec_certificate(ec_certificate_der: bytes) -> None:
    summary = load_certificate(ec_certificate_der)
    assert summary.public_key.algorithm == 'EC'
    assert summary.public_key.size == 256
    assert summary.public_key.detail == 'secp256r1'
    assert str(summary.public_key) == 'EC, 256 bits, secp256r1'


def test_serial_hex_is_even_length(rsa_certificate_der: bytes) -> None:
    serial = load_certificate(rsa_certificate_der).serial_hex
    assert serial == '1234567890ABCDEF'
    assert len(serial) % 2 == 0


def test_extensions(ec_certificate_der: bytes) -> None:
    extensions = load_certificate(ec_certificate_der).extensions
    assert [extension.name for extension in extensions] == ['basicConstraints']
    assert extensions[0].critical is True
    assert extensions[0].oid == '2.5.29.19'
    assert extensions[0].fields == (('ca', False), ('pathLength', None))
    assert 'ca=False' in extensions[0].summary


def test_key_usage_extension_is_broken_into_flags(rsa_certificate_der: bytes) -> None:
    # The sample certificates carry no keyUsage, so build one that does.
    from datetime import datetime, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec as ec_module
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.x509.oid import NameOID
    key = ec_module.generate_private_key(ec_module.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Usage')])
    der = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(
        key.public_key()).serial_number(1).not_valid_before(
            datetime(2020, 1, 1, tzinfo=timezone.utc)).not_valid_after(
                datetime(2030, 1, 1, tzinfo=timezone.utc)).add_extension(
                    x509.KeyUsage(digital_signature=True,
                                  content_commitment=False,
                                  key_encipherment=True,
                                  data_encipherment=False,
                                  key_agreement=False,
                                  key_cert_sign=False,
                                  crl_sign=False,
                                  encipher_only=False,
                                  decipher_only=False),
                    critical=True).sign(key, hashes.SHA256()).public_bytes(Encoding.DER))
    fields = dict(load_certificate(der).extensions[0].fields)
    assert fields['digitalSignature'] is True
    assert fields['keyEncipherment'] is True
    assert fields['keyAgreement'] is False
    # Without key agreement the last two flags are not readable, so they are left out.
    assert 'encipherOnly' not in fields


def test_pem_round_trips(ec_certificate_der: bytes) -> None:
    pem = load_certificate(ec_certificate_der).pem
    assert pem.startswith('-----BEGIN CERTIFICATE-----')
    assert pem.rstrip().endswith('-----END CERTIFICATE-----')


def test_load_certificate_rejects_rubbish() -> None:
    with pytest.raises(ValueError, match=r'.'):
        load_certificate(b'\x30\x82\x00\x04not a certificate')


def test_certificate_to_json(ec_certificate_der: bytes) -> None:
    rendered = certificate_to_json(load_certificate(ec_certificate_der))
    assert rendered['serialNumber'] == '1234567890ABCDEF'
    assert rendered['serialNumberDecimal'] == str(CERTIFICATE_SERIAL)
    assert rendered['publicKey'] == {'algorithm': 'EC', 'size': 256, 'detail': 'secp256r1'}
    assert rendered['extensions'][0]['name'] == 'basicConstraints'
    assert rendered['extensions'][0]['fields'] == {'ca': False, 'pathLength': None}
    assert rendered['der'] == ec_certificate_der.hex()
    assert rendered['pem'].startswith('-----BEGIN CERTIFICATE-----')


def test_certificate_lines(ec_certificate_der: bytes) -> None:
    lines = certificate_lines(load_certificate(ec_certificate_der), '  ')
    assert any(line.startswith('  Subject') for line in lines)
    assert any('secp256r1' in line for line in lines)
    assert '  Extensions' in lines
    assert any('basicConstraints (critical)' in line for line in lines)
    # Each field of a broken-out extension gets its own indented line.
    assert any(line.strip().startswith('pathLength') for line in lines)


def test_find_certificates_in_a_wrapper(ec_certificate_der: bytes) -> None:
    buffer = b'\x00' * 32 + ec_certificate_der + b'\xff' * 16
    found = find_certificates(buffer)
    assert len(found) == 1
    assert found[0] == (32, ec_certificate_der)


def test_find_certificates_finds_several(ec_certificate_der: bytes,
                                         rsa_certificate_der: bytes) -> None:
    found = find_certificates(ec_certificate_der + b'\x00' * 8 + rsa_certificate_der)
    assert [der for _, der in found] == [ec_certificate_der, rsa_certificate_der]


def test_find_certificates_ignores_a_false_start() -> None:
    # A sequence header that is not a certificate must not be reported.
    assert find_certificates(b'\x30\x82\x00\x10' + b'\x00' * 16) == ()


def test_find_certificates_in_an_empty_buffer() -> None:
    assert find_certificates(b'') == ()
