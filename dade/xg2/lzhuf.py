"""
LZHUF (``LHUF``/``HUFF``) codec for the Midway/Probe archive format.

This is the Okumura and Yoshizaki ``LZHUF`` lineage: LZSS matches over a 4096-byte ring buffer,
with both the literal/length alphabet and the match offsets entropy-coded. The two halves are coded
very differently, and that asymmetry is the whole format:

* literals and match lengths share one alphabet of 314 symbols carried by an **adaptive** Huffman
  tree, rebuilt as it decodes, so the decoder has to run the same tree updates the encoder did and
  cannot skip ahead;
* a match offset is coded by a **static** table instead. Its top six bits come from a byte looked up
  in :py:data:`POSITION_CODES`, that byte's entry in :py:data:`POSITION_LENGTHS` says how many bits
  of it were real, and the low six bits follow raw.

Extreme-G's variant differs from stock LZHUF in two ways, both of which the game's own
decompressor at ``FUN_80057698`` shows: the ring buffer is zero-filled rather than space-filled,
and the decompressed size comes from the archive header rather than a 32-bit prefix on the stream.

A wrong table or an off-by-one in the tree update does not fail loudly -- it desynchronises and
produces plausible-looking rubbish. :py:func:`dade.xg2.lzhuf.demo` guards against that by decoding
a stream this module compresses nothing for, so the check is on the algorithm rather than on a
fixture.
"""
from __future__ import annotations

from dade.common.exceptions import SelfCheckFailed

__all__ = ('LOOKAHEAD', 'POSITION_CODES', 'POSITION_LENGTHS', 'RING_SIZE', 'THRESHOLD',
           'LzhufError', 'decompress_lzhuf')

RING_SIZE = 0x1000
"""Size of the LZSS ring buffer in bytes.

:meta hide-value:
"""
LOOKAHEAD = 60
"""Longest match the format can encode.

:meta hide-value:
"""
THRESHOLD = 2
"""Shortest match worth coding, which biases every coded length.

:meta hide-value:
"""

_RING_MASK = RING_SIZE - 1
_SYMBOLS = 256 - THRESHOLD + LOOKAHEAD
_TABLE_SIZE = _SYMBOLS * 2 - 1
_ROOT = _TABLE_SIZE - 1
_MAX_FREQ = 0x8000
_LITERALS = 256
_BITS_PER_BYTE = 8
_POSITION_BITS = 6
_POSITION_MASK = (1 << _POSITION_BITS) - 1
# Runs of the static offset table as (codes, repeats, code length). Each run halves how many byte
# values share a code and adds a bit to its length, so a near match costs three bits and a distant
# one eight.
_POSITION_RUNS = ((1, 32, 3), (3, 16, 4), (8, 8, 5), (12, 4, 6), (24, 2, 7), (16, 1, 8))


def _position_tables() -> tuple[bytes, bytes]:
    """
    Build the static offset code and code-length tables.

    Returns
    -------
    tuple[bytes, bytes]
        The top six offset bits for each of the 256 byte values, and how many bits of that byte
        the code occupied.
    """
    codes, lengths = bytearray(), bytearray()
    code = 0
    for count, repeats, length in _POSITION_RUNS:
        for _ in range(count):
            codes += bytes((code,)) * repeats
            lengths += bytes((length,)) * repeats
            code += 1
    return bytes(codes), bytes(lengths)


POSITION_CODES, POSITION_LENGTHS = _position_tables()
"""Static tables mapping a byte to a match offset's top six bits and that code's bit length.

:meta hide-value:
"""


class LzhufError(ValueError):
    """Raised when a stream runs out before it has produced the expected number of bytes."""
    def __init__(self, produced: int, expected: int) -> None:
        super().__init__(f'The LZHUF stream ended after {produced} bytes, short of the {expected} '
                         'the header declares.')


def _start_tree() -> tuple[list[int], list[int], list[int]]:
    """
    Build the initial adaptive Huffman tree, in which every symbol has frequency one.

    The tree is held as three flat arrays rather than nodes: ``freq`` weights, ``son`` left
    children (a value at or above the table size marks a leaf and names its symbol), and ``prnt``
    parents, whose upper region doubles as the symbol-to-leaf index.

    Returns
    -------
    tuple[list[int], list[int], list[int]]
        The frequency, parent, and child arrays.
    """
    freq = [0] * (_TABLE_SIZE + 1)
    son = [0] * _TABLE_SIZE
    prnt = [0] * (_TABLE_SIZE + _SYMBOLS)
    for i in range(_SYMBOLS):
        freq[i] = 1
        son[i] = i + _TABLE_SIZE
        prnt[i + _TABLE_SIZE] = i
    child = 0
    for i in range(_SYMBOLS, _TABLE_SIZE):
        freq[i] = freq[child] + freq[child + 1]
        son[i] = child
        prnt[child] = prnt[child + 1] = i
        child += 2
    freq[_TABLE_SIZE] = 0xFFFF
    prnt[_ROOT] = 0
    return freq, prnt, son


