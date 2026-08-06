from __future__ import annotations

from destin.common.obj import encode_obj

_VERTICES = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
_FACES = [(0, 1, 2)]


def test_encode_obj_vertices_only() -> None:
    assert encode_obj(_VERTICES, _FACES, header=('o model',)) == ('o model\n'
                                                                  'v 0.000000 0.000000 0.000000\n'
                                                                  'v 1.000000 0.000000 0.000000\n'
                                                                  'v 0.000000 1.000000 0.000000\n'
                                                                  'f 1 2 3\n')


def test_encode_obj_with_texcoords() -> None:
    out = encode_obj(_VERTICES, _FACES, texcoords=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)])
    assert 'vt 0.000000 0.000000\n' in out
    assert out.endswith('f 1/1 2/2 3/3\n')


def test_encode_obj_with_normals_only() -> None:
    out = encode_obj(_VERTICES, _FACES, normals=[(0.0, 0.0, 1.0)] * 3)
    assert 'vn 0.000000 0.000000 1.000000\n' in out
    assert out.endswith('f 1//1 2//2 3//3\n')


def test_encode_obj_with_texcoords_and_normals() -> None:
    out = encode_obj(_VERTICES, _FACES, texcoords=[(0.0, 0.0)] * 3, normals=[(0.0, 0.0, 1.0)] * 3)
    assert out.endswith('f 1/1/1 2/2/2 3/3/3\n')


def test_encode_obj_normals_before_texcoords() -> None:
    out = encode_obj(_VERTICES,
                     _FACES,
                     texcoords=[(0.0, 0.0)] * 3,
                     normals=[(0.0, 0.0, 1.0)] * 3,
                     normals_before_texcoords=True)
    assert out.index('vn ') < out.index('vt ')


def test_encode_obj_material_and_base_zero() -> None:
    out = encode_obj(_VERTICES, [(1, 2, 3)], material='steel', base=0)
    assert 'usemtl steel\n' in out
    assert out.endswith('f 1 2 3\n')


def test_encode_obj_custom_formats() -> None:
    out = encode_obj([(1.5, 2.25, 3.0)], [(0, 0, 0)],
                     texcoords=[(0.5, 0.25)],
                     coordinate_format='{:g}',
                     texcoord_format='{:.2f}')
    assert 'v 1.5 2.25 3\n' in out
    assert 'vt 0.50 0.25\n' in out
