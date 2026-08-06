"""Tests for :mod:`destin.xg2.extract_xg1`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from destin.xg2.extract_xg1 import LEVEL_SUB_BLOBS, RunLog, run, unpack
from destin.xg2.mfs import MfsCalibrationError
import pytest

from .conftest import XG1_LEVEL_BASES

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pytest_mock import MockerFixture

_PALETTE = b'\x00\x03' * 256


def _texture_bank(*, palette: bool = True, truncated: bool = False) -> bytes:
    """Build a decompressed texture bank of two four-by-four indexed textures."""
    bank = bytearray(0x240)
    struct.pack_into('>I', bank, 0, 0x40 if palette else 0x38)
    struct.pack_into('>IHH', bank, 8, 0x20, 4, 4)
    struct.pack_into('>IHH', bank, 0x10, 0x23C if truncated else 0x30, 4, 4)
    bank[0x40:0x240] = _PALETTE
    return bytes(bank)


def test_run_log_records_and_writes(tmp_path: Path) -> None:
    run_log = RunLog()
    run_log.add('something happened')
    run_log.write(tmp_path / 'extract.log')
    assert (tmp_path / 'extract.log').read_text() == 'something happened\n'


def test_run_log_writes_an_empty_file(tmp_path: Path) -> None:
    RunLog().write(tmp_path / 'extract.log')
    assert not (tmp_path / 'extract.log').read_text()


def test_run_writes_the_boot_segment(make_xg1_rom: Callable[..., bytes], tmp_path: Path) -> None:
    counts = run(make_xg1_rom(), tmp_path)
    assert counts['boot'] == 1
    assert (tmp_path / 'boot' / 'main_8004b8a0.bin').is_file()


def test_run_writes_the_mfs_files(make_xg1_rom: Callable[..., bytes], tmp_path: Path) -> None:
    assert run(make_xg1_rom(), tmp_path)['mfs'] == 2
    assert (tmp_path / 'mfs' / 'file_00.bin').read_bytes() == b'alpha'
    assert (tmp_path / 'mfs' / 'file_01.bin').read_bytes() == b'beta'


def test_run_records_an_uncalibratable_mfs(make_xg1_rom: Callable[..., bytes], tmp_path: Path,
                                           mocker: MockerFixture) -> None:
    mocker.patch('destin.xg2.extract_xg1.iter_files', side_effect=MfsCalibrationError)
    assert run(make_xg1_rom(), tmp_path)['mfs'] == 0
    assert 'mfs:' in (tmp_path / 'extract.log').read_text()


def test_run_writes_the_master_directory(make_xg1_rom: Callable[..., bytes],
                                         tmp_path: Path) -> None:
    assert run(make_xg1_rom(), tmp_path)['directory'] == 1
    assert (tmp_path / 'dir' / 'directory_0002000.bin').stat().st_size == 0x100


def test_run_keeps_compressed_level_slices(make_xg1_rom: Callable[..., bytes],
                                           tmp_path: Path) -> None:
    counts = run(make_xg1_rom(), tmp_path)
    assert counts['containers'] == len(XG1_LEVEL_BASES)
    level = tmp_path / 'levels' / f'00_{XG1_LEVEL_BASES[0]:07X}'
    assert (level / 't1_desc.lzhuf.raw').is_file()
    assert (level / 'r2.lzhuf.raw').is_file()
    assert not (level / 'r3.lzhuf.raw').exists()
    assert not (level / 't4.lzhuf.raw').exists()
    assert 'LZHUF is not implemented' in (tmp_path / 'extract.log').read_text()


def test_run_writes_the_object_table(make_xg1_rom: Callable[..., bytes], tmp_path: Path) -> None:
    run(make_xg1_rom(), tmp_path)
    objects = tmp_path / 'levels' / f'00_{XG1_LEVEL_BASES[0]:07X}' / 'objects.bin'
    assert objects.stat().st_size == 2 * 0x28


def test_run_decompresses_level_blobs_when_the_codec_exists(make_xg1_rom: Callable[..., bytes],
                                                            tmp_path: Path,
                                                            mocker: MockerFixture) -> None:
    mocker.patch('destin.xg2.extract_xg1.decompress_lzhuf', return_value=b'decoded')
    counts = run(make_xg1_rom(), tmp_path)
    level = tmp_path / 'levels' / f'00_{XG1_LEVEL_BASES[0]:07X}'
    assert (level / 't1_desc.bin').read_bytes() == b'decoded'
    # Two of the four sub-blobs in each container, plus the first container's object table.
    assert counts['levels'] == len(XG1_LEVEL_BASES) * (len(LEVEL_SUB_BLOBS) - 2) + 1


def test_run_skips_conversion_by_default(make_xg1_rom: Callable[..., bytes],
                                         tmp_path: Path) -> None:
    counts = run(make_xg1_rom(), tmp_path)
    assert counts['textures'] == 0
    assert counts['audio'] == 0


def test_run_records_a_skipped_texture_bank(make_xg1_rom: Callable[..., bytes],
                                            tmp_path: Path) -> None:
    assert run(make_xg1_rom(), tmp_path, convert=True)['textures'] == 0
    assert 'texture bank global' in (tmp_path / 'extract.log').read_text()


def test_run_writes_texture_bank_pngs(make_xg1_rom: Callable[..., bytes], tmp_path: Path,
                                      mocker: MockerFixture) -> None:
    mocker.patch('destin.xg2.extract_xg1.decompress_lzhuf', return_value=_texture_bank())
    assert run(make_xg1_rom(), tmp_path, convert=True)['textures'] == 4
    assert (tmp_path / 'textures' / 'global' / 'tex000_4x4.png').is_file()


def test_run_falls_back_to_greyscale_without_a_palette(make_xg1_rom: Callable[..., bytes],
                                                       tmp_path: Path,
                                                       mocker: MockerFixture) -> None:
    mocker.patch('destin.xg2.extract_xg1.decompress_lzhuf',
                 return_value=_texture_bank(palette=False))
    assert run(make_xg1_rom(), tmp_path, convert=True)['textures'] == 4


def test_run_skips_a_truncated_texture(make_xg1_rom: Callable[..., bytes], tmp_path: Path,
                                       mocker: MockerFixture) -> None:
    mocker.patch('destin.xg2.extract_xg1.decompress_lzhuf',
                 return_value=_texture_bank(truncated=True))
    assert run(make_xg1_rom(), tmp_path, convert=True)['textures'] == 2


def test_run_records_a_bank_without_descriptors(make_xg1_rom: Callable[..., bytes], tmp_path: Path,
                                                mocker: MockerFixture) -> None:
    mocker.patch('destin.xg2.extract_xg1.decompress_lzhuf', return_value=b'\x00' * 0x100)
    assert run(make_xg1_rom(), tmp_path, convert=True)['textures'] == 0
    assert 'no valid descriptor table' in (tmp_path / 'extract.log').read_text()


def test_run_ignores_an_implausible_bank_size(make_xg1_rom: Callable[..., bytes],
                                              tmp_path: Path) -> None:
    rom = bytearray(make_xg1_rom())
    struct.pack_into('>I', rom, 0x300000, 0x300000)  # Larger than the maximum bank.
    run(bytes(rom), tmp_path, convert=True)
    log = (tmp_path / 'extract.log').read_text()
    assert 'texture bank global' not in log
    assert 'texture bank bank_0310000' in log


def test_run_writes_a_bank_whose_table_runs_to_the_end(make_xg1_rom: Callable[..., bytes],
                                                       tmp_path: Path,
                                                       mocker: MockerFixture) -> None:
    bank = bytearray(0x10)
    struct.pack_into('>IHH', bank, 8, 0x0C, 1, 1)
    mocker.patch('destin.xg2.extract_xg1.decompress_lzhuf', return_value=bytes(bank))
    assert run(make_xg1_rom(), tmp_path, convert=True)['textures'] == 0


def test_run_converts_the_sequences(make_xg1_rom: Callable[..., bytes], tmp_path: Path) -> None:
    assert run(make_xg1_rom(), tmp_path, convert=True)['audio'] > 0
    directory = tmp_path / 'audio' / 'soundbank_0500000'
    for name in ('seq00.seq', 'seq00.mid', 'seq00.xg.mid', 'seq00.gm.mid'):
        assert (directory / name).is_file()


def test_run_records_a_sequence_that_will_not_convert(make_xg1_rom: Callable[...,
                                                                             bytes], tmp_path: Path,
                                                      mocker: MockerFixture) -> None:
    mocker.patch('destin.xg2.extract_xg1.to_midi', side_effect=IndexError)
    run(make_xg1_rom(), tmp_path, convert=True)
    assert 'ALCSeq to MIDI failed' in (tmp_path / 'extract.log').read_text()


def test_run_skips_a_sequence_without_tracks(make_xg1_rom: Callable[..., bytes], tmp_path: Path,
                                             mocker: MockerFixture) -> None:
    mocker.patch('destin.xg2.extract_xg1.to_midi', return_value=(b'', 0))
    run(make_xg1_rom(), tmp_path, convert=True)
    assert not (tmp_path / 'audio' / 'soundbank_0500000' / 'seq00.mid').exists()


def test_run_records_a_failed_xg_conversion(make_xg1_rom: Callable[..., bytes], tmp_path: Path,
                                            mocker: MockerFixture) -> None:
    mocker.patch('destin.xg2.extract_xg1.to_xg', side_effect=ValueError('bad'))
    run(make_xg1_rom(), tmp_path, convert=True)
    assert 'XG conversion failed' in (tmp_path / 'extract.log').read_text()


def test_run_writes_the_sample_wavs(make_xg1_rom: Callable[..., bytes], tmp_path: Path) -> None:
    run(make_xg1_rom(), tmp_path, convert=True)
    assert (tmp_path / 'audio' / 'samples_0600000' / 'sample000.wav').is_file()
    assert 'audio bank at 0x600000' in (tmp_path / 'extract.log').read_text()


def test_run_skips_an_empty_sample(make_xg1_rom: Callable[..., bytes], tmp_path: Path,
                                   mocker: MockerFixture) -> None:
    mocker.patch('destin.xg2.extract_xg1.parse_bank',
                 return_value={
                     'sample_rate': 22050,
                     'instruments': [],
                     'percussion': [],
                     'samples': [[], [1, 2, 3]]
                 })
    run(make_xg1_rom(), tmp_path, convert=True)
    assert not (tmp_path / 'audio' / 'samples_0600000' / 'sample000.wav').exists()
    assert (tmp_path / 'audio' / 'samples_0600000' / 'sample001.wav').is_file()


def test_run_ignores_a_bank_with_no_sounds(make_xg1_rom: Callable[..., bytes], tmp_path: Path,
                                           mocker: MockerFixture) -> None:
    mocker.patch('destin.xg2.extract_xg1.parse_bank',
                 return_value={
                     'sample_rate': 22050,
                     'instruments': [],
                     'percussion': [],
                     'samples': [[]]
                 })
    assert run(make_xg1_rom(), tmp_path, convert=True)['audio'] == 4
    assert not (tmp_path / 'audio' / 'ExtremeG.sf2').exists()


def test_run_builds_the_combined_soundfont(make_xg1_rom: Callable[..., bytes],
                                           tmp_path: Path) -> None:
    run(make_xg1_rom(), tmp_path, convert=True)
    assert (tmp_path / 'audio' / 'ExtremeG.sf2').read_bytes()[:4] == b'RIFF'


def test_run_passes_a_fallback_drum_bank(make_xg1_rom: Callable[..., bytes], tmp_path: Path,
                                         mocker: MockerFixture) -> None:
    build = mocker.patch('destin.xg2.extract_xg1.build_combined', return_value=b'RIFF')
    run(make_xg1_rom(banks=2), tmp_path, convert=True)
    assert build.call_args.args[1:] == (0x600000, 0x600000)


def test_run_records_a_failed_soundfont(make_xg1_rom: Callable[..., bytes], tmp_path: Path,
                                        mocker: MockerFixture) -> None:
    mocker.patch('destin.xg2.extract_xg1.build_combined', side_effect=ValueError('no bank'))
    run(make_xg1_rom(), tmp_path, convert=True)
    assert 'combined SoundFont failed' in (tmp_path / 'extract.log').read_text()


def test_run_without_any_audio(make_xg1_rom: Callable[..., bytes], tmp_path: Path) -> None:
    assert run(make_xg1_rom(audio=False), tmp_path, convert=True)['audio'] == 0


def test_unpack_writes_the_boot_images(make_xg1_rom: Callable[..., bytes], tmp_path: Path) -> None:
    unpack(make_xg1_rom(), tmp_path, 'xg')
    for name in ('xg.boot.bin', 'xg.bootram.bin', 'xg.extended.z64'):
        assert (tmp_path / name).is_file()


def test_unpack_writes_a_manifest(make_xg1_rom: Callable[..., bytes], tmp_path: Path) -> None:
    counts = unpack(make_xg1_rom(), tmp_path)
    assert counts == {'files': 2, 'bytes': 9}
    manifest = (tmp_path / 'extreme-g.files' / 'manifest.txt').read_text()
    assert manifest.startswith('# index')
    assert manifest.count('\n') == 3


def test_unpack_propagates_a_calibration_failure(make_xg1_rom: Callable[..., bytes],
                                                 tmp_path: Path) -> None:
    rom = bytearray(make_xg1_rom())
    struct.pack_into('>I', rom, 0x7A2DFC + 4, 0xFFFFFF)  # Demand more than the ROM holds.
    with pytest.raises(MfsCalibrationError):
        unpack(bytes(rom), tmp_path)
