"""Shared typing helpers and converter result types for :py:mod:`dade.amplitude`."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, NamedTuple, NotRequired, TypeAlias, TypedDict

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    import numpy as np

__all__ = ('ARKEntry', 'ArenaMeta', 'ArkLayout', 'Asset', 'AvatarArm', 'AvatarPart', 'AvatarTrack',
           'BankMeta', 'DataArrayNode', 'EnvironMeta', 'Geometry', 'IPUMeta', 'LightMeta',
           'LnmMeta', 'MIDIFile', 'MIDITrack', 'MMVMeta', 'MatMeta', 'MmeshMeta', 'MovieMeta',
           'PoolOutcome', 'RndBones', 'RndFilter', 'RndKey', 'RndMesh', 'RndTransAnim',
           'RndTransform', 'RndVertex', 'SampleMeta', 'TnmFilterMeta', 'TnmKeyMeta', 'TnmMeta',
           'TnmScanMeta', 'ViewMeta')

ArkLayout: TypeAlias = Literal['amplitude', 'frequency']
"""
The name of a Harmonix v2 ARK layout: the Amplitude (magic-less) or FreQuency (``ARK\\0``) format.

:meta hide-value:
"""

DataArrayNode: TypeAlias = 'int | float | str | list[DataArrayNode]'
"""
A decoded Harmonix DataArray element: an ``int``/``float``/``str`` scalar or a nested array.

:meta hide-value:
"""


class ARKEntry(NamedTuple):
    """A single file record in a Harmonix v2 ARK directory."""

    path: str
    """Full ``dir/file`` path of the entry within the archive."""
    offset: int
    """Absolute byte offset of the entry's data in the ARK."""
    size: int
    """Size of the entry's data in bytes."""
    flags: int
    """Entry flags from the directory record."""


class Asset(NamedTuple):
    """A single carve-out from an ARK archive: an entry's path and its raw, unconverted bytes."""

    name: str
    """The entry's full ``dir/file`` path within its ARK archive."""
    data: bytes
    """The entry's raw bytes exactly as stored in the ARK (never gunzipped or converted)."""


class PoolOutcome(NamedTuple):
    """The success and failure counts from a parallel-pool run."""

    succeeded: int
    """Number of items that produced a result (a non-``None`` return)."""
    failed: int
    """Number of items that raised and were skipped (non-zero only when failures are ignored)."""


class Geometry(NamedTuple):
    """Located vertex/face vectors within a parsed RndMesh body."""

    vertex_count: int
    """Number of vertices."""
    vertex_start: int
    """Byte offset of the first vertex."""
    face_count: int
    """Number of triangles."""
    face_start: int
    """Byte offset of the first face."""
    material: str
    """Referenced material object name (may be empty)."""


class MIDITrack(TypedDict):
    """A decoded MIDI track, its title and its events (each with an absolute ``tick``)."""

    event_count: int
    """Number of events in the track."""
    events: Sequence[dict[str, Any]]
    """The track's events in order; each is a mido message dict with an absolute ``tick``."""
    name: str
    """The track name (from a ``track_name`` meta event; empty if none)."""


class MIDIFile(TypedDict):
    """A decoded Standard MIDI File."""

    division: int
    """Ticks per quarter note (the SMF division)."""
    format: int
    """SMF format type (0, 1, or 2)."""
    track_count: int
    """Number of tracks."""
    tracks: Sequence[MIDITrack]
    """The decoded tracks."""


class IPUMeta(TypedDict):
    """Metadata of a PS2 IPU video."""

    frame_count: int
    """Number of frames."""
    height: int
    """Frame height in pixels."""
    magic: str
    """Always ``'ipum'``."""
    width: int
    """Frame width in pixels."""


class MMVMeta(TypedDict):
    """Metadata of a ``MOVS`` movie; the variant fields depend on ``type``."""

    bank_count: NotRequired[int]
    """Number of streamed hardware-synth banks (soundbank movie)."""
    codec: NotRequired[str]
    """Frame codec of an animated texture (e.g. ``'RLE8'``)."""
    height: NotRequired[int]
    """Frame height in pixels (animated texture)."""
    magic: str
    """Always ``'MOVS'``."""
    size: int
    """Total file size in bytes."""
    tick_rate: int
    """Playback tick rate."""
    track_count: int
    """Number of tracks in the container."""
    type: str
    """``'animated_texture'``, ``'soundbank_movie'``, or ``'unknown'``."""
    version: int
    """Container version (8 = animated texture, 16 = soundbank movie)."""
    width: NotRequired[int]
    """Frame width in pixels (animated texture)."""


