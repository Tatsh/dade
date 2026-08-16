"""Tests for :py:mod:`destin.jubeatplus.archives` and :py:mod:`destin.jubeatplus.audio`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json
import plistlib
import subprocess as sp
import zipfile

from destin.common.bfcodec import BFCodec
from destin.jubeatplus.archives import unpack_jbt, unpack_zip
from destin.jubeatplus.audio import caf_to_wav
from destin.jubeatplus.cipher import bgm_key, texture_key, tune_info_key
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def test_unpack_jbt_names_every_entry(tmp_path: Path, make_jbt: Callable[..., Path],
                                      fake_pngdefry: Path) -> None:
    written = unpack_jbt(make_jbt(), tmp_path / 'out', fake_pngdefry)
    assert sorted(
        p.name for p in written) == ['artwork.png', 'bgm.m4a', 'info.json', 'seq_bas.json']


def test_unpack_jbt_decodes_the_metadata(tmp_path: Path, make_jbt: Callable[..., Path],
                                         tune_info: dict[str, object], fake_pngdefry: Path) -> None:
    unpack_jbt(make_jbt(), tmp_path / 'out', fake_pngdefry)
    assert json.loads((tmp_path / 'out' / 'info.json').read_text()) == tune_info


def test_unpack_jbt_decodes_the_chart(tmp_path: Path, make_jbt: Callable[..., Path],
                                      fake_pngdefry: Path) -> None:
    unpack_jbt(make_jbt(), tmp_path / 'out', fake_pngdefry)
    chart = json.loads((tmp_path / 'out' / 'seq_bas.json').read_text())
    assert chart['difficulty'] == 'basic'
    assert chart['counts'] == {'end': 1, 'tap': 1, 'tempo': 1}


def test_unpack_jbt_writes_the_audio_stream_whole(tmp_path: Path, make_jbt: Callable[...,
                                                                                     Path]) -> None:
    source = make_jbt()
    with zipfile.ZipFile(source) as archive:
        expected = BFCodec(bgm_key()).decipher(archive.read('bgm'))
    unpack_jbt(source, tmp_path / 'out')
    assert (tmp_path / 'out' / 'bgm.m4a').read_bytes() == expected


def test_unpack_jbt_leaves_the_artwork_a_whole_png(tmp_path: Path, make_jbt: Callable[..., Path],
                                                   make_png: Callable[..., bytes],
                                                   fake_pngdefry: Path) -> None:
    unpack_jbt(make_jbt(), tmp_path / 'out', fake_pngdefry)
    assert (tmp_path / 'out' / 'artwork.png').read_bytes() == make_png(2, 2)


def test_unpack_jbt_defries_the_artwork(tmp_path: Path, make_jbt: Callable[..., Path],
                                        fake_pngdefry: Path) -> None:
    unpack_jbt(make_jbt(), tmp_path / 'out', fake_pngdefry)
    assert b'CgBI' not in (tmp_path / 'out' / 'artwork.png').read_bytes()


def test_unpack_jbt_without_pngdefry_keeps_the_artwork_as_it_is(
        tmp_path: Path, make_jbt: Callable[..., Path]) -> None:
    unpack_jbt(make_jbt(), tmp_path / 'out')
    assert b'CgBI' in (tmp_path / 'out' / 'artwork.png').read_bytes()


def test_unpack_jbt_reads_the_v2_metadata_entry(tmp_path: Path, make_jbt: Callable[...,
                                                                                   Path]) -> None:
    unpack_jbt(make_jbt('infov2'), tmp_path / 'out')
    assert (tmp_path / 'out' / 'infov2.json').is_file()


def test_unpack_jbt_reads_the_v3_metadata_entry(tmp_path: Path, tune_info: dict[str,
                                                                                object]) -> None:
    # infov3 is keyed with the tune-info key and carries the four-byte header the others lack.
    path = tmp_path / 'tune.jbt'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('infov3',
                         BFCodec(tune_info_key()).encipher(b'\0\0\0\0' + plistlib.dumps(tune_info)))
    unpack_jbt(path, tmp_path / 'out')
    assert json.loads((tmp_path / 'out' / 'infov3.json').read_text()) == tune_info


def test_unpack_jbt_warns_about_a_bad_digest(tmp_path: Path, make_jbt: Callable[..., Path],
                                             caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level('WARNING'):
        unpack_jbt(make_jbt(corrupt_digest=True), tmp_path / 'out')
    assert 'MD5 trailer' in caplog.text


def test_unpack_jbt_still_unpacks_an_archive_with_no_trailer(
        tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = tmp_path / 'tiny.jbt'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('note', b'plain')
    with caplog.at_level('WARNING'):
        assert unpack_jbt(path, tmp_path / 'out') == (tmp_path / 'out' / 'note',)
    assert 'MD5 trailer' in caplog.text


def test_unpack_jbt_rejects_a_file_that_is_not_a_zip(tmp_path: Path) -> None:
    path = tmp_path / 'stub.jbt'
    path.write_bytes(b'far too short')
    with pytest.raises(zipfile.BadZipFile):
        unpack_jbt(path, tmp_path / 'out')


def test_an_entry_deciphering_to_less_than_a_header(tmp_path: Path) -> None:
    # A marker ZIP entry whose plaintext cannot hold the four-byte header is kept as it is rather
    # than sliced into nothing.
    path = tmp_path / 'mk9999.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('ma00', BFCodec(texture_key()).encipher(b'ab'))
    written = unpack_zip(path, tmp_path / 'out')
    assert written[0].read_bytes() == BFCodec(texture_key()).encipher(b'ab')


def test_unpack_zip_decodes_the_images(tmp_path: Path, marker_zip: Path,
                                       fake_pngdefry: Path) -> None:
    written = unpack_zip(marker_zip, tmp_path / 'out', fake_pngdefry)
    assert sorted(p.name for p in written) == ['filename.txt', 'ma00.png', 'settings.plist.json']
    assert b'CgBI' not in (tmp_path / 'out' / 'markers' / 'ma00.png').read_bytes()


def test_unpack_zip_keeps_a_plain_entry_as_it_is(tmp_path: Path, marker_zip: Path) -> None:
    unpack_zip(marker_zip, tmp_path / 'out')
    assert (tmp_path / 'out' / 'markers' / 'filename.txt').read_bytes() == b'classic'


def test_unpack_zip_decodes_a_plain_property_list(tmp_path: Path, marker_zip: Path) -> None:
    unpack_zip(marker_zip, tmp_path / 'out')
    written = tmp_path / 'out' / 'markers' / 'settings.plist.json'
    assert json.loads(written.read_text()) == {'frames': 24}


def test_unpack_zip_rejects_a_file_that_is_not_a_zip(tmp_path: Path) -> None:
    path = tmp_path / 'broken.zip'
    path.write_bytes(b'not a ZIP')
    with pytest.raises(zipfile.BadZipFile):
        unpack_zip(path, tmp_path / 'out')


def test_an_entry_that_looks_like_a_plist_but_is_not(tmp_path: Path) -> None:
    path = tmp_path / 'tune.jbt'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('odd', BFCodec(bgm_key()).encipher(b'bplist00 but truncated'))
    written = unpack_jbt(path, tmp_path / 'out')
    assert written == (tmp_path / 'out' / 'odd',)


def test_caf_to_wav(tmp_path: Path, fake_ffmpeg: Path) -> None:
    source = tmp_path / 'sound.caf'
    source.write_bytes(b'caff\0\1\0\0')
    destination = tmp_path / 'sound.wav'
    assert caf_to_wav(source, destination, fake_ffmpeg) == destination
    assert destination.read_bytes().startswith(b'RIFF')


def test_caf_to_wav_propagates_a_failure(tmp_path: Path, failing_tool: Path) -> None:
    source = tmp_path / 'sound.caf'
    source.write_bytes(b'caff\0\1\0\0')
    with pytest.raises(sp.CalledProcessError):
        caf_to_wav(source, tmp_path / 'sound.wav', failing_tool)
