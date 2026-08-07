from __future__ import annotations

from typing import TYPE_CHECKING
import json
import struct

from destin.harmonix import audio
from destin.harmonix.typing import InvalidFormatError
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

_WAV_HEADER = 44


def _bank(descriptors: Sequence[tuple[int, int]], names: Sequence[str]) -> bytes:
    # A SAMP index whose descriptor count need not match its SANM name count.
    table = bytearray()
    for rate, offset in descriptors:
        record = bytearray(22)
        struct.pack_into('<IIH', record, 0, 1, 1, rate)
        struct.pack_into('<I', record, 18, offset)
        table += record
    body = b''.join(struct.pack('<I', len(name)) + name.encode() for name in names)
    return (b'SAMP' + struct.pack('<I',
                                  len(descriptors) * 22) + bytes(table) + b'SANM' + bytes(8) + body)


def test_str_to_wav_deinterleaves() -> None:
    data = b'LLLL' + b'RRRR' + b'llll' + b'rrrr'
    wav = audio.str_to_wav(data, rate=44100, block=4)
    assert wav[:4] == b'RIFF'
    assert wav[8:12] == b'WAVE'
    assert len(wav) == _WAV_HEADER + 16
    assert struct.unpack_from('<H', wav, 22)[0] == 2  # Stereo.
    assert struct.unpack_from('<I', wav, 24)[0] == 44100


def test_convert_writes_wav_and_removes_source(tmp_path: Path) -> None:
    source = tmp_path / 'song.str'
    source.write_bytes(bytes(4096))
    out = audio.convert(source)
    assert out == tmp_path / 'song.wav'
    assert not source.exists()
    assert out.read_bytes()[:4] == b'RIFF'


def test_decode_vag_adpcm(make_vag: Callable[..., bytes]) -> None:
    pcm = audio.decode_vag_adpcm(make_vag(3))
    assert len(pcm) == 3 * 28


def test_decode_vag_adpcm_stops_at_end_flag(make_vag: Callable[..., bytes]) -> None:
    blob = make_vag(1, flag=1) + make_vag(2, flag=0)
    assert len(audio.decode_vag_adpcm(blob)) == 28


def test_decode_vag_adpcm_stops_at_mute_flag(make_vag: Callable[..., bytes]) -> None:
    assert len(audio.decode_vag_adpcm(make_vag(2, flag=7))) == 28


def test_decode_vag_adpcm_max_bytes(make_vag: Callable[..., bytes]) -> None:
    assert len(audio.decode_vag_adpcm(make_vag(4, flag=0), 0, 32)) == 56


@pytest.mark.parametrize(('predictor', 'shift'), [(7, 12), (0, 0), (4, 1)])
def test_decode_vag_adpcm_predictor_and_shift(make_vag: Callable[..., bytes], predictor: int,
                                              shift: int) -> None:
    # An out-of-range predictor falls back to the first coefficient pair; a small shift clamps.
    pcm = audio.decode_vag_adpcm(make_vag(2, predictor=predictor, shift=shift))
    assert len(pcm) == 56
    assert all(-32768 <= sample <= 32767 for sample in pcm)


def test_bnk_to_json(make_samp_bank: Callable[..., bytes]) -> None:
    meta = audio.bnk_to_json(make_samp_bank((('kick', 22050, 0), ('snare', 44100, 48))))
    assert meta['magic'] == 'SAMP'
    assert meta['sample_count'] == 2
    assert meta['descriptor_stride'] == 22
    assert [sample['name'] for sample in meta['samples']] == ['kick', 'snare']
    assert meta['samples'][1]['rate'] == 44100


@pytest.mark.parametrize('data', [b'NOPE' + bytes(32), b'SAMP\x00'])
def test_bnk_to_json_not_a_bank(data: bytes) -> None:
    with pytest.raises(InvalidFormatError, match='Not a `SAMP` bank'):
        audio.bnk_to_json(data)


def test_bnk_to_json_stops_at_bad_name_length(make_samp_bank: Callable[..., bytes]) -> None:
    # Trailing bytes that do not form a plausible length prefix end the name scan.
    data = make_samp_bank((('kick', 22050, 0),)) + b'\xff\xff\xff\xff'
    assert audio.bnk_to_json(data)['sample_count'] == 1


