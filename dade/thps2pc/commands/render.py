"""``dade thps2pc render-*`` - software renders of a PSX scene."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import json
import logging

import click

from dade.thps2pc.render import (
    HANGAR_SCENERY_NODES,
    SceneryNode,
    render_authoritative,
    render_layers,
    render_node_map,
    render_object_models,
    render_objects,
)

from .utils import (
    canvas_options,
    convert_path_option,
    debug_option,
    read_scene,
    run_montage,
    save_image,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dade.thps2pc.typing import Point, Rgb

__all__ = ('render_authoritative_command', 'render_layers_command', 'render_node_map_command',
           'render_object_models_command', 'render_objects_command')

log = logging.getLogger(__name__)

_FONT_ROOT = Path('/usr/share/fonts')
_FONT_HINTS = ('DejaVuSans', 'DejaVu', 'Sans')


def _find_font() -> Path | None:
    if not _FONT_ROOT.is_dir():
        return None
    for hint in _FONT_HINTS:
        for candidate in sorted(_FONT_ROOT.rglob('*.ttf')):
            if hint.lower() in candidate.name.lower():
                return candidate
    return None


def _parse_highlights(entries: Sequence[str]) -> dict[int, Rgb]:
    """
    Parse ``SECTOR:RRGGBB`` highlight arguments.

    Parameters
    ----------
    entries : Sequence[str]
        The raw option values.

    Returns
    -------
    dict[int, Rgb]
        Sector index to its pinned colour.

    Raises
    ------
    click.BadParameter
        If an entry is not a sector index and a six-digit hexadecimal colour.
    """
    chosen: dict[int, Rgb] = {}
    for entry in entries:
        index, _, value = entry.partition(':')
        try:
            chosen[int(index)] = (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
        except ValueError as e:
            msg = f'Could not parse highlight {entry!r}; expected SECTOR:RRGGBB.'
            raise click.BadParameter(msg) from e
    return chosen


def _load_nodes(path: Path | None) -> tuple[SceneryNode, ...]:
    if path is None:
        return HANGAR_SCENERY_NODES
    payload = json.loads(path.read_text())
    return tuple(
        SceneryNode(str(entry['label']), int(entry['x']), int(entry['z'])) for entry in payload)


@click.command(name='render-authoritative')
@click.argument('scene', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('output', type=click.Path(dir_okay=False, path_type=Path))
@canvas_options(1200, 850, 20)
@click.option('--no-placement',
              is_flag=True,
              help='Draw every sector at the origin instead of its placed position.')
@click.option('--hide-nonrendered',
              is_flag=True,
              help='Drop faces on the non-rendering layer, such as air-trick hit boxes.')
@convert_path_option
@debug_option
def render_authoritative_command(scene: Path,
                                 output: Path,
                                 width: int,
                                 height: int,
                                 padding: int,
                                 convert_path: Path | None = None,
                                 *,
                                 no_placement: bool = False,
                                 hide_nonrendered: bool = False) -> None:
    """
    Render SCENE from above to OUTPUT using the descriptor table's instance placement.

    Each sector is tinted by a hash of its index. Give OUTPUT a .ppm suffix to skip ImageMagick.
    """
    framebuffer = render_authoritative(read_scene(scene),
                                       width=width,
                                       height=height,
                                       padding=padding,
                                       placement=not no_placement,
                                       hide=hide_nonrendered)
    save_image(framebuffer.to_ppm(), output, convert_path)
    click.echo(f'Wrote {output}.')


@click.command(name='render-layers')
@click.argument('scene', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('output', type=click.Path(dir_okay=False, path_type=Path))
@canvas_options(1400, 1000, 20)
@convert_path_option
@debug_option
def render_layers_command(scene: Path,
                          output: Path,
                          width: int,
                          height: int,
                          padding: int,
                          convert_path: Path | None = None) -> None:
    """
    Render SCENE from above to OUTPUT with each face coloured by its render layer.

    Grey is the permanent layer, then blue, red, and green for the three conditional layers,
    drawn in that order so the upper layers stay visible.
    """
    framebuffer = render_layers(read_scene(scene), width=width, height=height, padding=padding)
    save_image(framebuffer.to_ppm(), output, convert_path)
    click.echo(f'Wrote {output}.')


@click.command(name='render-node-map')
@click.argument('scene', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('output', type=click.Path(dir_okay=False, path_type=Path))
@canvas_options(1500, 1050, 30)
@click.option('-n',
              '--nodes',
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help='JSON array of {"label", "x", "z"} objects. Defaults to the Hangar nodes.')
@click.option('--font',
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help='TrueType font for the labels. Autodetected when omitted.')
@click.option('--no-labels', is_flag=True, help='Draw the markers without their labels.')
@convert_path_option
@debug_option
def render_node_map_command(scene: Path,
                            output: Path,
                            width: int,
                            height: int,
                            padding: int,
                            nodes: Path | None = None,
                            font: Path | None = None,
                            convert_path: Path | None = None,
                            *,
                            no_labels: bool = False) -> None:
    """
    Render SCENE from above to OUTPUT in flat grey with scenery nodes marked.

    The default node list is the seventeen positions the original tool carried for the Hangar, so
    pass --nodes for any other level. Labels need ImageMagick and a usable font; without one the
    markers are still drawn.
    """
    marks: Sequence[Point]
    framebuffer, marks = render_node_map(read_scene(scene),
                                         _load_nodes(nodes),
                                         width=width,
                                         height=height,
                                         padding=padding)
    labels = _load_nodes(nodes)
    args: list[str] = []
    if not no_labels:
        chosen = font or _find_font()
        args = ['-pointsize', '20', '-fill', 'white']
        if chosen is not None:
            args += ['-font', str(chosen)]
        else:
            log.debug('No TrueType font was found; labels may use the default face.')
        for node, mark in zip(labels, marks, strict=True):
            args += ['-annotate', f'+{int(mark[0]) + 11}+{int(mark[1]) + 5}', node.label]
    save_image(framebuffer.to_ppm(), output, convert_path, args)
    click.echo(f'Wrote {output} with {len(labels)} nodes.')


@click.command(name='render-object-models')
@click.argument('scene', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('outdir', type=click.Path(file_okay=False, path_type=Path))
@click.option('--size', default=220, show_default=True, help='Tile width and height in pixels.')
@click.option('--padding', default=14, show_default=True, help='Margin in pixels within a tile.')
@click.option('--tile', default='5x4', show_default=True, help='Contact sheet grid for montage.')
@click.option('--suffix',
              default='.png',
              show_default=True,
              help='Image format for each tile. Use .ppm to avoid needing ImageMagick.')
@click.option('--no-montage', is_flag=True, help='Write the tiles without a contact sheet.')
@click.option('--montage-path',
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help='Path to the ImageMagick montage binary.')
@convert_path_option
@debug_option
def render_object_models_command(scene: Path,
                                 outdir: Path,
                                 size: int,
                                 padding: int,
                                 tile: str,
                                 suffix: str,
                                 convert_path: Path | None = None,
                                 montage_path: Path | None = None,
                                 *,
                                 no_montage: bool = False) -> None:
    """
    Render every sector of the object scene SCENE as an isometric tile under OUTDIR.

    Each tile is flat-shaded with a depth buffer and named ``s<NN><suffix>``. Unless --no-montage
    is given they are also gathered into ``models<suffix>``, labelled with each sector's index and
    its vertex and face counts.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    tiles: list[Path] = []
    labels: list[str] = []
    for sector, framebuffer in render_object_models(read_scene(scene), size=size, padding=padding):
        destination = outdir / f's{sector.index:02d}{suffix}'
        save_image(framebuffer.to_ppm(), destination, convert_path)
        tiles.append(destination)
        labels.append(f's{sector.index} v{sector.vertex_count} f{sector.num_faces}')
    if not tiles:
        click.echo('The scene holds no sectors.', err=True)
        return
    if no_montage:
        click.echo(f'Rendered {len(tiles)} models into {outdir}.')
        return
    sheet = outdir / f'models{suffix}'
    args: list[str] = []
    for path, label in zip(tiles, labels, strict=True):
        args += ['-label', label, str(path)]
    args += [
        '-tile', tile, '-geometry', '+3+3', '-background', 'gray15', '-fill', 'yellow',
        '-pointsize', '13',
        str(sheet)
    ]
    run_montage(args, sheet, montage_path)
    click.echo(f'Rendered {len(tiles)} models into {sheet}.')


@click.command(name='render-objects')
@click.argument('level', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('objects', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('output', type=click.Path(dir_okay=False, path_type=Path))
@canvas_options(1400, 1000, 20)
@click.option('--highlight',
              'highlights',
              multiple=True,
              help='Force a sector to a colour, as SECTOR:RRGGBB (repeatable).')
@convert_path_option
@debug_option
def render_objects_command(level: Path,
                           objects: Path,
                           output: Path,
                           width: int,
                           height: int,
                           padding: int,
                           highlights: tuple[str, ...] = (),
                           convert_path: Path | None = None) -> None:
    """
    Render LEVEL from above in grey with the placed objects of OBJECTS drawn over it in colour.

    Object sectors cycle through hues derived from their index unless pinned with --highlight,
    which takes a sector index and a hexadecimal colour, such as ``3:FF2828``.
    """
    framebuffer = render_objects(read_scene(level),
                                 read_scene(objects),
                                 width=width,
                                 height=height,
                                 padding=padding,
                                 highlights=_parse_highlights(highlights))
    save_image(framebuffer.to_ppm(), output, convert_path)
    click.echo(f'Wrote {output}.')
