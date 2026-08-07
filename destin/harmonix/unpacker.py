"""Template base for the per-game Harmonix ARK unpackers (Amplitude and FreQuency)."""
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar
import asyncio
import logging

import anyio
import click

from .ark import _FREQ_MAGIC, parse_directory
from .pipeline import _find_arks, run_game
from .typing import Asset

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator
    from pathlib import Path

    from .typing import ArkLayout

__all__ = ('Asset', 'Unpacker')

log = logging.getLogger(__name__)


def _carve(data: bytes) -> Iterator[Asset]:
    for entry in parse_directory(data).entries:
        end = entry.offset + entry.size
        if end <= len(data):  # Skip any record whose data runs past the archive.
            yield Asset(entry.path, data[entry.offset:end])


class Unpacker:
    """
    Template base for a single Harmonix game's ARK unpacker, bound to a source directory.

    A concrete subclass sets :py:attr:`game_name` and :py:attr:`ark_layout`; the base supplies
    :py:meth:`accepts` (which detects whether :py:attr:`source` holds this game's ARKs) and
    :py:meth:`unpack` (which validates the source and delegates to
    :py:func:`destin.harmonix.pipeline.run_game` with the fixed layout).

    An instance is also iterable over its raw carve-outs: :py:meth:`__aiter__` (primary) and
    :py:meth:`__iter__` (convenience) yield an :py:class:`destin.harmonix.typing.Asset` per entry of
    every ARK under :py:attr:`source`, in a deterministic order (ARKs sorted by path, then each
    ARK's entry-table order), without decompressing or converting anything.
    """

    ark_layout: ClassVar[ArkLayout]
    """The ARK layout this unpacker reads (``'amplitude'`` or ``'frequency'``)."""
    game_name: ClassVar[str]
    """The human-readable game name (for example ``'Amplitude'``)."""
    def __init__(self, source: Path) -> None:
        """
        Bind the unpacker to a source directory.

        Parameters
        ----------
        source : pathlib.Path
            The game's root directory (the disc root) to scan for ARKs and disc audio.
        """
        self.source = source
        """The game's root directory bound to this unpacker."""

    def __aiter__(self) -> AsyncIterator[Asset]:
        """
        Return an async iterator over the raw carve-outs of every ARK under :py:attr:`source`.

        Returns
        -------
        collections.abc.AsyncIterator[destin.harmonix.typing.Asset]
            An async iterator yielding one asset per ARK entry, in deterministic order.
        """
        return self._aiter()

    def __iter__(self) -> Iterator[Asset]:
        """
        Yield the raw carve-outs of every ARK under :py:attr:`source`.

        Yields
        ------
        destin.harmonix.typing.Asset
            Each ARK entry's path and raw bytes, in deterministic order.
        """
        for ark_path in _find_arks(self.source):
            yield from _carve(ark_path.read_bytes())

    def accepts(self) -> bool:
        r"""
        Report whether :py:attr:`source` holds at least one ARK with this game's layout.

        Every ``*.ark`` found under :py:attr:`source` is peeked (its leading four bytes); a
        ``ARK\0`` magic marks the FreQuency layout and anything else marks the Amplitude layout.

        Returns
        -------
        bool
            ``True`` if some ARK under :py:attr:`source` matches :py:attr:`ark_layout`.
        """
        for ark_path in _find_arks(self.source):
            with ark_path.open('rb') as src:
                layout: ArkLayout = 'frequency' if src.read(4) == _FREQ_MAGIC else 'amplitude'
            if layout == self.ark_layout:
                return True
        return False

    async def unpack(self,
                     out: Path,
                     *,
                     convert: bool = True,
                     gunzip: bool = True,
                     keep_gz: bool = False,
                     ignore_failures: bool = False,
                     jobs: int = 0,
                     on_status: Callable[[str], None] | None = None) -> dict[str, str]:
        """
        Unpack this game's ARKs under :py:attr:`source` into ``out``.

        Parameters
        ----------
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
        on_status : collections.abc.Callable[[str], None] | None
            An optional progress hook called with a short status string at each phase (for example
            ``'Unpacking GEN/MAIN.ARK'`` or ``'Converting assets'``).

        Returns
        -------
        dict[str, str]
            A human-readable summary keyed by each ARK's path, as returned by
            :py:func:`destin.harmonix.pipeline.run_game`.

        Raises
        ------
        click.Abort
            If :py:attr:`source` holds no ARK with this game's layout.
        """
        if not self.accepts():
            log.error('No %s ARK archive found under `%s`.', self.game_name, self.source)
            msg = f'No {self.game_name} ARK archive found under `{self.source}`.'
            raise click.Abort(msg) from ValueError(msg)
        return await run_game(self.source,
                              out,
                              convert=convert,
                              gunzip=gunzip,
                              ignore_failures=ignore_failures,
                              jobs=jobs,
                              keep_gz=keep_gz,
                              layout=self.ark_layout,
                              on_status=on_status)

    async def _aiter(self) -> AsyncIterator[Asset]:
        for ark_path in _find_arks(self.source):
            data = await anyio.Path(ark_path).read_bytes()
            directory = await asyncio.to_thread(parse_directory, data)
            for entry in directory.entries:
                end = entry.offset + entry.size
                if end <= len(data):  # Skip any record whose data runs past the archive.
                    yield Asset(entry.path, data[entry.offset:end])
