from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import pytest

from destin.common.exceptions import InvalidFormatError
from destin.harmonix.typing import Asset
from destin.harmonix.unpacker import Unpacker

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pytest_mock import MockerFixture

    from destin.harmonix.typing import ArkLayout


class _AmpUnpacker(Unpacker):
    ark_layout: ClassVar[ArkLayout] = 'amplitude'
    game_name: ClassVar[str] = 'Amplitude'


class _FreqUnpacker(Unpacker):
    ark_layout: ClassVar[ArkLayout] = 'frequency'
    game_name: ClassVar[str] = 'FreQuency'


def test_accepts_matching_layout(make_amp_ark: Callable[..., bytes], tmp_path: Path) -> None:
    (tmp_path / 'MAIN.ARK').write_bytes(make_amp_ark((('gen/a.txt', b'AAA'),)))
    assert _AmpUnpacker(tmp_path).accepts()
    assert not _FreqUnpacker(tmp_path).accepts()


def test_accepts_frequency_layout(make_freq_ark: Callable[..., bytes], tmp_path: Path) -> None:
    (tmp_path / 'ROOT.ARK').write_bytes(make_freq_ark((('gen/a.txt', b'AAA'),)))
    assert _FreqUnpacker(tmp_path).accepts()
    assert not _AmpUnpacker(tmp_path).accepts()


def test_accepts_no_arks(tmp_path: Path) -> None:
    assert not _AmpUnpacker(tmp_path).accepts()


@pytest.mark.asyncio
async def test_unpack_delegates_with_layout(make_amp_ark: Callable[..., bytes],
                                            mocker: MockerFixture, tmp_path: Path) -> None:
    game = tmp_path / 'game'
    game.mkdir()
    (game / 'MAIN.ARK').write_bytes(make_amp_ark((('gen/a.txt', b'AAA'),)))
    run_game = mocker.patch('destin.harmonix.unpacker.run_game', return_value={'MAIN.ARK': 'ok'})
    out = tmp_path / 'out'
    assert await _AmpUnpacker(game).unpack(out, jobs=2) == {'MAIN.ARK': 'ok'}
    assert run_game.call_args.args == (out,)  # Processed in place in the output directory.
    assert (out / 'MAIN.ARK').is_file()  # The source was materialised into the output directory.
    assert (game / 'MAIN.ARK').is_file()  # The source is left untouched.
    assert run_game.call_args.kwargs['jobs'] == 2
    assert run_game.call_args.kwargs['layout'] == 'amplitude'


@pytest.mark.asyncio
async def test_unpack_rejects_wrong_game(make_freq_ark: Callable[..., bytes], mocker: MockerFixture,
                                         tmp_path: Path) -> None:
    game = tmp_path / 'game'
    game.mkdir()
    (game / 'ROOT.ARK').write_bytes(make_freq_ark((('gen/a.txt', b'AAA'),)))
    run_game = mocker.patch('destin.harmonix.unpacker.run_game')
    with pytest.raises(InvalidFormatError):
        await _AmpUnpacker(game).unpack(tmp_path / 'out')
    run_game.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('subpath', ['.', 'nested/out'])
async def test_unpack_rejects_output_inside_input(make_amp_ark: Callable[..., bytes],
                                                  mocker: MockerFixture, subpath: str,
                                                  tmp_path: Path) -> None:
    (tmp_path / 'MAIN.ARK').write_bytes(make_amp_ark((('a.txt', b'AAA'),)))
    run_game = mocker.patch('destin.harmonix.unpacker.run_game')
    with pytest.raises(ValueError, match='cannot be inside the input'):
        await _AmpUnpacker(tmp_path).unpack(tmp_path / subpath)
    run_game.assert_not_called()


def test_accepts_iso_image(make_amp_ark: Callable[..., bytes], make_iso9660: Callable[..., bytes],
                           tmp_path: Path) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_bytes(make_iso9660(ark_data=make_amp_ark((('a.txt', b'AAA'),))))
    assert _AmpUnpacker(iso).accepts()
    assert not _FreqUnpacker(iso).accepts()


def test_accepts_iso_frequency_image(make_iso9660: Callable[..., bytes], tmp_path: Path) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_bytes(make_iso9660(ark_data=b'ARK\x00padding'))
    assert _FreqUnpacker(iso).accepts()
    assert not _AmpUnpacker(iso).accepts()


def test_accepts_cuebin(make_amp_ark: Callable[..., bytes], make_cuebin: Callable[..., Path],
                        make_iso9660: Callable[..., bytes]) -> None:
    cue = make_cuebin(make_iso9660(ark_data=make_amp_ark((('a.txt', b'AAA'),))))
    assert _AmpUnpacker(cue).accepts()


