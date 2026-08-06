from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from destin.amplitude import mesh
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path


def _rstr(text: str) -> bytes:
    return struct.pack('<I', len(text)) + text.encode()


def _mat(names: Sequence[str] = ('ship_tex.bmp',)) -> bytes:
    # A material blob mixing an implausible length, a non-printable run, a name with no texture
    # extension, and the real texture names.
    return (struct.pack('<I', 0) + struct.pack('<I', 4) + b'\x01\x02\x03\x04' +
            _rstr('not_a_texture') + b''.join(_rstr(name) for name in names))


def _obj_with_material(material: str = 'ship.mat') -> str:
    return f'# Harmonix RndMesh -> OBJ\n# material: {material}\nv 0 0 0\n'


def test_mesh_to_obj_v14(make_v14_mesh: Callable[..., bytes]) -> None:
    obj = mesh.mesh_to_obj(make_v14_mesh(vertices=3, faces=((0, 1, 2), (2, 1, 0))))
    assert obj is not None
    lines = obj.splitlines()
    assert lines[0] == '# Harmonix RndMesh -> OBJ'
    assert lines[1] == '# material: ship.mat'
    assert obj.count('\nv ') == 3
    assert obj.count('\nvt ') == 3
    assert obj.count('\nvn ') == 3
    assert lines[-1] == 'f 3/3/3 2/2/2 1/1/1'


def test_mesh_to_obj_v14_without_material(make_v14_mesh: Callable[..., bytes]) -> None:
    obj = mesh.mesh_to_obj(make_v14_mesh(material=''))
    assert obj is not None
    assert '# material:' not in obj


def test_mesh_to_obj_v10(make_v10_mesh: Callable[..., bytes]) -> None:
    obj = mesh.mesh_to_obj(make_v10_mesh())
    assert obj is not None
    assert obj.count('\nv ') == 3
    assert '# material:' not in obj


def test_mesh_to_obj_v10_skips_decoy_vectors(make_v10_mesh: Callable[..., bytes]) -> None:
    # Non-finite positions, a zero face count, and out-of-range indices are all rejected.
    obj = mesh.mesh_to_obj(make_v10_mesh(decoys=True))
    assert obj is not None
    assert obj.count('\nv ') == 3


@pytest.mark.parametrize('transform_version', [0, 1, 3])
def test_mesh_to_obj_v14_transform_versions(make_v14_mesh: Callable[..., bytes],
                                            transform_version: int) -> None:
    # Transform versions above zero carry a constraint block, and 2..4 an extra flag byte.
    data = make_v14_mesh(handles=('parent.tnm', 'child.mesh'), transform_version=transform_version)
    obj = mesh.mesh_to_obj(data)
    assert obj is not None
    assert obj.count('\nv ') == 3


@pytest.mark.parametrize('data', [b'', b'\x00' * 8, struct.pack('<I', 14) + bytes(120)])
def test_mesh_to_obj_rejects_unparseable(data: bytes) -> None:
    assert mesh.mesh_to_obj(data) is None


def test_mesh_to_obj_v10_without_geometry() -> None:
    assert mesh.mesh_to_obj(struct.pack('<II', 10, 0) + bytes(64)) is None


def test_mesh_to_obj_rejects_empty_geometry(make_v14_mesh: Callable[..., bytes]) -> None:
    assert mesh.mesh_to_obj(make_v14_mesh(vertices=0, faces=())) is None


def test_mesh_to_obj_rejects_truncated_face_count(make_v14_mesh: Callable[..., bytes]) -> None:
    assert mesh.mesh_to_obj(make_v14_mesh(faces=())[:-2]) is None


def test_mesh_to_obj_rejects_face_table_past_end(make_v14_mesh: Callable[..., bytes]) -> None:
    data = bytearray(make_v14_mesh())
    struct.pack_into('<I', data, len(data) - 10, 1000)  # A face count the body cannot hold.
    assert mesh.mesh_to_obj(bytes(data)) is None


