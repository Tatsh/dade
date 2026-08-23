from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias
import gzip
import json
import struct

import pytest

from destin.harmonix import pipeline

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from pytest_mock import MockerFixture

_Builder: TypeAlias = 'Callable[..., bytes]'
_MAT_BLOB = struct.pack('<I', len('ship_tex.bmp')) + b'ship_tex.bmp'


def _ark_entries(make_hmx_bitmap: _Builder, make_dtb: _Builder, make_milo: _Builder,
                 make_v14_mesh: _Builder, make_samp_bank: _Builder,
                 make_vag: _Builder) -> Sequence[tuple[str, bytes]]:
    return (
        ('gen/ship_tex.bmp', make_hmx_bitmap(4, 4, bpp=8)),
        ('gen/config.txt.bin', make_dtb([['name', 'value']])),
        ('gen/scene.rnd',
         make_milo([('RndMesh', 'ship.mesh', make_v14_mesh()),
                    ('Rnd::Mat', 'ship.mat', _MAT_BLOB)])),
        ('audio/song.bnk', make_samp_bank((('kick', 22050, 0),))),
        ('audio/song.nse', make_vag(2, flag=0)),
        ('audio/meta.bnk', make_samp_bank((('pad', 44100, 0),))),
        ('audio/broken.bnk', b'JUNK' + bytes(16)),
        ('notes.txt.gz', gzip.compress(b'read me')),
    )


@pytest.mark.asyncio
async def test_run_extract_only(make_amp_ark: _Builder, tmp_path: Path) -> None:
    archive = tmp_path / 'MAIN.ARK'
    archive.write_bytes(make_amp_ark((('gen/a.txt', b'AAA'),)))
    steps = await pipeline.run(archive, tmp_path / 'out', convert=False)
    assert list(steps) == ['extract']
    assert steps['extract'].startswith('1 files')
    assert (tmp_path / 'out' / 'gen' / 'a.txt').is_file()


@pytest.mark.asyncio
async def test_run_converts_assets(make_amp_ark: _Builder, make_hmx_bitmap: _Builder,
                                   make_dtb: _Builder, make_milo: _Builder, make_v14_mesh: _Builder,
                                   make_samp_bank: _Builder, make_vag: _Builder,
                                   tmp_path: Path) -> None:
    entries = _ark_entries(make_hmx_bitmap, make_dtb, make_milo, make_v14_mesh, make_samp_bank,
                           make_vag)
    archive = tmp_path / 'MAIN.ARK'
    archive.write_bytes(make_amp_ark(entries))
    out = tmp_path / 'out'
    steps = await pipeline.run(archive, out)
    assert set(steps) == {'extract', 'milo', 'convert', 'references', 'materials', 'banks'}
    assert steps['milo'] == '1 archives decomposed'
    assert steps['banks'] == '1 split, 1 json-only'
    assert steps['materials'] == '1 linked'
    assert (out / 'gen' / 'ship_tex.png').is_file()
    assert (out / 'gen' / 'config.txt.json').is_file()
    assert (out / 'gen' / 'scene' / 'ship.obj').is_file()
    assert (out / 'gen' / 'scene' / 'ship.mtl').is_file()
    assert (out / 'audio' / 'song' / 'manifest.json').is_file()
    meta_json = (out / 'audio' / 'meta.bnk.json').read_text(encoding='utf-8')
    assert json.loads(meta_json)['magic'] == 'SAMP'
    assert not (out / 'audio' / 'broken.bnk.json').exists()
    assert (out / 'notes.txt').read_bytes() == b'read me'


@pytest.mark.asyncio
async def test_run_keeps_intermediates_by_default(make_amp_ark: _Builder, make_hmx_bitmap: _Builder,
                                                  make_dtb: _Builder, make_milo: _Builder,
                                                  make_v14_mesh: _Builder, make_samp_bank: _Builder,
                                                  make_vag: _Builder, tmp_path: Path) -> None:
    entries = _ark_entries(make_hmx_bitmap, make_dtb, make_milo, make_v14_mesh, make_samp_bank,
                           make_vag)
    archive = tmp_path / 'MAIN.ARK'
    archive.write_bytes(make_amp_ark(entries))
    out = tmp_path / 'out'
    steps = await pipeline.run(archive, out)
    assert 'deleted' not in steps
    assert (out / 'gen' / 'ship_tex.bmp').is_file()
    assert (out / 'gen' / 'config.txt.bin').is_file()
    assert (out / 'gen' / 'scene.rnd').is_file()
    assert (out / 'audio' / 'song.bnk').is_file()


