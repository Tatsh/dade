"""Developer-facing unpacker for the PS2 game FreQuency (Harmonix)."""
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from dade.harmonix.unpacker import Unpacker

if TYPE_CHECKING:
    from dade.harmonix.typing import ArkLayout

__all__ = ('FrequencyUnpacker',)


class FrequencyUnpacker(Unpacker):
    r"""Unpacker for the PS2 game FreQuency (its ``ARK\0`` ``ARK/*.ARK`` layout)."""

    ark_layout: ClassVar[ArkLayout] = 'frequency'
    game_name: ClassVar[str] = 'FreQuency'