def test_bnk_to_json_without_names() -> None:
    with pytest.raises(InvalidFormatError, match='no sample names'):
        audio.bnk_to_json(b'SAMP' + struct.pack('<I', 22) + bytes(22))


def test_split_bank_without_blob(tmp_path: Path, make_samp_bank: Callable[..., bytes]) -> None:
    bnk = tmp_path / 'song.bnk'
    bnk.write_bytes(make_samp_bank((('kick', 22050, 0),)))
    assert audio.split_bank(bnk) is None


def test_split_bank_not_a_bank(tmp_path: Path) -> None:
    bnk = tmp_path / 'song.bnk'
    bnk.write_bytes(b'JUNK' + bytes(16))
    (tmp_path / 'song.nse').write_bytes(b'')
    assert audio.split_bank(bnk) is None


def test_split_bank(tmp_path: Path, make_vag: Callable[..., bytes]) -> None:
    # Two usable descriptors sharing a name, plus one whose data lies past the blob.
    bnk = tmp_path / 'song.bnk'
    bnk.write_bytes(_bank(((22050, 0), (0, 32), (44100, 9999)), ('kick', 'kick')))
    (tmp_path / 'song.nse').write_bytes(make_vag(4, flag=0))
    out = audio.split_bank(bnk)
    assert out == tmp_path / 'song'
    manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['sample_count'] == 3
    assert [sample['file'] for sample in manifest['samples']] == ['kick.wav', 'kick_1.wav']
    assert manifest['samples'][1]['rate'] == 22050  # A zero rate falls back to the VAG default.
    assert (out / 'kick.wav').read_bytes()[:4] == b'RIFF'


def test_split_bank_falls_back_to_generated_names(tmp_path: Path,
                                                  make_vag: Callable[..., bytes]) -> None:
    bnk = tmp_path / 'song.bnk'
    bnk.write_bytes(_bank(((22050, 0), (22050, 32)), ('kick',)))
    (tmp_path / 'song.nse').write_bytes(make_vag(4, flag=0))
    out = audio.split_bank(bnk)
    assert out is not None
    manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    assert [sample['name'] for sample in manifest['samples']] == ['kick', 'sample_001']


def test_parse_sd_bank(make_sd_bank: Callable[..., bytes]) -> None:
    parsed = audio.parse_sd_bank(make_sd_bank(((0, 22050, 0), (32, 44100, 1)), bd_size=64))
    assert parsed == (64, [(0, 22050, 0), (32, 44100, 1)])


def test_parse_sd_bank_wrong_magic() -> None:
    assert audio.parse_sd_bank(b'NOTSCEI!' + bytes(64)) is None


@pytest.mark.parametrize('missing', [b'IECSdaeH', b'IECSigaV'])
def test_parse_sd_bank_missing_chunk(make_sd_bank: Callable[..., bytes], missing: bytes) -> None:
    data = make_sd_bank(((0, 22050, 0),)).replace(missing, b'XXXXXXXX')
    assert audio.parse_sd_bank(data) is None


def test_parse_sd_bank_truncated_vagi(make_sd_bank: Callable[..., bytes]) -> None:
    assert audio.parse_sd_bank(make_sd_bank(((0, 22050, 0),))[:-24]) is None


@pytest.mark.parametrize('count', [0, 5000])
def test_parse_sd_bank_bad_count(make_sd_bank: Callable[..., bytes], count: int) -> None:
    data = bytearray(make_sd_bank(((0, 22050, 0),)))
    struct.pack_into('<I', data, data.index(b'IECSigaV') + 12, count)
    assert audio.parse_sd_bank(bytes(data)) is None


def test_parse_sd_bank_offset_table_overruns(make_sd_bank: Callable[..., bytes]) -> None:
    data = bytearray(make_sd_bank(((0, 22050, 0),)))
    struct.pack_into('<I', data, data.index(b'IECSigaV') + 12, 100)
    assert audio.parse_sd_bank(bytes(data)) is None


def test_parse_sd_bank_record_out_of_range(make_sd_bank: Callable[..., bytes]) -> None:
    data = bytearray(make_sd_bank(((0, 22050, 0),)))
    struct.pack_into('<I', data, data.index(b'IECSigaV') + 16, 4096)  # Record offset past the end.
    assert audio.parse_sd_bank(bytes(data)) is None


