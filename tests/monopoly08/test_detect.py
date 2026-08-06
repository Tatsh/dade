from __future__ import annotations

from typing import TYPE_CHECKING

from destin.monopoly08.detect import detect, find_bigs
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from destin.monopoly08.typing import Platform


def test_find_bigs_only_returns_files(make_disc: Callable[[Sequence[str]], Path]) -> None:
    root = make_disc(['b.BIG', 'a.big', 'notes.txt', 'decoy.big/inner.txt'])
    assert [p.name for p in find_bigs(root)] == ['a.big', 'b.BIG']


@pytest.mark.parametrize(('names', 'platform', 'binary'),
                         [(['default.xex', 'audio.big'], 'xbox360', 'default.xex'),
                          (['PS3_GAME/USRDIR/EBOOT.BIN'], 'ps3', 'EBOOT.BIN'),
                          (['PS3_GAME/EBOOT.elf'], 'ps3', 'EBOOT.elf'),
                          (['PS3_GAME/'], 'ps3', 'PS3_GAME'), (['SYSTEM.CNF'], 'ps2', 'SYSTEM.CNF'),
                          (['sys/main.dol', 'files/hp_r.elf'], 'wii', 'hp_r.elf'),
                          (['sys/main.dol'], 'wii', 'main.dol'), (['boot.bin'], 'wii', 'boot.bin'),
                          (['audio.big'], 'xbox360', None)])
def test_detect_platform(make_disc: Callable[[Sequence[str]], Path], names: Sequence[str],
                         platform: Platform, binary: str | None) -> None:
    info = detect(make_disc(names))
    assert info.platform == platform
    assert (info.binary.name if info.binary else None) == binary


def test_detect_counts_archives(make_disc: Callable[[Sequence[str]], Path]) -> None:
    assert len(detect(make_disc(['default.xex', 'a.big', 'sub/b.big'])).bigs) == 2


def test_detect_without_any_marker(make_disc: Callable[[Sequence[str]], Path]) -> None:
    with pytest.raises(ValueError, match='no known platform marker'):
        detect(make_disc(['readme.txt']))