def test_mesh_to_obj_rejects_out_of_range_faces(make_v14_mesh: Callable[..., bytes]) -> None:
    assert mesh.mesh_to_obj(make_v14_mesh(faces=((0, 1, 9),))) is None


def test_convert_writes_obj(make_v14_mesh: Callable[..., bytes], tmp_path: Path) -> None:
    source = tmp_path / 'ship.mesh'
    source.write_bytes(make_v14_mesh())
    out = mesh.convert(source)
    assert out == tmp_path / 'ship.obj'
    assert source.exists()  # The lossless object is kept.
    assert out.read_text(encoding='utf-8').startswith('# Harmonix RndMesh -> OBJ')


def test_convert_returns_none_on_junk(tmp_path: Path) -> None:
    source = tmp_path / 'ship.mesh'
    source.write_bytes(b'JUNK' + bytes(64))
    assert mesh.convert(source) is None


def test_link_materials(tmp_path: Path) -> None:
    (tmp_path / 'scene').mkdir()
    (tmp_path / 'scene' / 'ship.obj').write_text(_obj_with_material(), encoding='utf-8')
    (tmp_path / 'scene' / 'ship.mat').write_bytes(_mat())
    (tmp_path / 'pool').mkdir()
    (tmp_path / 'pool' / 'ship_tex.png').write_bytes(b'png-bytes')
    assert mesh.link_materials(tmp_path) == 1
    assert (tmp_path / 'scene' / 'ship.png').read_bytes() == b'png-bytes'
    mtl = (tmp_path / 'scene' / 'ship.mtl').read_text(encoding='utf-8')
    assert mtl == 'newmtl ship\nKd 1 1 1\nmap_Kd ship.png\n'
    obj = (tmp_path / 'scene' / 'ship.obj').read_text(encoding='utf-8')
    assert obj.splitlines()[2:4] == ['mtllib ship.mtl', 'usemtl ship']


def test_link_materials_prefers_bmp_over_tex(tmp_path: Path) -> None:
    (tmp_path / 'ship.obj').write_text(_obj_with_material(), encoding='utf-8')
    (tmp_path / 'ship.mat').write_bytes(_mat(('only.tex', 'winner.bmp')))
    (tmp_path / 'only.png').write_bytes(b'tex')
    (tmp_path / 'winner.png').write_bytes(b'bmp')
    assert mesh.link_materials(tmp_path) == 1
    assert (tmp_path / 'ship.png').read_bytes() == b'bmp'


def test_link_materials_skips_self_copy(tmp_path: Path) -> None:
    # The resolved texture already sits where the material link needs it.
    (tmp_path / 'ship.obj').write_text(_obj_with_material(), encoding='utf-8')
    (tmp_path / 'ship.mat').write_bytes(_mat(('ship.bmp',)))
    (tmp_path / 'ship.png').write_bytes(b'already-here')
    assert mesh.link_materials(tmp_path) == 1
    assert (tmp_path / 'ship.png').read_bytes() == b'already-here'


def test_link_materials_without_material_comment(tmp_path: Path) -> None:
    (tmp_path / 'ship.obj').write_text('# Harmonix RndMesh -> OBJ\nv 0 0 0\n', encoding='utf-8')
    assert mesh.link_materials(tmp_path) == 0


def test_link_materials_without_material_file(tmp_path: Path) -> None:
    (tmp_path / 'ship.obj').write_text(_obj_with_material('missing.mat'), encoding='utf-8')
    assert mesh.link_materials(tmp_path) == 0


def test_link_materials_without_texture_png(tmp_path: Path) -> None:
    (tmp_path / 'ship.obj').write_text(_obj_with_material(), encoding='utf-8')
    (tmp_path / 'ship.mat').write_bytes(_mat())
    assert mesh.link_materials(tmp_path) == 0
    assert not (tmp_path / 'ship.mtl').exists()


def test_link_materials_without_any_texture_name(tmp_path: Path) -> None:
    (tmp_path / 'ship.obj').write_text(_obj_with_material(), encoding='utf-8')
    (tmp_path / 'ship.mat').write_bytes(_mat(()))
    assert mesh.link_materials(tmp_path) == 0
