from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from destin.harmonix.unpacker import Unpacker
import click
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from destin.harmonix.typing import ArkLayout
    from pytest_mock import MockerFixture


class _AmpUnpacker(Unpacker):
    ark_layout: ClassVar[ArkLayout] = 'amplitude'
    game_name: ClassVar[str] = 'Amplitude'


class _FreqUnpacker(Unpacker):
    ark_layout: ClassVar[ArkLayout] = 'frequency'
    game_name: ClassVar[str] = 'FreQuency'


def test_accepts_matching_layout(make_amp_ark: Callable[..., bytes], tmp_path: Path) -> None:
    (tmp_path / 'MAIN.ARK').write_bytes(make_amp_ark((('gen/a.txt', b'AAA'),)))
    assert _AmpUnpacker().accepts(tmp_path)
    assert not _FreqUnpacker().accepts(tmp_path)


def test_accepts_frequency_layout(make_freq_ark: Callable[..., bytes], tmp_path: Path) -> None:
    (tmp_path / 'ROOT.ARK').write_bytes(make_freq_ark((('gen/a.txt', b'AAA'),)))
    assert _FreqUnpacker().accepts(tmp_path)
    assert not _AmpUnpacker().accepts(tmp_path)


def test_accepts_no_arks(tmp_path: Path) -> None:
    assert not _AmpUnpacker().accepts(tmp_path)


@pytest.mark.asyncio
async def test_unpack_delegates_with_layout(make_amp_ark: Callable[..., bytes],
                                            mocker: MockerFixture, tmp_path: Path) -> None:
    (tmp_path / 'MAIN.ARK').write_bytes(make_amp_ark((('gen/a.txt', b'AAA'),)))
    run_game = mocker.patch('destin.harmonix.unpacker.run_game', return_value={'MAIN.ARK': 'ok'})
    out = tmp_path / 'out'
    assert await _AmpUnpacker().unpack(tmp_path, out, jobs=2) == {'MAIN.ARK': 'ok'}
    assert run_game.call_args.args == (tmp_path, out)
    assert run_game.call_args.kwargs['jobs'] == 2
    assert run_game.call_args.kwargs['layout'] == 'amplitude'


@pytest.mark.asyncio
async def test_unpack_rejects_wrong_game(make_freq_ark: Callable[..., bytes], mocker: MockerFixture,
                                         tmp_path: Path) -> None:
    (tmp_path / 'ROOT.ARK').write_bytes(make_freq_ark((('gen/a.txt', b'AAA'),)))
    run_game = mocker.patch('destin.harmonix.unpacker.run_game')
    with pytest.raises(click.Abort):
        await _AmpUnpacker().unpack(tmp_path, tmp_path / 'out')
    run_game.assert_not_called()
