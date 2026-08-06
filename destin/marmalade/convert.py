"""
High-level resource conversion.

:func:`decode_group_to_dir` ties the sans-I/O decoders together: it parses a ``.group.bin`` and
writes each resource to *gdir* as an open format (textures/fonts -> PNG, materials -> JSON, models
-> OBJ + optional WebGL HTML), falling back to a raw ``.bin`` dump when a resource cannot be decoded
or a conversion is disabled.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import logging
import struct

from .font import decode_font
from .material import decode_material
from .model import decode_model
from .resgroup import parse
from .texture import decode_texture
from .viewer import obj_to_html

__all__ = ('ConvertOptions', 'decode_group_to_dir')

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConvertOptions:
    """Which conversions :func:`decode_group_to_dir` should perform."""

    png: bool = True
    """Convert ``CIwTexture`` and ``CIwGxFont`` to PNG."""
    material_json: bool = True
    """Convert ``CIwMaterial`` to JSON."""
    obj: bool = True
    """Convert ``CIwModel`` to Wavefront OBJ."""
    html: bool = True
    """Also emit a standalone WebGL viewer next to each OBJ."""


def decode_group_to_dir(data: bytes,
                        gdir: str | Path,
                        options: ConvertOptions | None = None) -> dict[str, int]:
    """
    Decode a ``.group.bin`` into *gdir*, one subfolder per resource class.

    Parameters
    ----------
    data : bytes
        Full ``.group.bin`` contents.
    gdir : str or pathlib.Path
        Output directory (created if absent); ``CIwTexture/`` etc. go inside it.
    options : ConvertOptions, optional
        Conversion toggles. Defaults to converting everything.

    Returns
    -------
    dict[str, int]
        Resource count per class name.
    """
    opts = options or ConvertOptions()
    root = Path(gdir)
    group = parse(data)
    name = group.name or root.name or 'group'
    texture_names = {
        res.name_hash: f'{res.name_hash:08x}.png'
        for res in group.resources.get('CIwTexture', [])
    }
    log.debug('Decoding group %r into %s with options %r.', name, root, opts)
    counts: dict[str, int] = {}
    for cname, items in group.resources.items():
        cdir = root / cname
        cdir.mkdir(parents=True, exist_ok=True)
        for i, res in enumerate(items):
            stem = f'{i:03d}_{res.name_hash:08x}'
            _write_resource(cname, res.body, cdir, stem, name, texture_names, opts)
        counts[cname] = len(items)
        log.debug('Wrote %d %s resource(s) to %s.', len(items), cname, cdir)
    return counts


def _convert_resource(cname: str, body: bytes, cdir: Path, stem: str, group_name: str,
                      texture_names: dict[int, str], opts: ConvertOptions) -> bool:
    """
    Convert a single resource to an open format, if a converter applies and is enabled.

    Parameters
    ----------
    cname : str
        Resource class name.
    body : bytes
        Raw serialised resource body.
    cdir : pathlib.Path
        Directory for this resource class.
    stem : str
        Output file name without extension.
    group_name : str
        Owning group name, used in model viewer titles.
    texture_names : dict[int, str]
        Texture name-hash to file name, for material cross-references.
    opts : ConvertOptions
        Conversion toggles.

    Returns
    -------
    bool
        ``True`` if a converted file was written, ``False`` if the caller should dump raw bytes.
    """
    if cname == 'CIwTexture' and opts.png:
        img = decode_texture(body)
        if img is not None:
            img.save(cdir / f'{stem}.png')
            return True
    elif cname == 'CIwGxFont' and opts.png:
        img = decode_font(body)
        if img is not None:
            img.save(cdir / f'{stem}.png')
            return True
    elif cname == 'CIwMaterial' and opts.material_json:
        (cdir / f'{stem}.json').write_text(
            json.dumps(decode_material(body, texture_names), indent=2))
        return True
    elif cname == 'CIwModel' and opts.obj:
        obj = decode_model(body).to_obj(comment=f'{group_name}/{stem}')
        (cdir / f'{stem}.obj').write_text(obj)
        if opts.html:
            html = obj_to_html(obj, f'{group_name}/{stem}')
            if html is not None:
                (cdir / f'{stem}.html').write_text(html)
        return True
    return False


def _write_resource(cname: str, body: bytes, cdir: Path, stem: str, group_name: str,
                    texture_names: dict[int, str], opts: ConvertOptions) -> None:
    """Convert and write a single resource, falling back to a raw ``.bin`` dump."""
    try:
        handled = _convert_resource(cname, body, cdir, stem, group_name, texture_names, opts)
    except (ValueError, struct.error, IndexError):
        log.debug('Could not decode %s resource %s; writing raw .bin instead.',
                  cname,
                  stem,
                  exc_info=True)
        handled = False
    if not handled:
        (cdir / f'{stem}.bin').write_bytes(body)
