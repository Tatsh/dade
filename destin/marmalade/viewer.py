"""
Standalone WebGL viewer for decoded models.

:func:`obj_to_html` embeds an OBJ's geometry into a single self-contained HTML file (no external
assets) that renders the mesh with orbit/zoom controls, so a decoded
:class:`destin.marmalade.model.Model` can be inspected in any browser. The HTML itself lives in
``templates/viewer.html.j2`` and is
rendered with Jinja2.
"""
from __future__ import annotations

from importlib.resources import files
import logging

from jinja2 import Environment, PackageLoader, select_autoescape

__all__ = ('obj_to_html',)

log = logging.getLogger(__name__)

_ENV = Environment(loader=PackageLoader('destin.marmalade', 'templates'),
                   autoescape=select_autoescape(default=True),
                   keep_trailing_newline=True)
_TEMPLATE = _ENV.get_template('viewer.html.j2')
_WEBGL_JS = (files('destin.marmalade') / 'templates' / 'viewer.js').read_text(encoding='utf-8')
"""The render loop, embedded verbatim into the rendered HTML (a trusted asset)."""


def obj_to_html(obj_text: str, title: str = 'model') -> str | None:
    """
    Build a standalone WebGL viewer for an OBJ document.

    The geometry is normalised (centred and scaled to fit) and embedded directly, so the returned
    HTML needs no external files.

    Parameters
    ----------
    obj_text : str
        Wavefront OBJ text (e.g. from :meth:`destin.marmalade.model.Model.to_obj`).
    title : str
        Title shown in the viewer's HUD.

    Returns
    -------
    str or None
        Self-contained HTML, or ``None`` if the OBJ has no faces.
    """
    verts: list[list[float]] = []
    faces: list[list[int]] = []
    for line in obj_text.splitlines():
        tok = line.split()
        if not tok:
            continue
        if tok[0] == 'v':
            verts.append([float(tok[1]), float(tok[2]), float(tok[3])])
        elif tok[0] == 'f':
            ix = [int(p.split('/')[0]) - 1 for p in tok[1:]]
            faces.extend([ix[0], ix[i], ix[i + 1]] for i in range(1, len(ix) - 1))
    if not verts or not faces:
        log.debug('OBJ %r has no faces; not generating a viewer.', title)
        return None
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    cx, cy, cz = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2
    scale = 2.0 / (max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)) or 1.0)
    pos = [
        round(c, 4) for v in verts
        for c in ((v[0] - cx) * scale, (v[1] - cy) * scale, (v[2] - cz) * scale)
    ]
    idx = [i for f in faces for i in f]
    log.debug('Rendering viewer for %r with %d vertices and %d triangles.', title, len(verts),
              len(faces))
    return _TEMPLATE.render(title=title,
                            nv=len(verts),
                            nf=len(faces),
                            pos=pos,
                            idx=idx,
                            webgl_js=_WEBGL_JS)
