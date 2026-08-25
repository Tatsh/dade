"""Tests for :mod:`dade.xg2.extract_pc`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from dade.xg2.extract_pc import MODEL_SUBDIRECTORIES, iter_model_blobs, process_model, run

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pytest_mock import MockerFixture


def _pc_model() -> bytes:
    model = bytearray(struct.pack('<I', 0x05000000) + b'\x00' * 4)
    model += struct.pack('<I', 0xAC000000)
    model += struct.pack('<I', 0x05000100)
    model += struct.pack('<I', 0x00040808)
    model += struct.pack('<I', 0x05000800)
    return bytes(model) + b'\x00' * (0x1000 - len(model))


def _make_data1(root: Path) -> Path:
    data1 = root / 'data1'
    for subdirectory in MODEL_SUBDIRECTORIES:
        (data1 / subdirectory).mkdir(parents=True)
    (data1 / 'WAVS').mkdir(parents=True)
    return data1


def test_process_model_writes_the_blob(tmp_path: Path) -> None:
    assert process_model(b'\x00' * 16, tmp_path, 'model') == 0
    assert (tmp_path / 'model.bin').read_bytes() == b'\x00' * 16


def test_process_model_writes_textures(tmp_path: Path) -> None:
    assert process_model(_pc_model(), tmp_path, 'model') == 1
    assert list((tmp_path / 'model').glob('*.png'))


def test_process_model_creates_the_destination(tmp_path: Path) -> None:
    destination = tmp_path / 'nested' / 'deeper'
    process_model(b'\x00' * 16, destination, 'model')
    assert (destination / 'model.bin').is_file()


def test_run_on_an_empty_tree(tmp_path: Path) -> None:
    counts = run(_make_data1(tmp_path), tmp_path / 'out')
    assert counts == {'containers': 0, 'raw': 0, 'textures': 0, 'wavs': 0, 'bitmaps': 0}


def test_run_mirrors_the_layout(tmp_path: Path) -> None:
    data1 = _make_data1(tmp_path)
    (data1 / 'BIKES' / 'bike.cmp').write_bytes(_pc_model())
    out = tmp_path / 'out'
    counts = run(data1, out)
    assert counts['raw'] == 1
    assert (out / 'BIKES' / 'bike.bin').is_file()


def test_run_copies_wavs(tmp_path: Path, mocker: MockerFixture) -> None:
    data1 = _make_data1(tmp_path)
    (data1 / 'WAVS' / 'engine.wav').write_bytes(b'RIFF')
    copy = mocker.patch('dade.xg2.extract_pc.shutil.copy2')
    assert run(data1, tmp_path / 'out')['wavs'] == 1
    copy.assert_called_once()


def test_run_converts_bitmaps(tmp_path: Path, mocker: MockerFixture) -> None:
    data1 = _make_data1(tmp_path)
    (data1 / 'logo.bmp').write_bytes(b'BM' + b'\x00' * 64)
    mocker.patch('dade.xg2.extract_pc.bmp_to_png', return_value=True)
    assert run(data1, tmp_path / 'out')['bitmaps'] == 1


def test_run_unpacks_a_container(tmp_path: Path, make_archive: Callable[..., bytes]) -> None:
    data1 = _make_data1(tmp_path)
    blob = make_archive([(b'COPY', _pc_model()), (b'COPY', _pc_model())], '<')
    (data1 / 'BULK' / 'DATA').mkdir(parents=True, exist_ok=True)
    (data1 / 'BULK' / 'DATA' / 'bulk.bin').write_bytes(blob)
    out = tmp_path / 'out'
    counts = run(data1, out)
    assert counts['containers'] == 1
    assert (out / 'BULK' / 'DATA' / 'bulk' / '000.bin').is_file()
    assert (out / 'BULK' / 'DATA' / 'bulk' / '001.bin').is_file()


def test_run_puts_a_single_entry_alongside(tmp_path: Path, make_archive: Callable[...,
                                                                                  bytes]) -> None:
    data1 = _make_data1(tmp_path)
    (data1 / 'BULK' / 'DATA' / 'one.bin').write_bytes(make_archive([(b'COPY', _pc_model())], '<'))
    out = tmp_path / 'out'
    run(data1, out)
    assert (out / 'BULK' / 'DATA' / 'one.bin').is_file()


def test_run_skips_missing_subdirectories(tmp_path: Path) -> None:
    data1 = tmp_path / 'data1'
    data1.mkdir()
    assert run(data1, tmp_path / 'out')['containers'] == 0


def test_iter_model_blobs_labels_container_entries(tmp_path: Path,
                                                   make_archive: Callable[..., bytes]) -> None:
    data1 = _make_data1(tmp_path)
    (data1 / 'BULK' / 'DATA' / 'bulk.bin').write_bytes(
        make_archive([(b'COPY', b'a' * 16), (b'COPY', b'b' * 16)], '<'))
    labels = [label for label, _ in iter_model_blobs(data1)]
    assert labels == ['bulk.bin[0]', 'bulk.bin[1]']


def test_iter_model_blobs_labels_raw_files(tmp_path: Path) -> None:
    data1 = _make_data1(tmp_path)
    (data1 / 'TRACKS' / 'aqua1.pcb').write_bytes(b'\x00' * 64)
    assert [label for label, _ in iter_model_blobs(data1)] == ['aqua1.pcb']


def test_iter_model_blobs_ignores_directories(tmp_path: Path) -> None:
    data1 = _make_data1(tmp_path)
    (data1 / 'BIKES' / 'nested').mkdir()
    assert iter_model_blobs(data1) == []


def _sized_lzss() -> bytes:
    # Eight maximum-length matches against the zero-filled ring: 17 bytes in, 144 out.
    return struct.pack('<I', 144) + bytes([0x00]) + bytes([0x00, 0x0F]) * 8


def _truncated_container() -> bytes:
    return struct.pack('<I', 100) + b'\x00' * 8 + b'SSZL' + b'\x00' * 8


def test_run_skips_a_container_with_an_unreadable_directory(tmp_path: Path) -> None:
    data1 = _make_data1(tmp_path)
    (data1 / 'BULK' / 'DATA' / 'short.bin').write_bytes(_truncated_container())
    counts = run(data1, tmp_path / 'out')
    assert counts['containers'] == 0
    assert counts['raw'] == 1


def test_run_decompresses_a_sized_blob(tmp_path: Path) -> None:
    data1 = _make_data1(tmp_path)
    (data1 / 'BIKES' / 'bike.cmp').write_bytes(_sized_lzss())
    out = tmp_path / 'out'
    assert run(data1, out)['containers'] == 1
    assert (out / 'BIKES' / 'bike.bin').read_bytes() == b'\x00' * 144


def test_run_ignores_directories_inside_a_subdirectory(tmp_path: Path) -> None:
    data1 = _make_data1(tmp_path)
    (data1 / 'TRACKS' / 'nested').mkdir()
    assert run(data1, tmp_path / 'out')['raw'] == 0


def test_run_ignores_a_bitmap_it_cannot_convert(tmp_path: Path, mocker: MockerFixture) -> None:
    data1 = _make_data1(tmp_path)
    for name in ('a.bmp', 'b.bmp'):
        (data1 / name).write_bytes(b'BM')
    mocker.patch('dade.xg2.extract_pc.bmp_to_png', return_value=False)
    assert run(data1, tmp_path / 'out')['bitmaps'] == 0


def test_iter_model_blobs_skips_a_missing_subdirectory(tmp_path: Path) -> None:
    data1 = tmp_path / 'data1'
    (data1 / 'BIKES').mkdir(parents=True)
    (data1 / 'BIKES' / 'bike.cmp').write_bytes(_sized_lzss())
    assert [label for label, _ in iter_model_blobs(data1)] == ['bike.cmp']


def test_iter_model_blobs_decompresses_a_sized_blob(tmp_path: Path) -> None:
    data1 = _make_data1(tmp_path)
    (data1 / 'BIKES' / 'bike.cmp').write_bytes(_sized_lzss())
    assert iter_model_blobs(data1)[0][1] == b'\x00' * 144
