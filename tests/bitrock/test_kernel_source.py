from __future__ import annotations

import pytest

from dade.bitrock.password_cracker.kernel_source import MAX_IV_POOL, MAX_PASSWORD, kernel_source
from dade.common.twofish import H_QSEQ, MDS, MDS_POLYNOMIAL, Q0, Q1, RS, RS_POLYNOMIAL


@pytest.mark.parametrize(
    'placeholder',
    ['/*TABLES*/', '/*MDS_POLY*/', '/*RS_POLY*/', '/*MAX_PASSWORD*/', '/*MAX_IV_POOL*/'])
def test_kernel_source_leaves_no_placeholders(placeholder: str) -> None:
    assert placeholder not in kernel_source()


def test_kernel_source_returns_str() -> None:
    assert isinstance(kernel_source(), str)


def test_kernel_source_qt_table() -> None:
    body = ', '.join(str(v) for v in (*Q0, *Q1))
    assert f'CONSTANT u8 QT[] = {{{body}}};' in kernel_source()


def test_kernel_source_qseq_table() -> None:
    qseq = [1 if table is Q1 else 0 for row in H_QSEQ for table in row]
    body = ', '.join(str(v) for v in qseq)
    assert f'CONSTANT u8 QSEQ[] = {{{body}}};' in kernel_source()


def test_kernel_source_mds_table() -> None:
    body = ', '.join(str(c) for row in MDS for c in row)
    assert f'CONSTANT u8 MDS[] = {{{body}}};' in kernel_source()


def test_kernel_source_rs_table() -> None:
    body = ', '.join(str(c) for row in RS for c in row)
    assert f'CONSTANT u8 RS[] = {{{body}}};' in kernel_source()


@pytest.mark.parametrize(('define', 'value'), [
    ('MDS_POLY', MDS_POLYNOMIAL),
    ('RS_POLY', RS_POLYNOMIAL),
    ('MAX_PASSWORD', MAX_PASSWORD),
    ('MAX_IV_POOL', MAX_IV_POOL),
])
def test_kernel_source_defines(define: str, value: int) -> None:
    assert f'#define {define}' in kernel_source()
    assert str(value) in kernel_source()


@pytest.mark.parametrize('token', [
    '#ifdef __OPENCL_VERSION__',
    'typedef uchar u8;',
    'typedef unsigned char u8;',
    '#define KERNEL __kernel',
    '#define KERNEL extern "C" __global__',
    '#define ATOMIC_CAS(p, cmp, val) atomic_cmpxchg((p), (cmp), (val))',
    '#define ATOMIC_CAS(p, cmp, val) atomicCAS((p), (cmp), (val))',
])
def test_kernel_source_dialect_bridge(token: str) -> None:
    assert token in kernel_source()


@pytest.mark.parametrize('function', [
    'sha256_block',
    'sha256',
    'tf_init',
    'tf_encrypt',
    'tf_decrypt',
    'cbc_encrypt',
    'cbc_decrypt',
    'crack_kernel',
])
def test_kernel_source_functions_present(function: str) -> None:
    assert function in kernel_source()
