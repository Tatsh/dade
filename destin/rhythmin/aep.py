"""
Reading of the AEP ``.idx`` animation indexes.

The ``.idx`` files in ``PopnRhythmin.app`` (``music_select.idx``, ``title.idx``, and so on) drive
the AEP 2D scene layer and frame animation system. Every offset below is relative to ``idxBase``,
which is the file plus four bytes, matching ``AepManager::readIndexFile`` and ``relocateData``:

* the header is ``int16`` group id, ``int16`` reserved, then five ``int32`` of which three are the
  offsets of the frame, layer, and user name blocks;
* each name block is a run of NUL-terminated strings closed by an empty string, after which the
  producer aligns the cursor to eight bytes;
* the frame-name block's aligned end is the sprite-record table, one stride-8 record per frame name
  in frame-name ordinal order, so ``sprite_records[getFrameNo(name)]`` is the atlas rectangle a
  drawn sprite samples. The texture atlas is paged into 2048 by 2048 pages, and ``atlas_v`` runs
  across those pages;
* the layer-name block is followed by one ``int16`` layer ordinal per layer name, padded to a
  multiple of four ordinals, and the frame-entry array starts there;
* a frame entry is ten ``int16`` fields followed by four ``int32`` channel offsets, again relative
  to ``idxBase``, where zero means the channel is absent.

The alignment deserves a note, because getting it wrong is silent. ``buildAepNameHashTable``
aligns by the cursor's raw address, and at run time the ``.idx`` is a 16-byte-aligned buffer whose
``idxBase`` is therefore four modulo eight, which lands the following block at a file offset that
is a multiple of eight. Aligning the file offset to eight reproduces that. Reading the unaligned
end instead shifts the whole sprite table by one ``int16`` pair, which overflows the atlas for 19
of the 218 records in ``game_cmn_ipad.idx``; the aligned base overflows none.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple
import functools
import struct

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = ('ATLAS_PAGE_SIZE', 'COLOR_KEYFRAME_SIZE', 'ENTRY_TYPES', 'FRAME_ENTRY_SIZE',
           'POSITION_KEYFRAME_SIZE', 'SPRITE_RECORD_SIZE', 'AepHeader', 'AepIndex', 'ColorKeyframe',
           'FrameEntry', 'NameLocation', 'PositionKeyframe', 'SpriteRecord', 'entry_to_json',
           'index_to_json', 'read_aep_index')

FRAME_ENTRY_SIZE = 0x24
"""Stride of one ``AepFrameEntry``.

:meta hide-value:
"""
POSITION_KEYFRAME_SIZE = 8
"""Stride of one position keyframe, four ``int16`` of frame, x, y, and a reserved field.

:meta hide-value:
"""
COLOR_KEYFRAME_SIZE = 4
"""Stride of one colour keyframe, an ``int16`` frame and a packed ``int16``.

:meta hide-value:
"""
SPRITE_RECORD_SIZE = 8
"""Stride of one sprite record, four ``int16`` stored as atlas u, atlas v, width, and height.

:meta hide-value:
"""
ATLAS_PAGE_SIZE = 2048
"""Edge length of one ``game_cmn_ipad_N.png`` atlas page.

:meta hide-value:
"""
ENTRY_TYPES = {0: 'sprite', 2: 'layer', 3: 'group'}
"""Frame-entry type to its readable name. A negative type terminates a layer chain.

