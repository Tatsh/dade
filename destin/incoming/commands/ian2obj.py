"""``ian2obj`` - convert an Incoming ``.ian`` or Dreamcast ``*_M.BIN`` model to Wavefront OBJ."""
from __future__ import annotations

from pathlib import Path
import logging

from incoming_extractor.context import using_input_root
from incoming_extractor.converters.models import ian_to_obj
from incoming_extractor.converters.models_dc import mbin_to_obj
from incoming_extractor.utils import pluralize
import click

from .utils import debug_option

__all__ = ('ian2obj',)

log = logging.getLogger(__name__)


def _is_dc_model(model: Path) -> bool:
    return model.name.lower().endswith('_m.bin')


def _find_game_root(model: Path) -> Path | None:
    if _is_dc_model(model):
        return next((parent for parent in model.parents
                     if (parent / 'TEXTURES').is_dir() or (parent / 'textures').is_dir()), None)
    return next((parent for parent in model.parents
                 if (parent / 'pcobject').is_dir() and (parent / 'ppm').is_dir()), None)


@click.command(name='ian2obj', context_settings={'help_option_names': ('-h', '--help')})
@click.argument('model',
                type=click.Path(exists=True, dir_okay=False, path_type=Path, resolve_path=True))
@click.argument('outdir', type=click.Path(file_okay=False, path_type=Path))
@click.option('--game-root',
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help='Game directory used to resolve textures; auto-detected from MODEL if omitted.')
@click.option('--no-texture', is_flag=True, help='Do not resolve or write textures.')
@debug_option
def ian2obj(model: Path, outdir: Path, *, game_root: Path | None, no_texture: bool) -> None:
    """
    Convert an Incoming model MODEL to Wavefront OBJ and MTL in OUTDIR.

    A PC ``.ian`` model yields a single OBJ and MTL. A Dreamcast ``*_M.BIN`` model pack yields one
    OBJ and MTL per contained object under ``OUTDIR/<model name>/`` and needs the matching
    ``*_ML.BIN`` index beside it. Each texture is resolved from the game root -- ``.odl`` plus
    ``.ppm`` files for a PC model, or the level ``*_T.PVR`` pack (which requires ``spvr2png`` on
    ``PATH``) for a Dreamcast model -- and written next to the material, unless ``--no-texture`` is
    given.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    convert = mbin_to_obj if _is_dc_model(model) else ian_to_obj
    root = None if no_texture else game_root or _find_game_root(model)
    log.debug('Converting `%s` into `%s` (game root `%s`).', model, outdir, root)
    if root is None:
        outputs = convert(model, outdir)
    else:
        with using_input_root(root):
            outputs = convert(model, outdir)
    click.echo(f'Wrote {pluralize(len(outputs), "file")} to {outdir}.')
