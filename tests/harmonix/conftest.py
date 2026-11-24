"""Shared pytest configuration and synthetic asset builders for the ``harmonix`` tests."""
from __future__ import annotations

from typing import TYPE_CHECKING
import gzip
import json
import math
import struct
import zlib

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping, Sequence
    from pathlib import Path

    from dade.harmonix.typing import DataArrayNode

_SENTINEL = b'\xad\xde\xad\xde'
"""The Milo inter-object body terminator.

:meta hide-value:
"""
_BLOCK = 0x800
"""The FreQuency ARK data block size.

:meta hide-value:
"""


def _rstr(text: str) -> bytes:
    return struct.pack('<I', len(text)) + text.encode()


def _turn(degrees: float) -> tuple[float, float, float, float]:
    half = math.radians(degrees) / 2
    return (0.0, 0.0, math.sin(half), math.cos(half))


def _at(x: float, y: float, z: float) -> tuple[float, ...]:
    return (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, x, y, z)


def _scene(path: Path, objects: Mapping[str, bytes], extra: Sequence[tuple[str, str]] = ()) -> None:
    path.mkdir(parents=True, exist_ok=True)
    entries = [{'type': typ, 'name': name, 'file': name} for typ, name in extra]
    entries += [{
        'type': 'Mat' if name.endswith('.mat') else 'Mesh',
        'name': name,
        'file': name
    } for name in objects]
    (path / 'manifest.json').write_text(json.dumps({'objects': entries}), encoding='utf-8')
    for name, body in objects.items():
        (path / name).write_bytes(body)


@pytest.fixture
def make_amp_ark() -> Callable[[Sequence[tuple[str, bytes]]], bytes]:
    """
    Build an Amplitude (magic-less, version-first) ARK archive.

    Returns
    -------
    collections.abc.Callable[[collections.abc.Sequence[tuple[str, bytes]]], bytes]
        A callable turning ``(path, data)`` pairs into a complete archive.
    """
    def build(entries: Sequence[tuple[str, bytes]]) -> bytes:
        names: list[str] = []

        def intern(name: str) -> int:
            if name not in names:
                names.append(name)
            return names.index(name)

        buckets = []
        for path, _ in entries:
            dname, _, fname = path.rpartition('/')
            buckets.append((intern(fname), intern(dname) if dname else 0xFFFFFFFF))
        pool = bytearray()
        offsets = []
        for name in names:
            offsets.append(len(pool))
            pool += name.encode() + b'\0'
        n_buckets = len(names)
        dir_end = 8 + len(entries) * 20 + 4 + len(pool) + 4 + n_buckets * 4
        out = bytearray(struct.pack('<II', 2, len(entries)))
        pos = dir_end
        for (_, data), (file_bkt, dir_bkt) in zip(entries, buckets, strict=True):
            out += struct.pack('<5I', pos, file_bkt, dir_bkt, len(data), 0)
            pos += len(data)
        out += struct.pack('<I', len(pool)) + bytes(pool)
        out += struct.pack('<I', n_buckets) + struct.pack(f'<{n_buckets}I', *offsets)
        for _, data in entries:
            out += data
        return bytes(out)

    return build


