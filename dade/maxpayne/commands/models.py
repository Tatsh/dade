"""Find the models a level's NPCs and pickups are drawn with, and read them off disk."""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import re

from dade.maxpayne.blocks import unwrap
from dade.maxpayne.model import InvalidModelError, read_model
from dade.maxpayne.typing import TextureImage

if TYPE_CHECKING:
    from pathlib import Path

    from dade.maxpayne.typing import Level, Model

__all__ = ('load_models',)

log = logging.getLogger(__name__)

_EXPORT_DATA = re.compile(r'ExportData\s*=\s*([^;]+);', re.IGNORECASE)
"""How a pickup's ``.txt`` names the file holding its geometry."""


def _skin(database: Path, skin: str) -> Path | None:
    """
    Find a character's model.

    Parameters
    ----------
    database : pathlib.Path
        The ``data/database`` directory.
    skin : str
        The skin's directory name, as the level records it.

    Returns
    -------
    pathlib.Path | None
        The model, or :py:obj:`None` when the directory holds none.
    """
    directory = database / 'skins' / skin
    if not directory.is_dir():
        return None
    found = sorted(p for p in directory.iterdir() if p.suffix.lower() == '.kfs')
    # A skin ships one model per level of detail; the nearest is the one to draw.
    return next((p for p in found if p.stem.lower().endswith('_l0')), found[0] if found else None)


def _item(database: Path, item: str) -> Path | None:
    """
    Find a pickup's model, which its script names rather than the directory listing.

    Parameters
    ----------
    database : pathlib.Path
        The ``data/database`` directory.
    item : str
        The pickup's directory name, as the level records it.

    Returns
    -------
    pathlib.Path | None
        The model, or :py:obj:`None` when the script does not name a readable one.
    """
    script = database / 'level_items' / f'{item}.txt'
    if not script.is_file():
        return None
    match = _EXPORT_DATA.search(script.read_text('latin-1'))
    if match is None:
        return None
    model = database / 'level_items' / item / match.group(1).strip()
    return model if model.is_file() else None


def _read(path: Path) -> Model | None:
    """
    Read one model and the images its materials name.

    The model carries a search path -- its own ``textures`` directory, then the shared one beside
    it -- and the images are looked up along it in order.

    Parameters
    ----------
    path : pathlib.Path
        The model file.

    Returns
    -------
    Model | None
        The model with its images filled in, or :py:obj:`None` when it will not read.
    """
    try:
        model = read_model(unwrap(path.read_bytes())[0])
    except (IndexError, InvalidModelError, ValueError):
        log.warning('Could not read the model `%s`.', path)
        return None
    textures = []
    for file in dict.fromkeys(model.materials.values()):
        for folder in model.search:
            candidate = path.parent / folder / file
            if candidate.is_file():
                textures.append(TextureImage(data=candidate.read_bytes(), kind=0, path=file))
                break
        else:
            log.debug('No image named `%s` for `%s`.', file, path.name)
    return model._replace(textures=tuple(textures))


def load_models(database: Path, level: Level) -> dict[str, Model]:
    """
    Read every model a level needs, keyed by the node label its placements get.

    Parameters
    ----------
    database : pathlib.Path
        The game's ``data/database`` directory.
    level : Level
        The level whose NPCs and pickups are to be drawn.

    Returns
    -------
    dict[str, Model]
        Node label to model, missing an entry for anything that could not be found.
    """
    wanted = {f'character:{c.skin}': ('skins', c.skin) for c in level.characters}
    wanted.update({f'item:{i.item}': ('items', i.item) for i in level.items})
    out: dict[str, Model] = {}
    for label, (kind, name) in wanted.items():
        path = _skin(database, name) if kind == 'skins' else _item(database, name)
        if path is None:
            log.debug('No model for `%s`.', label)
            continue
        model = _read(path)
        if model is not None:
            out[label] = model
    log.debug('Read %d of %d models.', len(out), len(wanted))
    return out