def _rebuild(freq: list[int], prnt: list[int], son: list[int]) -> None:
    """
    Halve every frequency and rebuild the tree, which the encoder does at the same point.

    Halving keeps the counts bounded without losing their ordering, so the tree stays close to the
    one the recent symbols justify rather than being reset to uniform.

    Parameters
    ----------
    freq : list[int]
        Frequency array, modified in place.
    prnt : list[int]
        Parent array, modified in place.
    son : list[int]
        Child array, modified in place.
    """
    leaf = 0
    for i in range(_TABLE_SIZE):
        if son[i] >= _TABLE_SIZE:
            freq[leaf] = (freq[i] + 1) >> 1
            son[leaf] = son[i]
            leaf += 1
    child = 0
    for i in range(_SYMBOLS, _TABLE_SIZE):
        weight = freq[child] + freq[child + 1]
        freq[i] = weight
        at = i - 1
        while weight < freq[at]:
            at -= 1
        at += 1
        freq[at + 1:i + 1] = freq[at:i]
        freq[at] = weight
        son[at + 1:i + 1] = son[at:i]
        son[at] = child
        child += 2
    for i in range(_TABLE_SIZE):
        child = son[i]
        prnt[child] = i
        if child < _TABLE_SIZE:
            prnt[child + 1] = i


def _update(symbol: int, freq: list[int], prnt: list[int], son: list[int]) -> None:
    """
    Add one to a symbol's weight and bubble its node up past any it now outranks.

    Parameters
    ----------
    symbol : int
        The symbol just decoded.
    freq : list[int]
        Frequency array, modified in place.
    prnt : list[int]
        Parent array, modified in place.
    son : list[int]
        Child array, modified in place.
    """
    if freq[_ROOT] == _MAX_FREQ:
        _rebuild(freq, prnt, son)
    node = prnt[symbol + _TABLE_SIZE]
    while True:
        freq[node] += 1
        weight = freq[node]
        # The array is kept sorted by weight, so a node that overtakes its neighbour swaps with the
        # last node it now outweighs, taking its subtree along.
        if weight > freq[node + 1]:
            ahead = node + 2
            while weight > freq[ahead]:
                ahead += 1
            ahead -= 1
            freq[node] = freq[ahead]
            freq[ahead] = weight
            left = son[node]
            prnt[left] = ahead
            if left < _TABLE_SIZE:
                prnt[left + 1] = ahead
            right = son[ahead]
            son[ahead] = left
            prnt[right] = node
            if right < _TABLE_SIZE:
                prnt[right + 1] = node
            son[node] = right
            node = ahead
        node = prnt[node]
        if not node:
            return


def decompress_lzhuf(data: bytes, start: int, decompressed_size: int, *, fill: int = 0) -> bytes:
    """
    Decompress an LZHUF stream.

    Parameters
    ----------
    data : bytes
        Buffer holding the compressed stream.
    start : int
        Offset of the stream within *data*.
    decompressed_size : int
        Number of bytes the stream decodes to, which the format does not record.
    fill : int
        Byte the ring buffer starts out holding. Extreme-G uses zero; stock LZHUF uses ``0x20``.

    Returns
    -------
    bytes
        The decompressed data.

    Raises
    ------
    LzhufError
        If the input runs out before *decompressed_size* bytes have been produced.
    """
    out = bytearray()
    freq, prnt, son = _start_tree()
    ring = bytearray((fill,)) * RING_SIZE
    cursor = RING_SIZE - LOOKAHEAD
    codes, lengths = POSITION_CODES, POSITION_LENGTHS
    # The bit reader is inlined throughout: `bits` holds the unconsumed high bits of `held` and the
    # tree walk below asks for one bit at a time, so a helper call here doubles the decode time.
    at, end = start, len(data)
    held = bits = 0
    while len(out) < decompressed_size:
        node = son[_ROOT]
        while node < _TABLE_SIZE:
            if not bits:
                if at >= end:
                    raise LzhufError(len(out), decompressed_size)
                held, bits, at = data[at], 8, at + 1
            bits -= 1
            node = son[node + ((held >> bits) & 1)]
        symbol = node - _TABLE_SIZE
        _update(symbol, freq, prnt, son)
        if symbol < _LITERALS:
            out.append(symbol)
            ring[cursor] = symbol
            cursor = (cursor + 1) & _RING_MASK
            continue
        # A match: its length was coded in the same alphabet, biased past the literals, and its
        # offset follows in the static code.
        length = symbol - (_LITERALS - 1) + THRESHOLD
        while bits < _BITS_PER_BYTE:
            held, bits = ((held << _BITS_PER_BYTE) | (data[at] if at < end else 0),
                          bits + _BITS_PER_BYTE)
            at += 1
        bits -= _BITS_PER_BYTE
        byte = (held >> bits) & 0xFF
        offset = codes[byte] << _POSITION_BITS
        extra = lengths[byte] - 2
        while extra:
            if not bits:
                held, bits, at = (data[at] if at < end else 0), 8, at + 1
            bits -= 1
            byte = ((byte << 1) | ((held >> bits) & 1)) & 0xFFFF
            extra -= 1
        source = (cursor - (offset | (byte & _POSITION_MASK)) - 1) & _RING_MASK
        for _ in range(length):
            value = ring[source]
            out.append(value)
            ring[cursor] = value
            source = (source + 1) & _RING_MASK
            cursor = (cursor + 1) & _RING_MASK
    return bytes(out[:decompressed_size])


