"""
Extreme-G asset toolkit (Probe Entertainment / Acclaim).

``xg2`` unpacks and converts the assets of Extreme-G (N64) and Extreme-G XG2 (N64 and Windows).
The two games share their container, codec, texture, and audio formats; the PC port differs only
in byte order, so one implementation serves both platforms throughout.

Public surface (all sans-I/O unless noted - they take ``bytes`` and return data structures):

- :func:`destin.common.lz.decompress_lzss0` - the Okumura LZSS variant both games use.
- :func:`destin.xg2.archive.parse_archive` / :func:`destin.xg2.archive.decode_entry` - the
  ``XG2Arch`` container, in either byte order.
- :func:`destin.xg2.mfs.iter_files` - the Extreme-G 1 ``mfs`` archive, including base calibration.
- :func:`destin.xg2.models.collect_textures` - every texture in a model blob, whatever its shape.
- :func:`destin.xg2.albank.parse_bank` - an ``ALBankFile`` bank with its sounds decoded to PCM.
- :func:`destin.xg2.alcseq.to_midi` - an ``ALCSeq`` sequence as a standard MIDI file.
- :func:`destin.xg2.soundfont.build_sf2` - a SoundFont from decoded banks.
- :func:`destin.xg2.extract_xg1.run`, :func:`destin.xg2.extract_xg2.run`, and
  :func:`destin.xg2.extract_pc.run` - the three extraction pipelines, which do write to disc.

The ``LHUF`` codec is not implemented; see :mod:`destin.xg2.lzhuf` for what that would need and
what is skipped in the meantime.
"""
