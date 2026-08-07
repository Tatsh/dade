"""
End-to-end ARK unpacking and asset-conversion pipeline.

Extracts an ARK archive into an output directory, decompresses ``.gz`` entries, decomposes the
contained Milo (``.rnd``) scenes, converts every recognised asset in place (bitmaps, DataArray,
meshes, audio, icons, video metadata), and runs the material-linking and sample-bank post-passes.
The CPU-bound conversion phases run across a process pool (see :py:mod:`destin.amplitude.workers`).
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging

from destin.common.json import write_json

from . import ark, audio, bitmap, mesh, workers
from .typing import InvalidFormatError

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('run', 'run_game')

log = logging.getLogger(__name__)


def _decompose_milo(root: Path, *, jobs: int, ignore_failures: bool) -> int:
    rnd_files = sorted(root.rglob('*.rnd'))
    outcome = workers.run_pool(workers.decompose_milo_file,
                               rnd_files,
                               jobs=jobs,
                               ignore_failures=ignore_failures,
                               label='decompose')
    return outcome.succeeded


def _convert_assets(root: Path, *, jobs: int, ignore_failures: bool) -> tuple[int, int]:
    assets = [
        path for path in sorted(root.rglob('*'))
        if path.is_file() and workers.has_converter(path.name)
    ]
    outcome = workers.run_pool(workers.convert_file,
                               assets,
                               jobs=jobs,
                               ignore_failures=ignore_failures,
                               label='convert')
    return outcome.succeeded, outcome.failed


def _split_banks(root: Path, *, jobs: int, ignore_failures: bool) -> tuple[int, int]:
    # The heavy VAG-ADPCM decode (per-sample WAV extraction) runs in the pool; the cheap
    # metadata-only sidecar for an ``.nse``-less ``.bnk`` is handled sequentially afterwards.
    splittable = [bnk for bnk in sorted(root.rglob('*.bnk')) if bnk.with_suffix('.nse').is_file()]
    splittable += sorted(root.rglob('*.hd'))
    outcome = workers.run_pool(workers.split_bank_file,
                               splittable,
                               jobs=jobs,
                               ignore_failures=ignore_failures,
                               label='split bank')
    json_only = 0
    for bnk in sorted(root.rglob('*.bnk')):
        if (bnk.with_suffix('') / 'manifest.json').is_file():  # A split already produced WAVs.
            continue
        try:
            bank = audio.bnk_to_json(bnk.read_bytes())
        except InvalidFormatError:
            continue
        write_json(bnk.with_name(f'{bnk.name}.json'),
                   bank,
                   ensure_ascii=False,
                   trailing_newline=False)
        json_only += 1
    return outcome.succeeded, json_only


def _convert_disc_str(game_dir: Path, out: Path, *, jobs: int, ignore_failures: bool) -> int:
    # Disc streaming songs live on the filesystem (e.g. Amplitude's AUDIO/*.STR), not inside an ARK.
    pairs = [(src, (out / src.relative_to(game_dir)).with_suffix('.wav'))
             for src in sorted(game_dir.rglob('*'))
             if src.is_file() and src.suffix.lower() == '.str' and out not in src.parents]
    outcome = workers.run_pool(workers.str_to_wav_file,
                               pairs,
                               jobs=jobs,
                               ignore_failures=ignore_failures,
                               label='convert disc audio')
    return outcome.succeeded


def run(ark_path: Path,
        out: Path,
        *,
        convert: bool = True,
        gunzip: bool = True,
        keep_gz: bool = False,
        ignore_failures: bool = False,
        jobs: int = 1,
        disc_audio: Path | None = None) -> dict[str, str]:
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
    jobs : int
        Maximum worker processes for the CPU-bound conversion phases; ``1`` runs sequentially.
    disc_audio : pathlib.Path | None
        If given, also convert the disc streaming songs in this directory to ``out/disc_audio``.

    Returns
    -------
    dict[str, str]
        A human-readable summary per pipeline step, keyed by step name.
    """
    stats = ark.extract(ark_path, out, gunzip=gunzip, keep_gz=keep_gz)
    log.info('Extracted %d files (%d skipped, %d gunzipped).', stats.written, stats.skipped,
             stats.gunzipped)
    steps = {
        'extract': f'{stats.written} files, {stats.skipped} skipped, {stats.gunzipped} gunzipped',
    }
    if not convert:
        return steps
    log.info('Decomposing Milo (.rnd) scenes...')
    decomposed = _decompose_milo(out, jobs=jobs, ignore_failures=ignore_failures)
    steps['milo'] = f'{decomposed} archives decomposed'
    log.info('Converting assets...')
    converted, failed = _convert_assets(out, jobs=jobs, ignore_failures=ignore_failures)
    steps['convert'] = f'{converted} converted, {failed} failed'
    log.info('Linking texture references...')
    referenced = bitmap.link_references(out)
    log.info('Materialised %d texture reference(s).', referenced)
    steps['references'] = f'{referenced} linked'
    linked = mesh.link_materials(out)
    log.info('Linked %d material reference(s).', linked)
    steps['materials'] = f'{linked} linked'
    bank_split, bank_json = _split_banks(out, jobs=jobs, ignore_failures=ignore_failures)
    log.info('Split %d sample bank(s) (%d json-only).', bank_split, bank_json)
    steps['banks'] = f'{bank_split} split, {bank_json} json-only'
    if disc_audio is not None:
        n_str = _convert_disc_str(disc_audio,
                                  out / 'disc_audio',
                                  jobs=jobs,
                                  ignore_failures=ignore_failures)
        steps['disc_audio'] = f'{n_str} songs'
    return steps


