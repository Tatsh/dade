"""
Shared kernel-source templating for the GPU backends.

Both the CUDA and OpenCL backends compile the same :file:`kernel.cl`, which bridges the two dialects
with an ``#ifdef __OPENCL_VERSION__`` prelude. This module fills its placeholders with the Twofish
tables and sizes from :py:mod:`~destin.bitrock.crypto`, so the device and CPU cannot diverge on the
lookup tables.
"""
from __future__ import annotations

from functools import cache
from importlib import resources
from typing import TYPE_CHECKING

from destin.common.twofish import H_QSEQ, MDS, MDS_POLYNOMIAL, Q0, Q1, RS, RS_POLYNOMIAL

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ('MAX_IV_POOL', 'MAX_PASSWORD', 'kernel_source')

_PACKAGE = 'destin.bitrock.password_cracker'
"""Package holding :file:`kernel.cl`, resolved by :py:func:`importlib.resources.files`.

:meta hide-value:
"""

MAX_PASSWORD = 64
"""
Longest candidate password the kernel accepts, in bytes.

:meta hide-value:
"""
MAX_IV_POOL = 8192
"""
Largest encrypted IV pool the kernel handles, in bytes (per-thread scratch).

:meta hide-value:
"""


def _c_array(name: str, values: Iterable[int]) -> str:
    """
    Render a flat constant unsigned-char array initialiser for the kernel prelude.

    ``CONSTANT`` and ``u8`` are macros the kernel defines per dialect.

    Parameters
    ----------
    name : str
        The array name.
    values : Iterable[int]
        The byte values.

    Returns
    -------
    str
        A declaration line.
    """
    body = ', '.join(str(v) for v in values)
    return f'CONSTANT u8 {name}[] = {{{body}}};'


@cache
def kernel_source() -> str:
    """
    Read :file:`kernel.cl` and substitute the Twofish tables and sizes.

    Returns
    -------
    str
        The complete kernel source, ready for either back end to compile.
    """
    qseq = (1 if table is Q1 else 0 for row in H_QSEQ for table in row)
    tables = '\n'.join((
        _c_array('QT', (*Q0, *Q1)),
        _c_array('QSEQ', qseq),
        _c_array('MDS', (c for row in MDS for c in row)),
        _c_array('RS', (c for row in RS for c in row)),
    ))
    template = resources.files(_PACKAGE).joinpath('kernel.cl').read_text(encoding='utf-8')
    return template.replace('/*TABLES*/', tables).replace(
        '/*MDS_POLY*/', str(MDS_POLYNOMIAL)).replace('/*RS_POLY*/', str(RS_POLYNOMIAL)).replace(
            '/*MAX_PASSWORD*/', str(MAX_PASSWORD)).replace('/*MAX_IV_POOL*/', str(MAX_IV_POOL))
