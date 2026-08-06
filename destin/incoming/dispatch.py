"""Mirror a source tree into an output directory, converting or copying each file."""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import asyncio
import logging
import pathlib
import shutil

from anyio import Path
from destin.common.context import using_input_root
from destin.common.utils import pluralize
from typing_extensions import override

from .converters import RULES, ConversionError, UnsupportedFormatError

if TYPE_CHECKING:
    from .converters import Rule
    from .sources import PreparedSource

__all__ = ('ConversionJob', 'ConversionSummary', 'convert_file', 'run_conversions')

log = logging.getLogger(__name__)


class ConversionSummary(NamedTuple):
    """Totals from mirroring a source tree into an output directory."""

    converted: int
    """Number of source files successfully converted."""
    produced: int
    """Number of converted output files written."""
    copied: int
    """Number of files copied verbatim (no converter, or not yet decoded)."""
    skipped: int
    """Number of matched files whose format is documented but not yet decoded."""
    failed: int
    """Number of matched files that errored during conversion (copied verbatim instead)."""
    @override
    def __add__(self, other: object) -> ConversionSummary:
        """
        Add two summaries field by field.

        Returns
        -------
        ConversionSummary
            The element-wise sum of the two summaries.
        """
        if not isinstance(other, ConversionSummary):
            return NotImplemented
        return ConversionSummary(*(a + b for a, b in zip(self, other, strict=True)))


class ConversionJob(NamedTuple):
    """A single file to convert or copy into a destination directory."""

    source: Path
    """The source file."""
    dest_dir: Path
    """The destination directory (already created)."""
    input_root: Path
    """The root of the source tree, used to resolve sibling assets such as textures."""


_EMPTY_SUMMARY = ConversionSummary(0, 0, 0, 0, 0)


def _match_rule(path: pathlib.Path) -> Rule | None:
    return next((rule for rule in RULES if rule.match(path)), None)


def _copy(source: pathlib.Path, dest_dir: pathlib.Path) -> None:
    shutil.copy2(source, dest_dir / source.name)


def _convert_sync(rule: Rule, source: pathlib.Path, dest_dir: pathlib.Path,
                  input_root: pathlib.Path) -> pathlib.Path | tuple[pathlib.Path, ...]:
    with using_input_root(input_root):
        return rule.convert(source, dest_dir)


async def convert_file(source: Path, dest_dir: Path, input_root: Path,
                       warned: set[str]) -> ConversionSummary:
    """
    Convert or copy a single file into *dest_dir*.

    The synchronous converter (or file copy) runs in a worker thread so that gathered jobs make
    progress concurrently.

    Parameters
    ----------
    source : anyio.Path
        The source file.
    dest_dir : anyio.Path
        The destination directory (already created).
    input_root : anyio.Path
        The root of the source tree, used to resolve sibling assets such as textures.
    warned : set[str]
        Format names already warned about, mutated to suppress duplicate warnings.

    Returns
    -------
    ConversionSummary
        The totals contributed by this file.
    """
    src = pathlib.Path(source)
    dest = pathlib.Path(dest_dir)
    if (rule := _match_rule(src)) is None:
        await asyncio.to_thread(_copy, src, dest)
        return ConversionSummary(0, 0, 1, 0, 0)
    try:
        result = await asyncio.to_thread(_convert_sync, rule, src, dest, pathlib.Path(input_root))
    except UnsupportedFormatError as e:
        if rule.name not in warned:
            warned.add(rule.name)
            log.warning('Copying %s files unconverted: %s', rule.name, e)
        await asyncio.to_thread(_copy, src, dest)
        return ConversionSummary(0, 0, 1, 1, 0)
    except ConversionError as e:
        log.error('%s', e)  # ruff:ignore[error-instead-of-exception]
        await asyncio.to_thread(_copy, src, dest)
        return ConversionSummary(0, 0, 1, 0, 1)
    produced = len(result) if isinstance(result, tuple) else 1
    log.debug('Converted `%s` to %s.', src, pluralize(produced, 'file'))
    return ConversionSummary(1, produced, 0, 0, 0)


async def _enqueue_jobs(prepared: PreparedSource, output: Path,
                        queue: asyncio.Queue[ConversionJob | None]) -> None:
    if prepared.root is not None:
        root = Path(prepared.root)
        for source in sorted([path async for path in root.rglob('*')], key=str):
            if not await source.is_file():
                continue
            dest_dir = output / source.relative_to(root).parent
            await dest_dir.mkdir(parents=True, exist_ok=True)
            await queue.put(ConversionJob(source, dest_dir, root))
    for asset in prepared.files:
        path = Path(asset)
        await queue.put(ConversionJob(path, output, path.parent))


async def _worker(queue: asyncio.Queue[ConversionJob | None],
                  warned: set[str]) -> ConversionSummary:
    total = _EMPTY_SUMMARY
    while (job := await queue.get()) is not None:
        total += await convert_file(job.source, job.dest_dir, job.input_root, warned)
    return total


async def run_conversions(prepared: PreparedSource, output: Path, *,
                          jobs: int) -> ConversionSummary:
    """
    Convert every prepared file into *output* using a pool of worker tasks.

    All jobs are enqueued, then *jobs* workers consume the queue concurrently and their per-worker
    totals are gathered and summed.

    Parameters
    ----------
    prepared : PreparedSource
        The tree root and loose files to convert.
    output : anyio.Path
        The output directory the source tree is mirrored into.
    jobs : int
        The number of concurrent worker tasks.

    Returns
    -------
    ConversionSummary
        The aggregate totals.
    """
    queue: asyncio.Queue[ConversionJob | None] = asyncio.Queue()
    warned: set[str] = set()
    await _enqueue_jobs(prepared, output, queue)
    for _ in range(jobs):
        await queue.put(None)
    totals = await asyncio.gather(*(_worker(queue, warned) for _ in range(jobs)))
    return sum(totals, _EMPTY_SUMMARY)
