from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
import json
import struct

import pytest

from dade.incoming.converters.state import cfg_to_json, lev_to_json, sav_to_json, xxx_to_json

if TYPE_CHECKING:
    from pathlib import Path

_MISSION_SIZE = 0x81a30
_LEVEL_SIZE = 0x81a24
_CFG_TOTAL = 10980
_CFG_INPUT_AXIS_OFFSET = 32
_CFG_CAMERA_OFFSET = 256
_CFG_KEYBIND_OFFSET = 868
_CFG_FORCE_FEEDBACK_OFFSET = 1028
_CFG_MISSION_SLOT_OFFSET = 1032
_CFG_HIGH_SCORE_OFFSET = 1582
_CFG_HIGH_SCORE_SIZE = 8932
_CFG_INPUT_STATE_OFFSET = 10514
_CFG_OPTIONS_OFFSET = 10626
_CFG_CHECKSUM_OFFSET = 10646


def _load(path: Path) -> dict[str, Any]:
    return cast('dict[str, Any]', json.loads(path.read_text('utf-8')))


def _build_cfg() -> bytearray:
    data = bytearray(_CFG_TOTAL)
    data[0:24] = b'Wed Apr 15 16:24:58 1998'
    struct.pack_into('<I', data, _CFG_FORCE_FEEDBACK_OFFSET, 1)
    struct.pack_into('<i', data, _CFG_KEYBIND_OFFSET, 0x39)  # page 0, slot 0 = space
    for i, value in enumerate((2, 6, 2, 1, 3)):
        struct.pack_into('<i', data, _CFG_OPTIONS_OFFSET + i * 4, value)
    struct.pack_into('<I', data, _CFG_HIGH_SCORE_OFFSET, 4200)  # table 0, entry 0 score
    data[_CFG_HIGH_SCORE_OFFSET + 4:_CFG_HIGH_SCORE_OFFSET + 7] = b'ACE'
    struct.pack_into('<i', data, _CFG_HIGH_SCORE_OFFSET + 108, 5)  # categoryId
    struct.pack_into('<i', data, _CFG_HIGH_SCORE_OFFSET + 112, 1)  # subIndex
    struct.pack_into('<i', data, _CFG_HIGH_SCORE_OFFSET + 116 + 108, -1)  # terminator record
    checksum = sum(struct.unpack_from(f'<{_CFG_HIGH_SCORE_SIZE}b', data,
                                      _CFG_HIGH_SCORE_OFFSET)) & 0xFFFFFFFF
    struct.pack_into('<I', data, _CFG_CHECKSUM_OFFSET, checksum)
    return data


def test_sav(tmp_path: Path) -> None:
    data = bytearray(_MISSION_SIZE)
    struct.pack_into('<i', data, 0x00000, 605)
    struct.pack_into('<I', data, 0x1d30, 7)
    struct.pack_into('<f', data, 0x81040, 1.5)
    source = tmp_path / 'file0.sav'
    source.write_bytes(data)
    obj = _load(sav_to_json(source, tmp_path))
    assert obj['format'] == 'incoming-save'
    assert obj['fields']['currentMissionId'] == 605
    assert obj['fields']['snapshotCdTrack'] == 7
    assert obj['fields']['cameraPosX'] == pytest.approx(1.5)


def test_sav_unexpected_size(tmp_path: Path) -> None:
    source = tmp_path / 's.sav'
    source.write_bytes(b'ab')
    obj = _load(sav_to_json(source, tmp_path))
    assert obj['size'] == 2
    assert obj['fields'] == {'unknownAt_000000': [0x61, 0x62]}


def test_xxx(tmp_path: Path) -> None:
    data = bytearray(_MISSION_SIZE)
    struct.pack_into('<i', data, 0x00000, 0x69)
    source = tmp_path / 't.xxx'
    source.write_bytes(data)
    obj = _load(xxx_to_json(source, tmp_path))
    assert obj['format'] == 'incoming-debug-snapshot'
    assert obj['fields']['currentMissionId'] == 0x69


def test_lev(tmp_path: Path) -> None:
    data = bytearray(_LEVEL_SIZE)
    # The level region starts at g_dwNetworkMissionFlag (global 0xc), so it sits at file offset 0.
    struct.pack_into('<I', data, 0x00000, 0xABCD)
    source = tmp_path / 'store.lev'
    source.write_bytes(data)
    obj = _load(lev_to_json(source, tmp_path))
    assert obj['format'] == 'incoming-level-snapshot'
    assert obj['fields']['networkMissionFlag'] == 0xABCD
    assert 'currentMissionId' not in obj['fields']


def test_cfg(tmp_path: Path) -> None:
    source = tmp_path / 'incoming.cfg'
    source.write_bytes(_build_cfg())
    blocks = _load(cfg_to_json(source, tmp_path))['blocks']
    assert blocks['buildStamp'] == 'Wed Apr 15 16:24:58 1998'
    assert blocks['checksum']['valid'] is True
    assert blocks['forceFeedbackDevicePresent'] is True
    assert blocks['keybindOffsets'][0][0] == {'directInputScancode': 0x39, 'name': 'Space'}
    assert len(blocks['keybindOffsets']) == 4
    assert blocks['optionValues'] == {
        'comPort': 3,
        'baudRate': 9600,
        'stopBits': '2',
        'parity': 'odd',
        'flowControl': 'dtr',
    }
    assert blocks['highScoreTables'] == [{
        'categoryId': 5,
        'subIndex': 1,
        'entries': [{
            'score': 4200,
            'name': 'ACE'
        }] + [{
            'score': 0,
            'name': ''
        }] * 8,
    }]
    assert len(blocks) == 21


