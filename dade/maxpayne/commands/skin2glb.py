"""``dade maxpayne skin2glb`` - convert characters to rigged, animated binary glTF."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
import functools
import json
import logging
import re

import click

from dade.maxpayne.blocks import unwrap
from dade.maxpayne.character import InvalidCharacterError, read_animation, read_weights
from dade.maxpayne.gltf import build_character_glb
from dade.maxpayne.model import InvalidModelError, read_model

from .models import read_model_file
from .utils import debug_option, find_path

if TYPE_CHECKING:
    from dade.maxpayne.typing import Animation, Model

__all__ = ('skin2glb',)

log = logging.getLogger(__name__)

_COMMENT = re.compile(r'//[^\n]*|/\*.*?\*/', re.DOTALL)
_INCLUDE = re.compile(r'#include\s*[<"]([^>"]+)[>"]', re.IGNORECASE)
_SKELETON = re.compile(r'\bSkeleton\s*=\s*"?([^";\s]+)"?\s*;', re.IGNORECASE)
_GEOMETRY = re.compile(
    r'ExportData\s*=\s*"?([^";]+?)"?\s*;(?:\s*SkinData\s*=\s*"?([^";]+?)"?\s*;)?', re.IGNORECASE)
_ANIMATION = re.compile(r'\[Animation\]\s*Index\s*=\s*(\w+)\s*;\s*Filename\s*=\s*"?([^";]+?)"?\s*;',
                        re.IGNORECASE)


def _script(path: Path, seen: set[Path] | None = None) -> str:
    """
    Read an ``R_Script`` file with its comments removed and its includes expanded.

    Parameters
    ----------
    path : pathlib.Path
        The script.
    seen : set[pathlib.Path] | None
        Scripts already expanded, to stop an include cycle.

    Returns
    -------
    str
        The script's text followed by each included script's.
    """
    seen = seen if seen is not None else set()
    seen.add(path)
    text = _COMMENT.sub('', path.read_text('latin-1'))
    parts = [text]
    # Evaluated one include at a time, and an include expanded earlier is therefore in `seen` by
    # the time a later one is checked.
    parts.extend(
        _script(found, seen) for name in _INCLUDE.findall(text)
        if (found := find_path(path.parent, name)) is not None and found not in seen)
    return '\n'.join(parts)


@functools.cache
def _animation(path: Path) -> Animation | None:
    """
    Read a character animation once, however many skins use it.

    Parameters
    ----------
    path : pathlib.Path
        The ``.kf2``.

    Returns
    -------
    Animation | None
        The clip, or :py:obj:`None` when it will not read.
    """
    try:
        return read_animation(unwrap(path.read_bytes())[0])
    except (IndexError, InvalidCharacterError, ValueError):
        log.warning('Could not read the animation `%s`.', path)
        return None


@functools.cache
def _skeleton(path: Path) -> Model | None:
    """
    Read a skeleton once, however many skins use it.

    Parameters
    ----------
    path : pathlib.Path
        The skeleton model, its meshes the bones.

    Returns
    -------
    Model | None
        The skeleton, or :py:obj:`None` when it will not read.
    """
    try:
        return read_model(unwrap(path.read_bytes())[0])
    except (IndexError, InvalidModelError, ValueError):
        log.warning('Could not read the skeleton `%s`.', path)
        return None


def _skeleton_files(database: Path, name: str) -> tuple[Path, Path, str] | None:
    """
    Find a skeleton's directory, its model, and its script's text.

    The first game describes each skeleton in ``skeletons/<name>.txt``, whose geometry entry
    identifies the model. The second game has no such script and ships the model as
    ``skeletons/<name>/skeleton_<name>.kf2``.

    Parameters
    ----------
    database : pathlib.Path
        The game's ``data/database`` directory.
    name : str
        The skeleton, as a skin's script records it.

    Returns
    -------
    tuple[pathlib.Path, pathlib.Path, str] | None
        The directory, the model, and the script's text (empty when there is no script), or
        :py:obj:`None` when the skeleton cannot be found.
    """
    if (directory := find_path(database, f'skeletons/{name}')) is None:
        return None
    text = ''
    model = None
    if (script := find_path(database, f'skeletons/{name}.txt')) is not None:
        text = _script(script)
        if (match := _GEOMETRY.search(text)) is not None:
            model = find_path(directory, match.group(1))
    model = model or find_path(directory, f'skeleton_{name}.kf2')
    return (directory, model, text) if model is not None else None


def _clips(directory: Path, text: str, *, every: bool) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Find the animations a character's scripts list.

    Parameters
    ----------
    directory : pathlib.Path
        The skeleton's directory, where the scripts' file names are relative to.
    text : str
        The skin's and the skeleton's scripts.
    every : bool
        Also take every ``.kf2`` in the skeleton's ``anim`` directory the scripts do not list.

    Returns
    -------
    tuple[list[dict[str, Any]], list[str]]
        One entry per animation file with the indices that play it, and the file names that could
        not be found.
    """
    found: dict[Path, dict[str, Any]] = {}
    missing: set[str] = set()
    for index, recorded in _ANIMATION.findall(text):
        file = recorded.strip().replace('\\', '/')
        if (path := find_path(directory, file)) is None:
            missing.add(file)
            continue
        found.setdefault(path, {'file': file, 'indices': set(), 'path': path})['indices'].add(index)
    if every and (anim := find_path(directory, 'anim')) is not None:
        for path in sorted(anim.rglob('*')):
            if path.suffix.lower() == '.kf2':
                found.setdefault(path, {
                    'file': path.relative_to(directory).as_posix(),
                    'indices': set(),
                    'path': path
                })
    return [{
        **entry, 'indices': sorted(entry['indices'])
    } for entry in found.values()], sorted(missing)


