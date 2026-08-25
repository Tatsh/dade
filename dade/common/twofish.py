"""
Twofish block cipher and CBC helpers.

The :py:class:`Twofish` block cipher is a pure-Python implementation of the standard cipher (the
standard ``q`` permutations, MDS and Reed-Solomon matrices, and key schedule), verified against the
official Twofish known-answer test vectors (see the test suite). The :py:func:`cbc_encrypt` /
:py:func:`cbc_decrypt` helpers add plain CBC mode (no padding).

References
----------
- Twofish reference implementation used for cross-checking: `TwoFish.py
  <https://github.com/K-Czaplicki/TwoFish/blob/main/TwoFish.py>`_.
"""
from __future__ import annotations

__all__ = ('H_QSEQ', 'MDS', 'MDS_POLYNOMIAL', 'Q0', 'Q1', 'RS', 'RS_POLYNOMIAL', 'Twofish',
           'cbc_decrypt', 'cbc_encrypt')

_MASK32 = 0xFFFFFFFF
_BLOCK_SIZE = 16
_ROUNDS = 16
_RHO = 0x01010101
_KEY_WORDS_256 = 4
_KEY_WORDS_192 = 3
MDS_POLYNOMIAL = 0x169
"""Reduction polynomial for the MDS matrix multiply.

:meta hide-value:
"""
RS_POLYNOMIAL = 0x14D
"""Reduction polynomial for the Reed-Solomon matrix multiply.

:meta hide-value:
"""

Q0 = (0xA9, 0x67, 0xB3, 0xE8, 0x04, 0xFD, 0xA3, 0x76, 0x9A, 0x92, 0x80, 0x78, 0xE4, 0xDD, 0xD1,
      0x38, 0x0D, 0xC6, 0x35, 0x98, 0x18, 0xF7, 0xEC, 0x6C, 0x43, 0x75, 0x37, 0x26, 0xFA, 0x13,
      0x94, 0x48, 0xF2, 0xD0, 0x8B, 0x30, 0x84, 0x54, 0xDF, 0x23, 0x19, 0x5B, 0x3D, 0x59, 0xF3,
      0xAE, 0xA2, 0x82, 0x63, 0x01, 0x83, 0x2E, 0xD9, 0x51, 0x9B, 0x7C, 0xA6, 0xEB, 0xA5, 0xBE,
      0x16, 0x0C, 0xE3, 0x61, 0xC0, 0x8C, 0x3A, 0xF5, 0x73, 0x2C, 0x25, 0x0B, 0xBB, 0x4E, 0x89,
      0x6B, 0x53, 0x6A, 0xB4, 0xF1, 0xE1, 0xE6, 0xBD, 0x45, 0xE2, 0xF4, 0xB6, 0x66, 0xCC, 0x95,
      0x03, 0x56, 0xD4, 0x1C, 0x1E, 0xD7, 0xFB, 0xC3, 0x8E, 0xB5, 0xE9, 0xCF, 0xBF, 0xBA, 0xEA,
      0x77, 0x39, 0xAF, 0x33, 0xC9, 0x62, 0x71, 0x81, 0x79, 0x09, 0xAD, 0x24, 0xCD, 0xF9, 0xD8,
      0xE5, 0xC5, 0xB9, 0x4D, 0x44, 0x08, 0x86, 0xE7, 0xA1, 0x1D, 0xAA, 0xED, 0x06, 0x70, 0xB2,
      0xD2, 0x41, 0x7B, 0xA0, 0x11, 0x31, 0xC2, 0x27, 0x90, 0x20, 0xF6, 0x60, 0xFF, 0x96, 0x5C,
      0xB1, 0xAB, 0x9E, 0x9C, 0x52, 0x1B, 0x5F, 0x93, 0x0A, 0xEF, 0x91, 0x85, 0x49, 0xEE, 0x2D,
      0x4F, 0x8F, 0x3B, 0x47, 0x87, 0x6D, 0x46, 0xD6, 0x3E, 0x69, 0x64, 0x2A, 0xCE, 0xCB, 0x2F,
      0xFC, 0x97, 0x05, 0x7A, 0xAC, 0x7F, 0xD5, 0x1A, 0x4B, 0x0E, 0xA7, 0x5A, 0x28, 0x14, 0x3F,
      0x29, 0x88, 0x3C, 0x4C, 0x02, 0xB8, 0xDA, 0xB0, 0x17, 0x55, 0x1F, 0x8A, 0x7D, 0x57, 0xC7,
      0x8D, 0x74, 0xB7, 0xC4, 0x9F, 0x72, 0x7E, 0x15, 0x22, 0x12, 0x58, 0x07, 0x99, 0x34, 0x6E,
      0x50, 0xDE, 0x68, 0x65, 0xBC, 0xDB, 0xF8, 0xC8, 0xA8, 0x2B, 0x40, 0xDC, 0xFE, 0x32, 0xA4,
      0xCA, 0x10, 0x21, 0xF0, 0xD3, 0x5D, 0x0F, 0x00, 0x6F, 0x9D, 0x36, 0x42, 0x4A, 0x5E, 0xC1,
      0xE0)
