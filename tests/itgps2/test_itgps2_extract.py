from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Self
import struct
import wave

import pytest

from dade.common.exceptions import InvalidFormatError
from dade.common.io import BytesReader
from dade.itgps2.extract import extract_disc
from dade.itgps2.test_utils import av_stream, pck_pack

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

_SONG = 'Songs/In The Groove 2/A/'
_FFMPEG = Path('/usr/bin/ffmpeg')
_ICON = (struct.pack('<3IfI', 0x10000, 1, 7, 1.0, 3) + bytes(24 * 3) +
         struct.pack('<2If2I', 1, 60, 1.0, 0, 0))
_SIMFILE = b'#MUSIC:A.av;\n#BGCHANGES:-10000.000=_movie=1.000=0=0=1;\n'


def _packs(*, itg2: bool = True) -> dict[str, bytes]:
    return {
        'D0000001.PCK':
            pck_pack(
                {
                    f'{_SONG}A.sm': _SIMFILE,
                    f'{_SONG}A.sm.orig': b'#MUSIC:A.ogg;',
                    f'{_SONG}A.av': av_stream(b'\x01\x00' * 8, b'\x00\x00\x01\xb3'),
                    f'{_SONG}A (sample).av': av_stream(b'\x02\x00' * 4),
                    'Themes/ps2/Other/Icon.ico': _ICON,
                    'Themes/ps2/Other/Bad.ico': b'junk',
                    f'{_SONG}A-banner.bmp': b'BM',
                    f'{_SONG}A-banner.png.orig': b'\x89PNG',
                    f'{_SONG}A-bg (640x480).png': b'\x89PNG small',
                    f'{_SONG}A-bg.png.orig': b'\x89PNG big',
                    'Courses/Workout/A.crs': b'#COURSE:A;',
                    'Courses/Workout/A.png.orig': b'\x89PNG course',
                    'Cache/Songs/1234': b'cache',
                },
                itg2=itg2),
        'S0000002.PCK':
            pck_pack({
                'Courses/Workout/A.crs': b'#COURSE:A;',
                '/Data/AI.ini': b'[AI]'
            }, itg2=itg2),
        'BROKEN.PCK':
            b'not a pack',
    }


def _write_disc(root: Path, executable: str, *, itg2: bool = True) -> Path:
    (root / 'PCKS').mkdir(parents=True)
    (root / executable).write_bytes(b'ELF')
    for name, data in _packs(itg2=itg2).items():
        (root / 'PCKS' / name).write_bytes(data)
    return root


@pytest.mark.parametrize(('executable', 'itg2', 'release'), [('SLUS_000.00', True, 'itg2-beta'),
                                                             ('SLUS_211.77', False, 'itg')])
def test_extract_disc_writes_a_stepmania_tree(mocker: MockerFixture, tmp_path: Path,
                                              executable: str, release: str, *, itg2: bool) -> None:
    run = mocker.patch('dade.itgps2.extract.sp.run')
    disc = _write_disc(tmp_path / 'disc', executable, itg2=itg2)
    name, counts = extract_disc(disc, tmp_path / 'out', _FFMPEG, 2)
    assert name == release
    assert counts == {
        'av': 1,
        'copied': 4,
        'icon': 1,
        'original': 3,
        'reduced': 2,
        'sample': 1,
        'simfile': 1,
        'skipped': 1
    }
    song = tmp_path / 'out' / release / _SONG
    assert sorted(path.name for path in song.iterdir()) == [
        'A-banner.png', 'A-bg.png', 'A.sm', 'A.sm.orig', 'A.wav'
    ]
    assert (song / 'A.sm').read_text() == ('#MUSIC:A.wav;\n'
                                           '#BGCHANGES:0.000=A.mpg=1.000=0=0=1;\n')
    assert (song / 'A-bg.png').read_bytes() == b'\x89PNG big'
    with wave.open(str(song / 'A.wav')) as wav:
        assert (wav.getnchannels(), wav.getframerate(), wav.getnframes()) == (2, 48000, 4)
    run.assert_called_once()
    command = run.call_args.args[0]
    assert command[-1] == str(song / 'A.mpg')
    assert command[command.index('-f') + 1] == 'mpegvideo'
    assert command[command.index('-c') + 1] == 'copy'
    assert run.call_args.kwargs == {'check': True, 'input': b'\x00\x00\x01\xb3'}
    assert (tmp_path / 'out' / release / 'Data' / 'AI.ini').read_bytes() == b'[AI]'
    assert (tmp_path / 'out' / release / 'Courses' / 'Workout' / 'A.png').is_file()
    assert not (tmp_path / 'out' / release / 'Cache').exists()
    assert (tmp_path / 'out' / release / 'Samples' / 'In The Groove 2' / 'A' /
            'A (sample).wav').is_file()
    other = tmp_path / 'out' / release / 'Themes' / 'ps2' / 'Other'
    assert sorted(path.name for path in other.iterdir()) == ['Bad.ico', 'Icon.glb', 'Icon.gltf']


