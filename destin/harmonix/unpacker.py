"""Template base for the per-game Harmonix ARK unpackers (Amplitude and FreQuency)."""
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar
import logging

import click

from .ark import _FREQ_MAGIC
from .pipeline import _find_arks, run_game

if TYPE_CHECKING:
    from pathlib import Path

    from .typing import ArkLayout

__all__ = ('Unpacker',)

log = logging.getLogger(__name__)


class Unpacker:
    """
    Template base for a single Harmonix game's ARK unpacker.

    A concrete subclass sets :py:attr:`game_name` and :py:attr:`ark_layout`; the base supplies
    :py:meth:`accepts` (which detects whether a directory holds this game's ARKs) and
    :py:meth:`unpack` (which validates the directory and delegates to
    :py:func:`destin.harmonix.pipeline.run_game` with the fixed layout).
    """

    ark_layout: ClassVar[ArkLayout]
    """The ARK layout this unpacker reads (``'amplitude'`` or ``'frequency'``)."""
    game_name: ClassVar[str]
    """The human-readable game name (for example ``'Amplitude'``)."""
    def accepts(self, game_dir: Path) -> bool:
        r"""
        Report whether ``game_dir`` holds at least one ARK with this game's layout.

        Every ``*.ark`` found under ``game_dir`` is peeked (its leading four bytes); a ``ARK\0``
        magic marks the FreQuency layout and anything else marks the Amplitude layout.

        Parameters
        ----------
        game_dir : pathlib.Path
            The game's root directory to scan for ARK archives.

        Returns
        -------
        bool
            ``True`` if some ARK under ``game_dir`` matches :py:attr:`ark_layout`.
        """
        for ark_path in _find_arks(game_dir):
            with ark_path.open('rb') as src:
                layout: ArkLayout = 'frequency' if src.read(4) == _FREQ_MAGIC else 'amplitude'
            if layout == self.ark_layout:
                return True
        return False

    async def unpack(self,
                     game_dir: Path,
                     out: Path,
                     *,
                     convert: bool = True,
                     gunzip: bool = True,
                     keep_gz: bool = False,
                     ignore_failures: bool = False,
                     jobs: int = 0) -> dict[str, str]:
        """
        Unpack this game's ARKs under ``game_dir`` into ``out``.

        Parameters
        ----------
        game_dir : pathlib.Path
            The game's root directory (the disc root) to scan for ARKs and disc audio.
        out : pathlib.Path
            Output directory (created if missing).
        convert : bool
            Convert extracted assets to standard formats (otherwise extract raw).
        gunzip : bool
            Decompress ``.gz`` entries in place during extraction.
        keep_gz : bool
            Keep the original ``.gz`` entry alongside the decompressed output.
        ignore_failures : bool
            Log and skip a converter/decompose failure instead of stopping the run.
        jobs : int
            Maximum concurrent workers for the CPU-bound conversion phases; ``0`` uses the CPU
            count.

        Returns
        -------
        dict[str, str]
            A human-readable summary keyed by each ARK's path, as returned by
            :py:func:`destin.harmonix.pipeline.run_game`.

        Raises
        ------
        click.Abort
            If ``game_dir`` holds no ARK with this game's layout.
        """
        if not self.accepts(game_dir):
            log.error('No %s ARK archive found under `%s`.', self.game_name, game_dir)
            msg = f'No {self.game_name} ARK archive found under `{game_dir}`.'
            raise click.Abort(msg) from ValueError(msg)
        return await run_game(game_dir,
                              out,
                              convert=convert,
                              gunzip=gunzip,
                              ignore_failures=ignore_failures,
                              jobs=jobs,
                              keep_gz=keep_gz,
                              layout=self.ark_layout)