def test_cfg_checksum_invalid(tmp_path: Path) -> None:
    data = _build_cfg()
    struct.pack_into('<I', data, _CFG_CHECKSUM_OFFSET, 0xDEADBEEF)
    source = tmp_path / 'bad.cfg'
    source.write_bytes(data)
    assert _load(cfg_to_json(source, tmp_path))['blocks']['checksum']['valid'] is False


def test_cfg_empty_build_stamp(tmp_path: Path) -> None:
    data = _build_cfg()
    data[0] = 0
    source = tmp_path / 'blank.cfg'
    source.write_bytes(data)
    assert not _load(cfg_to_json(source, tmp_path))['blocks']['buildStamp']


def test_cfg_unexpected_size(tmp_path: Path) -> None:
    source = tmp_path / 'c.cfg'
    source.write_bytes(b'\x00rest')
    obj = _load(cfg_to_json(source, tmp_path))
    assert 'blocks' not in obj
    assert obj['raw'] == [0, 0x72, 0x65, 0x73, 0x74]


def test_cfg_subfield_blocks(tmp_path: Path) -> None:
    data = _build_cfg()
    struct.pack_into('<I', data, _CFG_INPUT_AXIS_OFFSET + 0x10, 100)  # musicVolumeIndex
    struct.pack_into('<I', data, _CFG_INPUT_AXIS_OFFSET + 0xd0, 0x11111111)  # sessionElapsedLo
    struct.pack_into('<I', data, _CFG_INPUT_AXIS_OFFSET + 0xd4, 0x22222222)  # sessionElapsedHi
    struct.pack_into('<f', data, _CFG_CAMERA_OFFSET, 2.0)  # cameraPosX
    data[_CFG_INPUT_STATE_OFFSET + 0x54:_CFG_INPUT_STATE_OFFSET + 0x58] = b'HOST'
    struct.pack_into('<I', data, _CFG_INPUT_STATE_OFFSET + 0x34, 0b101)  # netGameFlags
    data[_CFG_MISSION_SLOT_OFFSET:_CFG_MISSION_SLOT_OFFSET + 6] = b'WINNER'
    struct.pack_into('<B', data, _CFG_MISSION_SLOT_OFFSET + 0x35, 3)
    struct.pack_into('<B', data, _CFG_MISSION_SLOT_OFFSET + 0x36, 7)
    source = tmp_path / 'sub.cfg'
    source.write_bytes(data)
    blocks = _load(cfg_to_json(source, tmp_path))['blocks']
    assert blocks['inputAxisOptions']['musicVolumeIndex'] == 100
    assert blocks['inputAxisOptions']['sessionElapsed'] == 0x2222222211111111
    assert blocks['cameraState']['cameraPosX'] == pytest.approx(2.0)
    assert blocks['inputStateBlock']['netSessionName'] == 'HOST'
    assert blocks['inputStateBlock']['netGameFlags']['deathmatch'] is True  # bit 0
    assert blocks['inputStateBlock']['netGameFlags']['bit1'] is False
    assert blocks['inputStateBlock']['netGameFlags']['bit2'] is True
    assert blocks['joystickAxisBind']['joystickAxisBind'] == [0] * 44
    assert len(blocks['savedMissionSlotTable']) == 10
    assert blocks['savedMissionSlotTable'][0] == {
        'name': 'WINNER',
        'missionSlot': 3,
        'levelValue': 7,
    }


def test_cfg_special_keybinds_and_full_high_score(tmp_path: Path) -> None:
    data = _build_cfg()
    struct.pack_into('<i', data, _CFG_HIGH_SCORE_OFFSET + 116 + 108, 0)  # drop the terminator
    struct.pack_into('<i', data, _CFG_KEYBIND_OFFSET + 4, 0x100)  # special input code
    struct.pack_into('<i', data, _CFG_KEYBIND_OFFSET + 8, 0x77)  # unmapped scancode
    checksum = sum(struct.unpack_from(f'<{_CFG_HIGH_SCORE_SIZE}b', data,
                                      _CFG_HIGH_SCORE_OFFSET)) & 0xFFFFFFFF
    struct.pack_into('<I', data, _CFG_CHECKSUM_OFFSET, checksum)
    source = tmp_path / 'full.cfg'
    source.write_bytes(data)
    blocks = _load(cfg_to_json(source, tmp_path))['blocks']
    page0 = blocks['keybindOffsets'][0]
    assert page0[1] == {'directInputScancode': 0x100, 'name': 'special1'}
    assert page0[2] == {'directInputScancode': 0x77, 'name': 'scancode_0x77'}
    assert len(blocks['highScoreTables']) == _CFG_HIGH_SCORE_SIZE // 116
