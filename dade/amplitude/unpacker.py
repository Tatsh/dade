"""Developer-facing unpacker for the PS2 game Amplitude (Harmonix)."""
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from dade.harmonix.unpacker import Unpacker

if TYPE_CHECKING:
    from dade.harmonix.typing import ArkLayout

__all__ = ('AmplitudeUnpacker',)


class AmplitudeUnpacker(Unpacker):
    """Unpacker for the PS2 game Amplitude (its magic-less ``GEN/MAIN.ARK`` layout)."""

    ark_layout: ClassVar[ArkLayout] = 'amplitude'
    game_name: ClassVar[str] = 'Amplitude'
