"""``tonesphere save`` - inspect and edit ``save.bin``."""
from __future__ import annotations

from pathlib import Path
import logging

import click

from dade.bit192.save import DLC_OFFSETS, SaveFile

from .utils import console, debug_option

__all__ = ('save',)

log = logging.getLogger(__name__)


@click.group()
def save() -> None:
    """Inspect and edit a Tone Sphere ``save.bin``."""


@save.command(name='device-id')
@click.argument('save_path', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@debug_option
def device_id(save_path: Path) -> None:
    """Print the device id cached in SAVE_PATH (DLC tokens are bound to it)."""
    found = SaveFile.load(save_path).device_id
    console.print(f'Device ID: {found}.' if found else 'No device id is cached; run the game once.')


@save.command(name='unlock-dlc')
@click.argument('save_path', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('-o',
              '--out',
              type=click.Path(dir_okay=False, path_type=Path),
              help='Write to this path instead of overwriting SAVE_PATH.')
@click.option('-p',
              '--pack',
              'packs',
              multiple=True,
              type=click.Choice(sorted(DLC_OFFSETS)),
              help='Unlock only this pack (repeatable). Default: all packs.')
@debug_option
def unlock_dlc(save_path: Path, out: Path | None, packs: tuple[str, ...]) -> None:
    """
    Write DLC ownership tokens into SAVE_PATH.

    Tokens are ``MD5(device_id + pack)``, so the save must come from the target device (its device
    id is read straight out of the file). The integrity hash is never verified on load, so no
    checksum fix-up is needed for local use.
    """
    sf = SaveFile.load(save_path)
    log.debug('Editing save with device id %r.', sf.device_id)
    unlocked = [*packs] if packs else sf.unlock_all_dlc()
    for name in packs:
        sf.unlock_dlc(name)
    dest = out or save_path
    sf.save(dest)
    console.print(f'[green]Unlocked {", ".join(unlocked)} and wrote {dest}.[/green]')


@save.command(name='unlock-songs')
@click.argument('save_path', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('-o',
              '--out',
              type=click.Path(dir_okay=False, path_type=Path),
              help='Write to this path instead of overwriting SAVE_PATH.')
@debug_option
def unlock_songs(save_path: Path, out: Path | None) -> None:
    """
    Unlock every regular (non-DLC) song in SAVE_PATH.

    Sets the whole song unlock-flag array, so every ``UnlockNum``-gated song becomes visible without
    meeting its ``CondChart``/``CondStar`` condition. DLC episodes need device-bound tokens instead;
    use ``unlock-dlc`` (or ``unlock-all``) for those.
    """
    sf = SaveFile.load(save_path)
    count = sf.unlock_all_songs()
    dest = out or save_path
    sf.save(dest)
    console.print(f'[green]Set {count} song unlock flags and wrote {dest}.[/green]')


@save.command(name='unlock-all')
@click.argument('save_path', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('-o',
              '--out',
              type=click.Path(dir_okay=False, path_type=Path),
              help='Write to this path instead of overwriting SAVE_PATH.')
@debug_option
def unlock_all(save_path: Path, out: Path | None) -> None:
    """
    Unlock everything in SAVE_PATH: every regular song and every DLC pack.

    Combines ``unlock-songs`` and ``unlock-dlc``. DLC tokens are device-bound, so the save must come
    from the target device (its device id is read straight out of the file).
    """
    sf = SaveFile.load(save_path)
    log.debug('Editing save with device id %r.', sf.device_id)
    count = sf.unlock_all_songs()
    packs = sf.unlock_all_dlc()
    dest = out or save_path
    sf.save(dest)
    console.print(
        f'[green]Set {count} song flags and unlocked {", ".join(packs)}; wrote {dest}.[/green]')


@save.command(name='generate')
@click.argument('out', type=click.Path(dir_okay=False, path_type=Path))
@click.option('-i',
              '--device-id',
              default='',
              help='Device id for DLC tokens ("iOS" on iOS; the ANDROID_ID/SSAID on Android).')
@click.option('-f',
              '--from-save',
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help='Copy the device id from an existing save instead of passing --device-id.')
@click.option('--no-dlc', is_flag=True, help='Unlock songs only; do not write DLC tokens.')
@debug_option
def generate(out: Path, device_id: str, from_save: Path | None, *, no_dlc: bool) -> None:
    """
    Generate a fresh, fully-unlocked ``save.bin`` at OUT (from a zero-initialised save).

    Every regular song is unlocked unconditionally. DLC tokens are device-bound
    (``MD5(device_id + pack)``), so supply the target device's id via ``--device-id`` or copy it
    from an existing save with ``--from-save``; on iOS the id is always ``"iOS"``. Songs do not
    depend on the device id. The integrity hash is never verified on load, so the result loads
    as-is.
    """
    resolved_id = SaveFile.load(from_save).device_id if from_save is not None else device_id
    sf = SaveFile.blank()
    sf.set_device_id(resolved_id)
    log.debug('Generating save with device id %r.', resolved_id)
    count = sf.unlock_all_songs()
    if no_dlc:
        sf.save(out)
        console.print(f'[green]Generated {out} with {count} songs unlocked (DLC skipped).[/green]')
        return
    packs = sf.unlock_all_dlc()
    sf.save(out)
    console.print(f'[green]Generated {out}: {count} song flags + {len(packs)} DLC packs.[/green]')
    if not resolved_id:
        console.print('[yellow]Note:[/yellow] no device id was set, so the DLC tokens will not '
                      'match a real device. Pass --device-id or --from-save to bind them.')
