"""
LZHUF (``LHUF``/``HUFF``) codec placeholder for the Midway/Probe archive format.

.. warning::

   This codec is **not implemented**. The original scripts did not implement it either: they
   appended a vendored ``unpacker/`` directory to :py:data:`sys.path` and imported
   ``modules.module_Midway.HUFF`` from the Zoinkity *Midwaydec* tree. That directory is absent
   this repository, so those scripts fail at import time or on the first ``LHUF`` entry. Rather
   than guess at the codec and emit plausible-looking rubbish, every call site here catches
   :py:class:`LzhufUnavailableError`, logs a warning, and skips the affected entry. All ``LZSS``
   and ``COPY`` entries, which are the majority, decode normally.

What an implementation needs
----------------------------
The format is LZSS with adaptive Huffman coding, the Okumura/Yoshizaki ``LZHUF`` lineage, with the
ring buffer zero-filled rather than space-filled (the original call site passes ``fill=0``). A
correct decoder requires, in addition to the standard adaptive Huffman tree update:

* the exact ring buffer geometry (size, initial write cursor, minimum match length);
* the position-code tables mapping the next input byte to a code length and the upper bits of a
  match offset.

Those tables were not recoverable from the sources in this repository and must be taken from the
reference implementation or re-derived from the game's own decompressor (``FUN_80057698`` in the
Extreme-G 1 ROM, per the original script's notes) before this module can be completed. Verify any
implementation by round-tripping known archive entries, not by eye.
"""
from __future__ import annotations

__all__ = ('LzhufUnavailableError', 'decompress_lzhuf')


class LzhufUnavailableError(NotImplementedError):
    """Raised when an ``LHUF``/``HUFF`` entry is encountered."""
    def __init__(self, start: int = 0, decompressed_size: int = 0) -> None:
        super().__init__(f'The LZHUF codec is not implemented, so the {decompressed_size} byte '
                         f'entry at 0x{start:X} cannot be decoded. See dade.xg2.lzhuf for what '
                         f'an implementation requires.')


def decompress_lzhuf(data: bytes, start: int, decompressed_size: int) -> bytes:
    """
    Decompress an LZHUF stream.

    Parameters
    ----------
    data : bytes
        Buffer holding the compressed stream.
    start : int
        Offset of the stream within *data*.
    decompressed_size : int
        Number of bytes the stream decodes to.

    Raises
    ------
    LzhufUnavailableError
        Always, until the codec is implemented.
    """
    del data
    raise LzhufUnavailableError(start, decompressed_size)