:meta hide-value:
"""

_IDX_BASE = 4
_NAME_ALIGNMENT = 8
_LAYER_ORDINAL_GROUP = 4
_MAX_KEYFRAMES = 4096
_CHANNEL_OFFSET = 0x14
_SIGNED_BYTE_LIMIT = 128
_HEADER_FORMAT = '<hhiiiii'
_PLAUSIBLE_ENTRY_TYPES = (-1, 0, 2, 3)
_PLAUSIBLE_FRAME_LIMIT = 0x4000


class AepHeader(NamedTuple):
    """The ``AepIndexHeader`` at the start of an index."""

    group_id: int
    """Identifier of the group this index defines."""
    frame_names_offset: int
    """``idxBase``-relative offset of the frame-name block."""
    layer_names_offset: int
    """``idxBase``-relative offset of the layer-name block."""
    user_names_offset: int
    """``idxBase``-relative offset of the user-name block."""


class SpriteRecord(NamedTuple):
    """One frame name's rectangle in the texture atlas."""

    width: int
    """Width in pixels."""
    height: int
    """Height in pixels."""
    atlas_u: int
    """Left edge in the atlas."""
    atlas_v: int
    """Top edge in the atlas, running across 2048-tall pages."""
    @property
    def page(self) -> int:
        """
        Atlas page this record samples from.

        Returns
        -------
        int
            The page ordinal.
        """
        return self.atlas_v // ATLAS_PAGE_SIZE

    @property
    def fits(self) -> bool:
        """
        Whether the rectangle lies inside its atlas page.

        A record that does not is a sign the table was read from the wrong base.

        Returns
        -------
        bool
            ``True`` when the rectangle is a plausible sprite.
        """
        return (self.width > 0 and self.height > 0 and self.atlas_u >= 0 and self.atlas_v >= 0
                and self.atlas_u + self.width <= ATLAS_PAGE_SIZE)


class FrameEntry(NamedTuple):
    """One ``AepFrameEntry`` from the flat entry array."""

    offset: int
    """File offset the entry was read from."""
    entry_type: int
    """0 for a leaf sprite, 2 for a nested layer, 3 for a group callback, negative to terminate."""
    child: int
    """Frame ordinal, nested layer, or user-name ordinal, depending on the type."""
    blend_flags: int
    """Blend mode and flags."""
    frame_speed: int
    """Playback rate."""
    frame_start: int
    """First frame of the entry's window."""
    frame_end: int
    """One past the last frame of the entry's window."""
    loop_offset: int
    """Frame the animation loops back to."""
    anchor_x: int
    """Horizontal anchor."""
    anchor_y: int
    """Vertical anchor."""
    position_channel: int
    """``idxBase``-relative offset of the position channel, or 0 when absent."""
    scale_channel: int
    """``idxBase``-relative offset of the scale channel, or 0 when absent."""
    color_channel: int
    """``idxBase``-relative offset of the colour channel, or 0 when absent."""
    rotation_channel: int
    """``idxBase``-relative offset of the rotation channel, or 0 when absent."""
    @property
    def type_name(self) -> str:
        """
        Readable name of the entry's type.

        Returns
        -------
        str
            One of the :data:`ENTRY_TYPES` names, or ``'terminator'`` for a negative type.
        """
        if self.entry_type < 0:
            return 'terminator'
        return ENTRY_TYPES.get(self.entry_type, f'unknown ({self.entry_type})')


class PositionKeyframe(NamedTuple):
    """One key of a position channel."""

    frame: int
    """Frame the key applies at."""
    x: int
    """Horizontal offset."""
    y: int
    """Vertical offset."""


class ColorKeyframe(NamedTuple):
    """One key of a colour channel, whose two components are read signed."""

    frame: int
    """Frame the key applies at."""
    color: int
    """Brightness delta."""
    alpha: int
    """Opacity delta."""


class NameLocation(NamedTuple):
    """Where a name was found in an index."""

    block: str
    """The block holding it: ``'frame'``, ``'layer'``, or ``'user'``."""
    ordinal: int
    """Its position within that block."""
    sprite: SpriteRecord | None
    """Its atlas rectangle, for a frame name that has one."""


def _read_header(data: bytes) -> AepHeader:
    group_id, _, frame_offset, _, _, layer_offset, user_offset = struct.unpack_from(
        _HEADER_FORMAT, data, _IDX_BASE)
    return AepHeader(group_id, frame_offset, layer_offset, user_offset)


def _read_frame_entry(data: bytes, offset: int) -> FrameEntry:
    # The eighth field is reserved and has no place in the record.
    fields = struct.unpack_from('<10h', data, offset)
    channels = struct.unpack_from('<4i', data, offset + _CHANNEL_OFFSET)
    return FrameEntry(offset, *fields[:7], *fields[8:], *channels)