def test_split_sd_bank_without_body(tmp_path: Path, make_sd_bank: Callable[..., bytes]) -> None:
    hd = tmp_path / 'bank.hd'
    hd.write_bytes(make_sd_bank(((0, 22050, 0),)))
    assert audio.split_sd_bank(hd) is None


def test_split_sd_bank_invalid_header(tmp_path: Path) -> None:
    hd = tmp_path / 'bank.hd'
    hd.write_bytes(b'JUNKJUNK' + bytes(32))
    (tmp_path / 'bank.bd').write_bytes(bytes(16))
    assert audio.split_sd_bank(hd) is None


def test_split_sd_bank(tmp_path: Path, make_sd_bank: Callable[..., bytes],
                       make_vag: Callable[..., bytes]) -> None:
    # The third VAG starts past the body limit, so it decodes to nothing and is skipped.
    hd = tmp_path / 'bank.hd'
    hd.write_bytes(make_sd_bank(((0, 22050, 0), (32, 0, 4), (64, 44100, 0)), bd_size=64))
    (tmp_path / 'bank.bd').write_bytes(make_vag(4, flag=0))
    out = audio.split_sd_bank(hd)
    assert out == tmp_path / 'bank'
    manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['vag_count'] == 3
    assert [sample['file']
            for sample in manifest['samples']] == ['sample_000.wav', 'sample_001.wav']
    assert manifest['samples'][1]['rate'] == 22050  # A zero rate falls back to the VAG default.


def test_split_all_banks(tmp_path: Path, make_samp_bank: Callable[..., bytes],
                         make_sd_bank: Callable[..., bytes], make_vag: Callable[...,
                                                                                bytes]) -> None:
    (tmp_path / 'sfx').mkdir()
    splittable = tmp_path / 'sfx' / 'song.bnk'
    splittable.write_bytes(make_samp_bank((('kick', 22050, 0),)))
    (tmp_path / 'sfx' / 'song.nse').write_bytes(make_vag(2, flag=0))
    (tmp_path / 'meta.bnk').write_bytes(make_samp_bank((('pad', 44100, 0),)))
    (tmp_path / 'broken.bnk').write_bytes(b'JUNK' + bytes(16))
    (tmp_path / 'scei.hd').write_bytes(make_sd_bank(((0, 22050, 0),), bd_size=32))
    (tmp_path / 'scei.bd').write_bytes(make_vag(2, flag=0))
    (tmp_path / 'orphan.hd').write_bytes(make_sd_bank(((0, 22050, 0),)))  # No sibling ``.bd``.
    assert audio.split_all_banks(tmp_path) == (2, 1)
    assert (tmp_path / 'sfx' / 'song' / 'manifest.json').is_file()
    assert (tmp_path / 'scei' / 'manifest.json').is_file()
    assert json.loads((tmp_path / 'meta.bnk.json').read_text(encoding='utf-8'))['magic'] == 'SAMP'
    assert not (tmp_path / 'broken.bnk.json').exists()


def test_split_all_banks_ignores_unsplittable_bank(tmp_path: Path,
                                                   make_samp_bank: Callable[..., bytes]) -> None:
    # An ``.nse`` is present but the index is not a bank, so the split returns nothing.
    (tmp_path / 'song.bnk').write_bytes(make_samp_bank((('kick', 22050, 0),)))
    (tmp_path / 'song.nse').write_bytes(b'')
    assert audio.split_all_banks(tmp_path) == (1, 0)


def test_convert_disc_audio(tmp_path: Path) -> None:
    src_dir = tmp_path / 'AUDIO'
    src_dir.mkdir()
    (src_dir / 'SONG1.STR').write_bytes(bytes(4096))
    (src_dir / 'SONG2.str').write_bytes(bytes(4096))
    (src_dir / 'README.TXT').write_bytes(b'ignored')
    assert audio.convert_disc_audio(src_dir, tmp_path / 'out', block=512) == 2
    assert sorted(p.name for p in (tmp_path / 'out').iterdir()) == ['SONG1.wav', 'SONG2.wav']
