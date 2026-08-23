"""
End-to-end ARK unpacking and asset-conversion pipeline.

Extracts an ARK archive into an output directory, decompresses ``.gz`` entries, decomposes the
contained Milo (``.rnd``) scenes, converts every recognised asset in place (bitmaps, DataArray,
meshes, audio, icons, video metadata), and runs the material-linking and sample-bank post-passes.
The CPU-bound conversion phases run concurrently across a thread pool (see
:py:mod:`destin.harmonix.workers`).
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import asyncio
import logging

import anyio

from destin.common.exceptions import InvalidFormatError
from destin.common.json import write_json

from . import ark, audio, bitmap, mesh, workers

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from .typing import ArkLayout

__all__ = ('run', 'run_game')

log = logging.getLogger(__name__)

_BANK_SIBLINGS = {'.bnk': '.nse', '.hd': '.bd'}
"""Companion file removed alongside each consumed sample bank keyed by the bank's suffix.

:meta hide-value:
"""


def _delete_intermediates(paths: Iterable[Path]) -> int:
    """
    Delete converted intermediate files (and any sample-bank companion) from the output tree.

    Parameters
    ----------
    paths : collections.abc.Iterable[pathlib.Path]
        The intermediate input files whose conversions succeeded.

    Returns
    -------
    int
        The number of files removed.
    """
    removed = 0
    for path in paths:
        targets = [path]
        if (sibling := _BANK_SIBLINGS.get(path.suffix.lower())) is not None:
            targets.append(path.with_suffix(sibling))
        for target in targets:
            if target.is_file():
                target.unlink()
                removed += 1
    return removed


async def _decompose_milo(root: anyio.Path,
                          *,
                          jobs: int,
                          ignore_failures: bool,
                          consumed: list[Path] | None = None) -> int:
    rnd_files = sorted([Path(p) async for p in root.rglob('*.rnd')])
    outcome = await workers.run_pool(workers.decompose_milo_file,
                                     rnd_files,
                                     consumed=consumed,
                                     ignore_failures=ignore_failures,
                                     jobs=jobs,
                                     label='decompose')
    return outcome.succeeded


async def _convert_assets(root: anyio.Path,
                          *,
                          jobs: int,
                          ignore_failures: bool,
                          consumed: list[Path] | None = None) -> tuple[int, int]:
    assets = sorted([
        Path(path) async for path in root.rglob('*')
        if await path.is_file() and workers.has_converter(path.name)
    ])
    outcome = await workers.run_pool(workers.convert_file,
                                     assets,
                                     consumed=consumed,
                                     ignore_failures=ignore_failures,
                                     jobs=jobs,
                                     label='convert')
    return outcome.succeeded, outcome.failed


async def _split_banks(root: anyio.Path,
                       *,
                       jobs: int,
                       ignore_failures: bool,
                       consumed: list[Path] | None = None) -> tuple[int, int]:
    # The heavy VAG-ADPCM decode (per-sample WAV extraction) runs in the pool; the cheap
    # metadata-only sidecar for an ``.nse``-less ``.bnk`` is handled sequentially afterwards.
    splittable = sorted(
        [Path(bnk) async for bnk in root.rglob('*.bnk') if await bnk.with_suffix('.nse').is_file()])
    splittable += sorted([Path(hd) async for hd in root.rglob('*.hd')])
    outcome = await workers.run_pool(workers.split_bank_file,
                                     splittable,
                                     consumed=consumed,
                                     ignore_failures=ignore_failures,
                                     jobs=jobs,
                                     label='split bank')
    json_only = 0
    for bnk in sorted([bnk async for bnk in root.rglob('*.bnk')]):
        # A split that already produced WAVs writes a manifest, so skip the metadata-only sidecar.
        if await (bnk.with_suffix('') / 'manifest.json').is_file():
            continue
        try:
            bank = audio.bnk_to_json(await bnk.read_bytes())
        except InvalidFormatError:
            continue
        write_json(Path(bnk.with_name(f'{bnk.name}.json')),
                   bank,
                   ensure_ascii=False,
                   trailing_newline=False)
        if consumed is not None:
            consumed.append(Path(bnk))
        json_only += 1
    return outcome.succeeded, json_only


async def _convert_disc_str(game_dir: anyio.Path,
                            out: anyio.Path,
                            *,
                            jobs: int,
                            ignore_failures: bool,
                            consumed: list[Path] | None = None) -> int:
    # Disc streaming songs live on the filesystem (e.g. Amplitude's AUDIO/*.STR), not inside an ARK.
    pairs = sorted([(Path(src), Path((out / src.relative_to(game_dir)).with_suffix('.wav')))
                    async for src in game_dir.rglob('*')
                    if await src.is_file() and src.suffix.lower() == '.str'])
    outcome = await workers.run_pool(workers.str_to_wav_file,
                                     pairs,
                                     ignore_failures=ignore_failures,
                                     jobs=jobs,
                                     label='convert disc audio')
    if consumed is not None:
        for src, dst in pairs:
            if await anyio.Path(dst).is_file():
                consumed.append(src)
    return outcome.succeeded


async def run(ark_path: Path,
              out: Path,
              *,
              convert: bool = True,
              gunzip: bool = True,
              keep_gz: bool = False,
              ignore_failures: bool = False,
              delete: bool = False,
              jobs: int = 1,
              disc_audio: Path | None = None,
              layout: ArkLayout | None = None,
              on_status: Callable[[str], None] | None = None) -> dict[str, str]:
    """
    Unpack an ARK archive into ``out`` and convert its assets in place.

    Parameters
    ----------
    ark_path : pathlib.Path
        The ARK archive to unpack.
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
        Delete each converted intermediate file from ``out`` once the reference-linking passes have
        run (the extracted source stays untouched). Ignored when ``convert`` is false.
    jobs : int
        Maximum concurrent workers for the CPU-bound conversion phases; ``0`` uses the CPU count.
    disc_audio : pathlib.Path | None
        If given, also convert the disc streaming songs in this directory to ``out/disc_audio``.
    layout : destin.harmonix.typing.ArkLayout | None
        Force a specific ARK layout, or ``None`` to auto-detect it from the leading bytes.
    on_status : collections.abc.Callable[[str], None] | None
        An optional progress hook called with a short status string at each conversion phase.

    Returns
    -------
    dict[str, str]
        A human-readable summary per pipeline step, keyed by step name.
    """
    stats = ark.extract(ark_path, out, gunzip=gunzip, keep_gz=keep_gz, layout=layout)
    log.info('Extracted %d files (%d skipped, %d gunzipped).', stats.written, stats.skipped,
             stats.gunzipped)
    steps = {
        'extract': f'{stats.written} files, {stats.skipped} skipped, {stats.gunzipped} gunzipped',
    }
    if not convert:
        return steps
    anyio_out = anyio.Path(out)
    # Intermediates are collected across the conversion phases and pruned only after the
    # reference-linking passes below, which rewrite every reference to a converted name.
    consumed: list[Path] | None = [] if delete else None
    log.info('Decomposing Milo (.rnd) scenes...')
    if on_status is not None:
        on_status('Decomposing Milo scenes')
    decomposed = await _decompose_milo(anyio_out,
                                       consumed=consumed,
                                       ignore_failures=ignore_failures,
                                       jobs=jobs)
    steps['milo'] = f'{decomposed} archives decomposed'
    log.info('Converting assets...')
    if on_status is not None:
        on_status('Converting assets')
    converted, failed = await _convert_assets(anyio_out,
                                              consumed=consumed,
                                              ignore_failures=ignore_failures,
                                              jobs=jobs)
    steps['convert'] = f'{converted} converted, {failed} failed'
    log.info('Linking texture references...')
    referenced = await asyncio.to_thread(bitmap.link_references, out)
    log.info('Materialised %d texture reference(s).', referenced)
    steps['references'] = f'{referenced} linked'
    linked = await asyncio.to_thread(mesh.link_materials, out)
    log.info('Linked %d material reference(s).', linked)
    steps['materials'] = f'{linked} linked'
    bank_split, bank_json = await _split_banks(anyio_out,
                                               consumed=consumed,
                                               ignore_failures=ignore_failures,
                                               jobs=jobs)
    log.info('Split %d sample bank(s) (%d json-only).', bank_split, bank_json)
    steps['banks'] = f'{bank_split} split, {bank_json} json-only'
    if consumed is not None:
        removed = await asyncio.to_thread(_delete_intermediates, consumed)
        log.info('Deleted %d intermediate file(s).', removed)
        steps['deleted'] = f'{removed} intermediates removed'
    if disc_audio is not None:
        n_str = await _convert_disc_str(anyio.Path(disc_audio),
                                        anyio.Path(out / 'disc_audio'),
                                        jobs=jobs,
                                        ignore_failures=ignore_failures)
        steps['disc_audio'] = f'{n_str} songs'
    return steps


def _find_arks(game_dir: Path) -> list[Path]:
    return sorted(p for p in game_dir.rglob('*') if p.is_file() and p.suffix.lower() == '.ark')


async def run_game(work_dir: Path,
                   *,
                   convert: bool = True,
                   gunzip: bool = True,
                   keep_gz: bool = False,
                   ignore_failures: bool = False,
                   delete: bool = False,
                   jobs: int = 1,
                   layout: ArkLayout | None = None,
                   on_status: Callable[[str], None] | None = None) -> dict[str, str]:
    """
    Unpack a whole game in place: every ARK in ``work_dir`` plus its on-disc streaming audio.

    ``work_dir`` already holds the materialised disc (see
    :py:func:`destin.common.disc.materialize`). Each ``*.ark`` in it is unpacked beside itself (e.g.
    ``GEN/MAIN.ARK`` -> ``GEN/MAIN/``) and its assets converted; disc streaming songs (``*.STR``)
    are converted to WAV in place. The ARK layout (Amplitude vs FreQuency) is auto-detected. With
    ``delete``, the materialised intermediates -- the ARK archives, the ``.str`` files, and the raw
    pre-conversion assets -- are removed, leaving only the converted output.

    Parameters
    ----------
    work_dir : pathlib.Path
        The directory holding the materialised disc, processed in place.
    convert : bool
        Convert extracted assets to standard formats (otherwise extract raw).
    gunzip : bool
        Decompress ``.gz`` entries in place during extraction.
    keep_gz : bool
        Keep the original ``.gz`` entry alongside the decompressed output.
    ignore_failures : bool
        Log and skip a converter/decompose failure instead of stopping the run.
    delete : bool
        Delete the materialised intermediates (the ARK archives, the ``.str`` files, and the raw
        assets) after conversion. Ignored when ``convert`` is false.
    jobs : int
        Maximum concurrent workers for the CPU-bound conversion phases; ``0`` uses the CPU count.
    layout : destin.harmonix.typing.ArkLayout | None
        Force a specific ARK layout for every archive, or ``None`` to auto-detect each one.
    on_status : collections.abc.Callable[[str], None] | None
        An optional progress hook called with a short status string as each ARK and the disc audio
        are processed (for example ``'Unpacking GEN/MAIN.ARK'``).

    Returns
    -------
    dict[str, str]
        A human-readable summary keyed by each ARK's path (relative to ``work_dir``), plus a
        ``disc_audio`` entry when on-disc ``.STR`` songs are present.

    Raises
    ------
    FileNotFoundError
        If no ARK files are found in ``work_dir``.
    """
    # Snapshot the ARK list before extraction so files produced by unpacking are not re-scanned.
    arks = sorted([
        Path(p) async for p in anyio.Path(work_dir).rglob('*')
        if await p.is_file() and p.suffix.lower() == '.ark'
    ])
    if not arks:
        msg = f'No .ark files found in `{work_dir}`.'
        raise FileNotFoundError(msg)
    log.info('Found %d ARK(s) in `%s` (jobs=%d).', len(arks), work_dir, jobs)
    summary: dict[str, str] = {}
    # Top-level intermediates (the ARK archives and disc ``.str`` files) are removed at the end when
    # ``delete`` is set; ``run`` already prunes each ARK's own converted intermediates.
    consumed: list[Path] = []
    for ark_path in arks:
        rel = ark_path.relative_to(work_dir)
        dest = work_dir / rel.with_suffix('')
        log.info('Unpacking `%s` -> `%s`.', rel, dest)
        if on_status is not None:
            on_status(f'Unpacking {rel}')
        steps = await run(ark_path,
                          dest,
                          convert=convert,
                          delete=delete,
                          gunzip=gunzip,
                          ignore_failures=ignore_failures,
                          jobs=jobs,
                          keep_gz=keep_gz,
                          layout=layout,
                          on_status=on_status)
        summary[str(rel)] = '; '.join(f'{k}: {v}' for k, v in steps.items())
        if delete:
            consumed.append(ark_path)
    if convert:
        if on_status is not None:
            on_status('Converting disc audio')
        if n_str := await _convert_disc_str(anyio.Path(work_dir),
                                            anyio.Path(work_dir),
                                            consumed=consumed if delete else None,
                                            ignore_failures=ignore_failures,
                                            jobs=jobs):
            summary['disc_audio'] = f'{n_str} disc .str songs converted'
    if delete and consumed:
        removed = await asyncio.to_thread(_delete_intermediates, consumed)
        log.info('Deleted %d disc intermediate(s).', removed)
        summary['deleted'] = f'{removed} disc files removed'
    return summary
