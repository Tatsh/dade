"""Tests for :mod:`dade.xg2.extract_xg2`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

from dade.xg2.extract_xg2 import iter_model_blobs, run, unpack
from dade.xg2.offsets import XG2_MELODIC_BANK, XG2_SOUNDBANKS

from .conftest import XG2_LEVEL_BASES, XG2_MODEL_ARCHIVE

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pytest_mock import MockerFixture

_SEQUENCES = 'audio/sequences'


@pytest.fixture(autouse=True)
def _no_fluidsynth(mocker: MockerFixture) -> None:
    mocker.patch('dade.xg2.extract_xg2.render_directory', return_value=0)


def test_run_writes_the_level_containers(make_xg2_rom: Callable[..., bytes],
                                         tmp_path: Path) -> None:
    assert run(make_xg2_rom(), tmp_path)['levels'] == len(XG2_LEVEL_BASES)
    assert (tmp_path / 'levels' / f'level_00_{XG2_LEVEL_BASES[0]:07X}.bin').stat().st_size == 0x20


def test_run_falls_back_for_an_implausible_level_size(make_xg2_rom: Callable[..., bytes],
                                                      tmp_path: Path) -> None:
    run(make_xg2_rom(levels=(XG2_LEVEL_BASES[0], 0x800000)), tmp_path)
    assert (tmp_path / 'levels' / 'level_01_0800000.bin').stat().st_size == 0x80000


def test_run_writes_the_sequences(make_xg2_rom: Callable[..., bytes], tmp_path: Path) -> None:
    counts = run(make_xg2_rom(), tmp_path)
    assert counts['sequences'] == 1
    assert counts['midis'] == 0
    assert (tmp_path / _SEQUENCES / 'seq00.seq').is_file()


def test_run_converts_the_sequences(make_xg2_rom: Callable[..., bytes], tmp_path: Path) -> None:
    assert run(make_xg2_rom(), tmp_path, convert=True)['midis'] == 1
    assert (tmp_path / _SEQUENCES / 'seq00.mid').read_bytes()[:4] == b'MThd'


def test_run_skips_a_sequence_that_will_not_convert(make_xg2_rom: Callable[..., bytes],
                                                    tmp_path: Path, mocker: MockerFixture,
                                                    caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch('dade.xg2.extract_xg2.to_midi', side_effect=struct.error)
    with caplog.at_level('WARNING'):
        assert run(make_xg2_rom(), tmp_path, convert=True)['midis'] == 0
    assert 'could not be converted to MIDI' in caplog.text


def test_run_skips_a_sequence_without_tracks(make_xg2_rom: Callable[..., bytes], tmp_path: Path,
                                             mocker: MockerFixture) -> None:
    mocker.patch('dade.xg2.extract_xg2.to_midi', return_value=(b'', 0))
    assert run(make_xg2_rom(), tmp_path, convert=True)['midis'] == 0


def test_run_moves_the_drum_channel_aside(make_xg2_rom: Callable[..., bytes], tmp_path: Path,
                                          mocker: MockerFixture) -> None:
    mocker.patch('dade.xg2.extract_xg2.used_channels', return_value={9})
    remap = mocker.patch('dade.xg2.extract_xg2.remap_channel', return_value=b'MThd')
    run(make_xg2_rom(), tmp_path, convert=True)
    assert remap.call_args.args[1:] == (9, 0)


def test_run_keeps_the_drum_channel_when_none_is_free(make_xg2_rom: Callable[...,
                                                                             bytes], tmp_path: Path,
                                                      mocker: MockerFixture) -> None:
    mocker.patch('dade.xg2.extract_xg2.used_channels', return_value=set(range(16)))
    remap = mocker.patch('dade.xg2.extract_xg2.remap_channel')
    run(make_xg2_rom(), tmp_path, convert=True)
    remap.assert_not_called()


def test_run_writes_the_raw_samples(make_xg2_rom: Callable[..., bytes], tmp_path: Path) -> None:
    counts = run(make_xg2_rom(), tmp_path)
    assert counts['wavs'] == 0
    assert (tmp_path / 'audio' / f'bank_{XG2_SOUNDBANKS[0]:07X}' / 'smp000.raw').is_file()


def test_run_converts_the_samples(make_xg2_rom: Callable[..., bytes], tmp_path: Path) -> None:
    counts = run(make_xg2_rom(), tmp_path, convert=True)
    assert counts['wavs'] == len(XG2_SOUNDBANKS) + 1
    assert counts['soundfonts'] == 1
    assert (tmp_path / 'audio' / f'bank_{XG2_MELODIC_BANK:07X}.sf2').read_bytes()[:4] == b'RIFF'


def test_run_skips_an_empty_sample(make_xg2_rom: Callable[..., bytes], tmp_path: Path,
                                   mocker: MockerFixture) -> None:
    mocker.patch('dade.xg2.extract_xg2.parse_bank',
                 return_value={
                     'sample_rate': 22050,
                     'instruments': [],
                     'percussion': [],
                     'samples': [[], [1, 2, 3]]
                 })
    run(make_xg2_rom(), tmp_path, convert=True)
    directory = tmp_path / 'audio' / f'bank_{XG2_SOUNDBANKS[0]:07X}'
    assert not (directory / 'smp000.raw').exists()
    assert (directory / 'smp001.raw').is_file()


def test_run_skips_a_soundfont_it_cannot_build(make_xg2_rom: Callable[..., bytes], tmp_path: Path,
                                               mocker: MockerFixture) -> None:
    mocker.patch('dade.xg2.extract_xg2.bank_to_sf2', return_value=None)
    assert run(make_xg2_rom(), tmp_path, convert=True)['soundfonts'] == 0


def test_run_warns_about_a_bank_that_will_not_parse(make_xg2_rom: Callable[..., bytes],
                                                    tmp_path: Path, mocker: MockerFixture,
                                                    caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch('dade.xg2.extract_xg2.parse_bank', return_value=None)
    with caplog.at_level('WARNING'):
        run(make_xg2_rom(), tmp_path)
    assert 'did not parse' in caplog.text


def test_run_sorts_the_mfs_entries_by_kind(make_xg2_rom: Callable[..., bytes],
                                           tmp_path: Path) -> None:
    counts = run(make_xg2_rom(), tmp_path)
    assert (counts['bmc'], counts['shaw'], counts['other']) == (2, 2, 1)
    root = tmp_path / 'mfs'
    assert (root / 'aud000_engine.bin').is_file()
    assert (root / 'aud003_unnamed_003.bin').is_file()
    assert (root / 'data002_01020304.bin').is_file()
    assert 'BMC' in (root / 'manifest.txt').read_text()


def test_run_converts_the_bmc_sounds(make_xg2_rom: Callable[..., bytes], tmp_path: Path) -> None:
    run(make_xg2_rom(), tmp_path, convert=True)
    assert (tmp_path / 'mfs' / 'aud000_engine.wav').is_file()
    assert not (tmp_path / 'mfs' / 'aud003_unnamed_003.wav').exists()


def test_run_dumps_the_shaw_resources(make_xg2_rom: Callable[..., bytes], tmp_path: Path) -> None:
    run(make_xg2_rom(), tmp_path)
    directory = tmp_path / 'mfs' / 'shaw001'
    assert (directory / '_container.bin').is_file()
    assert (directory / 'res000_0000040.bin').stat().st_size == 0x10
    assert '1 resources' in (tmp_path / 'mfs' / 'manifest.txt').read_text()


def test_run_skips_undecodable_mfs_entries(make_xg2_rom: Callable[..., bytes], tmp_path: Path,
                                           caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level('WARNING'):
        counts = run(make_xg2_rom(lhuf=True), tmp_path)
    assert counts['other'] == 1
    assert 'LHUF codec is not implemented' in caplog.text


def test_run_decodes_the_textures(make_xg2_rom: Callable[..., bytes], tmp_path: Path) -> None:
    assert run(make_xg2_rom(), tmp_path, convert=True)['textures'] == 1
    directory = tmp_path / 'textures' / 'models' / f'arch_{XG2_MODEL_ARCHIVE:07X}' / '000'
    assert list(directory.glob('*.png'))


def test_run_renders_the_sequences(make_xg2_rom: Callable[..., bytes], tmp_path: Path,
                                   mocker: MockerFixture) -> None:
    render = mocker.patch('dade.xg2.extract_xg2.render_directory', return_value=3)
    fluidsynth = tmp_path / 'fluidsynth'
    assert run(make_xg2_rom(), tmp_path, convert=True, fluidsynth_path=fluidsynth)['rendered'] == 3
    assert render.call_args.args[2] == fluidsynth


def test_iter_model_blobs_labels_every_source(make_xg2_rom: Callable[..., bytes]) -> None:
    labels = [label for label, _ in iter_model_blobs(make_xg2_rom())]
    assert labels[:4] == ['mfs/file000', 'mfs/file001', 'mfs/file002', 'mfs/file003']
    assert labels[4] == 'mfs/file004'
    assert f'models/arch_{XG2_MODEL_ARCHIVE:07X}/000' in labels
    assert f'models/arch_{XG2_MODEL_ARCHIVE + 0x10000:07X}' in labels


def test_unpack_writes_the_boot_images(make_xg2_rom: Callable[..., bytes], tmp_path: Path) -> None:
    counts = unpack(make_xg2_rom(), tmp_path, 'xg2')
    assert counts['files'] == 5
    for name in ('xg2.boot.bin', 'xg2.bootram.bin', 'xg2.extended.z64'):
        assert (tmp_path / name).is_file()


def test_unpack_writes_a_manifest(make_xg2_rom: Callable[..., bytes], tmp_path: Path) -> None:
    unpack(make_xg2_rom(), tmp_path)
    manifest = (tmp_path / 'extreme-g-2.files' / 'manifest.txt').read_text()
    assert manifest.startswith('# index')
    assert manifest.count('\n') == 6