class SampleMeta(TypedDict):
    """A single sample descriptor in a ``SAMP`` bank."""

    channels: int
    """Channel count."""
    name: str
    """The sample name (from the ``SANM`` chunk)."""
    rate: int
    """Sample rate in Hz."""
    type: int
    """Sample type code from the descriptor."""


class BankMeta(TypedDict):
    """Decoded ``SAMP`` sample-bank metadata."""

    descriptor_stride: int
    """Bytes per sample descriptor."""
    magic: str
    """Always ``'SAMP'``."""
    sample_count: int
    """Number of samples."""
    samples: Sequence[SampleMeta]
    """The per-sample descriptors."""
    table_size: int
    """Size of the descriptor table in bytes."""


class ViewMeta(TypedDict):
    """Decoded ``Rnd::View`` (``.view``) scene-graph node metadata."""

    mesh: str | None
    """The first referenced ``.mesh`` object, or ``None`` if there is none."""
    references: Sequence[str]
    """Every referenced object name, in file order with duplicates removed."""
    transform: Sequence[float] | None
    """The node's best 4x3 row-major transform (twelve floats), or ``None`` if none was found."""
    version: int
    """Object version (``u32`` at offset ``0``)."""


class TnmScanMeta(TypedDict):
    """References and transforms found by scanning a FreQuency ``Rnd::TransAnim`` (``.tnm``)."""

    mesh_refs: Sequence[str]
    """The referenced ``.mesh`` object names."""
    references: Sequence[str]
    """Every referenced object name, in file order with duplicates removed."""
    tnm_refs: Sequence[str]
    """The referenced ``.tnm`` object names."""
    transforms: Sequence[Sequence[float]]
    """Every 4x3 row-major transform (twelve floats each) found in the body."""
    version: int
    """Object version (``u32`` at offset ``0``)."""


class TnmKeyMeta(TypedDict):
    """One key of a ``Rnd::TransAnim`` track."""

    frame: float
    """The key's frame, in song ticks."""
    value: Sequence[float]
    """The key's value: a quaternion ``(x, y, z, w)`` or a vector ``(x, y, z)``."""


class TnmFilterMeta(TypedDict):
    """One filter of a ``Rnd::Animatable``."""

    data: str
    """The filter's parameters as hexadecimal bytes."""
    type: str
    """The filter's class (``ScaleOffset``, ``MinMaxLoop``, ``ZeroOrder``, and so on)."""


class TnmMeta(TypedDict):
    """Decoded ``Rnd::TransAnim`` (``.tnm``) keyframe animation."""

    anims: Sequence[str]
    """The animations the ``Rnd::Animatable`` base drives along with this one."""
    draws: Sequence[str]
    """The ``Rnd::Drawable`` base's draw list."""
    filters: Sequence[TnmFilterMeta]
    """The ``Rnd::Animatable`` base's frame filters."""
    follow_path: bool
    """Whether the target turns to face along its translation path."""
    frames_owner: str
    """The animation whose keys are played (this one when it names itself)."""
    repeat_translation: bool
    """Whether the translation keys repeat, each repetition offset by the path's span."""
    rotation_keys: Sequence[TnmKeyMeta]
    """The rotation keys."""
    scale_interpolation: str
    """The interpolation of the scale keys (``linear`` or ``spline``)."""
    scale_keys: Sequence[TnmKeyMeta]
    """The scale keys."""
    showing: bool
    """The ``Rnd::Drawable`` base's visibility flag."""
    target: str
    """The ``Rnd::Transformable`` the animation moves."""
    translation_interpolation: str
    """The interpolation of the translation keys (``linear`` or ``spline``)."""
    translation_keys: Sequence[TnmKeyMeta]
    """The translation keys."""
    version: int
    """Object version (always ``3``)."""


class AvatarPart(NamedTuple):
    """One part of the FreQ avatar, resolved from the ``db avatar parts`` configuration."""

    number: int
    """The part's number (``0`` left arm through ``7`` instrument)."""
    dirs: tuple[Path, ...]
    """The decomposed Milo scenes the part loads, the geometry first."""
    trans_root: str
    """The mesh the part hangs from its parent by."""
    joint: str
    """The mesh of the parent part the trans root hangs from."""
    draw_root: str
    """The mesh the part's draw lists start from."""
    anims: tuple[str, ...]
    """The bones the part animates (an arm's forearm and hand)."""
    material: str | None
    """The material of an instrument mesh, or ``None`` for a part drawing with its scene's first."""


class AvatarTrack(NamedTuple):
    """The keys of one ``fbase_<bone>.tnm`` animation, as arrays."""

    rotation_frames: np.ndarray
    """The frame of each rotation key, ``(n,)``."""
    rotations: np.ndarray
    """The rotation keys as quaternions ``(x, y, z, w)``, ``(n, 4)``."""
    translation_frames: np.ndarray
    """The frame of each translation key, ``(m,)``."""
    translations: np.ndarray
    """The translation keys, ``(m, 3)``."""