@pytest.fixture
def make_freq_ark() -> Callable[[Sequence[tuple[str, bytes]]], bytes]:
    r"""
    Build a FreQuency (``ARK\0``) ARK archive.

    Returns
    -------
    collections.abc.Callable[[collections.abc.Sequence[tuple[str, bytes]]], bytes]
        A callable turning ``(path, data)`` pairs into a complete archive.
    """
    def build(entries: Sequence[tuple[str, bytes]]) -> bytes:
        dirs: list[str] = []
        files: list[tuple[str, int]] = []
        for path, _ in entries:
            dname, _, fname = path.rpartition('/')
            if dname not in dirs:
                dirs.append(dname)
            files.append((fname, dirs.index(dname)))
        n_files, n_dirs = len(entries), len(dirs)
        frec_off = 0x100
        drec_off = frec_off + n_files * 24
        pool_off = drec_off + n_dirs * 8
        pool = bytearray()
        name_offs = []
        for fname, _ in files:
            name_offs.append(pool_off + len(pool))
            pool += fname.encode() + b'\0'
        dir_offs = []
        for dname in dirs:
            dir_offs.append(pool_off + len(pool))
            pool += dname.encode() + b'\0'
        data_off = -(-(pool_off + len(pool)) // _BLOCK) * _BLOCK
        out = bytearray(data_off)
        struct.pack_into('<10I', out, 0, 0x004B5241, 2, frec_off, n_files, drec_off, n_dirs,
                         pool_off, n_files + n_dirs, data_off, _BLOCK)
        pos = data_off
        for i, (_, data) in enumerate(entries):
            packed = ((pos % _BLOCK) << 16) | files[i][1]
            struct.pack_into('<6I', out, frec_off + i * 24, 0, name_offs[i], packed, pos // _BLOCK,
                             len(data), len(data))
            pos += len(data)
        for i, off in enumerate(dir_offs):
            struct.pack_into('<2I', out, drec_off + i * 8, 0, off)
        out[pool_off:pool_off + len(pool)] = pool
        for _, data in entries:
            out += data
        return bytes(out)

    return build


@pytest.fixture
def make_hmx_bitmap() -> Callable[..., bytes]:
    """
    Build a console-native HMX bitmap.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking ``width``, ``height``, and a keyword ``bpp`` and returning the bitmap.
    """
    def build(width: int = 4, height: int = 4, *, bpp: int = 8) -> bytes:
        header = bytes((0, bpp, 3, 1)) + struct.pack('<HH', width, height) + bytes(8)
        if bpp == 32:
            return header + bytes(i % 256 for i in range(width * height * 4))
        ncol = 1 << bpp
        palette = b''.join(
            bytes((i & 0xFF, (i * 3) & 0xFF, (i * 7) & 0xFF, 64)) for i in range(ncol))
        n_pixels = width * height if bpp == 8 else (width * height + 1) // 2
        return header + palette + bytes(i % ncol for i in range(n_pixels))

    return build


@pytest.fixture
def make_abm() -> Callable[..., bytes]:
    """
    Build a FreQuency ``ABitmap`` (``.abm``).

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking ``width``, ``height``, and keyword ``bpp`` and ``rle`` flags.
    """
    def build(width: int = 4, height: int = 4, *, bpp: int = 8, rle: bool = False) -> bytes:
        stride = width * bpp // 8
        if bpp == 32:
            pixels = bytes(i % 256 for i in range(width * height * 4))
            return (bytes(5) + bytes(1) + struct.pack('<HHH', width, height, stride) + bytes(4) +
                    struct.pack('<I', len(pixels)) + bytes(4) + pixels)
        target = stride * height
        raw = bytes(i % 256 for i in range(target))
        # Alternate literal runs (control bit set) with single-byte repeat runs.
        region = (b''.join(
            bytes((0x81 if i % 2 else 0x01, byte)) for i, byte in enumerate(raw)) if rle else raw)
        palette = b''.join(
            bytes((i & 0xFF, (i * 5) & 0xFF, (i * 9) & 0xFF, 255)) for i in range(256))
        return (bytes(5) + bytes(1) + struct.pack('<HHH', width, height, stride) + bytes(4) +
                struct.pack('<I', len(region)) + bytes(12) + palette + region)

    return build


@pytest.fixture
def make_dtb() -> Callable[..., bytes]:
    """
    Build a compiled version-2 Harmonix DataArray.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking the root element list and a keyword ``symbols`` sequence.
    """
    def node(items: Sequence[DataArrayNode]) -> bytes:
        n_tag_words = (len(items) + 0xF) >> 4
        tags = [0] * n_tag_words
        payload = bytearray()
        for i, item in enumerate(items):
            if isinstance(item, str):
                tag = 1
                payload += struct.pack('<I', len(item)) + item.encode()
            elif isinstance(item, float):
                tag = 2
                payload += struct.pack('<f', item)
            elif isinstance(item, int):
                tag = 0
                payload += struct.pack('<i', item)
            else:
                tag = 3
                payload += node(item)
            tags[i >> 4] |= tag << ((i & 0xF) * 2)
        head = struct.pack('<HHHI', len(items), 0, 0, 0)
        return head + struct.pack(f'<{n_tag_words}I', *tags) + bytes(payload)

    def build(items: Sequence[DataArrayNode], *, symbols: Sequence[str] = ()) -> bytes:
        out = bytearray(b'\x02' + struct.pack('<I', len(symbols)))
        for symbol in symbols:
            out += _rstr(symbol)
        return bytes(out + node(items))

    return build


@pytest.fixture
def make_milo() -> Callable[..., bytes]:
    """
    Build a Milo/Rnd archive with the given ``(type, name, body)`` objects.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking the objects and keyword ``version``, ``magic``, and ``textures`` values.
    """
    def build(objects: Sequence[tuple[str, str, bytes]],
              *,
              version: int = 10,
              magic: int = 0xCBBEDEAF,
              textures: Sequence[str] = ()) -> bytes:
        directory = bytearray(struct.pack('<II', version, len(objects)))
        for typ, name, _ in objects:
            if version == 6:
                directory += typ.encode() + b'\0' + name.encode() + b'\0\x01'
            else:
                directory += _rstr(typ) + _rstr(name)
        if version == 6:
            directory += _SENTINEL
        if version >= 9:
            directory += struct.pack('<I', len(textures)) + b''.join(_rstr(t) for t in textures)
        for _, _, body in objects:
            directory += body + _SENTINEL
        if version == 6:
            return bytes(directory)
        if magic == 0xCABEDEAF:
            return struct.pack('<4I', magic, 0x14, 1, len(directory)) + bytes(4) + bytes(directory)
        block = (zlib.compress(bytes(directory)) if magic == 0xCBBEDEAF else gzip.compress(
            bytes(directory)))
        return (struct.pack('<4I', magic, 0x14, 1, len(block)) + struct.pack('<I', len(block)) +
                block)

    return build


@pytest.fixture
def make_vag() -> Callable[..., bytes]:
    """
    Build a run of PS2 VAG-ADPCM frames.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking a frame count and keyword ``shift``, ``predictor``, and ``flag`` values.
    """
    def build(frames: int = 2, *, shift: int = 12, predictor: int = 1, flag: int = 1) -> bytes:
        out = bytearray()
        for i in range(frames):
            out += bytes(((predictor << 4) | shift, flag if i == frames - 1 else 0))
            out += bytes((i + n) % 256 for n in range(14))
        return bytes(out)

    return build


@pytest.fixture
def make_samp_bank() -> Callable[[Sequence[tuple[str, int, int]]], bytes]:
    """
    Build a ``SAMP`` sample-bank index from ``(name, rate, offset)`` descriptors.

    Returns
    -------
    collections.abc.Callable[[collections.abc.Sequence[tuple[str, int, int]]], bytes]
        A callable returning the complete ``.bnk`` contents.
    """
    def build(samples: Sequence[tuple[str, int, int]]) -> bytes:
        table = bytearray()
        names = bytearray()
        for name, rate, offset in samples:
            record = bytearray(22)
            struct.pack_into('<IIH', record, 0, 1, 1, rate)
            struct.pack_into('<I', record, 18, offset)
            table += record
            names += _rstr(name)
        return (b'SAMP' + struct.pack('<I',
                                      len(samples) * 22) + bytes(table) + b'SANM' + bytes(8) +
                bytes(names))

    return build


@pytest.fixture
def make_sd_bank() -> Callable[..., bytes]:
    """
    Build a FreQuency SCEI (``sceSdBank``) ``.hd`` header.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking ``(bd_offset, rate, flags)`` VAG records and a keyword ``bd_size``.
    """
    def build(vags: Sequence[tuple[int, int, int]], *, bd_size: int = 4096) -> bytes:
        out = bytearray(b'IECSsreV' + bytes(8))
        out += b'IECSdaeH' + bytes(8) + struct.pack('<I', bd_size) + bytes(12)
        len(out)
        out += b'IECSigaV' + bytes(4) + struct.pack('<I', len(vags))
        record_off = 16 + len(vags) * 4
        out += struct.pack(f'<{len(vags)}I', *(record_off + i * 8 for i in range(len(vags))))
        for bd_offset, rate, flags in vags:
            out += struct.pack('<IHH', bd_offset, rate, flags)
        return bytes(out)

    return build


@pytest.fixture
def make_v14_mesh() -> Callable[..., bytes]:
    """
    Build an Amplitude version-14 ``RndMesh`` body.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking keyword ``material``, ``vertices``, ``faces``, ``handles``,
        ``transform_version``, ``world``, ``owner``, ``draws``, ``showing``, ``weights``, and
        ``bones`` values. ``world`` is twelve floats written as both the local and the world
        transform, and ``bones`` is ``(bone0, bone1, bind0, bind1)``.
    """
    identity = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)

    def build(*,
              material: str = 'ship.mat',
              vertices: int = 3,
              faces: Sequence[tuple[int, int, int]] = ((0, 1, 2),),
              handles: Sequence[str] = (),
              transform_version: int = 0,
              world: Sequence[float] = identity,
              owner: str = '',
              draws: Sequence[str] = (),
              showing: bool = True,
              weights: tuple[float, float] = (0.0, 0.0),
              bones: tuple[str, str, Sequence[float], Sequence[float]] | None = None) -> bytes:
        out = bytearray(struct.pack('<II', 14, transform_version))
        out += struct.pack('<24f', *world, *world)
        out += struct.pack('<I', len(handles))  # Child handle list.
        for handle in handles:
            out += _rstr(handle)
        if transform_version > 0:
            out += bytes(16)  # Constraint and pivot.
        if 2 <= transform_version <= 4:
            out += b'\0'
        out += struct.pack('<I', 0) + bytes((int(showing),)) + struct.pack('<I', len(draws))
        for draw in draws:
            out += _rstr(draw)
        out += struct.pack('<I', 0) + struct.pack('<I', 0)  # RndCollideable.
        out += bytes(8)
        out += _rstr(material) + _rstr('') + _rstr(owner)
        out += bytes(16)  # Bounds.
        out += _rstr('') + bytes(4) + b'\0'
        out += struct.pack('<I', vertices)
        for i in range(vertices):
            vertex = bytearray(56)
            struct.pack_into('<3f', vertex, 0, float(i), float(i) * 2, float(i) * 3)
            struct.pack_into('<2f', vertex, 12, *weights)
            struct.pack_into('<3f', vertex, 20, 0.0, 1.0, 0.0)
            struct.pack_into('<2f', vertex, 48, i / 4, i / 8)
            out += vertex
        out += struct.pack('<I', len(faces))
        for face in faces:
            out += struct.pack('<3H', *face)
        out += struct.pack('<I', 1) + struct.pack('<2H', 0, 1)  # One edge.
        if bones is None:
            out += _rstr('')
        else:
            out += _rstr(bones[0]) + _rstr(bones[1])
            out += struct.pack('<24f', *bones[2], *bones[3])
        return bytes(out)

    return build