def _find_arks(game_dir: Path) -> list[Path]:
    return sorted(p for p in game_dir.rglob('*') if p.is_file() and p.suffix.lower() == '.ark')


def run_game(game_dir: Path,
             out: Path,
             *,
             convert: bool = True,
             gunzip: bool = True,
             keep_gz: bool = False,
             ignore_failures: bool = False,
             jobs: int = 1) -> dict[str, str]:
    """
    Unpack a whole game: every ARK under ``game_dir`` plus its on-disc streaming audio.

    Each ``*.ark`` found anywhere under ``game_dir`` is unpacked (and converted) into ``out``
    mirroring its location in the game tree (e.g. ``GEN/MAIN.ARK`` -> ``out/GEN/MAIN/``). Disc
    streaming songs (``*.STR`` outside any ARK, e.g. Amplitude's ``AUDIO/``) are converted to WAV
    under ``out`` at the same relative path. The ARK layout (Amplitude vs FreQuency) is
    auto-detected.

    Parameters
    ----------
    game_dir : pathlib.Path
        The game's root directory (the disc root).
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
        Maximum worker processes for the CPU-bound conversion phases; ``1`` runs sequentially.

    Returns
    -------
    dict[str, str]
        A human-readable summary keyed by each ARK's path (relative to ``game_dir``), plus a
        ``disc_audio`` entry when on-disc ``.STR`` songs are present.

    Raises
    ------
    FileNotFoundError
        If no ARK files are found under ``game_dir``.
    """
    arks = _find_arks(game_dir)
    if not arks:
        msg = f'No .ark files found under `{game_dir}`.'
        raise FileNotFoundError(msg)
    log.info('Found %d ARK(s) under `%s` (jobs=%d).', len(arks), game_dir, jobs)
    out.mkdir(parents=True, exist_ok=True)
    summary: dict[str, str] = {}
    for ark_path in arks:
        rel = ark_path.relative_to(game_dir)
        dest = out / rel.with_suffix('')
        log.info('Unpacking `%s` -> `%s`.', rel, dest)
        steps = run(ark_path,
                    dest,
                    convert=convert,
                    gunzip=gunzip,
                    ignore_failures=ignore_failures,
                    jobs=jobs,
                    keep_gz=keep_gz)
        summary[str(rel)] = '; '.join(f'{k}: {v}' for k, v in steps.items())
    if convert and (n_str := _convert_disc_str(
            game_dir, out, jobs=jobs, ignore_failures=ignore_failures)):
        summary['disc_audio'] = f'{n_str} disc .str songs converted'
    return summary
