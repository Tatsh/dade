"""Tests for extracting Mario Kart World files."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import json
import struct
import subprocess as sp

import pytest
import zstandard

from dade.mkw.extract import extract

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def _source(tmp_path: Path) -> Path:
    source = tmp_path / 'source'
    (source / 'Model').mkdir(parents=True)
    (source / 'Tex').mkdir()
    return source


def _bars(offsets: tuple[int, ...], *, size: int = 128) -> bytes:
    archive = bytearray(size)
    archive[:4] = b'BARS'
    struct.pack_into('<I', archive, 12, len(offsets))
    for index, offset in enumerate(offsets):
        struct.pack_into('<I', archive, 16 + 4 * len(offsets) + 8 * index + 4, offset)
    return bytes(archive)


def test_extract_skips_unconverted_source_files(tmp_path: Path) -> None:
    source = _source(tmp_path)
    (source / 'Model/sample.extm').write_bytes(b'original')
    output = tmp_path / 'output'
    assert extract(source, output) == {
        'animations': 0,
        'audio': 0,
        'fonts': 0,
        'models': 0,
        'textures': 0,
        'unsupported': 0
    }
    assert not (output / 'raw').exists()


@pytest.mark.parametrize('layout', ['romfs', 'updates'])
def test_extract_finds_nested_romfs(tmp_path: Path, layout: str) -> None:
    root = tmp_path / 'source'
    romfs = root / 'romfs' if layout == 'romfs' else root / 'updates/1/romfs'
    (romfs / 'Model').mkdir(parents=True)
    (romfs / 'Tex').mkdir()
    (romfs / 'Tex/invalid.bntx').write_bytes(b'invalid')
    assert extract(root, tmp_path / 'output')['unsupported'] == 1


def test_extract_skips_incomplete_newer_update(tmp_path: Path) -> None:
    root = tmp_path / 'source'
    older = root / 'updates/1/romfs'
    (older / 'Model').mkdir(parents=True)
    (older / 'Tex').mkdir()
    (older / 'Tex/invalid.bntx').write_bytes(b'invalid')
    (root / 'updates/2/romfs/Model').mkdir(parents=True)
    assert extract(root, tmp_path / 'output')['unsupported'] == 1


def test_extract_rejects_missing_romfs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='No Mario Kart World romfs'):
        extract(tmp_path, tmp_path / 'output')


def test_extract_decompresses_zstandard_and_converts_multiple_textures(
        tmp_path: Path, mocker: MockerFixture) -> None:
    source = _source(tmp_path)
    (source / 'Tex/bundle.bntx.zs').write_bytes(zstandard.ZstdCompressor().compress(b'BNTX'))
    count = mocker.patch('dade.mkw.extract.texture_count', return_value=2)
    names = mocker.patch('dade.mkw.extract.texture_name',
                         side_effect=lambda _data, index: ('path/one', 'path\\two')[index])
    decode = mocker.patch('dade.mkw.extract.decode_texture',
                          side_effect=lambda _data, index: bytes((index + 1,)))
    output = tmp_path / 'output'
    assert extract(source, output)['textures'] == 2
    assert count.call_args.args == (b'BNTX',)
    assert (output / 'textures/Tex/bundle/00000-path_one.png').read_bytes() == b'\x01'
    assert (output / 'textures/Tex/bundle/00001-path_two.png').read_bytes() == b'\x02'
    assert extract(source, output)['textures'] == 2
    assert decode.call_count == 2
    count.return_value = 1
    assert extract(source, output, force=True)['textures'] == 1
    assert (output / 'textures/Tex/bundle.png').read_bytes() == b'\x01'
    assert names.call_count == 4


def test_extract_records_unsupported_texture_and_model(tmp_path: Path) -> None:
    source = _source(tmp_path)
    (source / 'Tex/invalid.bntx').write_bytes(b'invalid')
    (source / 'Model/invalid.bfres').write_bytes(b'invalid')
    counts = extract(source, tmp_path / 'output')
    assert counts['unsupported'] == 2
    assert counts['models'] == counts['textures'] == 0


def test_extract_writes_each_model_detail_level(tmp_path: Path, mocker: MockerFixture) -> None:
    source = _source(tmp_path)
    piece = source / 'Model/Piece_test.bfres.zs'
    piece.write_bytes(zstandard.ZstdCompressor().compress(b'BFRES'))
    mocker.patch('dade.mkw.extract.read_animations', return_value=[])
    mocker.patch('dade.mkw.extract.model_lod_count', return_value=3)
    decode = mocker.patch('dade.mkw.extract.decode_model',
                          side_effect=(b'lod0', None, b'lod2', b'lod1', b'new0', b'new1', b'new2'))
    output = tmp_path / 'output'
    assert extract(source, output)['models'] == 2
    target = output / 'models/Model/Piece_test.glb'
    assert target.read_bytes() == b'lod0'
    assert not (output / 'models/Model/Piece_test.lod1.glb').exists()
    assert (output / 'models/Model/Piece_test.lod2.glb').read_bytes() == b'lod2'
    assert decode.call_args.kwargs['external_images'] == output / 'textures/Tex'
    assert extract(source, output)['models'] == 3
    assert (output / 'models/Model/Piece_test.lod1.glb').read_bytes() == b'lod1'
    assert extract(source, output, force=True)['models'] == 3
    assert target.read_bytes() == b'new0'
    assert (output / 'models/Model/Piece_test.lod2.glb').read_bytes() == b'new2'
    assert decode.call_count == 7


def test_extract_model_without_meshes_or_external_images(tmp_path: Path,
                                                         mocker: MockerFixture) -> None:
    source = _source(tmp_path)
    (source / 'Model/empty.bfres').write_bytes(b'BFRES')
    mocker.patch('dade.mkw.extract.read_animations', return_value=[])
    mocker.patch('dade.mkw.extract.model_lod_count', return_value=1)
    decode = mocker.patch('dade.mkw.extract.decode_model', return_value=None)
    assert extract(source, tmp_path / 'output')['models'] == 0
    assert decode.call_args.kwargs['external_images'] is None


@pytest.mark.parametrize('archive', [b'', _bars((64,))[:20], _bars((20,)), _bars((200,))])
def test_extract_rejects_invalid_bars(tmp_path: Path, archive: bytes) -> None:
    source = _source(tmp_path)
    (source / 'sample.bars').write_bytes(archive)
    assert extract(source, tmp_path / 'output')['unsupported'] == 1


def test_extract_converts_embedded_bars_audio(tmp_path: Path, mocker: MockerFixture) -> None:
    source = _source(tmp_path)
    archive = bytearray(_bars((64,)))
    archive[64:68] = b'BWAV'
    (source / 'sample.bars.zs').write_bytes(zstandard.ZstdCompressor().compress(archive))
    mocker.patch('dade.mkw.extract.locate_tool', return_value=Path('vgmstream-cli'))
    convert = mocker.patch('dade.mkw.extract.sp.run')
    output = tmp_path / 'output'
    assert extract(source, output)['audio'] == 1
    assert not list(output.glob('.mkw-*'))
    assert not (output / 'raw').exists()
    convert.assert_called_once()


def test_extract_counts_missing_non_audio_and_failed_bars_assets(tmp_path: Path,
                                                                 mocker: MockerFixture) -> None:
    source = _source(tmp_path)
    archive = bytearray(_bars((64, 80, 96, 0xFFFFFFFF)))
    archive[64:68] = b'BWAV'
    archive[80:84] = b'NONE'
    archive[96:100] = b'BWAV'
    (source / 'sample.bars').write_bytes(archive)
    mocker.patch('dade.mkw.extract.locate_tool', return_value=Path('vgmstream-cli'))
    convert = mocker.patch('dade.mkw.extract.sp.run',
                           side_effect=(None, sp.CalledProcessError(1, 'vgmstream-cli')))
    output = tmp_path / 'output'
    assert extract(source, output) == {
        'animations': 0,
        'audio': 1,
        'fonts': 0,
        'models': 0,
        'textures': 0,
        'unsupported': 2
    }
    wav = output / 'audio/sample/00000.wav'
    wav.write_bytes(b'RIFF')
    convert.reset_mock()
    convert.side_effect = sp.CalledProcessError(1, 'vgmstream-cli')
    assert extract(source, output)['audio'] == 1
    assert convert.call_count == 1


def test_extract_collects_bgm_streams(tmp_path: Path, mocker: MockerFixture) -> None:
    source = _source(tmp_path)
    stream = source / 'Sound/Resource/Stream'
    stream.mkdir(parents=True)
    (stream / 'BGM_Stage_Test.bwav').write_bytes(b'BWAV')
    mocker.patch('dade.mkw.extract.locate_tool', side_effect=Path)
    convert = mocker.patch(
        'dade.mkw.extract.sp.run',
        side_effect=lambda command, **_: Path(command[3]
                                              if command[0] == 'vgmstream-cli' else command[-1]).
        write_bytes(b'RIFF' if command[0] == 'vgmstream-cli' else b'fLaC'))
    output = tmp_path / 'output'
    assert extract(source, output)['audio'] == 1
    assert (output / 'soundtrack/BGM_Stage_Test.flac').read_bytes() == b'fLaC'
    assert not (output / 'audio/Sound/Resource/Stream/BGM_Stage_Test.wav').exists()
    assert convert.call_count == 2


def test_extract_migrates_existing_bgm_wav(tmp_path: Path, mocker: MockerFixture) -> None:
    source = _source(tmp_path)
    stream = source / 'Sound/Resource/Stream'
    stream.mkdir(parents=True)
    (stream / 'BGM_Test.bwav').write_bytes(b'BWAV')
    output = tmp_path / 'output'
    wav = output / 'audio/Sound/Resource/Stream/BGM_Test.wav'
    wav.parent.mkdir(parents=True)
    wav.write_bytes(b'RIFF')
    old_song = output / 'soundtrack/BGM_Test.wav'
    old_song.parent.mkdir()
    old_song.write_bytes(b'RIFF')
    mocker.patch('dade.mkw.extract.locate_tool', side_effect=Path)
    run = mocker.patch('dade.mkw.extract.sp.run',
                       side_effect=lambda command, **_: Path(command[-1]).write_bytes(b'fLaC'))
    assert extract(source, output)['audio'] == 1
    assert (output / 'soundtrack/BGM_Test.flac').read_bytes() == b'fLaC'
    assert not wav.exists()
    assert not old_song.exists()
    assert extract(source, output)['audio'] == 1
    assert run.call_count == 1


def test_extract_forces_compressed_bgm_conversion(tmp_path: Path, mocker: MockerFixture) -> None:
    source = _source(tmp_path)
    stream = source / 'Sound/Resource/Stream'
    stream.mkdir(parents=True)
    (stream / 'BGM_Test.bwav.zs').write_bytes(zstandard.ZstdCompressor().compress(b'BWAV'))
    mocker.patch('dade.mkw.extract.locate_tool', side_effect=Path)
    observed: list[bytes] = []

    def convert(command: tuple[str, ...], **_: object) -> None:
        if command[0] == 'vgmstream-cli':
            observed.append(Path(command[-1]).read_bytes())
            Path(command[3]).write_bytes(b'RIFF')
        else:
            Path(command[-1]).write_bytes(b'fLaC')

    run = mocker.patch('dade.mkw.extract.sp.run', side_effect=convert)
    output = tmp_path / 'output'
    assert extract(source, output, force=True)['audio'] == 1
    assert observed == [b'BWAV']
    assert (output / 'soundtrack/BGM_Test.flac').read_bytes() == b'fLaC'
    assert run.call_count == 2
    assert not list(output.glob('.mkw-*'))


@pytest.mark.parametrize('compressed', [False, True])
def test_extract_converts_effects_and_skips_existing(tmp_path: Path, mocker: MockerFixture, *,
                                                     compressed: bool) -> None:
    source = _source(tmp_path)
    audio = source / ('Sound/effect.bwav.zs' if compressed else 'Sound/effect.bwav')
    audio.parent.mkdir()
    audio.write_bytes(zstandard.ZstdCompressor().compress(b'BWAV') if compressed else b'BWAV')
    mocker.patch('dade.mkw.extract.locate_tool', side_effect=Path)

    def convert(command: tuple[str, ...], **_: object) -> None:
        assert Path(command[-1]).read_bytes() == b'BWAV'
        Path(command[3]).write_bytes(b'RIFF')

    run = mocker.patch('dade.mkw.extract.sp.run', side_effect=convert)
    output = tmp_path / 'output'
    assert extract(source, output)['audio'] == 1
    assert (output / 'audio/Sound/effect.wav').read_bytes() == b'RIFF'
    assert extract(source, output)['audio'] == 1
    assert run.call_count == 1
    assert extract(source, output, force=True)['audio'] == 1
    assert run.call_count == 2


def test_extract_pattern_and_limit_select_only_requested_assets(tmp_path: Path,
                                                                mocker: MockerFixture) -> None:
    source = _source(tmp_path)
    (source / 'Model/A.bfres').write_bytes(b'A')
    (source / 'Model/B.bfres').write_bytes(b'B')
    mocker.patch('dade.mkw.extract.read_animations', return_value=[])
    mocker.patch('dade.mkw.extract.model_lod_count', return_value=1)
    decode = mocker.patch('dade.mkw.extract.decode_model', return_value=b'GLB')
    output = tmp_path / 'output'
    assert extract(source, output, limit=1, pattern='Model/*.bfres')['models'] == 1
    assert decode.call_count == 1
    assert decode.call_args.kwargs['external_images'] is None


def _font(font: bytes) -> bytes:
    key = b'\x21\x43\x65\x87'
    plain = b'\x7f\x9a\x02\x18' + len(font).to_bytes(4, 'big') + font
    return bytes(value ^ key[index % 4] for index, value in enumerate(plain))


def test_extract_decrypts_fonts(tmp_path: Path) -> None:
    source = _source(tmp_path)
    (source / 'Font').mkdir()
    (source / 'Font/Title.bfttf.zs').write_bytes(zstandard.ZstdCompressor().compress(
        _font(b'OTTOcff')))
    (source / 'Font/Body.bfotf').write_bytes(_font(b'true glyf'))
    (source / 'Font/Broken.bfttf').write_bytes(b'short')
    output = tmp_path / 'output'
    counts = extract(source, output)
    assert counts['fonts'] == 2
    assert counts['unsupported'] == 1
    title = output / 'fonts/Title.otf'
    assert title.read_bytes() == b'OTTOcff'
    assert (output / 'fonts/Body.ttf').read_bytes() == b'true glyf'
    title.write_bytes(b'kept')
    assert extract(source, output)['fonts'] == 2
    assert title.read_bytes() == b'kept'
    assert extract(source, output, force=True)['fonts'] == 2
    assert title.read_bytes() == b'OTTOcff'


def test_extract_writes_skeletal_animations(tmp_path: Path, mocker: MockerFixture) -> None:
    source = _source(tmp_path)
    (source / 'Model/Kart.bfres').write_bytes(b'FRES clips')
    (source / 'Model/Static.bfres').write_bytes(b'FRES')
    read = mocker.patch('dade.mkw.extract.read_animations',
                        side_effect=lambda data: [{
                            'name': 'Run'
                        }] if data == b'FRES clips' else [])
    mocker.patch('dade.mkw.extract.read_material_animations', return_value=[])
    mocker.patch('dade.mkw.extract.model_lod_count', return_value=0)
    output = tmp_path / 'output'
    assert extract(source, output)['animations'] == 1
    target = output / 'animations/Model/Kart.json'
    text = target.read_text(encoding='utf-8')
    assert json.loads(text) == {'clips': [{'name': 'Run'}], 'material_clips': []}
    assert text.endswith('}\n')
    assert not (output / 'animations/Model/Static.json').exists()
    assert read.call_count == 2
    target.write_text('kept', encoding='utf-8')
    assert extract(source, output)['animations'] == 1
    assert target.read_text(encoding='utf-8') == 'kept'
    assert read.call_count == 3
    assert extract(source, output, force=True)['animations'] == 1
    assert target.read_text(encoding='utf-8').startswith('{')
    assert read.call_count == 5


def _clips(data: bytes) -> list[dict[str, str]]:
    match data:
        case b'bad':
            message = 'Invalid BFRES archive.'
            raise ValueError(message)
        case b'idle' | b'run':
            return [{'name': data.decode().title()}]
        case _:
            return []


def test_extract_embeds_matching_animation_archives(tmp_path: Path, mocker: MockerFixture,
                                                    caplog: pytest.LogCaptureFixture) -> None:
    source = _source(tmp_path)
    model = source / 'Model'
    files = {
        'DriverA_Luigi_Run.anim.bfres': b'run',
        'DriverA_Mario_Bad.anim.bfres': b'bad',
        'Driver_Mario.Body.bfres': b'body',
        'Driver_Mario.Head.bfres': b'head',
        'Driver_Mario.anim.bfres': b'idle',
        'Kart.Body.bfres': b'kart',
        'Kart.anim.bfres': b'idle'
    }
    for name, content in files.items():
        (model / name).write_bytes(content)
    (model / 'DriverA_Mario_Run.anim.bfres.zs').write_bytes(
        zstandard.ZstdCompressor().compress(b'run'))
    read = mocker.patch('dade.mkw.extract.read_animations', side_effect=_clips)
    mocker.patch('dade.mkw.extract.read_material_animations', return_value=[])
    mocker.patch('dade.mkw.extract.model_lod_count', return_value=2)
    decode = mocker.patch('dade.mkw.extract.decode_model', return_value=b'GLB')
    extract(source, tmp_path / 'output')
    passed = {
        (call.args[1], call.kwargs['lod']): list(call.kwargs['animations'])
        for call in decode.call_args_list
    }
    driver = [('DriverA_Mario_Run:Run', {'name': 'Run'}), ('Driver_Mario:Idle', {'name': 'Idle'})]
    assert passed == {
        ('DriverA_Luigi_Run.anim', 0): [],
        ('DriverA_Luigi_Run.anim', 1): [],
        ('DriverA_Mario_Bad.anim', 0): [],
        ('DriverA_Mario_Bad.anim', 1): [],
        ('DriverA_Mario_Run.anim', 0): [],
        ('DriverA_Mario_Run.anim', 1): [],
        ('Driver_Mario.Body', 0): driver,
        ('Driver_Mario.Body', 1): [],
        ('Driver_Mario.Head', 0): driver,
        ('Driver_Mario.Head', 1): [],
        ('Driver_Mario.anim', 0): [],
        ('Driver_Mario.anim', 1): [],
        ('Kart.Body', 0): [('Kart:Idle', {
            'name': 'Idle'
        })],
        ('Kart.Body', 1): [],
        ('Kart.anim', 0): [],
        ('Kart.anim', 1): []
    }
    assert [call.args[0] for call in read.call_args_list].count(b'run') == 3
    assert [call.args[0] for call in read.call_args_list].count(b'bad') == 2
    assert sum('DriverA_Mario_Bad' in record.getMessage()
               and 'Cannot decode the animations' in record.getMessage()
               for record in caplog.records) == 2
