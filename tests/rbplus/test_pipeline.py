"""Tests for :py:mod:`dade.rbplus.pipeline`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json
import os
import plistlib
import zipfile

import pytest

from dade.rbplus.pipeline import Action, StepStats, extract_assets, extract_ipa, find_bundle, unpack

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pytest_mock import MockerFixture


def _out(app_bundle: Path, output_dir: Path) -> Path:
    return output_dir / 'Rb'


def test_find_bundle_accepts_the_bundle_itself(app_bundle: Path) -> None:
    bundle = app_bundle / 'Payload' / 'Rb.app'
    assert find_bundle(bundle) == bundle


def test_find_bundle_accepts_the_payload_directory(app_bundle: Path) -> None:
    assert find_bundle(app_bundle / 'Payload').name == 'Rb.app'


def test_find_bundle_accepts_the_directory_holding_payload(app_bundle: Path) -> None:
    assert find_bundle(app_bundle).name == 'Rb.app'


def test_find_bundle_rejects_a_directory_with_no_bundle(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r'No \.app bundle'):
        find_bundle(tmp_path)


def test_extract_ipa_returns_the_payload(tmp_path: Path, app_bundle: Path) -> None:
    archive = tmp_path / 'Rb.ipa'
    with zipfile.ZipFile(archive, 'w') as zipped:
        for path in (app_bundle / 'Payload').rglob('*'):
            if path.is_file():
                zipped.write(path, path.relative_to(app_bundle))
    assert extract_ipa(archive, tmp_path / 'staging').name == 'Payload'


def test_extract_ipa_rejects_an_archive_without_payload(tmp_path: Path) -> None:
    archive = tmp_path / 'wrong.ipa'
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('Something/else.txt', b'x')
    with pytest.raises(ValueError, match='No Payload directory'):
        extract_ipa(archive, tmp_path / 'staging')


def test_unpack_converts_every_kind(app_bundle: Path, tmp_path: Path) -> None:
    stats = unpack(app_bundle, tmp_path / 'out', workers=1)
    assert stats[Action.PACKAGE] == StepStats(0, 1)
    assert stats[Action.IMAGE] == StepStats(0, 1)
    assert stats[Action.PLIST] == StepStats(0, 1)
    assert stats[Action.STRINGS] == StepStats(0, 1)
    assert all(result.fail == 0 for result in stats.values())


def test_unpack_mirrors_the_bundle(app_bundle: Path, tmp_path: Path) -> None:
    unpack(app_bundle, tmp_path / 'out', workers=1)
    out = tmp_path / 'out' / 'Rb'
    assert (out / 'loose.png').is_file()
    assert (out / 'readme.txt').read_bytes() == b'copied verbatim'
    assert (out / 'Info.plist.json').is_file()
    assert (out / 'en.lproj' / 'Localizable.strings.json').is_file()


def test_unpack_leaves_the_executable_behind(app_bundle: Path, tmp_path: Path) -> None:
    unpack(app_bundle, tmp_path / 'out', workers=1)
    out = tmp_path / 'out' / 'Rb'
    assert not (out / 'Rb').exists()
    assert not (out / 'Rb.macho.json').exists()


def test_unpack_writes_a_tune_package_directory(app_bundle: Path, tmp_path: Path) -> None:
    unpack(app_bundle, tmp_path / 'out', workers=1)
    tune = tmp_path / 'out' / 'Rb' / '100000109'
    assert json.loads((tune / 'info.json').read_text())['ID'] == 100000109
    assert (tune / 'note_bas.json').is_file()
    assert (tune / 'note_bas.png').is_file()
    assert (tune / 'artwork.png').is_file()
    assert (tune / 'bgm.m4a').is_file()


def test_unpack_can_skip_the_chart_images(app_bundle: Path, tmp_path: Path) -> None:
    unpack(app_bundle, tmp_path / 'out', render=False, workers=1)
    tune = tmp_path / 'out' / 'Rb' / '100000109'
    assert (tune / 'note_bas.json').is_file()
    assert not (tune / 'note_bas.png').exists()


def test_unpack_copies_audio_without_ffmpeg(app_bundle: Path, tmp_path: Path) -> None:
    unpack(app_bundle, tmp_path / 'out', ffmpeg=None, workers=1)
    assert (tmp_path / 'out' / 'Rb' / 'sound.caf').is_file()


def test_unpack_converts_audio_with_ffmpeg(app_bundle: Path, tmp_path: Path, ffmpeg: Path) -> None:
    unpack(app_bundle, tmp_path / 'out', ffmpeg=ffmpeg, workers=1)
    written = tmp_path / 'out' / 'Rb' / 'sound.wav'
    assert written.read_bytes().startswith(b'RIFF')
    assert not (tmp_path / 'out' / 'Rb' / 'sound.caf').exists()


def test_unpack_copies_m4a_rather_than_converting_it(app_bundle: Path, tmp_path: Path,
                                                     ffmpeg: Path) -> None:
    unpack(app_bundle, tmp_path / 'out', ffmpeg=ffmpeg, workers=1)
    assert (tmp_path / 'out' / 'Rb' / 'tune.m4a').is_file()
    assert not (tmp_path / 'out' / 'Rb' / 'tune.wav').exists()


def test_unpack_leaves_pngs_alone_without_pngdefry(app_bundle: Path, tmp_path: Path) -> None:
    unpack(app_bundle, tmp_path / 'out', pngdefry=None, workers=1)
    assert b'CgBI' in (tmp_path / 'out' / 'Rb' / 'loose.png').read_bytes()[:32]


def test_unpack_defries_pngs_with_pngdefry(app_bundle: Path, tmp_path: Path,
                                           pngdefry: Path) -> None:
    unpack(app_bundle, tmp_path / 'out', pngdefry=pngdefry, workers=1)
    out = tmp_path / 'out' / 'Rb'
    assert b'CgBI' not in (out / 'loose.png').read_bytes()[:32]
    # The images inside a tune package go through the same conversion.
    assert b'CgBI' not in (out / '100000109' / 'artwork.png').read_bytes()[:32]


def test_unpack_leaves_an_ordinary_png_alone(app_bundle: Path, tmp_path: Path, pngdefry: Path,
                                             make_png: Callable[..., bytes]) -> None:
    plain = make_png()
    (app_bundle / 'Payload' / 'Rb.app' / 'plain.png').write_bytes(plain)
    unpack(app_bundle, tmp_path / 'out', pngdefry=pngdefry, workers=1)
    assert (tmp_path / 'out' / 'Rb' / 'plain.png').read_bytes() == plain


def test_unpack_reports_a_package_that_will_not_open(app_bundle: Path, tmp_path: Path) -> None:
    (app_bundle / 'Payload' / 'Rb.app' / 'broken.rb').write_bytes(b'not a zip')
    stats = unpack(app_bundle, tmp_path / 'out', workers=1)
    assert stats[Action.PACKAGE] == StepStats(1, 1)


def test_unpack_keeps_a_chart_that_will_not_parse(tmp_path: Path, app_bundle: Path,
                                                  make_package: Callable[..., Path]) -> None:
    package = make_package(name='999999999.rb', entries={'note_bas': b'NOTACHART' + bytes(64)})
    (app_bundle / 'Payload' / 'Rb.app' / package.name).write_bytes(package.read_bytes())
    unpack(app_bundle, tmp_path / 'out', workers=1)
    assert (tmp_path / 'out' / 'Rb' / '999999999' / 'note_bas.bin').is_file()


def test_unpack_accepts_an_ipa(tmp_path: Path, app_bundle: Path) -> None:
    archive = tmp_path / 'Rb.ipa'
    with zipfile.ZipFile(archive, 'w') as zipped:
        for path in (app_bundle / 'Payload').rglob('*'):
            if path.is_file():
                zipped.write(path, path.relative_to(app_bundle))
    stats = unpack(archive, tmp_path / 'out', workers=1)
    assert stats[Action.PACKAGE] == StepStats(0, 1)
    assert (tmp_path / 'out' / 'Rb' / 'readme.txt').is_file()


def test_unpack_reports_sc_info_when_there_is_some(app_bundle: Path, tmp_path: Path,
                                                   mocker: MockerFixture) -> None:
    record = mocker.Mock(records=[object()])
    mocker.patch('dade.rbplus.pipeline.read_bundles', return_value=[record])
    mocker.patch('dade.rbplus.pipeline.sc_info_to_json', return_value={'ok': True})
    stats = unpack(app_bundle, tmp_path / 'out', workers=1)
    assert stats['sc-info'] == StepStats(0, 1)
    assert (tmp_path / 'out' / 'Rb' / 'SC_Info.json').is_file()


def test_unpack_says_nothing_when_sc_info_is_empty(app_bundle: Path, tmp_path: Path,
                                                   mocker: MockerFixture) -> None:
    mocker.patch('dade.rbplus.pipeline.read_bundles', return_value=[])
    stats = unpack(app_bundle, tmp_path / 'out', workers=1)
    assert 'sc-info' not in stats


def test_unpack_survives_an_unreadable_sc_info(app_bundle: Path, tmp_path: Path,
                                               mocker: MockerFixture) -> None:
    mocker.patch('dade.rbplus.pipeline.read_bundles', side_effect=ValueError('none here'))
    assert 'sc-info' not in unpack(app_bundle, tmp_path / 'out', workers=1)


def test_unpack_skips_the_sc_info_directory_itself(app_bundle: Path, tmp_path: Path) -> None:
    sc_info = app_bundle / 'Payload' / 'Rb.app' / 'SC_Info'
    sc_info.mkdir()
    (sc_info / 'Rb.sinf').write_bytes(b'sinf bytes')
    unpack(app_bundle, tmp_path / 'out', workers=1)
    assert not (tmp_path / 'out' / 'Rb' / 'SC_Info' / 'Rb.sinf').exists()


def test_extract_assets_writes_every_entry(make_asset_archive: Callable[..., Path], tmp_path: Path,
                                           make_png: Callable[..., bytes]) -> None:
    archive = make_asset_archive(entries={
        'a.png': make_png(),
        'sub/b.png': make_png()
    },
                                 manifest=('a.png', 'sub/b.png'))
    stats = extract_assets(archive, tmp_path / 'out', workers=1)
    assert stats[Action.IMAGE] == StepStats(0, 2)
    assert stats['manifest'] == StepStats(0, 1)
    assert (tmp_path / 'out' / 'iPad' / 'a.png').is_file()
    assert (tmp_path / 'out' / 'iPad' / 'sub' / 'b.png').is_file()


def test_extract_assets_writes_the_manifest(make_asset_archive: Callable[..., Path],
                                            tmp_path: Path) -> None:
    archive = make_asset_archive(entries={'a.png': b'x'}, manifest=('a.png', 'b.png'))
    extract_assets(archive, tmp_path / 'out', workers=1)
    assert json.loads(
        (tmp_path / 'out' / 'iPad' / 'manifest.json').read_text()) == ['a.png', 'b.png']


def test_extract_assets_without_a_manifest(make_asset_archive: Callable[..., Path],
                                           tmp_path: Path) -> None:
    stats = extract_assets(make_asset_archive(entries={'a.png': b'x'}), tmp_path / 'out', workers=1)
    assert 'manifest' not in stats
    assert not (tmp_path / 'out' / 'iPad' / 'manifest.json').exists()


def test_extract_assets_defries_only_apple_pngs(make_asset_archive: Callable[..., Path],
                                                tmp_path: Path, make_png: Callable[..., bytes],
                                                pngdefry: Path) -> None:
    plain = make_png()
    archive = make_asset_archive(entries={'plain.png': plain, 'apple.png': make_png(cgbi=True)})
    extract_assets(archive, tmp_path / 'out', pngdefry=pngdefry, workers=1)
    out = tmp_path / 'out' / 'iPad'
    assert b'CgBI' not in (out / 'apple.png').read_bytes()[:32]
    assert (out / 'plain.png').read_bytes() == plain


def test_extract_assets_leaves_pngs_alone_without_pngdefry(make_asset_archive: Callable[..., Path],
                                                           tmp_path: Path,
                                                           make_png: Callable[..., bytes]) -> None:
    archive = make_asset_archive(entries={'apple.png': make_png(cgbi=True)})
    extract_assets(archive, tmp_path / 'out', pngdefry=None, workers=1)
    assert b'CgBI' in (tmp_path / 'out' / 'iPad' / 'apple.png').read_bytes()[:32]


def test_extract_assets_reports_an_entry_it_cannot_write(make_asset_archive: Callable[..., Path],
                                                         tmp_path: Path,
                                                         mocker: MockerFixture) -> None:
    mocker.patch('pathlib.Path.write_bytes', side_effect=OSError('disk full'))
    archive = make_asset_archive(entries={'a.png': b'x'})
    assert extract_assets(archive, tmp_path / 'out', workers=1)[Action.IMAGE] == StepStats(1, 0)


def test_extract_assets_handles_a_rootless_archive(tmp_path: Path) -> None:
    archive = tmp_path / 'flat.zip'
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('a.png', b'x')
    extract_assets(archive, tmp_path / 'out', workers=1)
    assert (tmp_path / 'out' / 'flat' / 'a.png').is_file()


def test_extract_assets_uses_more_than_one_chunk(make_asset_archive: Callable[..., Path],
                                                 tmp_path: Path) -> None:
    entries = {f'{index}.png': b'x' for index in range(9)}
    stats = extract_assets(make_asset_archive(entries=entries), tmp_path / 'out', workers=4)
    assert stats[Action.IMAGE] == StepStats(0, 9)


def test_a_plist_that_will_not_parse_is_reported(app_bundle: Path, tmp_path: Path) -> None:
    (app_bundle / 'Payload' / 'Rb.app' / 'Broken.plist').write_bytes(b'not a plist')
    assert unpack(app_bundle, tmp_path / 'out', workers=1)[Action.PLIST] == StepStats(1, 1)


def test_a_core_data_model_is_converted(app_bundle: Path, tmp_path: Path,
                                        mocker: MockerFixture) -> None:
    (app_bundle / 'Payload' / 'Rb.app' / 'History.mom').write_bytes(b'mom bytes')
    mocker.patch('dade.rbplus.pipeline.convert_coredata', return_value={'entities': []})
    assert unpack(app_bundle, tmp_path / 'out', workers=1)[Action.COREDATA] == StepStats(0, 1)
    assert (tmp_path / 'out' / 'Rb' / 'History.mom.json').is_file()


def test_a_binary_plist_strings_table_is_converted(app_bundle: Path, tmp_path: Path) -> None:
    unpack(app_bundle, tmp_path / 'out', workers=1)
    written = tmp_path / 'out' / 'Rb' / 'en.lproj' / 'Localizable.strings.json'
    assert json.loads(written.read_text()) == {'key': 'value'}


def test_many_failures_are_summarised(app_bundle: Path, tmp_path: Path,
                                      caplog: pytest.LogCaptureFixture) -> None:
    bundle = app_bundle / 'Payload' / 'Rb.app'
    for index in range(12):
        (bundle / f'broken{index}.rb').write_bytes(b'not a zip')
    with caplog.at_level('WARNING'):
        stats = unpack(app_bundle, tmp_path / 'out', workers=1)
    assert stats[Action.PACKAGE].fail == 12
    assert 'further failure(s) not listed' in caplog.text


def test_many_archive_failures_are_summarised(make_asset_archive: Callable[..., Path],
                                              tmp_path: Path, mocker: MockerFixture,
                                              caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch('pathlib.Path.write_bytes', side_effect=OSError('disk full'))
    archive = make_asset_archive(entries={f'{index}.png': b'x' for index in range(12)})
    with caplog.at_level('WARNING'):
        stats = extract_assets(archive, tmp_path / 'out', workers=1)
    assert stats[Action.IMAGE] == StepStats(12, 0)
    assert 'further failure(s) not listed' in caplog.text


@pytest.mark.skipif(os.geteuid() == 0, reason='A root user can read a mode 000 file.')
def test_a_file_that_cannot_be_read_is_not_taken_for_an_executable(app_bundle: Path,
                                                                   tmp_path: Path) -> None:
    unreadable = app_bundle / 'Payload' / 'Rb.app' / 'locked.bin'
    unreadable.write_bytes(b'\xcf\xfa\xed\xfe' + bytes(16))
    unreadable.chmod(0o000)
    try:
        stats = unpack(app_bundle, tmp_path / 'out', workers=1)
    finally:
        unreadable.chmod(0o644)
    # It is not recognised as a Mach-O, so it is copied like any other file, and the copy fails
    # because it still cannot be read.
    assert stats[Action.COPY].fail == 1


def test_an_info_plist_becomes_json(app_bundle: Path, tmp_path: Path) -> None:
    unpack(app_bundle, tmp_path / 'out', workers=1)
    written = tmp_path / 'out' / 'Rb' / 'Info.plist.json'
    assert json.loads(written.read_text()) == {'CFBundleName': 'Rb'}
    assert plistlib.loads((app_bundle / 'Payload' / 'Rb.app' / 'Info.plist').read_bytes())