"""Twofish ``q0`` byte permutation.

:meta hide-value:
"""
Q1 = (0x75, 0xF3, 0xC6, 0xF4, 0xDB, 0x7B, 0xFB, 0xC8, 0x4A, 0xD3, 0xE6, 0x6B, 0x45, 0x7D, 0xE8,
      0x4B, 0xD6, 0x32, 0xD8, 0xFD, 0x37, 0x71, 0xF1, 0xE1, 0x30, 0x0F, 0xF8, 0x1B, 0x87, 0xFA,
      0x06, 0x3F, 0x5E, 0xBA, 0xAE, 0x5B, 0x8A, 0x00, 0xBC, 0x9D, 0x6D, 0xC1, 0xB1, 0x0E, 0x80,
      0x5D, 0xD2, 0xD5, 0xA0, 0x84, 0x07, 0x14, 0xB5, 0x90, 0x2C, 0xA3, 0xB2, 0x73, 0x4C, 0x54,
      0x92, 0x74, 0x36, 0x51, 0x38, 0xB0, 0xBD, 0x5A, 0xFC, 0x60, 0x62, 0x96, 0x6C, 0x42, 0xF7,
      0x10, 0x7C, 0x28, 0x27, 0x8C, 0x13, 0x95, 0x9C, 0xC7, 0x24, 0x46, 0x3B, 0x70, 0xCA, 0xE3,
      0x85, 0xCB, 0x11, 0xD0, 0x93, 0xB8, 0xA6, 0x83, 0x20, 0xFF, 0x9F, 0x77, 0xC3, 0xCC, 0x03,
      0x6F, 0x08, 0xBF, 0x40, 0xE7, 0x2B, 0xE2, 0x79, 0x0C, 0xAA, 0x82, 0x41, 0x3A, 0xEA, 0xB9,
      0xE4, 0x9A, 0xA4, 0x97, 0x7E, 0xDA, 0x7A, 0x17, 0x66, 0x94, 0xA1, 0x1D, 0x3D, 0xF0, 0xDE,
      0xB3, 0x0B, 0x72, 0xA7, 0x1C, 0xEF, 0xD1, 0x53, 0x3E, 0x8F, 0x33, 0x26, 0x5F, 0xEC, 0x76,
      0x2A, 0x49, 0x81, 0x88, 0xEE, 0x21, 0xC4, 0x1A, 0xEB, 0xD9, 0xC5, 0x39, 0x99, 0xCD, 0xAD,
      0x31, 0x8B, 0x01, 0x18, 0x23, 0xDD, 0x1F, 0x4E, 0x2D, 0xF9, 0x48, 0x4F, 0xF2, 0x65, 0x8E,
      0x78, 0x5C, 0x58, 0x19, 0x8D, 0xE5, 0x98, 0x57, 0x67, 0x7F, 0x05, 0x64, 0xAF, 0x63, 0xB6,
      0xFE, 0xF5, 0xB7, 0x3C, 0xA5, 0xCE, 0xE9, 0x68, 0x44, 0xE0, 0x4D, 0x43, 0x69, 0x29, 0x2E,
      0xAC, 0x15, 0x59, 0xA8, 0x0A, 0x9E, 0x6E, 0x47, 0xDF, 0x34, 0x35, 0x6A, 0xCF, 0xDC, 0x22,
      0xC9, 0xC0, 0x9B, 0x89, 0xD4, 0xED, 0xAB, 0x12, 0xA2, 0x0D, 0x52, 0xBB, 0x02, 0x2F, 0xA9,
      0xD7, 0x61, 0x1E, 0xB4, 0x50, 0x04, 0xF6, 0xC2, 0x16, 0x25, 0x86, 0x56, 0x55, 0x09, 0xBE,
      0x91)
