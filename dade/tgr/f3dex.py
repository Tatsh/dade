"""
Geometry from the F3DEX display lists of Top Gear Rally.

Both releases use the same command words. The PC port retained the Nintendo 64 display lists and
interprets them itself, and the files of the PC disc are therefore read by the same code as the
cartridge.

Only the commands that decide geometry and the image a triangle samples are followed. The colour
combiner, the blender, and fog have no equivalent in glTF and are skipped.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import NamedTuple, TypeAlias
import struct

from .texture import FMT_CI, TextureKey

__all__ = ('Corner', 'DisplayListReader', 'Material', 'Triangle')

_G_CULL_BACK = 0x2000
_G_LIGHTING = 0x20000
_G_TEXTURE_GEN = 0x40000
_LOD_DETAIL = 2
_PALETTE_TMEM = 0x100
_PALETTE_TMEM_LAST = 0x1F0
_PALETTE_TILE = 6
_SECOND_PALETTE_TILE = 5
_VERTEX_SLOTS = 64
_VERTEX_SIZE = 16
_MAX_DEPTH = 32
_LARGEST_SHIFT_DOWN = 10
_MAX_COMMANDS = 1 << 20


class _Op(IntEnum):
    VTX = 0x04
    DL = 0x06
    LOADTLUT = 0xF0
    SETTILESIZE = 0xF2
    LOADBLOCK = 0xF3
    SETTILE = 0xF5
    SETTIMG = 0xFD
    TRI2 = 0xB1
    CLEARGEOMETRYMODE = 0xB6
    SETGEOMETRYMODE = 0xB7
    ENDDL = 0xB8
    SETOTHERMODE_H = 0xBA
    TEXTURE = 0xBB
    TRI1 = 0xBF


class Material(NamedTuple):
    """How a triangle is drawn, as far as glTF can express it."""

    texture: TextureKey | None
    """The image sampled, or :py:obj:`None` for an untextured triangle."""
    lit: bool
    """Whether the colour bytes of a vertex are a normal rather than a colour."""
    two_sided: bool
    """Whether the triangle is drawn from both sides."""


class Corner(NamedTuple):
    """One corner of a triangle."""

    position: tuple[float, float, float]
    """Position, in the units of the vertex."""
    uv: tuple[float, float]
    """Texture coordinate, 0 to 1 across the image."""
    colour: tuple[int, int, int, int]
    """The colour, or a signed normal in the first three bytes when the material is lit."""


class Triangle(NamedTuple):
    """A triangle and its material."""

    material: Material
    """How the triangle is drawn."""
    corners: tuple[Corner, Corner, Corner]
    """The corners, counter-clockwise from the front."""


@dataclass(slots=True)
class _Tile:
    cms: int = 0
    cmt: int = 0
    fmt: int = 0
    line: int = 0
    lrs: int = 0
    lrt: int = 0
    masks: int = 0
    maskt: int = 0
    palette: int = 0
    shifts: int = 0
    shiftt: int = 0
    siz: int = 0
    tmem: int = 0
    uls: int = 0
    ult: int = 0


_Slot: TypeAlias = tuple[float, float, float, int, int, tuple[int, int, int, int]]


def _shift_scale(shift: int) -> float:
    return 1 / (1 << shift) if shift <= _LARGEST_SHIFT_DOWN else float(1 << (16 - shift))


class DisplayListReader:
    """
    Follows display lists over one block of memory and collects their triangles.

    Every address is read with its high byte dropped and ``base`` subtracted. The game addresses a
    model either by its virtual address or by a segment whose base is the model itself, and the
    conversion resolves both to the same offset.

    Parameters
    ----------
    memory : bytes | bytearray
        The memory the display lists, the vertices, and the textures are in.
    base : int
        The address, without its high byte, of the first byte of ``memory``.
    """
    def __init__(self, memory: bytes | bytearray, base: int = 0) -> None:
        self.memory = memory
        """The memory the display lists, the vertices, and the textures are in."""
        self.base = base
        """The address, without its high byte, of the first byte of the memory."""
        self.triangles: list[Triangle] = []
        """Every triangle collected, in the order drawn."""
        self.geometry_mode = _G_CULL_BACK
        """The ``G_SETGEOMETRYMODE`` bits in effect."""
        self.other_mode_h = 0
        """The high word of the other modes in effect."""
        self.texture_on = True
        """Whether the last ``G_TEXTURE`` turned texturing on."""
        self.texture_tile = 0
        """The tile the last ``G_TEXTURE`` selected for drawing."""
        self.texture_scale = (1.0, 1.0)
        """The S and T scales of the last ``G_TEXTURE``, each as a fraction of 1."""
        self.bound: TextureKey | None = None
        """
        A texture forced onto every triangle, or :py:obj:`None` to resolve it from the tiles.

        A texture or tile command resets it.
        """
        self._image = 0
        self._tiles = [_Tile() for _ in range(8)]
        # The game sets the two palette tiles before every model, and the display lists of a model
        # load through them without setting them again.
        self._tiles[_PALETTE_TILE].tmem = _PALETTE_TMEM_LAST
        self._tiles[_SECOND_PALETTE_TILE].tmem = _PALETTE_TMEM
        self._tmem: dict[int, int] = {}
        self._slots: list[_Slot] = [(0.0, 0.0, 0.0, 0, 0, (0, 0, 0, 0))] * _VERTEX_SLOTS

    def offset(self, address: int) -> int:
        """
        Convert an address to an offset into the memory.

        Parameters
        ----------
        address : int
            The address.

        Returns
        -------
        int
            The offset, possibly outside the memory.
        """
        return (address & 0xFFFFFF) - self.base

    def run(self, address: int) -> None:
        """
        Follow a display list, and every list it calls, to its end.

        Parameters
        ----------
        address : int
            The address of the first command.
        """
        self._run(self.offset(address), 0)

    def _run(self, position: int, depth: int) -> None:
        if depth > _MAX_DEPTH:
            return
        for _ in range(_MAX_COMMANDS):
            if position < 0 or position + 8 > len(self.memory):
                return
            w0, w1 = struct.unpack_from('>II', self.memory, position)
            position += 8
            match w0 >> 24:
                case _Op.ENDDL:
                    return
                case _Op.DL:
                    self._run(self.offset(w1), depth + 1)
                    if (w0 >> 16) & 0xFF:
                        return
                case _:
                    self._command(w0, w1)

    def _command(self, w0: int, w1: int) -> None:
        match w0 >> 24:
            case _Op.VTX:
                self._vertices(w1, (w0 >> 10) & 0x3F, ((w0 >> 16) & 0xFF) // 2)
            case _Op.TRI1:
                self._triangle((w1 >> 16) & 0xFF, (w1 >> 8) & 0xFF, w1 & 0xFF)
            case _Op.TRI2:
                self._triangle((w0 >> 16) & 0xFF, (w0 >> 8) & 0xFF, w0 & 0xFF)
                self._triangle((w1 >> 16) & 0xFF, (w1 >> 8) & 0xFF, w1 & 0xFF)
            case _Op.SETGEOMETRYMODE:
                self.geometry_mode |= w1
            case _Op.CLEARGEOMETRYMODE:
                self.geometry_mode &= ~w1
            case _Op.SETOTHERMODE_H:
                shift, length = (w0 >> 8) & 0xFF, w0 & 0xFF
                mask = ((1 << length) - 1) << shift
                self.other_mode_h = (self.other_mode_h & ~mask) | (w1 & mask)
            case _Op.TEXTURE:
                self.texture_on = (w0 & 0xFF) != 0
                self.texture_tile = (w0 >> 8) & 7
                self.texture_scale = ((w1 >> 16) / 0x10000, (w1 & 0xFFFF) / 0x10000)
                self.bound = None
            case _Op.SETTIMG:
                self._image = w1
            case _Op.SETTILE:
                tile = self._tiles[(w1 >> 24) & 7]
                tile.fmt, tile.siz = (w0 >> 21) & 7, (w0 >> 19) & 3
                tile.line, tile.tmem = (w0 >> 9) & 0x1FF, w0 & 0x1FF
                tile.palette, tile.cmt = (w1 >> 20) & 0xF, (w1 >> 18) & 3
                tile.maskt, tile.shiftt = (w1 >> 14) & 0xF, (w1 >> 10) & 0xF
                tile.cms, tile.masks, tile.shifts = (w1 >> 8) & 3, (w1 >> 4) & 0xF, w1 & 0xF
                self.bound = None
            case _Op.SETTILESIZE:
                tile = self._tiles[(w1 >> 24) & 7]
                tile.uls, tile.ult = (w0 >> 12) & 0xFFF, w0 & 0xFFF
                tile.lrs, tile.lrt = (w1 >> 12) & 0xFFF, w1 & 0xFFF
                self.bound = None
            case _Op.LOADBLOCK | _Op.LOADTLUT:
                self._tmem[self._tiles[(w1 >> 24) & 7].tmem] = self._image
                self.bound = None
            case _:
                pass

    def _vertices(self, address: int, count: int, first: int) -> None:
        start = self.offset(address)
        for index in range(count):
            at = start + index * _VERTEX_SIZE
            if first + index >= _VERTEX_SLOTS or at < 0 or at + _VERTEX_SIZE > len(self.memory):
                return
            x, y, z, _, s, t, r, g, b, a = struct.unpack_from('>hhhHhhBBBB', self.memory, at)
            self._slots[first + index] = (float(x), float(y), float(z), s, t, (r, g, b, a))

    def _lookup(self, tmem: int) -> int | None:
        if (nearest := max((loaded for loaded in self._tmem if loaded <= tmem),
                           default=None)) is None:
            return None
        return self._tmem[nearest] + (tmem - nearest) * 8

    def _render_tile(self) -> int:
        detail = (self.other_mode_h >> 16) & 1 and (self.other_mode_h >> 17) & 3 == _LOD_DETAIL
        return (self.texture_tile + (1 if detail else 0)) & 7

    def _texture(self) -> tuple[TextureKey, _Tile] | None:
        if not self.texture_on or self.geometry_mode & _G_TEXTURE_GEN:
            return None
        tile = self._tiles[self._render_tile()]
        if self.bound is not None:
            return self.bound, tile
        if (image := self._lookup(tile.tmem)) is None:
            return None
        palette = -1
        if tile.fmt == FMT_CI:
            if (found := self._lookup(_PALETTE_TMEM + (tile.palette << 4))) is None:
                return None
            palette = self.offset(found)
        width = ((tile.lrs - tile.uls) >> 2) + 1
        height = ((tile.lrt - tile.ult) >> 2) + 1
        if tile.masks:
            width = min(width, 1 << tile.masks)
        if tile.maskt:
            height = min(height, 1 << tile.maskt)
        if width <= 0 or height <= 0:
            return None
        address = self.offset(image)
        if address < 0 or address >= len(self.memory):
            return None
        return TextureKey(address, palette, tile.fmt, tile.siz, width, height, tile.line), tile

    def _triangle(self, *slots: int) -> None:
        found = self._texture()
        lit = bool(self.geometry_mode & _G_LIGHTING)
        material = Material(found[0] if found else None, lit, not self.geometry_mode & _G_CULL_BACK)
        corners = []
        for slot in slots:
            x, y, z, s, t, colour = self._slots[(slot // 2) % _VERTEX_SLOTS]
            uv = (0.0, 0.0)
            if found:
                key, tile = found
                u = s / 32 * self.texture_scale[0] * _shift_scale(tile.shifts) - tile.uls / 4
                v = t / 32 * self.texture_scale[1] * _shift_scale(tile.shiftt) - tile.ult / 4
                uv = (u / key.width, v / key.height)
            corners.append(Corner((x, y, z), uv, colour))
        self.triangles.append(Triangle(material, (corners[0], corners[1], corners[2])))
