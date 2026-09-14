from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dade.common.disc import (
    as_directory,
    find_by_suffix,
    iter_ark_bytes,
    materialize,
    open_image,
)
from dade.common.exceptions import InvalidFormatError
from dade.common.iso9660 import Iso9660Image

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@pytest.mark.asyncio
async def test_materialize_iso_extracts(make_iso9660: Callable[..., bytes], tmp_path: Path) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_bytes(make_iso9660(top_data=b'TOP', ark_data=b'ARK DATA'))
    out = tmp_path / 'out'
    await materialize(iso, out)
    assert (out / 'TOP.DAT').read_bytes() == b'TOP'
    assert (out / 'GEN' / 'MAIN.ARK').read_bytes() == b'ARK DATA'


@pytest.mark.asyncio
async def test_materialize_cuebin_extracts(make_cuebin: Callable[..., Path],
                                           make_iso9660: Callable[...,
                                                                  bytes], tmp_path: Path) -> None:
    cue = make_cuebin(make_iso9660(ark_data=b'ARK DATA'))
    out = tmp_path / 'out'
    await materialize(cue, out)
    assert (out / 'GEN' / 'MAIN.ARK').read_bytes() == b'ARK DATA'


@pytest.mark.asyncio
async def test_materialize_directory_copies(tmp_path: Path) -> None:
    source = tmp_path / 'game'
    (source / 'GEN').mkdir(parents=True)
    (source / 'GEN' / 'MAIN.ARK').write_bytes(b'ARK DATA')
    out = tmp_path / 'out'
    await materialize(source, out)
    assert (out / 'GEN' / 'MAIN.ARK').read_bytes() == b'ARK DATA'
    assert (source / 'GEN' / 'MAIN.ARK').is_file()  # The source is not modified.


def test_iter_ark_bytes_directory(tmp_path: Path) -> None:
    (tmp_path / 'GEN').mkdir()
    (tmp_path / 'GEN' / 'MAIN.ARK').write_bytes(b'AAA')
    (tmp_path / 'B.ark').write_bytes(b'BBB')
    (tmp_path / 'notes.txt').write_bytes(b'ignored')
    assert sorted(iter_ark_bytes(tmp_path)) == [b'AAA', b'BBB']


def test_iter_ark_bytes_image(make_iso9660: Callable[..., bytes], tmp_path: Path) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_bytes(make_iso9660(ark_data=b'ARK DATA'))
    assert list(iter_ark_bytes(iso)) == [b'ARK DATA']


def test_open_image_iso(make_iso9660: Callable[..., bytes], tmp_path: Path) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_bytes(make_iso9660())
    image = open_image(iso)
    assert isinstance(image, Iso9660Image)
    assert image.contains('GEN/MAIN.ARK')


def test_open_image_cuebin(make_cuebin: Callable[..., Path], make_iso9660: Callable[...,
                                                                                    bytes]) -> None:
    cue = make_cuebin(make_iso9660())
    assert open_image(cue).contains('GEN/MAIN.ARK')


def test_open_image_invalid_raises(tmp_path: Path) -> None:
    junk = tmp_path / 'not-a-disc.iso'
    junk.write_bytes(b'this is not an ISO 9660 image')
    with pytest.raises(InvalidFormatError):
        open_image(junk)


def test_open_image_bin_beside_its_cue(make_cuebin: Callable[..., Path],
                                       make_iso9660: Callable[..., bytes]) -> None:
    # Handed the binary rather than the sheet, the sheet still records how to read it.
    cue = make_cuebin(make_iso9660(ark_data=b'ARK DATA'))
    image = open_image(cue.with_suffix('.bin'))
    assert any(path.upper().endswith('.ARK') for path, _ in image.iter_files())


def test_open_image_bin_without_a_cue(make_cuebin: Callable[..., Path],
                                      make_iso9660: Callable[..., bytes], tmp_path: Path) -> None:
    # No sheet; the layout comes from the sectors. A raw one opens with the sync pattern.
    cue = make_cuebin(make_iso9660(ark_data=b'ARK DATA'))
    lonely = tmp_path / 'lonely.bin'
    lonely.write_bytes(cue.with_suffix('.bin').read_bytes())
    cue.unlink()
    image = open_image(lonely)
    assert any(path.upper().endswith('.ARK') for path, _ in image.iter_files())


def test_open_image_bin_that_is_already_user_data(make_iso9660: Callable[..., bytes],
                                                  tmp_path: Path) -> None:
    # A track written without its error correction is what a reader wants already.
    plain = tmp_path / 'plain.bin'
    plain.write_bytes(make_iso9660(ark_data=b'ARK DATA'))
    image = open_image(plain)
    assert any(path.upper().endswith('.ARK') for path, _ in image.iter_files())


def test_open_image_bin_in_a_mode_it_cannot_read(make_cuebin: Callable[..., Path],
                                                 make_iso9660: Callable[..., bytes],
                                                 tmp_path: Path) -> None:
    cue = make_cuebin(make_iso9660(ark_data=b'ARK DATA'))
    raw = bytearray(cue.with_suffix('.bin').read_bytes())
    raw[15] = 9
    strange = tmp_path / 'strange.bin'
    strange.write_bytes(bytes(raw))
    with pytest.raises(InvalidFormatError, match='Unsupported sector mode'):
        open_image(strange)


def test_as_directory_yields_a_directory_source_untouched(tmp_path: Path) -> None:
    source = tmp_path / 'install'
    source.mkdir()
    (source / 'track.pcb').write_bytes(b'DATA')
    with as_directory(source) as directory:
        assert directory == source


def test_as_directory_extracts_an_image_and_cleans_up(make_iso9660: Callable[..., bytes],
                                                      tmp_path: Path) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_bytes(make_iso9660(top_data=b'TOP', ark_data=b'ARK DATA'))
    with as_directory(iso) as directory:
        extracted = directory
        assert (directory / 'TOP.DAT').read_bytes() == b'TOP'
        assert (directory / 'GEN' / 'MAIN.ARK').read_bytes() == b'ARK DATA'
    assert not extracted.exists()


def test_find_by_suffix_ignores_case(tmp_path: Path) -> None:
    (tmp_path / 'sub').mkdir()
    for name in ('lower.pcb', 'UPPER.PCB', 'Mixed.Pcb', 'other.dat'):
        (tmp_path / name).write_bytes(b'')
    (tmp_path / 'sub' / 'NESTED.PCB').write_bytes(b'')
    # Sorting is by full path; the subdirectory's entry follows the top-level ones.
    assert [p.name for p in find_by_suffix(tmp_path, '.pcb')] == [
        'Mixed.Pcb', 'UPPER.PCB', 'lower.pcb', 'NESTED.PCB'
    ]


def test_find_by_suffix_can_stay_at_the_top_level(tmp_path: Path) -> None:
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'top.bmp').write_bytes(b'')
    (tmp_path / 'sub' / 'nested.bmp').write_bytes(b'')
    assert [p.name for p in find_by_suffix(tmp_path, '.bmp', recursive=False)] == ['top.bmp']
