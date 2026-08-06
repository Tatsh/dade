"""
Disc-platform detection for an extracted Monopoly 2008 disc root.

The platform is recognised from its boot binary (the most reliable signal):
``default.xex`` (Xbox 360), ``PS3_GAME``/``EBOOT.BIN`` (PS3), ``SYSTEM.CNF`` (PS2),
or ``sys/main.dol`` (Wii). The ``BIGF`` archives are then discovered wherever they
live under the root (repo root, ``PS3_GAME/USRDIR``, ``files/`` …). Xbox 360 is the
fallback when archives are present but no other platform marker is found.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from .typing import Platform

__all__ = ('DiscInfo', 'detect', 'find_bigs')


class DiscInfo(NamedTuple):
    """The detected platform and located archives for a disc root."""

    platform: Platform
    """The detected console platform."""
    binary: Path | None
    """The boot binary used to identify the platform, if any."""
    bigs: tuple[Path, ...]
    """The ``BIGF`` archives found under the root, sorted by path."""


def _first(root: Path, *names: str) -> Path | None:
    lowered = {n.lower() for n in names}
    return next((p for p in root.rglob('*') if p.name.lower() in lowered), None)


def find_bigs(root: Path) -> tuple[Path, ...]:
    """
    Find every ``BIGF`` archive under ``root``.

    Parameters
    ----------
    root : pathlib.Path
        The extracted disc root.

    Returns
    -------
    tuple[pathlib.Path, ...]
        The ``.big`` archives, sorted by path.
    """
    def _iter() -> Iterator[Path]:
        for p in root.rglob('*'):
            if p.suffix.lower() == '.big' and p.is_file():
                yield p

    return tuple(sorted(_iter()))


def detect(root: Path) -> DiscInfo:
    """
    Detect the console platform of an extracted disc root.

    Parameters
    ----------
    root : pathlib.Path
        The extracted disc root (the directory passed on the command line).

    Returns
    -------
    DiscInfo
        The detected platform, the identifying binary and the located archives.

    Raises
    ------
    ValueError
        If no known platform marker and no archives can be found.
    """
    bigs = find_bigs(root)
    if xex := _first(root, 'default.xex'):
        return DiscInfo('xbox360', xex, bigs)
    if eboot := _first(root, 'EBOOT.BIN', 'EBOOT.elf'):
        return DiscInfo('ps3', eboot, bigs)
    if (ps3_dir := root / 'PS3_GAME').is_dir():
        return DiscInfo('ps3', ps3_dir, bigs)
    if cnf := _first(root, 'SYSTEM.CNF'):
        return DiscInfo('ps2', cnf, bigs)
    # The Wii game binary is the (non-stripped) engine ELF in files/ (here
    # ``hp_r.elf`` -- this title is built on EA's Harry Potter engine), not the
    # boot ``main.dol``; prefer it so the reported binary is the useful one.
    if elf := _first(root, 'hp_r.elf'):
        return DiscInfo('wii', elf, bigs)
    if dol := _first(root, 'main.dol', 'boot.bin'):
        return DiscInfo('wii', dol, bigs)
    if bigs:  # Archives present but no other marker: treat as Xbox 360.
        return DiscInfo('xbox360', None, bigs)
    msg = f'{root}: no known platform marker or BIGF archive found'
    raise ValueError(msg)
