"""Template base for the per-game Harmonix ARK unpackers (Amplitude and FreQuency)."""
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar
import asyncio
import logging

from destin.common.disc import mount, mount_sync, open_image
from destin.common.typing import InvalidFormatError
import anyio

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
    cue/bin pair (the CD release); a disc image is mounted read-only into a temporary directory for
    the duration of a walk (see :py:func:`destin.common.disc.mount`).

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
        with mount_sync(self.source) as root:
            for ark_path in _find_arks(root):
                yield from _carve(ark_path.read_bytes())

    def accepts(self) -> bool:
        r"""
        Report whether :py:attr:`source` holds at least one ARK with this game's layout.

        Every ``*.ark`` on the disc is peeked (its leading four bytes); a ``ARK\0`` magic marks the
        FreQuency layout and anything else marks the Amplitude layout. A disc image is peeked in
        place (its ARK headers are read directly), so no extraction happens.

        Returns
        -------
        bool
            ``True`` if some ARK under :py:attr:`source` matches :py:attr:`ark_layout`.
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
        Unpack this game's ARKs under :py:attr:`source` into ``out``.

        When :py:attr:`source` is a disc image, it is mounted read-only into a temporary directory
        for the run. An ``out`` that is, or is nested inside, a source directory is rejected with
        :py:exc:`ValueError` before any extraction begins.

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
            Delete each converted intermediate file from ``out`` (the source is never touched).
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
        destin.common.typing.InvalidFormatError
            If :py:attr:`source` is not a readable disc image, or holds no ARK with this game's
            layout.
        """
        self._reject_bad_output(out)
        async with mount(self.source) as root:
            if not any(layout == self.ark_layout for layout in _dir_ark_layouts(root)):
                log.error('No %s ARK archive found under `%s`.', self.game_name, self.source)
                msg = f'No {self.game_name} ARK archive found under `{self.source}`.'
                raise InvalidFormatError(msg)
            return await run_game(root,
                                  out,
                                  convert=convert,
                                  delete=delete,
                                  gunzip=gunzip,
                                  ignore_failures=ignore_failures,
                                  jobs=jobs,
                                  keep_gz=keep_gz,
                                  layout=self.ark_layout,
                                  on_status=on_status)

    async def _aiter(self) -> AsyncIterator[Asset]:
        # The mount must live inside this generator because ``__aiter__`` is synchronous and cannot
        # await it. Consuming the iterator with ``async for`` closes the generator and unwinds the
        # mount, so the temporary directory is always cleaned up (ASYNC119 flags only the
        # closed-on-garbage-collection edge, which this API does not expose).
        async with mount(self.source) as root:
            for ark_path in _find_arks(root):
                data = await anyio.Path(ark_path).read_bytes()
                directory = await asyncio.to_thread(parse_directory, data)
                for entry in directory.entries:
                    end = entry.offset + entry.size
                    if end <= len(data):  # Skip any record whose data runs past the archive.
                        yield Asset(entry.path, data[entry.offset:end])  # noqa: ASYNC119

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
            (writing outputs into the disc being read).
        """
        if not self.source.is_dir():
            return
        source = self.source.resolve()
        destination = out.resolve()
        if destination == source or source in destination.parents:
            log.error('Output directory `%s` is inside the input `%s`.', out, self.source)
            msg = f'Output directory `{out}` cannot be inside the input `{self.source}`.'
            raise ValueError(msg)