def test_extract_disc_without_ffmpeg_skips_movies(mocker: MockerFixture, tmp_path: Path) -> None:
    run = mocker.patch('dade.itgps2.extract.sp.run')
    disc = _write_disc(tmp_path / 'disc', 'README')
    (disc / 'PCKS' / 'S0000003.PCK').write_bytes(
        pck_pack({'Themes/x/Sounds/m.av': av_stream(b'', b'v')},
                 compressed=('Themes/x/Sounds/m.av',)))
    name, _ = extract_disc(disc, tmp_path / 'out')
    assert name == 'disc'
    run.assert_not_called()
    assert (tmp_path / 'out' / 'disc' / _SONG / 'A.wav').is_file()
    assert not any((tmp_path / 'out' / 'disc' / 'Themes' / 'x' / 'Sounds').iterdir())


def test_extract_disc_without_streams(tmp_path: Path) -> None:
    (tmp_path / 'disc').mkdir()
    (tmp_path / 'disc' / 'A.PCK').write_bytes(pck_pack({'Data/AI.ini': b'[AI]'}))
    assert extract_disc(tmp_path / 'disc', tmp_path / 'out') == ('disc', {'copied': 1})


class _FakeReader:
    def __init__(self, path: Path) -> None:
        self._reader = BytesReader(b''.join(_packs().values()))

    @property
    def size(self) -> int:
        return self._reader.size

    def read(self, offset: int, length: int, /) -> bytes:
        return self._reader.read(offset, length)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        pass


class _FakeImage:
    def __init__(self, reader: object) -> None:
        self._sizes = {f'PCKS/{name}': len(data) for name, data in _packs().items()}

    def iter_files(self) -> list[tuple[str, int]]:
        return [('SLUS_000.00', 3), ('PCKS/SLUS_000.00', 3), *self._sizes.items()]

    def locate(self, name: str) -> tuple[int, int]:
        offset = 0
        for other, size in self._sizes.items():
            if other == name:
                return offset, size
            offset += size
        raise KeyError(name)


def test_extract_disc_reads_an_image(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('dade.itgps2.extract.MmapReader', _FakeReader)
    mocker.patch('dade.itgps2.extract.ISO9660Image', _FakeImage)
    mocker.patch('dade.itgps2.extract.sp.run')
    image = tmp_path / 'disc.iso'
    image.write_bytes(b'')
    name, counts = extract_disc(image, tmp_path / 'out', _FFMPEG)
    assert name == 'itg2-beta'
    assert counts == {
        'av': 1,
        'copied': 4,
        'icon': 1,
        'original': 3,
        'reduced': 2,
        'sample': 1,
        'simfile': 1,
        'skipped': 1
    }
    assert (tmp_path / 'out' / 'itg2-beta' / 'Data' / 'AI.ini').read_bytes() == b'[AI]'


def test_extract_disc_requires_packs(tmp_path: Path) -> None:
    (tmp_path / 'disc').mkdir()
    with pytest.raises(InvalidFormatError, match='No PCK packs'):
        extract_disc(tmp_path / 'disc', tmp_path / 'out')