class AvatarArm(NamedTuple):
    """The bones of an arm posed by ``ArmPart::SolveIK``."""

    socket: int
    """The joint the three bones hang from."""
    upper: int
    """The upper arm."""
    forearm: int
    """The forearm."""
    hand: int
    """The hand."""
    left: bool
    """Whether this is the left arm, whose bend axis is not reversed."""
    upper_length: float
    """The distance from the shoulder to the elbow at rest."""
    forearm_length: float
    """The distance from the elbow to the wrist at rest."""


class RndTransform(NamedTuple):
    """The ``Rnd::Transformable`` part of an object."""

    revision: int
    """Revision of the stored transform."""
    local: tuple[float, ...]
    """The transform relative to the parent: twelve floats, rows ``X``, ``Y``, ``Z``, origin."""
    world: tuple[float, ...]
    """The transform in the scene, in the same layout as :py:attr:`local`."""
    children: tuple[str, ...]
    """The objects transformed relative to this one."""
    billboard: int
    """The billboard mode (``0`` when the revision stores none)."""
    origin: tuple[float, float, float]
    """The pivot origin (zero when the revision stores none)."""


class RndVertex(NamedTuple):
    """A ``Rnd::Mesh`` vertex."""

    position: tuple[float, float, float]
    """The position in the mesh's space."""
    weights: tuple[float, float]
    """The weights of the mesh's two bones (the transform owner takes the rest)."""
    normal: tuple[float, float, float]
    """The normal."""
    color: tuple[float, float, float, float]
    """The RGBA colour."""
    uv: tuple[float, float]
    """The texture coordinates, with a top-left origin."""


class RndBones(NamedTuple):
    """The two bones that deform a skinned ``Rnd::Mesh``."""

    names: tuple[str, str]
    """The ``Rnd::Transformable`` objects acting as bones (the second may be empty)."""
    binds: tuple[tuple[float, ...], tuple[float, ...]]
    """Each bone's bind transform, mapping the mesh's space into the bone's at rest."""


class RndMesh(NamedTuple):
    """A version-14 ``Rnd::Mesh`` object."""

    transform: RndTransform
    """The ``Rnd::Transformable`` base."""
    showing: bool
    """The ``Rnd::Drawable`` base's visibility flag."""
    draws: tuple[str, ...]
    """The objects drawn along with this mesh."""
    collides: tuple[str, ...]
    """The ``Rnd::Collideable`` base's collision list."""
    z_mode: int
    """The depth-buffer mode."""
    z_func: int
    """The depth comparison."""
    material: str
    """The ``Rnd::Mat`` the mesh draws with (may be empty)."""
    geometry_owner: str
    """The mesh whose vertices and faces are drawn (this one when it names itself)."""
    transform_owner: str
    """The ``Rnd::Transformable`` whose world transform places the mesh."""
    sphere: tuple[float, ...]
    """The bounding sphere as four floats, the centre and then the radius."""
    lod_next: str
    """The next, coarser level of detail (may be empty)."""
    min_screen: float
    """The screen size below which :py:attr:`lod_next` is drawn instead."""
    mutable: bool
    """Whether the geometry is rewritten at run time."""
    vertices: tuple[RndVertex, ...]
    """The vertices."""
    faces: tuple[tuple[int, int, int], ...]
    """The triangles, as vertex indices."""
    edges: tuple[tuple[int, int], ...]
    """The edges, as vertex indices."""
    bones: RndBones | None
    """The bones that deform the mesh, or ``None`` for a rigid mesh."""


class RndKey(NamedTuple):
    """One key of a ``Rnd::TransAnim`` track."""

    value: tuple[float, ...]
    """A quaternion ``(x, y, z, w)`` or a vector ``(x, y, z)``."""
    frame: float
    """The frame, in song ticks."""


class RndFilter(NamedTuple):
    """One frame filter of a ``Rnd::Animatable``."""

    type: int
    """The filter's class number."""
    data: bytes
    """The filter's parameters as stored."""


class RndTransAnim(NamedTuple):
    """A revision-3 ``Rnd::TransAnim`` object."""

    filters: tuple[RndFilter, ...]
    """The ``Rnd::Animatable`` base's frame filters."""
    anims: tuple[str, ...]
    """The animations the ``Rnd::Animatable`` base drives along with this one."""
    showing: bool
    """The ``Rnd::Drawable`` base's visibility flag."""
    draws: tuple[str, ...]
    """The ``Rnd::Drawable`` base's draw list."""
    target: str
    """The ``Rnd::Transformable`` the animation moves."""
    rotation_keys: tuple[RndKey, ...]
    """The rotation keys, quaternions ``(x, y, z, w)``."""
    translation_keys: tuple[RndKey, ...]
    """The translation keys."""
    frames_owner: str
    """The animation whose keys are played (this one when it names itself)."""
    translation_interpolation: int
    """``0`` for linear and ``1`` for spline translation."""
    repeat_translation: bool
    """Whether the translation keys repeat, each repetition offset by the path's span."""
    scale_keys: tuple[RndKey, ...]
    """The scale keys."""
    scale_interpolation: int
    """``0`` for linear and ``1`` for spline scale."""
    follow_path: bool
    """Whether the target turns to face along its translation path."""