class AepIndex:
    """
    One parsed ``.idx`` animation index.

    Parameters
    ----------
    data : bytes
        The whole file.

    Raises
    ------
    ValueError
        If the file is too short to hold a header.
    """
    def __init__(self, data: bytes) -> None:
        if len(data) < _IDX_BASE + struct.calcsize(_HEADER_FORMAT):
            msg = f'Too short for an AEP index header: {len(data)} bytes.'
            raise ValueError(msg)
        self.data = data
        """The whole file."""
        self.header = _read_header(data)
        """The parsed header."""
        self._name_blocks: dict[int, tuple[tuple[str, ...], int]] = {}

    def color_channel(self, offset: int) -> tuple[ColorKeyframe, ...]:
        """
        Decode a colour channel.

        Each key is an ``int16`` frame and a packed ``int16`` whose low byte is the brightness and
        whose high byte is the opacity, both read signed because the engine loads them with
        ``ldrsb``. A negative frame terminates the channel.

        Parameters
        ----------
        offset : int
            The channel's ``idxBase``-relative offset, as a frame entry records it. Zero yields no
            keys.

        Returns
        -------
        tuple[ColorKeyframe, ...]
            The channel's keys.
        """
        keys: list[ColorKeyframe] = []
        for position in self._channel_offsets(offset, COLOR_KEYFRAME_SIZE):
            frame, packed = struct.unpack_from('<2h', self.data, position)
            if frame < 0:
                break
            color = packed & 0xFF
            alpha = (packed >> 8) & 0xFF
            keys.append(
                ColorKeyframe(frame, color - 256 if color >= _SIGNED_BYTE_LIMIT else color,
                              alpha - 256 if alpha >= _SIGNED_BYTE_LIMIT else alpha))
        return tuple(keys)

    def find(self, name: str) -> tuple[NameLocation, ...]:
        """
        Locate a name in every block that holds it.

        Parameters
        ----------
        name : str
            The name to look for.

        Returns
        -------
        tuple[NameLocation, ...]
            One location per block the name appears in, which is usually one and may be none.
        """
        found: list[NameLocation] = []
        for block, names in (('frame', self.frame_names), ('layer', self.layer_names),
                             ('user', self.user_names)):
            if name not in names:
                continue
            ordinal = names.index(name)
            records = self.sprite_records if block == 'frame' else ()
            sprite = records[ordinal] if ordinal < len(records) else None
            found.append(NameLocation(block, ordinal, sprite))
        return tuple(found)

    @functools.cached_property
    def frame_entries(self) -> tuple[FrameEntry, ...]:
        """
        The flat frame-entry array.

        The array carries no length, and layer chains within it are contiguous and terminated by a
        negative type, so the walk stops at the first record whose fields cannot be an entry.

        Returns
        -------
        tuple[FrameEntry, ...]
            Every entry up to that point.
        """
        entries: list[FrameEntry] = []
        offset = self.frame_entries_offset
        while offset + FRAME_ENTRY_SIZE <= len(self.data):
            entry = _read_frame_entry(self.data, offset)
            if not (entry.entry_type in _PLAUSIBLE_ENTRY_TYPES
                    and -1 <= entry.frame_start <= _PLAUSIBLE_FRAME_LIMIT
                    and -1 <= entry.frame_end <= _PLAUSIBLE_FRAME_LIMIT
                    and 0 <= entry.position_channel < len(self.data)):
                break
            entries.append(entry)
            offset += FRAME_ENTRY_SIZE
        return tuple(entries)

    @functools.cached_property
    def frame_entries_offset(self) -> int:
        """
        File offset of the frame-entry array, past the layer names and their ordinals.

        Returns
        -------
        int
            The offset.
        """
        names, cursor = self._names_at(self.header.layer_names_offset)
        cursor += len(names) * 2
        if remainder := len(names) % _LAYER_ORDINAL_GROUP:
            cursor += (_LAYER_ORDINAL_GROUP - remainder) * 2
        return cursor

    @functools.cached_property
    def frame_names(self) -> tuple[str, ...]:
        """
        The frame-name block.

        Returns
        -------
        tuple[str, ...]
            Every frame name, in ordinal order.
        """
        return self._names_at(self.header.frame_names_offset)[0]

    def layer_chain(self, name: str) -> tuple[FrameEntry, ...]:
        """
        Walk one layer's frame-entry chain.

        The layer name's ordinal indexes :attr:`layer_numbers` to give the entry the chain starts
        at, and the chain runs until a negative type terminates it, exactly as
        ``AepManager::layerLength`` does. The terminator is included so that its ``frame_end``,
        which carries the chain's length, is not lost.

        Parameters
        ----------
        name : str
            The layer name.

        Returns
        -------
        tuple[FrameEntry, ...]
            The chain's entries.

        Raises
        ------
        KeyError
            If the index has no such layer name.
        """
        if name not in self.layer_names:
            msg = f'{name!r} is not a layer name in this index.'
            raise KeyError(msg)
        entry_index = self.layer_numbers[self.layer_names.index(name)]
        offset = self.frame_entries_offset + entry_index * FRAME_ENTRY_SIZE
        chain: list[FrameEntry] = []
        while offset + FRAME_ENTRY_SIZE <= len(self.data):
            entry = _read_frame_entry(self.data, offset)
            if entry.entry_type < 0:
                chain.append(entry)
                break
            # A chain is a run of sprite, layer, and group entries; anything else means the walk
            # has left the array and entered an adjacent section.
            if entry.entry_type not in ENTRY_TYPES:
                break
            chain.append(entry)
            offset += FRAME_ENTRY_SIZE
        return tuple(chain)

    @functools.cached_property
    def layer_names(self) -> tuple[str, ...]:
        """
        The layer-name block.

        Returns
        -------
        tuple[str, ...]
            Every layer name, in ordinal order.
        """
        return self._names_at(self.header.layer_names_offset)[0]

    @functools.cached_property
    def layer_numbers(self) -> tuple[int, ...]:
        """
        The per-ordinal entry-index table, ``m_layerNumbers``.

        A layer name's ordinal indexes this table to get the entry its chain starts at, mirroring
        ``getLyrNo``. The table sits immediately after the layer-name block.

        Returns
        -------
        tuple[int, ...]
            One entry index per layer name.
        """
        names, cursor = self._names_at(self.header.layer_names_offset)
        return struct.unpack_from(f'<{len(names)}h', self.data, cursor)

    def position_channel(self, offset: int) -> tuple[PositionKeyframe, ...]:
        """
        Decode a position channel, whose keys run until one carries a frame of ``-1``.

        Parameters
        ----------
        offset : int
            The channel's ``idxBase``-relative offset, as a frame entry records it. Zero yields no
            keys.

        Returns
        -------
        tuple[PositionKeyframe, ...]
            The channel's keys.
        """
        keys: list[PositionKeyframe] = []
        for position in self._channel_offsets(offset, POSITION_KEYFRAME_SIZE):
            frame, x, y, _ = struct.unpack_from('<4h', self.data, position)
            if frame == -1:
                break
            keys.append(PositionKeyframe(frame, x, y))
        return tuple(keys)

    @functools.cached_property
    def sprite_records(self) -> tuple[SpriteRecord, ...]:
        """
        The sprite-record table that follows the frame-name block.

        There is one record per frame name, in frame-name ordinal order, so the i-th record is the
        atlas rectangle the i-th frame name samples. In the file each record is stored as atlas u,
        atlas v, width, height; this returns them reordered to width, height, atlas u, atlas v,
        which is the order ``drawAepOtSprite`` reads them in.

        Returns
        -------
        tuple[SpriteRecord, ...]
            One record per frame name, truncated if the file ends early.
        """
        names, offset = self._names_at(self.header.frame_names_offset)
        records: list[SpriteRecord] = []
        for index in range(len(names)):
            position = offset + index * SPRITE_RECORD_SIZE
            if position + SPRITE_RECORD_SIZE > len(self.data):
                break
            atlas_u, atlas_v, width, height = struct.unpack_from('<4h', self.data, position)
            records.append(SpriteRecord(width, height, atlas_u, atlas_v))
        return tuple(records)

    @functools.cached_property
    def user_names(self) -> tuple[str, ...]:
        """
        The user-name block.

        Returns
        -------
        tuple[str, ...]
            Every user name, in ordinal order.
        """
        return self._names_at(self.header.user_names_offset)[0]

    def _channel_offsets(self, offset: int, stride: int) -> Iterator[int]:
        """
        Yield the file offsets of a channel's keys, bounding the walk.

        Parameters
        ----------
        offset : int
            The channel's ``idxBase``-relative offset. Zero yields nothing.
        stride : int
            Bytes per key.

        Yields
        ------
        int
            The file offset of each key.
        """
        if offset == 0:
            return
        position = _IDX_BASE + offset
        for _ in range(_MAX_KEYFRAMES):
            if position + stride > len(self.data):
                return
            yield position
            position += stride

    def _names_at(self, offset: int) -> tuple[tuple[str, ...], int]:
        """
        Parse a NUL-separated name block and report where the next block begins.

        Parameters
        ----------
        offset : int
            The block's ``idxBase``-relative offset.

        Returns
        -------
        tuple[tuple[str, ...], int]
            The names and the eight-byte-aligned file offset just past the block.

        Raises
        ------
        ValueError
            If the block runs off the end of the file, so the offset was not a name block.
        """
        if (cached := self._name_blocks.get(offset)) is not None:
            return cached
        names: list[str] = []
        position = _IDX_BASE + offset
        while position < len(self.data) and self.data[position:position + 1] != b'\0':
            end = self.data.find(b'\0', position)
            if end < 0:
                msg = f'Unterminated name block at offset {offset:#x}.'
                raise ValueError(msg)
            names.append(self.data[position:end].decode('latin1'))
            position = end + 1
        if position >= len(self.data):
            msg = f'Name block at offset {offset:#x} runs past the end of the file.'
            raise ValueError(msg)
        end = position + 1  # Past the terminating empty string.
        if remainder := end % _NAME_ALIGNMENT:
            end += _NAME_ALIGNMENT - remainder
        self._name_blocks[offset] = (tuple(names), end)
        return self._name_blocks[offset]