"""Twofish ``q1`` byte permutation.

:meta hide-value:
"""
MDS = (
    (0x01, 0xEF, 0x5B, 0x5B),
    (0x5B, 0xEF, 0xEF, 0x01),
    (0xEF, 0x5B, 0x01, 0xEF),
    (0xEF, 0x01, 0xEF, 0x5B),
)
"""MDS matrix (maximum distance separable) used by the ``h`` function.

:meta hide-value:
"""
RS = (
    (0x01, 0xA4, 0x55, 0x87, 0x5A, 0x58, 0xDB, 0x9E),
    (0xA4, 0x56, 0x82, 0xF3, 0x1E, 0xC6, 0x68, 0xE5),
    (0x02, 0xA1, 0xFC, 0xC1, 0x47, 0xAE, 0x3D, 0x19),
    (0xA4, 0x55, 0x87, 0x5A, 0x58, 0xDB, 0x9E, 0x03),
)
"""Reed-Solomon matrix used to derive the key-dependent S-box words.

:meta hide-value:
"""
H_QSEQ = (
    (Q1, Q1, Q0, Q0, Q1),
    (Q0, Q1, Q1, Q0, Q0),
    (Q0, Q0, Q0, Q1, Q1),
    (Q1, Q0, Q1, Q1, Q0),
)
"""
Per-byte-position ``q`` permutation choices for the ``h`` function.

Each row is ``(256-bit stage, 192-bit stage, inner, middle, outer)`` for one byte position.

:meta hide-value:
"""


def _gf_multiply(a: int, b: int, modulus: int) -> int:
    """
    Multiply two bytes in ``GF(2**8)`` modulo ``modulus``.

    Parameters
    ----------
    a : int
        First operand.
    b : int
        Second operand.
    modulus : int
        Reduction polynomial.

    Returns
    -------
    int
        The product byte.
    """
    result = 0
    for _ in range(8):
        if b & 1:
            result ^= a
        b >>= 1
        high = a & 0x80
        a = (a << 1) & 0xFF
        if high:
            a ^= modulus & 0xFF
    return result


def _matrix_multiply(matrix: tuple[tuple[int, ...], ...], values: tuple[int, ...],
                     modulus: int) -> int:
    """
    Multiply a matrix by a byte vector and pack the four result bytes little-endian.

    Parameters
    ----------
    matrix : tuple[tuple[int, ...], ...]
        A four-row matrix.
    values : tuple[int, ...]
        The byte vector.
    modulus : int
        Reduction polynomial.

    Returns
    -------
    int
        The packed 32-bit word.
    """
    out = 0
    for i, row in enumerate(matrix):
        acc = 0
        for coefficient, value in zip(row, values, strict=True):
            acc ^= _gf_multiply(coefficient, value, modulus)
        out |= acc << (8 * i)
    return out


def _rol(value: int, amount: int) -> int:
    """
    Rotate a 32-bit word left.

    Parameters
    ----------
    value : int
        The word to rotate.
    amount : int
        Number of bits to rotate by.

    Returns
    -------
    int
        The rotated word.
    """
    return ((value << amount) | (value >> (32 - amount))) & _MASK32


def _ror(value: int, amount: int) -> int:
    """
    Rotate a 32-bit word right.

    Parameters
    ----------
    value : int
        The word to rotate.
    amount : int
        Number of bits to rotate by.

    Returns
    -------
    int
        The rotated word.
    """
    return ((value >> amount) | (value << (32 - amount))) & _MASK32


