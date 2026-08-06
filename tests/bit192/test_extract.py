"""Integration tests for :mod:`destin.bit192.extract`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import io
import zipfile

from destin.bit192 import cz
from destin.bit192.extract import extract
from destin.marmalade.test_utils import build_derbh, build_model, build_resgroup
import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _group(name: str = 'thing') -> bytes:
    model = build_model([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])
    return build_resgroup(name, {'CIwModel': [model]})


def _data_archive() -> bytes:
    return build_derbh([('models/thing.group.bin', _group()), ('snd/x.raw', b'\x00\x01' * 8)])


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def _write_apk(tmp_path: Path, members: dict[str, bytes]) -> Path:
    path = tmp_path / 'app.apk'
    path.write_bytes(_zip_bytes(members))
    return path


def test_extract_apk_decodes_groups_and_raw(tmp_path: Path) -> None:
    apk = _write_apk(tmp_path, {
        'assets/gamedata.dz': _data_archive(),
        'assets/iwgxfontbrowser.group.bin': _group('fonts')
    })
    out = extract([apk], tmp_path / 'out')
    assert list((out / 'gamedata' / 'models' / 'thing' / 'CIwModel').glob('*.obj'))
    assert (out / 'gamedata' / 'snd' / 'x.wav').is_file()
    assert not list(out.rglob('*.group.bin'))  # decoded in place and removed
    assert list((out / 'iwgxfontbrowser' / 'CIwModel').glob('*.obj'))  # standalone group


def test_extract_decrypts_cz(tmp_path: Path) -> None:
    apk = _write_apk(tmp_path, {'assets/enc.cz': cz.decrypt(_data_archive())})
    out = extract([apk], tmp_path / 'out')
    assert list((out / 'enc' / 'models' / 'thing' / 'CIwModel').glob('*.obj'))


def test_extract_keep_group_bin(tmp_path: Path) -> None:
    apk = _write_apk(tmp_path, {'assets/gamedata.dz': _data_archive()})
    out = extract([apk], tmp_path / 'out', keep_group_bin=True)
    assert list(out.rglob('*.group.bin'))


def test_xapk_with_obb_overrides_apk_stub(tmp_path: Path) -> None:
    stub = build_derbh([('models/thing.group.bin', _group('stub'))])
    apk_bytes = _zip_bytes({'assets/gamedata.dz': stub})
    obb_bytes = _zip_bytes({'gamedata.dz': _data_archive()})
    xapk = tmp_path / 'app.xapk'
    xapk.write_bytes(_zip_bytes({'app.apk': apk_bytes, 'Android/obb/x/main.obb': obb_bytes}))
    out = extract([xapk], tmp_path / 'out')
    # The OBB's full-size gamedata.dz (with snd/x.raw) wins over the APK stub.
    assert (out / 'gamedata' / 'snd' / 'x.wav').is_file()


def test_xapk_without_obb_uses_apk_stub(tmp_path: Path) -> None:
    # Bundle carries an APK but no OBB: exercises the 'no obb_name' branch and the no-OBB warning.
    apk_bytes = _zip_bytes({'assets/gamedata.dz': _data_archive()})
    xapk = tmp_path / 'app.xapk'
    xapk.write_bytes(_zip_bytes({'app.apk': apk_bytes}))
    out = extract([xapk], tmp_path / 'out')
    assert (out / 'gamedata' / 'snd' / 'x.wav').is_file()


def test_apk_with_obb_only_bundle(tmp_path: Path) -> None:
    # A bare APK plus a bundle that holds only an OBB: exercises the 'no apk_name in bundle' branch.
    apk = _write_apk(tmp_path, {'assets/gamedata.dz': build_derbh([])})
    obb_bytes = _zip_bytes({'gamedata.dz': _data_archive()})
    xapk = tmp_path / 'obb.xapk'
    xapk.write_bytes(_zip_bytes({'Android/obb/x/main.obb': obb_bytes}))
    out = extract([apk, xapk], tmp_path / 'out')
    assert (out / 'gamedata' / 'snd' / 'x.wav').is_file()


def test_non_asset_and_non_archive_entries_ignored(tmp_path: Path) -> None:
    apk = _write_apk(
        tmp_path, {
            'assets/gamedata.dz': _data_archive(),
            'assets/notes.txt': b'ignored',
            'AndroidManifest.xml': b'<manifest/>'
        })
    out = extract([apk], tmp_path / 'out')
    assert (out / 'gamedata' / 'snd' / 'x.wav').is_file()


def test_obb_non_archive_entries_ignored(tmp_path: Path) -> None:
    apk_bytes = _zip_bytes({'assets/gamedata.dz': build_derbh([])})
    obb_bytes = _zip_bytes({'gamedata.dz': _data_archive(), 'readme.txt': b'ignored'})
    xapk = tmp_path / 'app.xapk'
    xapk.write_bytes(_zip_bytes({'app.apk': apk_bytes, 'Android/obb/x/main.obb': obb_bytes}))
    out = extract([xapk], tmp_path / 'out')
    assert (out / 'gamedata' / 'snd' / 'x.wav').is_file()


def test_cz_with_wrong_keys_is_skipped(tmp_path: Path) -> None:
    # `cz.decrypt` is symmetric, so storing decrypt(non-Derbh) makes it decrypt back to non-Derbh,
    # taking the 'did not decrypt to a Derbh archive' branch.
    apk = _write_apk(tmp_path, {
        'assets/good.dz': _data_archive(),
        'assets/bad.cz': cz.decrypt(bytes(16))
    })
    out = extract([apk], tmp_path / 'out')
    assert (out / 'good' / 'snd' / 'x.wav').is_file()
    assert not (out / 'bad').exists()


def test_image_named_group_bin_is_renamed(tmp_path: Path) -> None:
    apk = _write_apk(
        tmp_path,
        {'assets/gamedata.dz': build_derbh([('art/pic.group.bin', b'\x89PNG\r\n\x1a\n')])})
    out = extract([apk], tmp_path / 'out')
    assert (out / 'gamedata' / 'art' / 'pic.png').is_file()
    assert not list(out.rglob('*.group.bin'))


def test_unrecognised_group_bin_is_left_alone(tmp_path: Path) -> None:
    junk = build_derbh([('art/junk.group.bin', b'\x10\x20\x30\x40\x50\x60')])
    apk = _write_apk(tmp_path, {'assets/gamedata.dz': junk})
    out = extract([apk], tmp_path / 'out')
    assert (out / 'gamedata' / 'art' / 'junk.group.bin').is_file()


def test_unknown_input_rejected(tmp_path: Path) -> None:
    bad = tmp_path / 'thing.txt'
    bad.write_text('nope')
    with pytest.raises(ValueError, match=r'Unrecognised input'):
        extract([bad], tmp_path / 'out')


def test_no_apk_rejected(tmp_path: Path) -> None:
    obb = tmp_path / 'main.obb'
    obb.write_bytes(_zip_bytes({'gamedata.dz': _data_archive()}))
    with pytest.raises(ValueError, match=r'No APK'):
        extract([obb], tmp_path / 'out')
