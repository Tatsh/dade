from __future__ import annotations

from typing import TYPE_CHECKING

from destin.common.cuebin import cuebin_to_iso
from destin.common.exceptions import InvalidFormatError
from destin.common.iso9660 import Iso9660Image
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@pytest.mark.parametrize('mode', ['MODE1/2352', 'MODE2/2352', 'MODE1/2048'])
def test_cuebin_round_trips_iso(mode: str, make_iso9660: Callable[..., bytes],
                                make_cuebin: Callable[..., Path]) -> None:
    iso = make_iso9660()
    assert cuebin_to_iso(make_cuebin(iso, mode=mode)) == iso


def test_cuebin_feeds_iso_reader(make_iso9660: Callable[..., bytes],
                                 make_cuebin: Callable[..., Path]) -> None:
    iso = make_iso9660(ark_data=b'reassembled')
    image = Iso9660Image.from_bytes(cuebin_to_iso(make_cuebin(iso)))
    assert image.read_file('GEN/MAIN.ARK') == b'reassembled'


@pytest.mark.parametrize('content', ['TRACK 01 MODE1/2352\n', 'FILE "image.bin" BINARY\n'])
def test_unparseable_cue_raises(content: str, tmp_path: Path) -> None:
    cue = tmp_path / 'bad.cue'
    cue.write_text(content)
    with pytest.raises(InvalidFormatError, match='Unparseable'):
        cuebin_to_iso(cue)


def test_unsupported_mode_raises(tmp_path: Path) -> None:
    cue = tmp_path / 'image.cue'
    cue.write_text('FILE "image.bin" BINARY\n  TRACK 01 MODE2/2336\n')
    with pytest.raises(InvalidFormatError, match='Unsupported track mode'):
        cuebin_to_iso(cue)
