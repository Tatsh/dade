"""Typed data structures shared across :py:mod:`dade.maxpayne`."""
from __future__ import annotations

from typing import NamedTuple, TypeAlias

__all__ = ('ArchiveHeader', 'Corner', 'Level', 'LevelGeometry', 'Material', 'MeshFace', 'Polygon',
           'RASContents', 'RASDirectory', 'RASEntry', 'RenderMesh', 'StaticMesh', 'TaggedValue',
           'TextureImage', 'Vector3')

Vector3: TypeAlias = 'tuple[float, float, float]'
"""A point or direction in level space, where one unit is about a metre.

Nothing in a level says so outright, but the skins settle it: ``gognitti_vinnie_l0.kfs`` is a man
1.88 units tall, and the doors he walks through are a little over two."""


class ArchiveHeader(NamedTuple):
    """The decrypted 44-byte header at the start of every RAS archive."""

    seed: int
    """Signed cipher seed, stored in the clear, keying the rest of the archive."""
    file_count: int
    """Number of entries in the file table."""
    directory_count: int
    """Number of entries in the directory table."""
    file_table_size: int
    """Size of the file table in bytes."""
    directory_table_size: int
    """Size of the directory table in bytes."""
    version: float
    """Archive format version. Only ``1.20`` is known to exist."""
    crc: int
    """CRC32 of the header with this field zeroed."""
    file_crc: int
    """CRC32 of the decrypted file table."""
    directory_crc: int
    """CRC32 of the decrypted directory table."""
    archiver_id: int
    """Writer identity checked by ``R_File::verifyArchiverID``. Always ``3`` in shipped data."""


class RASDirectory(NamedTuple):
    """One entry of a RAS directory table."""

    name: str
    """Backslash-delimited path as stored, including leading and trailing separators."""
    modified: str | None
    """Modification time as ``YYYY-MM-DD HH:MM:SS.mmm``, or :py:obj:`None` when unset."""


class RASEntry(NamedTuple):
    """One member of a RAS archive."""

    name: str
    """Member name without any directory part."""
    path: str
    """Full slash-delimited path, formed by joining the member's directory with its name."""
    size: int
    """Size in bytes after any ``RA->`` or ``RC->`` wrapper is removed."""
    stored_size: int
    """Number of bytes occupied in the archive."""
    offset: int
    """Absolute byte offset of the member's payload, derived from the preceding members."""
    directory: int
    """Index into the archive's directory table."""
    modified: str | None
    """Modification time as ``YYYY-MM-DD HH:MM:SS.mmm``, or :py:obj:`None` when unset."""


class RASContents(NamedTuple):
    """Everything decoded from an archive's header and tables."""

    data_end: int
    """Offset one past the last member's payload. Equals the archive size when intact."""
    directories: tuple[RASDirectory, ...]
    """The directory table, in stored order."""
    entries: tuple[RASEntry, ...]
    """The file table, in stored order."""
    header: ArchiveHeader
    """The decrypted archive header."""


class Polygon(NamedTuple):
    """One convex face of a level's world geometry."""

    first_vertex: int
    """Index of the face's first corner in the level's vertex pool."""
    vertex_count: int
    """Number of corners, between three and eight. The corners are the pool entries from
    :py:attr:`first_vertex` onwards, so faces never share pool entries."""
    polygon_index: int
    """Index into a table that is not decoded yet. The name is provisional: on
    ``Part1_Level6.ldb`` it takes 4201 values over 15333 faces, and faces sharing a value do not
    reliably share a normal, so it is not a plane identifier."""
    mesh_index: int
    """Index into a smaller table that is not decoded yet, also provisionally named. It takes 5
    values on ``Part1_Level6.ldb`` and 39 on ``Part1_Level1.ldb``, splitting a level into a handful
    of large face sets, which is what :py:func:`dade.maxpayne.gltf.build_glb` groups primitives
    by."""
    normal: Vector3
    """Outward face normal."""
    origin: Vector3
    """A point on the face's plane."""


class LevelGeometry(NamedTuple):
    """The world geometry at the head of a ``.ldb``."""

    vertices: tuple[Vector3, ...]
    """The vertex pool, already de-indexed: every face owns a contiguous run of it."""
    polygons: tuple[Polygon, ...]
    """The faces, in stored order."""


class TaggedValue(NamedTuple):
    """One value decoded from a tagged ``R_MemoryFile`` stream."""

    offset: int
    """Byte offset of the tag within the stream."""
    end: int
    """Byte offset just past the value, which is where the next tag begins."""
    tag: int
    """Raw ``BasicType`` tag byte."""
    payload: bytes
    """Value bytes without the tag. Empty for markers such as ``ARRAY``; for a string this is the
    text alone, with its length prefix removed."""