def read_aep_index(path: Path) -> AepIndex:
    """
    Read one ``.idx`` animation index.

    A file too short to hold a header raises the :py:class:`ValueError` :class:`AepIndex` raises.

    Parameters
    ----------
    path : pathlib.Path
        The file to read.

    Returns
    -------
    AepIndex
        The parsed index.
    """
    return AepIndex(path.read_bytes())


def index_to_json(index: AepIndex, *, names_only: bool = False) -> dict[str, Any]:
    """
    Render a parsed index as JSON-ready values.

    Parameters
    ----------
    index : AepIndex
        The index to render.
    names_only : bool
        Emit only the header and the three name blocks, leaving out the sprite records and frame
        entries.

    Returns
    -------
    dict[str, Any]
        The rendered index.
    """
    rendered: dict[str, Any] = {
        'groupId': index.header.group_id,
        'frameNamesOffset': index.header.frame_names_offset,
        'layerNamesOffset': index.header.layer_names_offset,
        'userNamesOffset': index.header.user_names_offset,
        'frameNames': list(index.frame_names),
        'layerNames': list(index.layer_names),
        'userNames': list(index.user_names),
    }
    if names_only:
        return rendered
    # There is never more than one record per frame name, but a truncated file yields fewer.
    rendered['spriteRecords'] = [{
        'name': index.frame_names[ordinal],
        'width': record.width,
        'height': record.height,
        'atlasU': record.atlas_u,
        'atlasV': record.atlas_v,
        'page': record.page,
        'fits': record.fits,
    } for ordinal, record in enumerate(index.sprite_records)]
    rendered['layerNumbers'] = list(index.layer_numbers)
    rendered['frameEntriesOffset'] = index.frame_entries_offset
    rendered['frameEntries'] = [entry_to_json(index, entry) for entry in index.frame_entries]
    return rendered


def entry_to_json(index: AepIndex, entry: FrameEntry) -> dict[str, Any]:
    """
    Render one frame entry, with its position and colour channels decoded.

    Parameters
    ----------
    index : AepIndex
        The index the entry came from, used to read its channels.
    entry : FrameEntry
        The entry to render.

    Returns
    -------
    dict[str, Any]
        The rendered entry.
    """
    return {
        'offset': entry.offset,
        'type': entry.entry_type,
        'typeName': entry.type_name,
        'child': entry.child,
        'blendFlags': entry.blend_flags,
        'frameSpeed': entry.frame_speed,
        'frameStart': entry.frame_start,
        'frameEnd': entry.frame_end,
        'loopOffset': entry.loop_offset,
        'anchorX': entry.anchor_x,
        'anchorY': entry.anchor_y,
        'positionChannel': entry.position_channel,
        'scaleChannel': entry.scale_channel,
        'colorChannel': entry.color_channel,
        'rotationChannel': entry.rotation_channel,
        'positionKeys': [key._asdict() for key in index.position_channel(entry.position_channel)],
        'colorKeys': [key._asdict() for key in index.color_channel(entry.color_channel)],
    }