@pytest.fixture
def make_v10_mesh() -> Callable[..., bytes]:
    """
    Build a FreQuency version-10 ``RndMesh`` body.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking keyword ``vertices``, ``faces``, and a ``decoys`` flag.
    """
    def build(*,
              vertices: int = 3,
              faces: Sequence[tuple[int, int, int]] = ((0, 1, 2),),
              decoys: bool = False) -> bytes:
        out = bytearray(struct.pack('<II', 10, 0))
        if decoys:
            # A count whose vertex block has non-finite positions, then one whose face count is
            # zero, then one whose face indices are out of range: each is rejected by the scan.
            out += struct.pack('<I', 3) + b'\xff' * (3 * 56) + struct.pack('<I', 1)
            out += struct.pack('<3H', 0, 1, 2) + bytes(2)
            out += struct.pack('<I', 3) + bytes(3 * 56) + struct.pack('<I', 0)
            out += struct.pack('<I', 3) + bytes(3 * 56) + struct.pack('<I', 1)
            out += struct.pack('<3H', 9, 9, 9) + bytes(2)
        out += struct.pack('<I', vertices)
        for i in range(vertices):
            vertex = bytearray(56)
            struct.pack_into('<3f', vertex, 0, float(i), float(i) * 2, float(i) * 3)
            struct.pack_into('<3f', vertex, 12, 1.0, 0.0, 0.0)
            struct.pack_into('<2f', vertex, 28, i / 4, i / 8)
            out += vertex
        out += struct.pack('<I', len(faces))
        for face in faces:
            out += struct.pack('<3H', *face)
        return bytes(out)

    return build