@pytest.mark.asyncio
async def test_run_deletes_intermediates(make_amp_ark: _Builder, make_hmx_bitmap: _Builder,
                                         make_dtb: _Builder, make_milo: _Builder,
                                         make_v14_mesh: _Builder, make_samp_bank: _Builder,
                                         make_vag: _Builder, tmp_path: Path) -> None:
    entries = _ark_entries(make_hmx_bitmap, make_dtb, make_milo, make_v14_mesh, make_samp_bank,
                           make_vag)
    archive = tmp_path / 'MAIN.ARK'
    archive.write_bytes(make_amp_ark(entries))
    out = tmp_path / 'out'
    steps = await pipeline.run(archive, out, delete=True)
    assert steps['deleted'].endswith('intermediates removed')
    # The converted outputs (and the references they point at) survive.
    assert (out / 'gen' / 'ship_tex.png').is_file()
    assert (out / 'gen' / 'config.txt.json').is_file()
    assert (out / 'gen' / 'scene' / 'ship.obj').is_file()
    assert (out / 'gen' / 'scene' / 'ship.mtl').is_file()
    assert (out / 'audio' / 'song' / 'manifest.json').is_file()
    assert (out / 'audio' / 'meta.bnk.json').is_file()
    # The raw intermediates (and sample-bank companions) are gone.
    assert not (out / 'gen' / 'ship_tex.bmp').exists()
    assert not (out / 'gen' / 'config.txt.bin').exists()
    assert not (out / 'gen' / 'scene.rnd').exists()
    assert not (out / 'audio' / 'song.bnk').exists()
    assert not (out / 'audio' / 'song.nse').exists()
    assert not (out / 'audio' / 'meta.bnk').exists()
    # A file whose conversion failed is not treated as a consumed intermediate.
    assert (out / 'audio' / 'broken.bnk').is_file()
    # The extracted-from ARK (the source) is never touched.
    assert archive.is_file()


@pytest.mark.asyncio
async def test_run_converts_disc_audio(make_amp_ark: _Builder, tmp_path: Path) -> None:
    archive = tmp_path / 'MAIN.ARK'
    archive.write_bytes(make_amp_ark((('gen/a.txt', b'AAA'),)))
    disc = tmp_path / 'AUDIO'
    disc.mkdir()
    (disc / 'SONG.STR').write_bytes(bytes(4096))
    steps = await pipeline.run(archive, tmp_path / 'out', disc_audio=disc)
    assert steps['disc_audio'] == '1 songs'
    assert (tmp_path / 'out' / 'disc_audio' / 'SONG.wav').read_bytes()[:4] == b'RIFF'


@pytest.mark.asyncio
async def test_run_game(make_amp_ark: _Builder, make_hmx_bitmap: _Builder, make_dtb: _Builder,
                        make_milo: _Builder, make_v14_mesh: _Builder, make_samp_bank: _Builder,
                        make_vag: _Builder, tmp_path: Path) -> None:
    work = tmp_path / 'work'
    (work / 'GEN').mkdir(parents=True)
    (work / 'AUDIO').mkdir()
    entries = _ark_entries(make_hmx_bitmap, make_dtb, make_milo, make_v14_mesh, make_samp_bank,
                           make_vag)
    (work / 'GEN' / 'MAIN.ARK').write_bytes(make_amp_ark(entries))
    (work / 'AUDIO' / 'SONG.STR').write_bytes(bytes(4096))
    summary = await pipeline.run_game(work, jobs=1)
    assert set(summary) == {'GEN/MAIN.ARK', 'disc_audio'}
    assert summary['disc_audio'] == '1 disc .str songs converted'
    assert 'milo: 1 archives decomposed' in summary['GEN/MAIN.ARK']
    assert (work / 'GEN' / 'MAIN' / 'gen' / 'ship_tex.png').is_file()
    assert (work / 'AUDIO' / 'SONG.wav').read_bytes()[:4] == b'RIFF'
    # Without --delete the materialised ARK and STR are kept.
    assert (work / 'GEN' / 'MAIN.ARK').is_file()
    assert (work / 'AUDIO' / 'SONG.STR').is_file()