class Twofish:
    """
    The Twofish block cipher (128-bit blocks; 128-, 192-, or 256-bit keys).

    Parameters
    ----------
    key : bytes
        A 16-, 24-, or 32-byte key.

    Raises
    ------
    ValueError
        If ``key`` is not a supported length.
    """
    def __init__(self, key: bytes) -> None:
        if len(key) not in {16, 24, 32}:
            msg = f'Twofish key must be 16, 24, or 32 bytes, got {len(key)}.'
            raise ValueError(msg)
        k = len(key) // 8
        words = [int.from_bytes(key[4 * i:4 * i + 4], 'little') for i in range(2 * k)]
        self._k = k
        self._me = words[0::2]
        self._mo = words[1::2]
        self._sbox_keys = [
            _matrix_multiply(RS, tuple(key[8 * i:8 * i + 8]), RS_POLYNOMIAL)
            for i in range(k - 1, -1, -1)
        ]
        self._subkeys = self._expand_subkeys()
        self._gbox = self._build_gbox()

    def encrypt(self, block: bytes) -> bytes:
        """
        Encrypt a single 16-byte block.

        Parameters
        ----------
        block : bytes
            The 16-byte plaintext block.

        Returns
        -------
        bytes
            The 16-byte ciphertext block.

        Raises
        ------
        ValueError
            If ``block`` is not 16 bytes.
        """
        if len(block) != _BLOCK_SIZE:
            msg = f'Twofish block must be 16 bytes, got {len(block)}.'
            raise ValueError(msg)
        r = [int.from_bytes(block[4 * i:4 * i + 4], 'little') ^ self._subkeys[i] for i in range(4)]
        for rnd in range(_ROUNDS):
            t0 = self._g(r[0])
            t1 = self._g(_rol(r[1], 8))
            f0 = (t0 + t1 + self._subkeys[2 * rnd + 8]) & _MASK32
            f1 = (t0 + 2 * t1 + self._subkeys[2 * rnd + 9]) & _MASK32
            r = [_ror(r[2] ^ f0, 1), _rol(r[3], 1) ^ f1, r[0], r[1]]
        r = [r[2], r[3], r[0], r[1]]
        return b''.join((r[i] ^ self._subkeys[i + 4]).to_bytes(4, 'little') for i in range(4))

    def decrypt(self, block: bytes) -> bytes:
        """
        Decrypt a single 16-byte block.

        Parameters
        ----------
        block : bytes
            The 16-byte ciphertext block.

        Returns
        -------
        bytes
            The 16-byte plaintext block.

        Raises
        ------
        ValueError
            If ``block`` is not 16 bytes.
        """
        if len(block) != _BLOCK_SIZE:
            msg = f'Twofish block must be 16 bytes, got {len(block)}.'
            raise ValueError(msg)
        r = [
            int.from_bytes(block[4 * i:4 * i + 4], 'little') ^ self._subkeys[i + 4]
            for i in range(4)
        ]
        r = [r[2], r[3], r[0], r[1]]
        for rnd in range(_ROUNDS - 1, -1, -1):
            t0 = self._g(r[2])
            t1 = self._g(_rol(r[3], 8))
            f0 = (t0 + t1 + self._subkeys[2 * rnd + 8]) & _MASK32
            f1 = (t0 + 2 * t1 + self._subkeys[2 * rnd + 9]) & _MASK32
            r = [r[2], r[3], _rol(r[0], 1) ^ f0, _ror(r[1] ^ f1, 1)]
        return b''.join((r[i] ^ self._subkeys[i]).to_bytes(4, 'little') for i in range(4))

    def _expand_subkeys(self) -> list[int]:
        """
        Compute the 40 round subkeys.

        Returns
        -------
        list[int]
            The subkey words ``K0`` through ``K39``.
        """
        subkeys: list[int] = []
        for i in range(20):
            a = self._h((2 * i) * _RHO, self._me)
            b = _rol(self._h((2 * i + 1) * _RHO, self._mo), 8)
            subkeys.extend(((a + b) & _MASK32, _rol((a + 2 * b) & _MASK32, 9)))
        return subkeys

    def _g(self, word: int) -> int:
        """
        Apply the key-dependent S-box and MDS mix to a word using the precomputed g-boxes.

        Parameters
        ----------
        word : int
            The input word.

        Returns
        -------
        int
            The mixed word.
        """
        box = self._gbox
        return (box[0][word & 0xFF] ^ box[1][(word >> 8) & 0xFF] ^ box[2][(word >> 16) & 0xFF]
                ^ box[3][(word >> 24) & 0xFF])

    def _build_gbox(self) -> tuple[tuple[int, ...], ...]:
        """
        Precompute the four key-dependent S-box-and-MDS tables used by :py:meth:`_g`.

        Each table maps an input byte at one position to its full 32-bit contribution, folding the
        ``q`` permutations, the S-box key words, and the MDS matrix column into a single lookup.

        Returns
        -------
        tuple[tuple[int, ...], ...]
            Four tables of 256 words each, one per byte position.
        """
        tables: list[tuple[int, ...]] = []
        for position in range(4):
            column = []
            for value in range(256):
                vector = [0, 0, 0, 0]
                vector[position] = self._permute(position, value, self._sbox_keys)
                column.append(_matrix_multiply(MDS, tuple(vector), MDS_POLYNOMIAL))
            tables.append(tuple(column))
        return tuple(tables)

    def _permute(self, position: int, byte: int, key_words: list[int]) -> int:
        """
        Apply the ``h`` byte-permutation chain for one byte position.

        Parameters
        ----------
        position : int
            Byte position (0-3).
        byte : int
            The input byte.
        key_words : list[int]
            The key words that select the permutation stages.

        Returns
        -------
        int
            The permuted byte.
        """
        stage256, stage192, inner, middle, outer = H_QSEQ[position]
        shift = 8 * position
        result = byte
        if self._k == _KEY_WORDS_256:
            result = stage256[result] ^ ((key_words[3] >> shift) & 0xFF)
        if self._k >= _KEY_WORDS_192:
            result = stage192[result] ^ ((key_words[2] >> shift) & 0xFF)
        result = inner[result] ^ ((key_words[1] >> shift) & 0xFF)
        result = middle[result] ^ ((key_words[0] >> shift) & 0xFF)
        return outer[result]

    def _h(self, word: int, key_words: list[int]) -> int:
        """
        Apply the Twofish ``h`` function: byte permutations keyed by ``key_words``, then MDS.

        Parameters
        ----------
        word : int
            The 32-bit input.
        key_words : list[int]
            The key words that select the permutation stages.

        Returns
        -------
        int
            The 32-bit output.
        """
        y = tuple(self._permute(i, (word >> (8 * i)) & 0xFF, key_words) for i in range(4))
        return _matrix_multiply(MDS, y, MDS_POLYNOMIAL)