@pytest.fixture
def make_trans_anim() -> Callable[..., bytes]:
    """
    Build an Amplitude revision-3 ``RndTransAnim`` body.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking keyword ``rotations`` and ``translations`` (``(value, frame)`` pairs),
        ``filters`` (``(type, data)`` pairs), ``translation_interpolation``, and ``revision``.
    """
    def build(*,
              rotations: Sequence[tuple[Sequence[float], float]] = (),
              translations: Sequence[tuple[Sequence[float], float]] = (),
              filters: Sequence[tuple[int, bytes]] = (),
              translation_interpolation: int = 0,
              revision: int = 3) -> bytes:
        out = bytearray(struct.pack('<III', revision, 0, len(filters)))
        for kind, data in filters:
            out += struct.pack('<I', kind) + data
        out += struct.pack('<I', 1) + _rstr('other.tnm')  # Animatable list.
        out += struct.pack('<I', 0) + b'\x01' + struct.pack('<I', 0)  # RndDrawable.
        out += _rstr('bone.mesh')
        out += struct.pack('<I', len(rotations))
        for value, frame in rotations:
            out += struct.pack('<5f', *value, frame)
        out += struct.pack('<I', len(translations))
        for value, frame in translations:
            out += struct.pack('<4f', *value, frame)
        out += _rstr('owner.tnm') + struct.pack('<I', translation_interpolation) + b'\x01'
        out += struct.pack('<I', 1) + struct.pack('<4f', 1.0, 1.0, 1.0, 0.0)  # One scale key.
        out += struct.pack('<I', 7) + b'\x00'
        return bytes(out)

    return build


