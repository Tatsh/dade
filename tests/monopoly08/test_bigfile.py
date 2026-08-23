from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from destin.monopoly08.bigfile import BigEntry, iter_big_payloads, parse_toc, unpack

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

_ENTRIES: tuple[tuple[str, bytes],
                ...] = (('sound/one.snr', b'first'), ('art\\two.xmap', b'second-payload'))


def test_parse_toc(make_big: Callable[[Sequence[tuple[str, bytes]]], bytes],
                   tmp_path: Path) -> None:
    archive = tmp_path / 'audio.big'
    archive.write_bytes(make_big(_ENTRIES))
    entries, real = parse_toc(archive)
    assert real == archive.stat().st_size
    assert [e.name for e in entries] == ['sound/one.snr', 'art\\two.xmap']
    assert entries[0] == BigEntry(entries[0].offset, 5, 'sound/one.snr')


def test_parse_toc_rejects_bad_magic(tmp_path: Path) -> None:
    archive = tmp_path / 'audio.big'
    archive.write_bytes(b'NOPE' + b'\x00' * 12)
    with pytest.raises(ValueError, match='not a BIGF archive'):
        parse_toc(archive)


def test_unpack(make_big: Callable[[Sequence[tuple[str, bytes]]], bytes], tmp_path: Path) -> None:
    archive = tmp_path / 'audio.big'
    archive.write_bytes(make_big(_ENTRIES))
    count, written = unpack(archive, tmp_path / 'out')
    base = tmp_path / 'out' / 'audio'
    assert count == 2
    assert written == len(b'first') + len(b'second-payload')
    assert (base / 'sound' / 'one.snr').read_bytes() == b'first'
    assert (base / 'art' / 'two.xmap').read_bytes() == b'second-payload'
    assert (base / '_manifest.tsv').read_text().startswith('name\toffset\tsize\n')


def test_unpack_rejects_a_range_past_the_end(make_big: Callable[[Sequence[tuple[str, bytes]]],
                                                                bytes], tmp_path: Path) -> None:
    archive = tmp_path / 'audio.big'
    archive.write_bytes(make_big(_ENTRIES)[:-4])
    with pytest.raises(ValueError, match='exceeds file'):
        unpack(archive, tmp_path / 'out')


def test_unpack_rejects_an_escaping_name(make_big: Callable[[Sequence[tuple[str, bytes]]], bytes],
                                         tmp_path: Path) -> None:
    archive = tmp_path / 'audio.big'
    archive.write_bytes(make_big((('../escape.bin', b'nope'),)))
    with pytest.raises(ValueError, match='unsafe path escapes base'):
        unpack(archive, tmp_path / 'out')


def test_unpack_detects_a_short_read(make_big: Callable[[Sequence[tuple[str, bytes]]], bytes],
                                     make_oversized_path: Callable[[Path, int],
                                                                   Path], tmp_path: Path) -> None:
    archive = tmp_path / 'audio.big'
    raw = make_big((('one.bin', b'0123456789'),))
    archive.write_bytes(raw[:-6])  # Truncate the payload but keep the declared size.
    with pytest.raises(EOFError, match='short read'):
        unpack(make_oversized_path(archive, len(raw)), tmp_path / 'out')


def test_iter_big_payloads(make_big: Callable[[Sequence[tuple[str, bytes]]], bytes],
                           tmp_path: Path) -> None:
    archive = tmp_path / 'audio.big'
    archive.write_bytes(make_big(_ENTRIES))
    assert list(iter_big_payloads(archive)) == [('sound/one.snr', b'first'),
                                                ('art\\two.xmap', b'second-payload')]