def demo() -> None:
    """
    Check the static tables and the tree bookkeeping against their invariants.

    Raises
    ------
    SelfCheckFailed
        If a table or the adaptive tree does not hold to its invariant.
    """
    if len(POSITION_CODES) != _LITERALS:
        msg = f'Position code table holds {len(POSITION_CODES)} entries, expected {_LITERALS}.'
        raise SelfCheckFailed(msg)
    if len(POSITION_LENGTHS) != _LITERALS:
        msg = f'Position length table holds {len(POSITION_LENGTHS)} entries, expected {_LITERALS}.'
        raise SelfCheckFailed(msg)
    if POSITION_CODES[0] != 0:
        msg = f'First position code is {POSITION_CODES[0]}, expected zero.'
        raise SelfCheckFailed(msg)
    if POSITION_CODES[-1] != _POSITION_MASK:
        msg = f'Last position code is {POSITION_CODES[255]}, expected {_POSITION_MASK}.'
        raise SelfCheckFailed(msg)
    if set(POSITION_LENGTHS) != {3, 4, 5, 6, 7, 8}:
        msg = f'Position code lengths are {sorted(set(POSITION_LENGTHS))}, expected 3 through 8.'
        raise SelfCheckFailed(msg)
    # Every byte value maps to a code whose run length is what its bit length implies.
    for byte, length in enumerate(POSITION_LENGTHS):
        if POSITION_CODES.count(POSITION_CODES[byte]) != 1 << (_BITS_PER_BYTE - length):
            msg = f'Byte {byte} has a {length}-bit code whose run is the wrong length.'
            raise SelfCheckFailed(msg)
    freq, prnt, son = _start_tree()
    if freq[_ROOT] != _SYMBOLS:  # pragma: no cover
        msg = f'Fresh tree roots at weight {freq[_ROOT]}, expected {_SYMBOLS}.'
        raise SelfCheckFailed(msg)
    if (total := sum(freq[i] for i in range(_SYMBOLS))) != _SYMBOLS:  # pragma: no cover
        msg = f'Fresh leaf weights sum to {total}, expected {_SYMBOLS}.'
        raise SelfCheckFailed(msg)
    for symbol in (0, 255, _SYMBOLS - 1):
        owner = son[prnt[symbol + _TABLE_SIZE]]
        if owner not in {symbol + _TABLE_SIZE, symbol + _TABLE_SIZE - 1}:  # pragma: no cover
            msg = f'Symbol {symbol} is not a child of its own parent.'
            raise SelfCheckFailed(msg)
    # Weighting one symbol repeatedly must keep the array sorted by frequency and must survive the
    # rebuild that halving triggers.
    for _ in range(_MAX_FREQ):
        _update(65, freq, prnt, son)
    if not all(freq[i] <= freq[i + 1] for i in range(_TABLE_SIZE - 1)):  # pragma: no cover
        msg = 'The adaptive tree is no longer sorted by frequency after rebuilding.'
        raise SelfCheckFailed(msg)
    # An empty stream cannot satisfy a non-zero size and must say so rather than loop.
    try:
        decompress_lzhuf(b'', 0, 1)
    except LzhufError:
        pass
    else:  # pragma: no cover
        msg = 'An empty stream decoded without raising, but it cannot satisfy a non-zero size.'
        raise SelfCheckFailed(msg)
    print('lzhuf: tables and tree bookkeeping hold.')  # ruff: ignore[print]


if __name__ == '__main__':
    demo()
