"""Shared typing helpers and converter result types for :py:mod:`destin.amplitude`."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, NamedTuple, TypeAlias, TypedDict

from destin.common.typing import InvalidFormatError
from typing_extensions import NotRequired

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ('ARKEntry', 'ArenaMeta', 'ArkLayout', 'Asset', 'BankMeta', 'DataArrayNode',
           'EnvironMeta', 'Geometry', 'IPUMeta', 'InvalidFormatError', 'LightMeta', 'LnmMeta',
           'MIDIFile', 'MIDITrack', 'MMVMeta', 'MatMeta', 'MmeshMeta', 'MovieMeta', 'PoolOutcome',
           'SampleMeta', 'TnmMeta', 'ViewMeta')

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
    """A decoded MIDI track: its name and its events (each carrying an absolute ``tick``)."""

    event_count: int
    """Number of events in the track."""
    events: Sequence[dict[str, Any]]
    """The track's events in order; each is a mido message dict carrying an absolute ``tick``."""
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


class TnmMeta(TypedDict):
    """Decoded ``Rnd::Trans`` named-mesh group (``.tnm``) metadata."""

    mesh_refs: Sequence[str]
    """The referenced ``.mesh`` object names."""
    references: Sequence[str]
    """Every referenced object name, in file order with duplicates removed."""
    tnm_refs: Sequence[str]
    """The referenced child ``.tnm`` object names."""
    transforms: Sequence[Sequence[float]]
    """Every 4x3 row-major transform (twelve floats each) found in the body."""
    version: int
    """Object version (``u32`` at offset ``0``)."""


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