class MmeshMeta(TypedDict):
    """Decoded ``Rnd::MultiMesh`` (``.mmesh``) instanced-mesh metadata."""

    instance_transforms: Sequence[Sequence[float]]
    """Each instance's 4x3 row-major transform (twelve floats)."""
    mesh: str | None
    """The first referenced ``.mesh`` object, or ``None`` if there is none."""
    references: Sequence[str]
    """Every referenced object name, in file order with duplicates removed."""
    version: int
    """Object version (``u32`` at offset ``0``)."""


class LnmMeta(TypedDict):
    """Decoded ``Rnd::LightNamedMesh`` light group (``.lnm``) metadata."""

    lit_refs: Sequence[str]
    """The referenced ``.lit`` light object names."""
    references: Sequence[str]
    """Every referenced object name, in file order with duplicates removed."""
    transforms: Sequence[Sequence[float]]
    """Every 4x3 row-major transform (twelve floats each) found in the body."""
    version: int
    """Object version (``u32`` at offset ``0``)."""


class ArenaMeta(TypedDict):
    """Decoded ``Rnd::Arena`` scene (``.arena``) metadata."""

    references: Sequence[str]
    """Every referenced object name, in file order with duplicates removed."""
    version: int
    """Object version (``u32`` at offset ``0``)."""
    view_refs: Sequence[str]
    """The referenced ``.view`` sleeve object names."""


class MatMeta(TypedDict):
    """Decoded ``Rnd::Mat`` material (``.mat``) metadata."""

    blend_mode: int
    """Blend-mode enumerator (``u32`` at offset ``8``)."""
    textures: Sequence[str] | None
    """The referenced ``.tex``/``.bmp`` texture names, or ``None`` if there are none."""
    version: int
    """Material version (``2``, ``3``, or ``7``)."""


class LightMeta(TypedDict):
    """Decoded ``Rnd::Light`` (``.lit``) metadata; always exactly 200 bytes."""

    color: Sequence[float]
    """The light's RGB colour (three floats at offset ``0x7c``)."""
    cone_inner: float
    """Inner cone angle (float at offset ``0xb0``)."""
    cone_outer: float
    """Outer cone angle (float at offset ``0xac``)."""
    intensity: float
    """Light intensity (float at offset ``0xb8``)."""
    local_xfm: Sequence[float]
    """The local 4x3 row-major transform (twelve floats at offset ``0x08``)."""
    range: float
    """Light range (float at offset ``0xb4``)."""
    type: int
    """Light type (``0`` point, ``1`` directional, ``2`` spot)."""
    version: int
    """Object version (always ``1``)."""
    world_xfm: Sequence[float]
    """The world 4x3 row-major transform (twelve floats at offset ``0x38``)."""


class EnvironMeta(TypedDict):
    """
    Decoded ``Rnd::Environ`` (``.env``) metadata.

    The trailing fog block is present only when the bytes after the light-name list are exactly the
    expected length; otherwise just ``version`` and ``lights`` are populated.
    """

    ambient: NotRequired[Sequence[float]]
    """The ambient colour (four floats)."""
    fog_color: NotRequired[Sequence[float]]
    """The fog colour (four floats)."""
    fog_density: NotRequired[float]
    """The fog density."""
    fog_end: NotRequired[float]
    """The fog end distance."""
    fog_mode: NotRequired[str]
    """The fog mode name (one of the seven recognised modes)."""
    fog_start: NotRequired[float]
    """The fog start distance."""
    lights: Sequence[str]
    """The referenced ``.lit`` light object names."""
    version: int
    """Object version (always ``0``)."""


class MovieMeta(TypedDict):
    """Decoded ``Rnd::Movie`` (``.tmov``) animated-texture-movie metadata."""

    fps: float | None
    """Playback rate in frames per second, or ``None`` when the file omits it."""
    frames: int | None
    """The frame count, or ``None`` if it could not be read."""
    movie: str | None
    """The referenced ``.gif`` movie name, or ``None`` if there is none."""
    tex: str | None
    """The referenced ``.tex`` target-texture name, or ``None`` if there is none."""
    version: int
    """Object version (always ``2``)."""