@pytest.mark.asyncio
async def test_run_game_deletes_disc_intermediates(make_amp_ark: _Builder, tmp_path: Path) -> None:
    work = tmp_path / 'work'
    (work / 'GEN').mkdir(parents=True)
    (work / 'AUDIO').mkdir()
    (work / 'GEN' / 'MAIN.ARK').write_bytes(make_amp_ark((('gen/a.txt', b'AAA'),)))
    (work / 'AUDIO' / 'SONG.STR').write_bytes(bytes(4096))
    summary = await pipeline.run_game(work, delete=True, jobs=1)
    assert (work / 'AUDIO' / 'SONG.wav').read_bytes()[:4] == b'RIFF'
    assert not (work / 'GEN' / 'MAIN.ARK').exists()  # The ARK archive is removed.
    assert not (work / 'AUDIO' / 'SONG.STR').exists()  # The disc-audio source is removed.
    assert summary['deleted'].endswith('removed')


@pytest.mark.asyncio
async def test_run_game_keeps_unconverted_str_on_delete(make_amp_ark: _Builder,
                                                        mocker: MockerFixture,
                                                        tmp_path: Path) -> None:
    work = tmp_path / 'work'
    (work / 'GEN').mkdir(parents=True)
    (work / 'AUDIO').mkdir()
    (work / 'GEN' / 'MAIN.ARK').write_bytes(make_amp_ark((('gen/a.txt', b'AAA'),)))
    (work / 'AUDIO' / 'SONG.STR').write_bytes(bytes(4096))
    mocker.patch('destin.harmonix.workers.str_to_wav_file', side_effect=ValueError('boom'))
    await pipeline.run_game(work, delete=True, ignore_failures=True, jobs=1)
    assert not (work / 'GEN' / 'MAIN.ARK').exists()  # The ARK still unpacked and is removed.
    assert (work / 'AUDIO' / 'SONG.STR').is_file()  # A STR that failed to convert is kept.


@pytest.mark.asyncio
async def test_run_game_reports_status(make_amp_ark: _Builder, make_hmx_bitmap: _Builder,
                                       make_dtb: _Builder, make_milo: _Builder,
                                       make_v14_mesh: _Builder, make_samp_bank: _Builder,
                                       make_vag: _Builder, tmp_path: Path) -> None:
    work = tmp_path / 'work'
    (work / 'GEN').mkdir(parents=True)
    (work / 'AUDIO').mkdir()
    entries = _ark_entries(make_hmx_bitmap, make_dtb, make_milo, make_v14_mesh, make_samp_bank,
                           make_vag)
    (work / 'GEN' / 'MAIN.ARK').write_bytes(make_amp_ark(entries))
    (work / 'AUDIO' / 'SONG.STR').write_bytes(bytes(4096))
    statuses: list[str] = []
    await pipeline.run_game(work, jobs=1, on_status=statuses.append)
    assert 'Unpacking GEN/MAIN.ARK' in statuses
    assert 'Decomposing Milo scenes' in statuses
    assert 'Converting assets' in statuses
    assert 'Converting disc audio' in statuses


@pytest.mark.asyncio
async def test_run_game_convert_without_disc_audio(make_amp_ark: _Builder, tmp_path: Path) -> None:
    work = tmp_path / 'work'
    (work / 'ARK').mkdir(parents=True)
    (work / 'ARK' / 'ROOT.ark').write_bytes(make_amp_ark((('gen/a.txt', b'AAA'),)))
    summary = await pipeline.run_game(work)
    assert 'disc_audio' not in summary


@pytest.mark.asyncio
async def test_run_game_without_disc_audio(make_amp_ark: _Builder, tmp_path: Path) -> None:
    work = tmp_path / 'work'
    (work / 'ARK').mkdir(parents=True)
    (work / 'ARK' / 'ROOT.ark').write_bytes(make_amp_ark((('gen/a.txt', b'AAA'),)))
    summary = await pipeline.run_game(work, convert=False)
    assert list(summary) == ['ARK/ROOT.ark']
    assert (work / 'ARK' / 'ROOT' / 'gen' / 'a.txt').is_file()


@pytest.mark.asyncio
async def test_run_game_without_arks(tmp_path: Path) -> None:
    work = tmp_path / 'work'
    work.mkdir()
    with pytest.raises(FileNotFoundError, match=r'No \.ark files found'):
        await pipeline.run_game(work)