class TextureImage(NamedTuple):
    """One image a level carries, stored as a complete file."""

    path: str
    """Absolute path the artist authored the image at, used as the texture's key."""
    kind: int
    """Format code written beside the image. ``0`` accompanies Targa data and ``4`` JPEG."""
    data: bytes
    """The image file, byte for byte."""


class Material(NamedTuple):
    """One material binding a surface category to an image."""

    category: str
    """Surface category, such as ``wood`` or ``metal``. Drives footstep and impact sounds."""
    texture: str
    """The material's name, as the artist typed it. Usually looks like a filename but is not one:
    ``BOOKSHELF01_128X256.JPG`` names the material that draws with
    ``bookshelf01_256x256.jpg``. Use :py:attr:`image` to reach the picture."""
    image: str
    """Path of the embedded image the material draws with, matching a
    :py:attr:`TextureImage.path` exactly, or an empty string when the level's category table does
    not name one."""
    alpha: str = ''
    """Path of the embedded image holding the material's alpha, or an empty string when it is
    opaque. The colour images are JPEG or 8-bit PCX and carry no alpha channel of their own, so a
    material that needs one -- foliage, fences, neon signs, glass -- names a second image whose
    brightness is the mask."""
    blend: str = ''
    """glTF alpha mode the material asks for outright, or an empty string when it does not.

    Max Payne 2 says how a material blends rather than naming a mask, because its images are DDS
    and carry their own alpha channel. Max Payne 1 leaves this empty and the mode is worked out
    from :py:attr:`alpha` instead."""
    dual_sided: bool = False
    """Whether the material is drawn from both sides."""
    sort_priority: int = 0
    """How far in front of what it covers the material is drawn.

    Max Payne 2 states this for the surfaces laid over other surfaces -- graffiti, signage, decals
    -- so an exporter has no need to work it out from the geometry. Max Payne 1 stores nothing and
    leaves it at zero, and :py:mod:`dade.maxpayne.decals` does the working out instead."""


class Level(NamedTuple):
    """Everything decoded from a ``.ldb``."""

    geometry: LevelGeometry
    """The vertex pool and face table."""
    textures: tuple[TextureImage, ...]
    """The embedded images."""
    materials: dict[int, Material]
    """Material identifier to material."""
    mesh: RenderMesh | None
    """The renderable mesh, or :py:obj:`None` when it could not be located."""
    props: RenderMesh | None = None
    """The animated props -- doors, elevators, breakables -- which the editor keeps apart from the
    architecture because each can be driven by an animation."""
    characters: tuple[Character, ...] = ()
    """The NPCs the level spawns."""
    items: tuple[LevelItem, ...] = ()
    """The pickups the level holds."""
    lightmaps: tuple[TextureImage, ...] = ()
    """The baked lighting atlases, addressed by :py:attr:`Corner.lightmap_uv`. Each is an
    uncompressed 256 by 256 Targa."""


class Corner(NamedTuple):
    """One polygon corner of a level's renderable mesh."""

    uv: tuple[float, float]
    """Texture coordinate, as the game itself stores it."""
    lightmap_uv: tuple[float, float]
    """Second coordinate set, addressing the level's lightmap atlases."""
    neighbour: int
    """Which corner sits across the edge, packed with a crease bit.

    The engine tessellates a curved surface at runtime and needs to know what it is joined to:
    ``value & 0x7fffff`` is the neighbour, ``value >> 0x18`` the edge, ``value >> 0x17 & 1`` marks
    a crease, and ``0xffffffff`` means no neighbour. A viewer drawing the level as it is stored has
    no use for any of it."""
    position: int
    """Index into :py:attr:`RenderMesh.positions`."""


class MeshFace(NamedTuple):
    """One convex face of a level's renderable mesh."""

    first_corner: int
    """Index of the face's first corner in :py:attr:`RenderMesh.corners`."""
    corner_count: int
    """Number of corners the face owns, taken consecutively."""
    material: int
    """Identifier into :py:attr:`Level.materials`."""
    normal: Vector3
    """Outward face normal."""
    lightmap: int = -1
    """Index into :py:attr:`Level.lightmaps` of the atlas that lights the face, addressed by
    :py:attr:`Corner.lightmap_uv`. Every level's faces cover its atlas range exactly."""
    flags: int = 0
    """The face's rendering flags."""


class StaticMesh(NamedTuple):
    """One placed mesh: level architecture, a prop, or anything else built in the editor."""

    positions: tuple[Vector3, ...]
    """Vertex positions in the mesh's own space, before :py:attr:`transform`."""
    normals: tuple[Vector3, ...]
    """One normal per position."""
    transform: tuple[float, ...]
    """Twelve floats: three basis rows then a translation, placing the mesh in the level."""
    faces: tuple[MeshFace, ...]
    """The mesh's faces, whose corners index :py:attr:`RenderMesh.corners`."""