def _convert(database: Path, script: Path, output_dir: Path, *, every: bool) -> str:
    """
    Convert one skin, reporting what was written.

    Parameters
    ----------
    database : pathlib.Path
        The game's ``data/database`` directory.
    script : pathlib.Path
        The skin's script, ``skins/<name>.txt``.
    output_dir : pathlib.Path
        Directory to write the ``.glb`` and ``.json`` into.
    every : bool
        Add every animation of the skeleton, not only those the scripts list.

    Returns
    -------
    str
        A summary line, or an empty string when the skin was skipped.
    """
    name = script.stem
    text = _script(script)
    geometry = _GEOMETRY.search(text)
    skeleton_name = _SKELETON.search(text)
    if geometry is None or not geometry.group(2) or skeleton_name is None:
        log.debug('`%s` is not a skinned character.', name)
        return ''
    skin_dir = find_path(script.parent, name)
    files = _skeleton_files(database, skeleton_name.group(1))
    model_path = find_path(skin_dir, geometry.group(1)) if skin_dir else None
    weights_path = find_path(skin_dir, geometry.group(2)) if skin_dir else None
    if files is None or model_path is None or weights_path is None:
        log.warning('Skipping `%s`: its skeleton, model, or weights are missing.', name)
        return ''
    directory, skeleton_path, skeleton_text = files
    model = read_model_file(model_path)
    skeleton = _skeleton(skeleton_path)
    try:
        weights = read_weights(unwrap(weights_path.read_bytes())[0])
    except (IndexError, InvalidCharacterError, ValueError):
        log.warning('Skipping `%s`: its weights will not read.', name)
        return ''
    if model is None or skeleton is None:
        log.warning('Skipping `%s`: its model or skeleton will not read.', name)
        return ''
    found, missing = _clips(directory, f'{text}\n{skeleton_text}', every=every)
    clips = []
    report = []
    for entry in found:
        if (clip := _animation(entry['path'])) is None:
            missing.append(entry['file'])
            continue
        clip_name = entry['path'].stem
        clips.append((clip_name, clip))
        report.append({
            'duration': (clip.frames - 1) / clip.rate if clip.rate else 0.0,
            'file': entry['file'],
            'flag': clip.flag,
            'frame_rate': clip.rate,
            'frames': clip.frames,
            'indices': entry['indices'],
            'name': clip_name,
            'tracks': len(clip.tracks)
        })
    try:
        payload = build_character_glb(model, skeleton, weights, clips, name=name)
    except ValueError as e:
        log.warning('Skipping `%s`: %s', name, e)
        return ''
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f'{name}.glb').write_bytes(payload)
    (output_dir / f'{name}.json').write_text(
        json.dumps(
            {
                'bones': [{
                    'name': bone.name,
                    'parent': bone.parent
                } for bone in skeleton.meshes],
                'clips': report,
                'missing_clips': sorted(missing),
                'model': model_path.name,
                'skeleton': skeleton_name.group(1),
                'skeleton_model': skeleton_path.name,
                'weights': weights_path.name
            },
            indent=2,
            sort_keys=True) + '\n')
    return (f'{name}: {len(weights.influences)} vertices, {len(skeleton.meshes)} bones, '
            f'{len(clips)} clips ({len(missing)} missing)')


@click.command(name='skin2glb')
@click.argument('database', type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option('-o',
              '--output-dir',
              default='.',
              help='Directory to write the .glb and .json files into.',
              type=click.Path(file_okay=False, path_type=Path))
@click.option('-s',
              '--skin',
              'skins',
              multiple=True,
              help='Convert only this skin, identified by its directory under skins. Repeatable.')
@click.option('-a',
              '--all-clips',
              'every',
              is_flag=True,
              help="Add every animation in the skeleton's anim directory, not only those the "
              "character's scripts list.")
@debug_option
def skin2glb(database: Path, output_dir: Path, skins: tuple[str, ...], *, every: bool) -> None:
    """Convert each character under DATABASE/skins to a rigged and animated .glb."""  # ruff: ignore[docstring-missing-exception]
    wanted = {skin.lower() for skin in skins}
    scripts = sorted(p for p in (find_path(database, 'skins') or database).glob('*.txt')
                     if not wanted or p.stem.lower() in wanted)
    if not scripts:
        click.echo('No skin scripts found.', err=True)
        raise click.Abort
    converted = 0
    for script in scripts:
        if line := _convert(database, script, output_dir, every=every):
            click.echo(line)
            converted += 1
    click.echo(f'{converted}/{len(scripts)} skins converted into {output_dir}.')
