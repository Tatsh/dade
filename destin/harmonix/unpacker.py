"""Template base for the per-game Harmonix ARK unpackers (Amplitude and FreQuency)."""
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar
import asyncio
import logging

from destin.common.disc import iter_ark_bytes, materialize, open_image
from destin.common.exceptions import InvalidFormatError

from .ark import _FREQ_MAGIC, parse_directory
from .pipeline import _find_arks, run_game
from .typing import Asset

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator
    from pathlib import Path

    from destin.common.iso9660 import Iso9660Image

    from .typing import ArkLayout

__all__ = ('Asset', 'Unpacker')

log = logging.getLogger(__name__)


def _carve(data: bytes) -> Iterator[Asset]:
    for entry in parse_directory(data).entries:
        end = entry.offset + entry.size
        if end <= len(data):  # Skip any record whose data runs past the archive.
            yield Asset(entry.path, data[entry.offset:end])


def _dir_ark_layouts(root: Path) -> Iterator[ArkLayout]:
    for ark_path in _find_arks(root):
        with ark_path.open('rb') as src:
            yield 'frequency' if src.read(4) == _FREQ_MAGIC else 'amplitude'


def _image_ark_layouts(image: Iso9660Image) -> Iterator[ArkLayout]:
    for path, _ in image.iter_files():
        if path.upper().endswith('.ARK'):
            yield 'frequency' if image.read_file(path, 4) == _FREQ_MAGIC else 'amplitude'


class Unpacker:
    """
    Template base for a single Harmonix game's ARK unpacker, bound to a source disc.

    The source may be an already-extracted directory, a raw PS2 ISO image, or the ``.cue`` of a
    cue/bin pair (the CD release). :py:meth:`unpack` materialises the source into the output
    directory -- an image is extracted, a directory is copied -- and processes it there in place
    (see :py:func:`destin.common.disc.materialize`); the source is only read, never modified.

    A concrete subclass sets :py:attr:`game_name` and :py:attr:`ark_layout`; the base supplies
    :py:meth:`accepts` (which detects whether :py:attr:`source` holds this game's ARKs) and
    :py:meth:`unpack` (which validates the source and delegates to
    :py:func:`destin.harmonix.pipeline.run_game` with the fixed layout).

    An instance is also iterable over its raw carve-outs, read directly from the source without
    materialising anything: :py:meth:`__aiter__` (primary) and :py:meth:`__iter__` (convenience)
    yield an :py:class:`destin.harmonix.typing.Asset` per entry of every ARK on :py:attr:`source`,
    in a deterministic order (ARKs sorted by path, then each ARK's entry-table order), without
    decompressing or converting anything.
    """

    ark_layout: ClassVar[ArkLayout]
    """The ARK layout this unpacker reads (``'amplitude'`` or ``'frequency'``)."""
    game_name: ClassVar[str]
    """The human-readable game name (for example ``'Amplitude'``)."""
    def __init__(self, source: Path) -> None:
        """
        Bind the unpacker to a source disc.

        Parameters
        ----------
        source : pathlib.Path
            The game's disc: an already-extracted root directory, a PS2 ISO image, or the ``.cue``
            of a cue/bin pair.
        """
        self.source = source
        """The game's disc source bound to this unpacker."""

    def __aiter__(self) -> AsyncIterator[Asset]:
        """
        Return an async iterator over the raw carve-outs of every ARK on :py:attr:`source`.

        Returns
        -------
        collections.abc.AsyncIterator[destin.harmonix.typing.Asset]
            An async iterator yielding one asset per ARK entry, in deterministic order.
        """
        return self._aiter()

    def __iter__(self) -> Iterator[Asset]:
        """
        Yield the raw carve-outs of every ARK on :py:attr:`source`.

        Yields
        ------
        destin.harmonix.typing.Asset
            Each ARK entry's path and raw bytes, in deterministic order.
        """
        for data in iter_ark_bytes(self.source):
            yield from _carve(data)

    def accepts(self) -> bool:
        r"""
        Report whether :py:attr:`source` holds at least one ARK with this game's layout.

        Every ``*.ark`` on the disc is peeked (its leading four bytes); a ``ARK\0`` magic marks the
        FreQuency layout and anything else marks the Amplitude layout. A disc image is peeked in
        place (its ARK headers are read directly), so no extraction happens.

        Returns
        -------
        bool
            ``True`` if some ARK on :py:attr:`source` matches :py:attr:`ark_layout`.
        """
        if self.source.is_dir():
            return any(layout == self.ark_layout for layout in _dir_ark_layouts(self.source))
        return any(
            layout == self.ark_layout for layout in _image_ark_layouts(open_image(self.source)))

    async def unpack(self,
                     out: Path,
                     *,
                     convert: bool = True,
                     gunzip: bool = True,
                     keep_gz: bool = False,
                     ignore_failures: bool = False,
                     delete: bool = False,
                     jobs: int = 0,
                     on_status: Callable[[str], None] | None = None) -> dict[str, str]:
        """
        Materialise this game's disc into ``out`` and unpack it in place.

        The source is copied into ``out`` (an ISO or cue/bin image is extracted, a directory is
        copied) and every asset is then processed there; the source is never modified. An ``out``
        that is, or is nested inside, a source directory is rejected with :py:exc:`ValueError`
        before any work begins.

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
        delete : bool
            Delete every materialised intermediate from ``out`` -- the ARK archives, the disc-audio
            ``.str`` files, and the raw pre-conversion assets -- keeping only the converted output.
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
        destin.common.exceptions.InvalidFormatError
            If :py:attr:`source` is not a readable disc image, or holds no ARK with this game's
            layout.
        """
        self._reject_bad_output(out)
        if not self.accepts():
            log.error('No %s ARK archive found on `%s`.', self.game_name, self.source)
            msg = f'No {self.game_name} ARK archive found on `{self.source}`.'
            raise InvalidFormatError(msg)
        await materialize(self.source, out)
        return await run_game(out,
                              convert=convert,
                              delete=delete,
                              gunzip=gunzip,
                              ignore_failures=ignore_failures,
                              jobs=jobs,
                              keep_gz=keep_gz,
                              layout=self.ark_layout,
                              on_status=on_status)

    async def _aiter(self) -> AsyncIterator[Asset]:
        # Pull each ARK's bytes from the synchronous reader in a worker thread (its file/image reads
        # block), so the source is streamed without materialising anything and the event loop is
        # never blocked. ``None`` is the end sentinel -- an ARK's bytes are never ``None``.
        ark_bytes = iter_ark_bytes(self.source)
        while (data := await asyncio.to_thread(lambda: next(ark_bytes, None))) is not None:
            directory = await asyncio.to_thread(parse_directory, data)
            for entry in directory.entries:
                end = entry.offset + entry.size
                if end <= len(data):  # Skip any record whose data runs past the archive.
                    yield Asset(entry.path, data[entry.offset:end])

    def _reject_bad_output(self, out: Path) -> None:
        """
        Reject an output directory that is, or is nested inside, a source directory.

        Parameters
        ----------
        out : pathlib.Path
            The requested output directory.

        Raises
        ------
        ValueError
            If :py:attr:`source` is a directory and ``out`` is that directory or lies within it
            (materialising the disc into part of itself).
        """
        if not self.source.is_dir():
            return
        source = self.source.resolve()
        destination = out.resolve()
        if destination == source or source in destination.parents:
            log.error('Output directory `%s` is inside the input `%s`.', out, self.source)
            msg = f'Output directory `{out}` cannot be inside the input `{self.source}`.'
            raise ValueError(msg)
