"""Tests for :py:mod:`destin.jubeatplus.pipeline`."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
import json
import plistlib
import zipfile

import pytest

from destin.jubeatplus.pipeline import find_bundle, unpack

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def test_every_action_succeeds(unpacked: tuple[dict[str, Any], Path]) -> None:
    stats, _ = unpacked
    assert all(step.fail == 0 for step in stats.values())


def test_every_file_is_planned_as_its_own_kind(unpacked: tuple[dict[str, Any], Path]) -> None:
    # One count per file in the bundle, so a file routed to the wrong converter, counted twice, or
    # left out of the walk shows up here rather than only in whichever output test happens to look.
    stats, _ = unpacked
    assert {
        action: step.ok
        for action, step in stats.items()
    } == {
        'copy': 1,
        'coredata': 1,
        'jbt': 1,
        'macho': 1,
        'plist': 2,
        'png': 1,
        'strings': 1,
        'tex': 1,
        'zip': 1
    }
    assert list(stats) == sorted(stats)


def test_the_png_is_defried(unpacked: tuple[dict[str, Any], Path]) -> None:
    _, root = unpacked
    assert b'CgBI' not in (root / 'icon.png').read_bytes()


def test_the_texture_becomes_a_png(unpacked: tuple[dict[str, Any], Path]) -> None:
    _, root = unpacked
    written = root / 'texture.png'
    assert written.is_file()
    assert b'CgBI' not in written.read_bytes()
    assert not (root / 'texture.tex').exists()


def test_the_strings_table_becomes_json(unpacked: tuple[dict[str, Any], Path]) -> None:
    _, root = unpacked
    written = root / 'en.lproj' / 'Localizable.strings.json'
    assert json.loads(written.read_text()) == {'Key': 'Value'}


def test_the_settings_plist_becomes_json(unpacked: tuple[dict[str, Any], Path]) -> None:
    _, root = unpacked
    settings = json.loads((root / 'DefaultSettings.plist.json').read_text())
    assert settings['PrefTheme'] == 2
    assert settings['PrefjubeatLabURL']['deciphered'] == 'https://example.invalid/'


def test_the_tune_package_becomes_a_directory(unpacked: tuple[dict[str, Any], Path]) -> None:
    _, root = unpacked
    tune = root / 'Music' / '100000201'
    assert sorted(
        p.name for p in tune.iterdir()) == ['artwork.png', 'bgm.m4a', 'info.json', 'seq_bas.json']


def test_the_marker_zip_becomes_a_directory(unpacked: tuple[dict[str, Any], Path]) -> None:
    _, root = unpacked
    assert (root / 'mk0026' / 'markers' / 'ma00.png').is_file()


def test_the_executable_gets_a_properties_file(unpacked: tuple[dict[str, Any], Path]) -> None:
    _, root = unpacked
    info = json.loads((root / 'Example.macho.json').read_text())
    assert info['architectures'][0]['architecture'] == 'arm64'
    assert info['name'] == 'Example'


def test_an_unrecognised_file_is_copied(unpacked: tuple[dict[str, Any], Path]) -> None:
    _, root = unpacked
    assert (root / 'PkgInfo').read_bytes() == b'APPL????'


def test_an_empty_sc_info_writes_no_report(unpacked: tuple[dict[str, Any], Path]) -> None:
    stats, root = unpacked
    assert not (root / 'SC_Info.json').exists()
    assert 'sc_info' not in stats


def test_the_source_is_untouched(tmp_path: Path, make_bundle: Callable[..., Path],
                                 fake_ffmpeg: Path, fake_pngdefry: Path) -> None:
    root = make_bundle()
    before = {p.relative_to(root): p.stat().st_mtime for p in sorted(root.rglob('*'))}
    unpack(root, tmp_path / 'out', ffmpeg=fake_ffmpeg, pngdefry=fake_pngdefry, workers=1)
    after = {p.relative_to(root): p.stat().st_mtime for p in sorted(root.rglob('*'))}
    assert before == after


def test_unpacking_an_ipa(tmp_path: Path, make_ipa: Callable[[], Path], fake_ffmpeg: Path,
                          fake_pngdefry: Path) -> None:
    out = tmp_path / 'out'
    unpack(make_ipa(), out, ffmpeg=fake_ffmpeg, pngdefry=fake_pngdefry, workers=1)
    assert (out / 'Example.app' / 'texture.png').is_file()
    # The staging directory the archive was unpacked into is gone again.
    assert sorted(p.name for p in out.iterdir()) == ['Example.app']


def test_no_audio_copies_the_sound_effects(tmp_path: Path, make_bundle: Callable[..., Path],
                                           fake_pngdefry: Path) -> None:
    root = make_bundle()
    bundle = root / 'Payload' / 'Example.app'
    (bundle / 'SD_GO.caf').write_bytes(b'caff\0\1\0\0')
    out = tmp_path / 'out'
    unpack(root, out, pngdefry=fake_pngdefry, workers=1)
    assert (out / 'Example.app' / 'SD_GO.caf').read_bytes() == b'caff\0\1\0\0'


def test_audio_becomes_wav(tmp_path: Path, make_bundle: Callable[..., Path], fake_ffmpeg: Path,
                           fake_pngdefry: Path) -> None:
    root = make_bundle()
    (root / 'Payload' / 'Example.app' / 'SD_GO.caf').write_bytes(b'caff\0\1\0\0')
    out = tmp_path / 'out'
    unpack(root, out, ffmpeg=fake_ffmpeg, pngdefry=fake_pngdefry, workers=1)
    assert (out / 'Example.app' / 'SD_GO.wav').read_bytes().startswith(b'RIFF')


def test_no_pngdefry_copies_the_images(tmp_path: Path, make_bundle: Callable[..., Path]) -> None:
    out = tmp_path / 'out'
    unpack(make_bundle(), out, workers=1)
    assert b'CgBI' in (out / 'Example.app' / 'icon.png').read_bytes()


def test_a_failing_converter_is_counted_not_raised(tmp_path: Path, make_bundle: Callable[..., Path],
                                                   fake_pngdefry: Path,
                                                   caplog: pytest.LogCaptureFixture) -> None:
    root = make_bundle()
    (root / 'Payload' / 'Example.app' / 'broken.tex').write_bytes(b'not enciphered')
    with caplog.at_level('WARNING'):
        stats = unpack(root, tmp_path / 'out', pngdefry=fake_pngdefry, workers=1)
    assert stats['tex'].fail == 1
    assert stats['tex'].ok == 1
    assert 'broken.tex' in caplog.text


def test_many_failures_are_summarised(tmp_path: Path, make_bundle: Callable[..., Path],
                                      caplog: pytest.LogCaptureFixture) -> None:
    root = make_bundle()
    bundle = root / 'Payload' / 'Example.app'
    for index in range(12):
        (bundle / f'broken{index:02d}.tex').write_bytes(b'not enciphered')
    with caplog.at_level('WARNING'):
        unpack(root, tmp_path / 'out', workers=1)
    assert 'further failure(s) not listed' in caplog.text


def test_sc_info_is_described_when_it_holds_records(tmp_path: Path, make_bundle: Callable[...,
                                                                                          Path],
                                                    minimal_sinf: bytes) -> None:
    root = make_bundle()
    (root / 'Payload' / 'Example.app' / 'SC_Info' / 'Example.sinf').write_bytes(minimal_sinf)
    out = tmp_path / 'out'
    stats = unpack(root, out, workers=1)
    assert stats['sc_info'].ok == 1
    assert json.loads((out / 'Example.app' / 'SC_Info.json').read_text())[0]['records']


def test_a_bundle_with_no_sc_info_directory(tmp_path: Path, make_bundle: Callable[..., Path],
                                            caplog: pytest.LogCaptureFixture) -> None:
    root = make_bundle()
    (root / 'Payload' / 'Example.app' / 'SC_Info').rmdir()
    with caplog.at_level('INFO'):
        stats = unpack(root, tmp_path / 'out', workers=1)
    assert 'sc_info' not in stats
    assert 'No SC_Info to describe' in caplog.text


@pytest.mark.parametrize('layout', ['payload', 'bare', 'app'])
def test_every_accepted_layout(tmp_path: Path, make_bundle: Callable[..., Path],
                               layout: str) -> None:
    out = tmp_path / 'out'
    unpack(make_bundle(layout), out, workers=1)
    assert (out / 'Example.app' / 'Info.plist.json').is_file()


def test_find_bundle_rejects_a_directory_with_no_bundle(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r'No \.app bundle at or below'):
        find_bundle(tmp_path)


def test_unpack_rejects_an_archive_with_no_payload(tmp_path: Path) -> None:
    path = tmp_path / 'Empty.ipa'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('readme.txt', b'nothing here')
    with pytest.raises(ValueError, match='No Payload directory inside'):
        unpack(path, tmp_path / 'out', workers=1)


def test_an_info_plist_that_cannot_be_read_is_skipped(tmp_path: Path,
                                                      make_bundle: Callable[..., Path]) -> None:
    root = make_bundle()
    bundle = root / 'Payload' / 'Example.app'
    (bundle / 'Broken.bundle').mkdir()
    (bundle / 'Broken.bundle' / 'Info.plist').write_bytes(b'not a property list')
    out = tmp_path / 'out'
    stats = unpack(root, out, workers=1)
    # The unreadable Info.plist still fails its own conversion, but it does not stop the walk.
    assert stats['plist'].fail == 1
    assert (out / 'Example.app' / 'Example.macho.json').is_file()


def test_an_info_plist_naming_a_missing_executable(tmp_path: Path,
                                                   make_bundle: Callable[..., Path]) -> None:
    root = make_bundle()
    bundle = root / 'Payload' / 'Example.app'
    (bundle / 'Widget.bundle').mkdir()
    (bundle / 'Widget.bundle' / 'Info.plist').write_bytes(
        plistlib.dumps({'CFBundleExecutable': 'Absent'}))
    out = tmp_path / 'out'
    assert unpack(root, out, workers=1)['plist'].fail == 0


def test_a_bare_macho_with_no_info_plist_entry(tmp_path: Path, make_bundle: Callable[..., Path],
                                               macho_arm64_bytes: bytes) -> None:
    root = make_bundle()
    (root / 'Payload' / 'Example.app' / 'helper').write_bytes(macho_arm64_bytes)
    out = tmp_path / 'out'
    assert unpack(root, out, workers=1)['macho'].ok == 2
    assert (out / 'Example.app' / 'helper.macho.json').is_file()


def test_the_core_data_model_becomes_json(unpacked: tuple[dict[str, Any], Path]) -> None:
    _, root = unpacked
    assert json.loads((root / 'MapScore.cdm.json').read_text()) == {'entityMappings': []}