class PropAnimation(NamedTuple):
    """One clip a prop can play: a door swinging open, a lift rising, a fan turning."""

    name: str
    """The clip's name, such as ``open1``. A prop's clips chain by name from their scripts."""
    duration: float
    """How long the clip runs, in seconds."""
    start: tuple[float, ...]
    """The prop's transform at the beginning, as twelve floats."""
    end: tuple[float, ...]
    """The prop's transform at the end, as twelve floats."""
    distance: tuple[float, ...]
    """How far the prop has travelled, in world units. Its last sample is the whole distance from
    :py:attr:`start` to :py:attr:`end`, which holds on 4701 of the 4704 moving clips in the first
    game's levels."""
    turn: tuple[float, ...]
    """How far the prop has turned, from zero to one. The two curves are separate channels with
    their own sample counts, and a prop that both slides and turns eases them differently."""
    distance_times: tuple[float, ...] = ()
    """When each of :py:attr:`distance`'s samples falls, as a fraction of :py:attr:`duration`.
    Empty when the format spaces them evenly and states no times, which the first game does."""
    turn_times: tuple[float, ...] = ()
    """When each of :py:attr:`turn`'s samples falls, as a fraction of :py:attr:`duration`. Empty
    when the format spaces them evenly and states no times, which the first game does."""


class RenderMesh(NamedTuple):
    """A level's renderable geometry, carrying the game's own texture coordinates."""

    corners: tuple[Corner, ...]
    """Polygon corners shared by every mesh, each naming a position in its own mesh."""
    meshes: tuple[StaticMesh, ...]
    """The placed meshes, in stored order."""
    names: tuple[str, ...] = ()
    """One editor name per mesh, where the container stores them. The static mesh container keys
    its meshes by number and leaves this empty; the dynamic mesh container keys them by name."""
    keys: tuple[int, ...] = ()
    """One identifier per mesh, where the container keys them by number. The room table and the
    BSP's faces both name meshes by these."""
    animations: tuple[tuple[PropAnimation, ...], ...] = ()
    """The clips each mesh can play, in the same order as :py:attr:`meshes`. Only the animated
    props have any."""


class Placement(NamedTuple):
    """Where the editor put one thing that is not level architecture.

    ``X_LevelDBLevelObject::read`` gives every placed object the same head: a name, the transform
    that places it, a second transform, an identifier, and the room it belongs to.
    """

    name: str
    """The editor's name for the placement, such as ``::a5::e1``."""
    transform: tuple[float, ...]
    """Twelve floats: three basis rows then a translation."""
    room: str
    """Name of the room the object belongs to, empty when it belongs to none."""


class Character(NamedTuple):
    """One NPC the level spawns."""

    placement: Placement
    """Where the character stands."""
    skin: str
    """Directory name under ``data/database/skins``, such as ``gognitti_vinnie``."""


class LevelItem(NamedTuple):
    """One pickup: a weapon, ammunition, or a painkiller bottle."""

    placement: Placement
    """Where the pickup sits."""
    item: str
    """Directory name under ``data/database/level_items``, such as ``ammo_ingram``."""


class ModelFace(NamedTuple):
    """One triangle of a model."""

    positions: tuple[int, int, int]
    """Indices into :py:attr:`ModelMesh.positions`."""
    coords: tuple[int, int, int]
    """Indices into :py:attr:`ModelMesh.coords`, empty-safe when the mesh has none."""
    material: int
    """Index into :py:attr:`ModelMesh.materials`."""


class ModelMesh(NamedTuple):
    """One mesh of a model."""

    name: str
    """The mesh's name in the exporter that wrote it."""
    positions: tuple[Vector3, ...]
    """Vertex positions, converted from the exporter's Z-up space to the game's Y-up one."""
    normals: tuple[Vector3, ...]
    """One normal per position, or empty when the file stores none."""
    coords: tuple[tuple[float, float], ...]
    """Texture coordinates exactly as stored. Both components run outside ``0..1``, V almost
    always negative, so the sampler has to wrap them the way Direct3D did."""
    faces: tuple[ModelFace, ...]
    """The mesh's triangles."""
    materials: tuple[str, ...]
    """Names of the materials the faces index, as they appear in :py:attr:`Model.materials`."""


class Model(NamedTuple):
    """A ``.kfs`` skin or ``.kf2`` object: the models NPCs, pickups and weapons are drawn with."""

    meshes: tuple[ModelMesh, ...]
    """The meshes, in stored order."""
    materials: dict[str, str]
    """Material name to the file name of the image it draws with."""
    search: tuple[str, ...] = ()
    """Directories the model expects its images to be found in, relative to its own."""
    textures: tuple[TextureImage, ...] = ()
    """The images themselves. A model does not embed them, so a caller that wants the model
    textured has to read them off disk and put them here."""
