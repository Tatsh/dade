from __future__ import annotations

from typing import TYPE_CHECKING, cast
import gzip
import io
import struct
import zlib

from typing_extensions import override
import pytest

from dade.harmonix import ark

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

_ENTRIES = (('gen/a.txt', b'AAA'), ('b.bin', b'BB'))
_REPORTED_SIZE = 1 << 20
"""The inflated size a truncated archive claims to have.

:meta hide-value:
"""


class _TruncatedStream(io.BytesIO):
    """A stream that reports a far larger size than the bytes it actually holds."""
    @override
    def seek(self, pos: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_END:
            return _REPORTED_SIZE
        return super().seek(pos, whence)


class _TruncatedArk:
    """An archive stand-in whose stream ends long before its records say it should."""
    def __init__(self, data: bytes) -> None:
        self._data = data

    def open(self, mode: str) -> io.BytesIO:
        """
        Open the truncated archive for reading.

        Parameters
        ----------
        mode : str
            The open mode (only ``'rb'`` is used).

        Returns
        -------
        io.BytesIO
            The truncated stream.
        """
        assert mode == 'rb'
        return _TruncatedStream(self._data)


def _amp_header(records: bytes, pool: bytes, buckets: Sequence[int], *, version: int = 2) -> bytes:
    return (struct.pack('<II', version,
                        len(records) // 20) + records + struct.pack('<I', len(pool)) + pool +
            struct.pack('<I', len(buckets)) + struct.pack(f'<{len(buckets)}I', *buckets))


def test_parse_directory_amplitude(make_amp_ark: Callable[..., bytes]) -> None:
    directory = ark.parse_directory(make_amp_ark(_ENTRIES))
    assert directory.version == 2
    assert [entry.path for entry in directory.entries] == ['gen/a.txt', 'b.bin']
    assert directory.entries[0].size == 3
    assert directory.n_buckets == 3


def test_parse_directory_frequency(make_freq_ark: Callable[..., bytes]) -> None:
    directory = ark.parse_directory(
        make_freq_ark((('metagame/arena/a.txt', b'AAA'), ('b.bin', b'BB'))))
    assert directory.version == 2
    assert [entry.path for entry in directory.entries] == ['metagame/arena/a.txt', 'b.bin']
    assert directory.entries[1].offset == directory.dir_end + 3


def test_parse_directory_forces_amplitude_layout(make_amp_ark: Callable[..., bytes]) -> None:
    # An Amplitude archive has no magic; forcing 'amplitude' parses it just like auto-detect.
    data = make_amp_ark(_ENTRIES)
    forced = ark.parse_directory(data, layout='amplitude')
    assert [entry.path for entry in forced.entries] == ['gen/a.txt', 'b.bin']
    assert forced == ark.parse_directory(data, layout=None)


def test_parse_directory_forces_frequency_layout(make_freq_ark: Callable[..., bytes]) -> None:
    data = make_freq_ark(_ENTRIES)
    forced = ark.parse_directory(data, layout='frequency')
    assert [entry.path for entry in forced.entries] == ['gen/a.txt', 'b.bin']
    assert forced == ark.parse_directory(data, layout=None)


def test_extract_forces_layout(make_amp_ark: Callable[..., bytes], tmp_path: Path) -> None:
    archive = tmp_path / 'MAIN.ARK'
    archive.write_bytes(make_amp_ark(_ENTRIES))
    stats = ark.extract(archive, tmp_path / 'out', layout='amplitude')
    assert stats.written == 2
    assert (tmp_path / 'out' / 'gen' / 'a.txt').read_bytes() == b'AAA'


def test_parse_directory_amplitude_bad_version() -> None:
    with pytest.raises(ValueError, match='Unsupported ARK version 3'):
        ark.parse_directory(_amp_header(b'', b'', (), version=3))


def test_parse_directory_frequency_bad_version() -> None:
    data = bytearray(0x100)
    struct.pack_into('<10I', data, 0, 0x004B5241, 9, 0x100, 0, 0x100, 0, 0x100, 0, 0x800, 0x800)
    with pytest.raises(ValueError, match='Unsupported FreQuency ARK version 9'):
        ark.parse_directory(bytes(data))


def test_parse_directory_bucket_out_of_range() -> None:
    record = struct.pack('<5I', 0, 99, 0xFFFFFFFF, 0, 0)
    with pytest.raises(ValueError, match='Bucket index 99'):
        ark.parse_directory(_amp_header(record, b'', ()))


def test_parse_directory_name_offset_out_of_pool() -> None:
    record = struct.pack('<5I', 0, 0, 0xFFFFFFFF, 0, 0)
    with pytest.raises(ValueError, match='Name offset 0x63 out of pool'):
        ark.parse_directory(_amp_header(record, b'ab\0\0', (99,)))


def test_parse_directory_frequency_dir_index_out_of_range(
        make_freq_ark: Callable[..., bytes]) -> None:
    data = bytearray(make_freq_ark((('a.txt', b'AAA'),)))
    struct.pack_into('<I', data, 0x100 + 8, (0 << 16) | 5)  # packed: dir index 5, but nDirs is 1.
    with pytest.raises(ValueError, match='Dir index 5 >= nDirs 1'):
        ark.parse_directory(bytes(data))


def test_extract_writes_entries(make_amp_ark: Callable[..., bytes], tmp_path: Path) -> None:
    archive = tmp_path / 'MAIN.ARK'
    archive.write_bytes(make_amp_ark(_ENTRIES))
    stats = ark.extract(archive, tmp_path / 'out')
    assert stats == (2, 0, 0, 0, 5, 5)
    assert (tmp_path / 'out' / 'gen' / 'a.txt').read_bytes() == b'AAA'
    assert (tmp_path / 'out' / 'b.bin').read_bytes() == b'BB'


def test_extract_frequency(make_freq_ark: Callable[..., bytes], tmp_path: Path) -> None:
    archive = tmp_path / 'ROOT.ARK'
    archive.write_bytes(make_freq_ark(_ENTRIES))
    stats = ark.extract(archive, tmp_path / 'out')
    assert stats.written == 2
    assert (tmp_path / 'out' / 'gen' / 'a.txt').read_bytes() == b'AAA'


def test_extract_sanitises_paths(make_amp_ark: Callable[..., bytes], tmp_path: Path) -> None:
    archive = tmp_path / 'MAIN.ARK'
    archive.write_bytes(make_amp_ark((('/../evil name.txt', b'X'),)))
    ark.extract(archive, tmp_path / 'out')
    assert (tmp_path / 'out' / 'evil_name.txt').read_bytes() == b'X'


def test_extract_gunzips(make_amp_ark: Callable[..., bytes], tmp_path: Path) -> None:
    archive = tmp_path / 'MAIN.ARK'
    archive.write_bytes(make_amp_ark((('gen/big.txt.gz', gzip.compress(b'hello' * 100)),)))
    stats = ark.extract(archive, tmp_path / 'out')
    assert stats.gunzipped == 1
    assert (tmp_path / 'out' / 'gen' / 'big.txt').read_bytes() == b'hello' * 100


def test_extract_gunzips_concatenated_members(make_amp_ark: Callable[..., bytes],
                                              tmp_path: Path) -> None:
    payload = gzip.compress(b'first') + gzip.compress(b'second')
    archive = tmp_path / 'MAIN.ARK'
    archive.write_bytes(make_amp_ark((('joined.txt.gz', payload),)))
    ark.extract(archive, tmp_path / 'out')
    assert (tmp_path / 'out' / 'joined.txt').read_bytes() == b'firstsecond'


def test_extract_keeps_gz(make_amp_ark: Callable[..., bytes], tmp_path: Path) -> None:
    payload = gzip.compress(b'keep me')
    archive = tmp_path / 'MAIN.ARK'
    archive.write_bytes(make_amp_ark((('a.txt.gz', payload),)))
    ark.extract(archive, tmp_path / 'out', keep_gz=True)
    assert (tmp_path / 'out' / 'a.txt').read_bytes() == b'keep me'
    assert (tmp_path / 'out' / 'a.txt.gz').read_bytes() == payload


def test_extract_without_gunzip(make_amp_ark: Callable[..., bytes], tmp_path: Path) -> None:
    payload = gzip.compress(b'raw')
    archive = tmp_path / 'MAIN.ARK'
    archive.write_bytes(make_amp_ark((('a.txt.gz', payload),)))
    stats = ark.extract(archive, tmp_path / 'out', gunzip=False)
    assert stats.gunzipped == 0
    assert (tmp_path / 'out' / 'a.txt.gz').read_bytes() == payload


def test_extract_invalid_gzip_kept_verbatim(make_amp_ark: Callable[..., bytes],
                                            tmp_path: Path) -> None:
    archive = tmp_path / 'MAIN.ARK'
    archive.write_bytes(make_amp_ark((('bogus.txt.gz', b'not gzip at all'),)))
    stats = ark.extract(archive, tmp_path / 'out')
    assert stats.gunzip_failed == 1
    assert not (tmp_path / 'out' / 'bogus.txt').exists()
    assert (tmp_path / 'out' / 'bogus.txt.gz').read_bytes() == b'not gzip at all'


def test_extract_skips_truncated_entries(make_amp_ark: Callable[..., bytes],
                                         tmp_path: Path) -> None:
    archive = tmp_path / 'MAIN.ARK'
    archive.write_bytes(make_amp_ark((('a.txt', b'AAA'), ('b.txt', b'B' * 64)))[:-32])
    stats = ark.extract(archive, tmp_path / 'out')
    assert stats == (1, 1, 0, 0, 3, 3)


def test_extract_partial_gzip_stops_at_eof(make_amp_ark: Callable[..., bytes],
                                           tmp_path: Path) -> None:
    # The stream decompresses cleanly but the archive ends mid-member, so the copy loop stops.
    payload = zlib.compressobj(wbits=16 + zlib.MAX_WBITS)
    body = payload.compress(b'x' * 4096)
    archive = tmp_path / 'MAIN.ARK'
    archive.write_bytes(make_amp_ark((('trunc.txt.gz', body + payload.flush()),)))
    stats = ark.extract(archive, tmp_path / 'out')
    assert stats.gunzipped + stats.gunzip_failed == 1


def test_extract_empty_gzip_member(make_amp_ark: Callable[..., bytes], tmp_path: Path) -> None:
    # A member that decompresses to nothing yields no bytes to write.
    archive = tmp_path / 'MAIN.ARK'
    archive.write_bytes(make_amp_ark((('empty.txt.gz', gzip.compress(b'')),)))
    stats = ark.extract(archive, tmp_path / 'out')
    assert stats.gunzipped == 1
    assert (tmp_path / 'out' / 'empty.txt').read_bytes() == b''


def test_extract_concatenated_empty_member(make_amp_ark: Callable[..., bytes],
                                           tmp_path: Path) -> None:
    payload = gzip.compress(b'first') + gzip.compress(b'')
    archive = tmp_path / 'MAIN.ARK'
    archive.write_bytes(make_amp_ark((('joined.txt.gz', payload),)))
    ark.extract(archive, tmp_path / 'out')
    assert (tmp_path / 'out' / 'joined.txt').read_bytes() == b'first'


def test_extract_stops_on_short_read(make_amp_ark: Callable[..., bytes], tmp_path: Path) -> None:
    # The records claim more bytes than the stream holds, so each copy stops at the real end.
    data = make_amp_ark((('short.bin', b'A' * 4096),))
    archive = cast('Path', _TruncatedArk(data[:-4000]))
    stats = ark.extract(archive, tmp_path / 'out')
    assert stats.written == 1
    assert len((tmp_path / 'out' / 'short.bin').read_bytes()) == 96


def test_extract_gunzip_stops_on_short_read(make_amp_ark: Callable[..., bytes],
                                            tmp_path: Path) -> None:
    payload = bytes((i * 37) % 256 for i in range(8192))
    data = make_amp_ark((('short.txt.gz', gzip.compress(payload)),))
    archive = cast('Path', _TruncatedArk(data[:-32]))
    stats = ark.extract(archive, tmp_path / 'out')
    assert stats.gunzipped == 1
    written = (tmp_path / 'out' / 'short.txt').read_bytes()
    assert written
    assert payload.startswith(written)


def test_list_entries(make_amp_ark: Callable[..., bytes], tmp_path: Path) -> None:
    archive = tmp_path / 'MAIN.ARK'
    archive.write_bytes(make_amp_ark(_ENTRIES))
    assert [entry.path for entry in ark.list_entries(archive)] == ['gen/a.txt', 'b.bin']


def test_list_entries_rereads_oversized_directory(make_freq_ark: Callable[..., bytes],
                                                  tmp_path: Path) -> None:
    # A directory claiming to end past the first read forces a second, larger read.
    data = bytearray(make_freq_ark(_ENTRIES))
    struct.pack_into('<I', data, 32, len(data) * 4)  # dataOff, which is the directory end.
    archive = tmp_path / 'MAIN.ARK'
    archive.write_bytes(bytes(data))
    assert [entry.path for entry in ark.list_entries(archive)] == ['gen/a.txt', 'b.bin']