@pytest.fixture
def make_avatar_tree(make_dtb: Callable[..., bytes], make_v14_mesh: Callable[..., bytes],
                     make_trans_anim: Callable[..., bytes]) -> Callable[..., Path]:
    """
    Write a synthetic extracted ``MAIN.ARK`` with a small FreQ avatar.

    The lower body, the torso, the instrument, and both arms are complete; the head scene has no
    meshes, the head gear's scene is missing, and the face gear's choice is not listed.

    Returns
    -------
    collections.abc.Callable[..., pathlib.Path]
        A callable taking the root directory and keyword ``omit`` (part numbers left out of the
        default settings), ``hands`` (``'t'`` and ``'r'`` for the translation and rotation keys of
        each hand, empty for none), ``right_pole``, ``tracks``, ``scenes``, ``config``,
        ``base_rnd``, and ``incomplete`` values. It returns the root.
    """
    def mesh(**kwargs: object) -> bytes:
        kwargs.setdefault('material', '')
        return make_v14_mesh(**kwargs)

    def build(root: Path,
              *,
              omit: Collection[int] = (),
              hands: tuple[str, str] = ('tr', ''),
              right_pole: bool = True,
              tracks: bool = True,
              scenes: bool = True,
              config: str = 'gen/freq2_config.txt.bin',
              base_rnd: bool = True,
              incomplete: bool = False) -> Path:
        maker = root / 'freqmaker'
        base = maker / 'fullfreq'
        base.mkdir(parents=True)
        (base / 'other.bin').write_bytes(b'')
        if tracks:
            anims: dict[str, bytes] = {
                'pelvis':
                    make_trans_anim(
                        rotations=(((0.0, 0.0, 0.0, 1.0), 0.0), ((0.0, 0.0, 0.0, 1.0), 40.0)),
                        translations=(((0.0, 0.0, 10.0), 0.0), ((0.0, 0.0, 11.0), 40.0))),
                'torso':
                    make_trans_anim(rotations=((_turn(0), 0.0), (tuple(
                        -x for x in _turn(170)), 20.0), (_turn(300), 40.0))),
                'instr':
                    make_trans_anim(rotations=((_turn(10), 0.0),)),
                'larm_l':
                    make_trans_anim(translations=(((3.0, 2.0, 1.0), 0.0), ((3.0, 2.0, 2.0), 40.0))),
            }
            if right_pole:
                anims['rarm_l'] = make_trans_anim(translations=(((-3.0, 2.0, 1.0), 0.0),))
            for side, keys in zip(('larm_h', 'rarm_h'), hands, strict=True):
                if keys:
                    anims[side] = make_trans_anim(
                        rotations=((_turn(30), 0.0),) if 'r' in keys else (),
                        translations=(((3.5 if side == 'larm_h' else -3.5, -1.0, 1.0), 0.0),
                                      ((3.6 if side == 'larm_h' else -3.6, -1.0, 1.0),
                                       40.0)) if 't' in keys else ())
            for name, body in anims.items():
                (base / f'fbase_{name}.tnm').write_bytes(body)
        if scenes:
            _scene(
                maker / 'lowerbody' / 'g1', {
                    'pelvis.mesh':
                        mesh(world=_at(0, 0, 10),
                             handles=('torso_joint.mesh', 'missing.mesh'),
                             vertices=0,
                             faces=()),
                    'torso_joint.mesh':
                        mesh(world=_at(0, 0, 12), vertices=0, faces=()),
                    'skin.mesh':
                        mesh(owner='pelvis.mesh',
                             draws=('ghost.mesh', 'hidden.mesh', 'pelvis.mesh', 'rigid.mesh'),
                             weights=(0.5, 0.0),
                             bones=('torso_joint.mesh', '', _at(0, 0, -2), _at(0, 0, 0))),
                    'hidden.mesh':
                        mesh(showing=False),
                    'rigid.mesh':
                        mesh(),
                }, (('View', 'lg1.view'),))
            _scene(maker / 'lowerbody' / 'm1', {'lower.mat': _rstr('legs.tex')},
                   (('Mat', 'gone.mat'),))
            (maker / 'lowerbody' / 'm1' / 'legs.png').write_bytes(b'\x89PNG legs')
            mirrored = (-1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 16.0)
            _scene(
                maker / 'torso' / 'g1', {
                    'torso.mesh':
                        mesh(world=_at(0, 0, 12),
                             handles=('larm_u_joint.mesh', 'rarm_u_joint.mesh', 'instr_joint.mesh',
                                      'head_joint.mesh')),
                    'larm_u_joint.mesh':
                        mesh(world=_at(2, 0, 14), vertices=0, faces=()),
                    'rarm_u_joint.mesh':
                        mesh(world=_at(-2, 0, 14), vertices=0, faces=()),
                    'instr_joint.mesh':
                        mesh(world=_at(0, -2, 13), vertices=0, faces=()),
                    'head_joint.mesh':
                        mesh(world=mirrored, vertices=0, faces=()),
                    'torso.mat':
                        _rstr('nothing.tex'),
                })
            arms: dict[str, bytes] = {}
            for side, sign in (('l', 1.0), ('r', -1.0)):
                arms |= {
                    f'{side}arm_u.mesh':
                        mesh(world=_at(2 * sign, 0, 14), handles=(f'{side}arm_l.mesh',)),
                    f'{side}arm_l.mesh':
                        mesh(world=_at(4 * sign, 0, 14), handles=(f'{side}arm_h.mesh',)),
                    f'{side}arm_h.mesh':
                        mesh(world=_at(6 * sign, 0, 14)),
                    f'{side}arm_skin.mesh':
                        mesh(owner=f'{side}arm_h.mesh',
                             weights=(0.25, 0.25),
                             bones=(f'{side}arm_l.mesh', f'{side}arm_u.mesh', _at(
                                 2 * sign, 0, 0), _at(4 * sign, 0, 0))),
                }
            _scene(maker / 'arms' / 'g1', arms)
            _scene(maker / 'arms' / 'm1', {'arms.mat': _rstr('arms.tex')})
            (maker / 'arms' / 'm1' / 'arms.png').write_bytes(b'\x89PNG arms')
            _scene(maker / 'instr' / 'instr', {
                'instr_00.mesh': mesh(world=_at(0, -2, 13), vertices=0, faces=()),
            })
            _scene(maker / 'head' / 'g1', {})

        def part(number: int,
                 directory: str,
                 choice: list[DataArrayNode],
                 root_name: str,
                 draw_name: str,
                 anims: Sequence[str] = ()) -> list[DataArrayNode]:
            items: list[DataArrayNode] = [
                number, ['rnd_dir', directory], ['types', choice], ['trans_root', root_name]
            ]
            if not (incomplete and number == 2):
                items.append(['draw_root', draw_name])
            if anims:
                items.append(['anims', *anims])
            return items

        settings: list[DataArrayNode] = ['default_settings']
        for number, name in ((7, 'fm_none'), (0, 'fm_a'), (1, 'fm_a'), (2, 'fm_h'), (3, 'fm_t'),
                             (4, 'fm_lb'), (5, 'fm_hg'), (6, 'fm_none')):
            if number not in omit:
                settings.append([number, ['type', name]])
        avatar: list[DataArrayNode] = [
            'avatar',
            [
                'parts',
                part(4, 'FreqMaker/lowerbody', ['fm_lb', 'g1', 'm1'], 'pelvis', 'skin',
                     ('pelvis', 'torso_joint')),
                part(3, 'FreqMaker/torso', ['fm_t', 'g1', ''], 'torso', 'torso', ('torso',)),
                part(7, 'FreqMaker/instr/instr.rnd', ['fm_none', 0], 'instr', 'instr', ('instr',)),
                part(0, 'FreqMaker/arms', ['fm_a', 'g1', 'm1'], 'larm_u', 'larm_skin',
                     ('larm_l', 'larm_h')),
                part(1, 'FreqMaker/arms', ['fm_a', 'g1', 'm1'], 'rarm_u', 'rarm_skin',
                     ('rarm_l', 'rarm_h')),
                part(2, 'FreqMaker/head', ['fm_h', 'g1', ''], 'head', 'head'),
                part(5, 'FreqMaker/head_gear', ['fm_hg', 'g9', ''], 'head_gear', 'head_gear'),
                part(6, 'FreqMaker/face_gear', ['fm_fg', 'g1', ''], 'face_gear', 'face_gear'),
            ],
            settings,
            [
                'anims', ['clip', [3, 0, 40], [0, 10, 60], [4, 0, 0]], ['copy', [3, 0, 40]],
                ['empty'], 'junk', [5], ['bad', [3, 'x', 10]]
            ],
        ]
        if base_rnd:
            avatar.insert(1, ['base_rnd', 'FreqMaker/fullfreq.rnd'])
        (root / 'gen').mkdir(parents=True, exist_ok=True)
        (root / config).write_bytes(make_dtb([['version', 1], ['db', avatar]]))
        return root

    return build