@pytest.mark.asyncio
async def test_aiter_over_iso_image(make_amp_ark: Callable[..., bytes],
                                    make_iso9660: Callable[..., bytes], tmp_path: Path) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_bytes(make_iso9660(ark_data=make_amp_ark((('gen/a.txt', b'AAA'), ('b.txt', b'BB')))))
    assets = [asset async for asset in _AmpUnpacker(iso)]
    assert assets == [Asset('gen/a.txt', b'AAA'), Asset('b.txt', b'BB')]


def test_iter_over_iso_image(make_amp_ark: Callable[..., bytes], make_iso9660: Callable[..., bytes],
                             tmp_path: Path) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_bytes(make_iso9660(ark_data=make_amp_ark((('a.txt', b'AAA'),))))
    assert list(_AmpUnpacker(iso)) == [Asset('a.txt', b'AAA')]


@pytest.mark.asyncio
async def test_unpack_iso_end_to_end(make_amp_ark: Callable[..., bytes],
                                     make_iso9660: Callable[..., bytes], tmp_path: Path) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_bytes(make_iso9660(ark_data=make_amp_ark((('gen/a.txt', b'AAA'),))))
    out = tmp_path / 'out'
    await _AmpUnpacker(iso).unpack(out)
    assert (out / 'GEN' / 'MAIN' / 'gen' / 'a.txt').read_bytes() == b'AAA'
    assert (out / 'GEN' / 'MAIN.ARK').is_file()  # The materialised ARK is kept by default.
    assert iso.is_file()  # The source image is untouched.


@pytest.mark.asyncio
async def test_unpack_iso_delete_removes_materialized_ark(make_amp_ark: Callable[..., bytes],
                                                          make_iso9660: Callable[..., bytes],
                                                          tmp_path: Path) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_bytes(make_iso9660(ark_data=make_amp_ark((('gen/a.txt', b'AAA'),))))
    out = tmp_path / 'out'
    await _AmpUnpacker(iso).unpack(out, delete=True)
    assert (out / 'GEN' / 'MAIN' / 'gen' / 'a.txt').read_bytes() == b'AAA'
    assert not (out / 'GEN' / 'MAIN.ARK').exists()  # The materialised ARK is removed.
    assert iso.is_file()  # The source image is untouched.


def test_iter_yields_carved_assets(make_amp_ark: Callable[..., bytes], tmp_path: Path) -> None:
    (tmp_path / 'A.ARK').write_bytes(make_amp_ark((('gen/a.txt', b'AAA'), ('b.txt', b'BB'))))
    (tmp_path / 'B.ARK').write_bytes(make_amp_ark((('c.txt', b'CCC'),)))
    assert list(_AmpUnpacker(tmp_path)) == [
        Asset('gen/a.txt', b'AAA'),
        Asset('b.txt', b'BB'),
        Asset('c.txt', b'CCC'),
    ]


@pytest.mark.asyncio
async def test_aiter_yields_carved_assets(make_freq_ark: Callable[..., bytes],
                                          tmp_path: Path) -> None:
    (tmp_path / 'ROOT.ARK').write_bytes(make_freq_ark(
        (('gen/a.txt', b'AAA'), ('gen/b.txt', b'BB'))))
    assets = [asset async for asset in _FreqUnpacker(tmp_path)]
    assert assets == [Asset('gen/a.txt', b'AAA'), Asset('gen/b.txt', b'BB')]


def test_iter_skips_truncated_entry(make_amp_ark: Callable[..., bytes], tmp_path: Path) -> None:
    data = make_amp_ark((('a.txt', b'AAAAA'), ('b.txt', b'BBBBB')))
    (tmp_path / 'MAIN.ARK').write_bytes(data[:-5])  # Drop the last entry's data.
    assert list(_AmpUnpacker(tmp_path)) == [Asset('a.txt', b'AAAAA')]


@pytest.mark.asyncio
async def test_aiter_skips_truncated_entry(make_freq_ark: Callable[..., bytes],
                                           tmp_path: Path) -> None:
    data = make_freq_ark((('a.txt', b'AAAAA'), ('b.txt', b'BBBBB')))
    (tmp_path / 'ROOT.ARK').write_bytes(data[:-5])  # Drop the last entry's data.
    assets = [asset async for asset in _FreqUnpacker(tmp_path)]
    assert assets == [Asset('a.txt', b'AAAAA')]