def cbc_encrypt(cipher: Twofish, iv: bytes, data: bytes) -> bytes:
    """
    Encrypt ``data`` with ``cipher`` in CBC mode.

    Parameters
    ----------
    cipher : Twofish
        The block cipher.
    iv : bytes
        16-byte initialisation vector.
    data : bytes
        Plaintext whose length is a multiple of 16.

    Returns
    -------
    bytes
        The ciphertext.

    Raises
    ------
    ValueError
        If ``data`` is not a whole number of blocks.
    """
    if len(data) % _BLOCK_SIZE:
        msg = 'CBC data length must be a multiple of 16 bytes.'
        raise ValueError(msg)
    previous = iv
    out = bytearray()
    for offset in range(0, len(data), _BLOCK_SIZE):
        block = bytes(
            a ^ b for a, b in zip(data[offset:offset + _BLOCK_SIZE], previous, strict=True))
        previous = cipher.encrypt(block)
        out += previous
    return bytes(out)


def cbc_decrypt(cipher: Twofish, iv: bytes, data: bytes) -> bytes:
    """
    Decrypt ``data`` with ``cipher`` in CBC mode.

    Parameters
    ----------
    cipher : Twofish
        The block cipher.
    iv : bytes
        16-byte initialisation vector.
    data : bytes
        Ciphertext whose length is a multiple of 16.

    Returns
    -------
    bytes
        The plaintext.

    Raises
    ------
    ValueError
        If ``data`` is not a whole number of blocks.
    """
    if len(data) % _BLOCK_SIZE:
        msg = 'CBC data length must be a multiple of 16 bytes.'
        raise ValueError(msg)
    previous = iv
    out = bytearray()
    for offset in range(0, len(data), _BLOCK_SIZE):
        block = data[offset:offset + _BLOCK_SIZE]
        out += bytes(a ^ b for a, b in zip(cipher.decrypt(block), previous, strict=True))
        previous = block
    return bytes(out)
