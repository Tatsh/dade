"""
State converters: Incoming save, config, and snapshot files to JSON.

The schemas are reverse-engineered from the PC executable (``incoming.exe``). The configuration file
(``.cfg``) is a concatenation of fixed-size blocks described by the game's internal save-descriptor
table, so it is split into its named blocks, each decoded into a typed value (text, numeric arrays,
and the verified checksum). The snapshot files (``.sav``, ``.xxx``, and ``.lev``) are
``memcpy``-style images of a contiguous region of game globals, so a field table mapping each
global's offset, type, and name is applied. Every byte is decoded into a typed value: bytes not
covered by a known field
(gaps, large pools, and run-time pointer tables) are emitted as ``unknownAt_<offset>`` arrays of
32-bit words (or raw byte values when unaligned). Nothing is left as an opaque base64 blob.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
import json
import logging
import operator
import struct

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

__all__ = ('cfg_to_json', 'lev_to_json', 'sav_to_json', 'xxx_to_json')

log = logging.getLogger(__name__)

_FMT_SIZE = {'b': 1, 'B': 1, 'h': 2, 'H': 2, 'i': 4, 'I': 4, 'f': 4}

# ``incoming.cfg`` (SaveGameConfigFile @ 0x46eaa0) is these blocks concatenated in order, described
# by the in-game g_pConfigSaveDescriptorTable. Each entry is (name, kind, count) where kind is a
# struct character or 'str' (a NUL-terminated text buffer); the total size is fixed.
_CFG_BLOCKS: tuple[tuple[str, str, int], ...] = (
    ('buildStamp', 'str', 32),
    ('inputAxisOptions', 'B', 224),
    ('cameraState', 'f', 57),
    ('joystickAxisBind', 'i', 96),
    ('keybindOffsets', 'i', 40),
    ('forceFeedbackDevicePresent', 'I', 1),
    ('savedMissionSlotTable', 'B', 550),
    ('highScoreTables', 'I', 2233),
    ('inputStateBlock', 'i', 28),
    ('optionValues', 'i', 5),
    ('checksum', 'I', 1),
    ('stringBuffer0', 'str', 33),
    ('stringBuffer1', 'str', 33),
    ('stringBuffer2', 'str', 33),
    ('stringBuffer3', 'str', 33),
    ('stringBuffer4', 'str', 33),
    ('stringBuffer5', 'str', 33),
    ('stringBuffer6', 'str', 33),
    ('stringBuffer7', 'str', 33),
    ('stringBuffer8', 'str', 33),
    ('stringBuffer9', 'str', 33),
)


def _cfg_block_size(kind: str, count: int) -> int:
    if kind == 'str':
        return count
    if kind in _FMT_SIZE:
        return _FMT_SIZE[kind] * count
    return _STRUCT_TYPES[kind][0] * count


_CFG_TOTAL = sum(_cfg_block_size(kind, count) for _, kind, count in _CFG_BLOCKS)
_CFG_CHECKSUM_BLOCK = 'highScoreTables'

# The options block is the serial/modem multiplayer connection settings (from
# UpdateOptionsMenuScreen @ 0x452148): COM port, baud rate, stop bits, parity, and flow control.
_CFG_BAUD_RATES = (110, 300, 600, 1200, 2400, 4800, 9600, 14400, 19200, 38400, 56000, 57600, 115200,
                   128000, 256000)
_CFG_STOP_BITS = ('1', '1.5', '2')
_CFG_PARITY = ('none', 'odd', 'even', 'mark')
_CFG_FLOW_CONTROL = ('none', 'xon/xoff', 'rts', 'dtr', 'rts/dtr')

# The keybind block is 4 control-config pages of 10 action slots; each slot holds a DirectInput
# keyboard scancode (below the special base), or a special input code (at or above it). A 0 slot is
# unbound (empty name).
_KEYBIND_PAGES = 4
_KEYBIND_SLOTS_PER_PAGE = 10
_KEYBIND_SPECIAL_BASE = 0x100

# Reverse-engineered bit names for the bitfield (``*Flags``) globals, keyed by cleaned field name
# then bit index. Bits without a known meaning fall back to ``bit<n>``. Derived from incoming.exe.
_NET_GAME_FLAG_BITS = {0: 'deathmatch', 5: 'teamMode', 6: 'timedMission'}
_FLAG_BIT_NAMES: dict[str, dict[int, str]] = {
    'netGameFlags': _NET_GAME_FLAG_BITS,
    'savedNetGameFlags': _NET_GAME_FLAG_BITS,
    'gameSessionFlags': {
        0: 'splitScreen'
    },
    'netControlFlags': {
        0: 'netPlayActive'
    },
    'worldStateFlags': {
        0: 'worldReady'
    },
    'userCameraFlags': {
        1: 'spectator'
    },
    'hudOverlayFlags': {
        1: 'inGameOverlay'
    },
    'globalStateFlags': {
        0: 'scoreboardLayout',
        2: 'replayCameraActive',
        3: 'replayTrackPlayer',
    },
}

# Each high-score table record is 29 dwords (116 bytes): 9 entries of {score:u32, name:char[8]} then
# a category id and a 1-based sub-index. A record whose category id is -1 terminates the arena.
_HIGH_SCORE_RECORD_SIZE = 116
_HIGH_SCORE_ENTRY_SIZE = 12
_HIGH_SCORE_ENTRY_COUNT = 9

# The saved-mission-slot block (from UpdateMissionRestartHighScoreScreen @ 0x46af00) is 10 records
# of 55 bytes: a name string (empty slots hold a dashes string), then a mission-slot byte and a
# level-value byte.
_MISSION_SLOT_SIZE = 0x37
_MISSION_SLOT_COUNT = 10

# DirectInput keyboard scancodes (DIK_*, i.e. PS/2 set 1) to W3C ``KeyboardEvent.code`` values,
# used to make the keybind block readable.
_DIK_KEY_NAMES = {
    0x01: 'Escape',
    0x02: 'Digit1',
    0x03: 'Digit2',
    0x04: 'Digit3',
    0x05: 'Digit4',
    0x06: 'Digit5',
    0x07: 'Digit6',
    0x08: 'Digit7',
    0x09: 'Digit8',
    0x0a: 'Digit9',
    0x0b: 'Digit0',
    0x0c: 'Minus',
    0x0d: 'Equal',
    0x0e: 'Backspace',
    0x0f: 'Tab',
    0x10: 'KeyQ',
    0x11: 'KeyW',
    0x12: 'KeyE',
    0x13: 'KeyR',
    0x14: 'KeyT',
    0x15: 'KeyY',
    0x16: 'KeyU',
    0x17: 'KeyI',
    0x18: 'KeyO',
    0x19: 'KeyP',
    0x1a: 'BracketLeft',
    0x1b: 'BracketRight',
    0x1c: 'Enter',
    0x1d: 'ControlLeft',
    0x1e: 'KeyA',
    0x1f: 'KeyS',
    0x20: 'KeyD',
    0x21: 'KeyF',
    0x22: 'KeyG',
    0x23: 'KeyH',
    0x24: 'KeyJ',
    0x25: 'KeyK',
    0x26: 'KeyL',
    0x27: 'Semicolon',
    0x28: 'Quote',
    0x29: 'Backquote',
    0x2a: 'ShiftLeft',
    0x2b: 'Backslash',
    0x2c: 'KeyZ',
    0x2d: 'KeyX',
    0x2e: 'KeyC',
    0x2f: 'KeyV',
    0x30: 'KeyB',
    0x31: 'KeyN',
    0x32: 'KeyM',
    0x33: 'Comma',
    0x34: 'Period',
    0x35: 'Slash',
    0x36: 'ShiftRight',
    0x37: 'NumpadMultiply',
    0x38: 'AltLeft',
    0x39: 'Space',
    0x3a: 'CapsLock',
    0x3b: 'F1',
    0x3c: 'F2',
    0x3d: 'F3',
    0x3e: 'F4',
    0x3f: 'F5',
    0x40: 'F6',
    0x41: 'F7',
    0x42: 'F8',
    0x43: 'F9',
    0x44: 'F10',
    0x45: 'NumLock',
    0x46: 'ScrollLock',
    0x47: 'Numpad7',
    0x48: 'Numpad8',
    0x49: 'Numpad9',
    0x4a: 'NumpadSubtract',
    0x4b: 'Numpad4',
    0x4c: 'Numpad5',
    0x4d: 'Numpad6',
    0x4e: 'NumpadAdd',
    0x4f: 'Numpad1',
    0x50: 'Numpad2',
    0x51: 'Numpad3',
    0x52: 'Numpad0',
    0x53: 'NumpadDecimal',
    0x57: 'F11',
    0x58: 'F12',
    0x9c: 'NumpadEnter',
    0x9d: 'ControlRight',
    0xb5: 'NumpadDivide',
    0xb8: 'AltRight',
    0xc5: 'Pause',
    0xc7: 'Home',
    0xc8: 'ArrowUp',
    0xc9: 'PageUp',
    0xcb: 'ArrowLeft',
    0xcd: 'ArrowRight',
    0xcf: 'End',
    0xd0: 'ArrowDown',
    0xd1: 'PageDown',
    0xd2: 'Insert',
    0xd3: 'Delete'
}

# Field sub-tables for the cfg blocks that are runs of named globals (offset, name, format, count);
# decoded with the same machinery as the snapshot region. Derived from incoming.exe.
_INPUT_AXIS_OPTIONS_FIELDS: tuple[tuple[int, str, str, int], ...] = (
    (0x00, 'invertAxisX2', 'B', 1),
    (0x01, 'controlConfigFlag61', 'B', 1),
    (0x04, 'invertAxisY2', 'I', 1),
    (0x08, 'invertAxisX3', 'I', 1),
    (0x0c, 'invertAxisY3', 'I', 1),
    (0x10, 'musicVolumeIndex', 'I', 1),
    (0x14, 'forceTerrainDraw', 'I', 1),
    (0x18, 'mouseSensitivityX', 'f', 1),
    (0x1c, 'mouseSensitivityY', 'f', 1),
    (0x20, 'forceFeedbackEnabled', 'I', 1),
    (0x24, 'controlConfig84', 'I', 1),
    (0x28, 'controlConfig88', 'I', 1),
    (0x2c, 'controlConfig8c', 'I', 1),
    (0x30, 'controlModeTable', 'i', 16),
    (0x70, 'controlConfigPage', 'i', 1),
    (0x74, 'netGameTypeMenuSelection', 'i', 1),
    (0x78, 'netSessionMenuSelection', 'i', 1),
    (0x7c, 'modeMenuSelection', 'i', 1),
    (0x80, 'missionSetupSelection', 'i', 1),
    (0x84, 'highScoreEntryRegionByte', 'B', 1),
    (0x88, 'defaultReplaySync', 'I', 1),
    (0x8c, 'useObjectSpaceTransform', 'I', 1),
    (0x90, 'hasActiveEffectSlots', 'I', 1),
    (0x94, 'replayFinished', 'I', 1),
    (0x98, 'lastInputCodeA', 'I', 1),
    (0x9c, 'lastInputCodeB', 'I', 1),
    (0xa0, 'renderTerrainEnable', 'I', 1),
    (0xa4, 'detailFlagA', 'I', 1),
    (0xa8, 'detailFlagB', 'I', 1),
    (0xac, 'lowTextureDetail', 'I', 1),
    (0xb0, 'renderFeatureFlag2', 'I', 1),
    (0xb4, 'shadowProjectConfig', 'I', 1),
    (0xb8, 'inputWindowReady', 'I', 1),
    (0xbc, 'renderFeatureFlag4', 'I', 1),
    (0xc0, 'hudColorTarget', 'I', 1),
    (0xc4, 'controlConfigB24', 'I', 1),
    (0xc8, 'viewTurnRateDeg', 'I', 1),
    (0xcc, 'replaySyncFlag', 'I', 1),
    (0xd0, 'sessionElapsedLo', 'I', 1),
    (0xd4, 'sessionElapsedHi', 'I', 1),
    (0xd8, 'missionElapsedLo', 'I', 1),
    (0xdc, 'missionElapsedHi', 'I', 1),
)
_CAMERA_STATE_FIELDS: tuple[tuple[int, str, str, int], ...] = (
    (0x00, 'cameraPosX', 'f', 1),
    (0x04, 'cameraPosY', 'f', 1),
    (0x08, 'cameraPosZ', 'f', 1),
    (0x0c, 'cameraTargetX', 'f', 1),
    (0x10, 'cameraDefaultY', 'f', 1),
    (0x14, 'cameraTargetZ', 'f', 1),
    (0x18, 'cameraEyeX', 'f', 1),
    (0x1c, 'cameraEyeY', 'f', 1),
    (0x20, 'cameraEyeZ', 'f', 1),
    (0x24, 'cameraLookAtX', 'f', 1),
    (0x28, 'cameraLookAtY', 'f', 1),
    (0x2c, 'cameraLookAtZ', 'f', 1),
    (0x30, 'cameraYaw', 'f', 1),
    (0x34, 'cameraPitch', 'f', 1),
    (0x3c, 'viewRenderMode', 'I', 1),
    (0x40, 'reticleLockState', 'i', 1),
    (0x44, 'cameraFollowMode', 'I', 1),
    (0x48, 'globalStateFlags', 'I', 1),
    (0x4c, 'lockedTargetObjects', 'I', 32),
    (0xcc, 'reticleStateObject', 'I', 1),
    (0xd0, 'replayTrackedHumanObject', 'I', 1),
    (0xd4, 'replayTrackedFlag400Object', 'I', 1),
    (0xd8, 'reticleBlinkActive', 'I', 1),
    (0xdc, 'replayCameraObject', 'I', 1),
    (0xe0, 'savedReplayCameraObject', 'I', 1),
)
_JOYSTICK_AXIS_BIND_FIELDS: tuple[tuple[int, str, str, int], ...] = (
    (0x00, 'joystickAxisBind', 'i', 44),
    (0xb0, 'extendedInputState', 'B', 208),
)
_INPUT_STATE_BLOCK_FIELDS: tuple[tuple[int, str, str, int], ...] = (
    (0x00, 'inputStateBlock', 'i', 2),
    (0x08, 'analogAxisGroup', 'I', 2),
    (0x10, 'replayNextInputIndex', 'i', 2),
    (0x18, 'scoreEntryScrollB', 'i', 1),
    (0x1c, 'scoreEntryScrollA', 'i', 1),
    (0x20, 'hudInfoLineCount', 'I', 1),
    (0x24, 'hudInfoColor', 'I', 1),
    (0x28, 'selectedCraftIndex', 'i', 1),
    (0x2c, 'selectedColorScheme', 'i', 1),
    (0x30, 'missionTimeLimitMinutes', 'i', 1),
    (0x34, 'netGameFlags', 'I', 1),
    (0x38, 'savedNetGameFlags', 'I', 1),
    (0x3c, 'gameSessionFlags', 'I', 1),
    (0x40, 'onVictoryValue', 'I', 1),
    (0x44, 'onFailureValue', 'I', 1),
    (0x48, 'netControlFlags', 'I', 1),
    (0x4c, 'controlAuthorityMode', 'I', 1),
    (0x50, 'defaultControlMode', 'I', 1),
    (0x54, 'netSessionName', 'str', 9),
    (0x5d, 'netPlayerName', 'str', 19),
)
_CFG_SUBFIELDS = {
    'inputAxisOptions': _INPUT_AXIS_OPTIONS_FIELDS,
    'cameraState': _CAMERA_STATE_FIELDS,
    'joystickAxisBind': _JOYSTICK_AXIS_BIND_FIELDS,
    'inputStateBlock': _INPUT_STATE_BLOCK_FIELDS,
}

# Struct record layouts from incoming.exe, used to decode the snapshot's record-pool regions. A
# field whose format is one of these struct names (see _STRUCT_TYPES) is decoded as an array of
# records. The world-object pool is GameObject[1700] (slot stride 0xCC, from
# InitializeBuildingAndWorldPool @ 0x445740).
_GAME_OBJECT_FIELDS: tuple[tuple[int, str, str, int], ...] = (
    (0x00, 'objectClassIndex', 'H', 1),
    (0x02, 'typeId', 'H', 1),
    (0x04, 'nextFree', 'I', 1),
    (0x08, 'nextInChain', 'I', 1),
    (0x0c, 'childList', 'I', 1),
    (0x10, 'soundSource', 'I', 1),
    (0x14, 'objectDef', 'I', 1),
    (0x18, 'upX', 'f', 1),
    (0x1c, 'upY', 'f', 1),
    (0x20, 'upZ', 'f', 1),
    (0x24, 'rightX', 'f', 1),
    (0x28, 'rightY', 'f', 1),
    (0x2c, 'rightZ', 'f', 1),
    (0x30, 'fwdX', 'f', 1),
    (0x34, 'fwdY', 'f', 1),
    (0x38, 'fwdZ', 'f', 1),
    (0x3c, 'templateUpdate', 'I', 1),
    (0x40, 'templatePhaseSeed', 'I', 1),
    (0x44, 'dynamicsRecord', 'I', 1),
    (0x48, 'debrisDamp48', 'f', 1),
    (0x4c, 'debrisRate4c', 'f', 1),
    (0x50, 'field50', 'f', 1),
    (0x54, 'debrisState54', 'I', 1),
    (0x58, 'debrisAccum58', 'f', 1),
    (0x5c, 'field5c', 'H', 1),
    (0x5e, 'ttl', 'h', 1),
    (0x60, 'field60', 'f', 1),
    (0x64, 'field64', 'f', 1),
    (0x68, 'initLifetime', 'I', 1),
    (0x6c, 'emitterAttr', 'f', 1),
    (0x70, 'field70', 'f', 1),
    (0x74, 'field74', 'f', 1),
    (0x78, 'posX', 'f', 1),
    (0x7c, 'posY', 'f', 1),
    (0x80, 'posZ', 'f', 1),
    (0x84, 'param84', 'f', 1),
    (0x88, 'effectScalar', 'f', 1),
    (0x8c, 'sparkScale8c', 'f', 1),
    (0x90, 'dirX', 'f', 1),
    (0x94, 'dirY', 'f', 1),
    (0x98, 'dirZ', 'f', 1),
    (0x9c, 'behaviorId', 'I', 1),
    (0xa0, 'effectMode', 'I', 1),
    (0xa4, 'packedColor', 'I', 1),
    (0xa8, 'sparkColorA8', 'I', 1),
    (0xac, 'phase', 'I', 1),
    (0xb0, 'update', 'I', 1),
    (0xb4, 'targetPoint', 'I', 1),
    (0xb8, 'lifetime', 'I', 1),
    (0xbc, 'effectSubModeBc', 'I', 1),
    (0xc0, 'projectileTypeIndex', 'i', 1),
    (0xc4, 'fieldC4', 'I', 1),
    (0xc8, 'effectSlotIndex', 'H', 1),
    (0xca, 'stateFlags', 'H', 1),
)
# Script runtime tables: g_aScriptProcTable is ScriptProcRecord[5]; g_pScriptLabelTable is
# ScriptLabelEntry[120]. Pointer fields are run-time addresses (not meaningful across sessions).
_SCRIPT_PROC_FIELDS: tuple[tuple[int, str, str, int], ...] = (
    (0x00, 'cursor', 'I', 1),
    (0x04, 'endNode', 'I', 1),
    (0x08, 'cursorBound', 'I', 1),
    (0x0c, 'namePtr', 'I', 1),
    (0x10, 'loopCount', 'I', 1),
    (0x14, 'reserved14', 'B', 76),
    (0x60, 'resetWord', 'I', 1),
)
_SCRIPT_LABEL_FIELDS: tuple[tuple[int, str, str, int], ...] = (
    (0x00, 'tag', 'i', 1),
    (0x04, 'namePtr', 'I', 1),
    (0x08, 'object', 'I', 1),
    (0x0c, 'flag', 'i', 1),
)
_STRUCT_TYPES: dict[str, tuple[int, tuple[tuple[int, str, str, int], ...]]] = {
    'GameObject': (204, _GAME_OBJECT_FIELDS),
    'ScriptProcRecord': (100, _SCRIPT_PROC_FIELDS),
    'ScriptLabelEntry': (16, _SCRIPT_LABEL_FIELDS),
}

# Field table for the mission/level snapshot region, derived from the named globals of incoming.exe
# in [g_nCurrentMissionId, g_nCurrentMissionId + 0x81a30). Each entry is (offset, name, format,
# count) where format is a struct character ('i', 'I', 'f', 'H', 'h', 'B'). Run-time pointer fields
# are decoded as unsigned 32-bit words; their saved values are not meaningful across sessions.
_SNAPSHOT_FIELDS: tuple[tuple[int, str, str, int], ...] = (
    (0x00000, 'currentMissionId', 'i', 1),
    (0x00004, 'selectedMissionSlot', 'i', 1),
    (0x00008, 'gameModeFlag', 'I', 1),
    (0x0000c, 'networkMissionFlag', 'I', 1),
    (0x00010, 'scriptedMissionFlag', 'I', 1),
    (0x00014, 'defaultScriptRuntimeRec', 'I', 1),
    (0x00018, 'defaultScriptRecSelector', 'H', 1),
    (0x0001a, 'userCameraFlag', 'H', 1),
    (0x0001c, 'userCameraHeroBase', 'i', 1),
    (0x00020, 'userCameraMode', 'i', 1),
    (0x00024, 'userCamViewMat00', 'f', 1),
    (0x00028, 'userCamViewMat01', 'f', 1),
    (0x0003c, 'userCamDirX', 'f', 1),
    (0x00040, 'userCamDirY', 'f', 1),
    (0x00044, 'userCamDirZ', 'f', 1),
    (0x00048, 'userCamEyeX', 'f', 1),
    (0x0004c, 'userCamEyeY', 'f', 1),
    (0x00050, 'userCamEyeZ', 'f', 1),
    (0x00054, 'userCamViewMatOut', 'f', 1),
    (0x00058, 'userCamViewMatOut1', 'f', 1),
    (0x00078, 'userCamPrevEyeX', 'f', 1),
    (0x0007c, 'userCamPrevEyeY', 'f', 1),
    (0x00080, 'userCamPrevEyeZ', 'f', 1),
    (0x00084, 'userCameraEyeTarget', 'I', 1),
    (0x00088, 'userCameraLookTarget', 'I', 1),
    (0x0008c, 'userCameraEyeBase', 'I', 1),
    (0x00090, 'userCameraLookBase', 'I', 1),
    (0x00094, 'userCameraFov', 'f', 1),
    (0x00098, 'userCamTargetX', 'f', 1),
    (0x0009c, 'userCamTargetY', 'f', 1),
    (0x000a0, 'userCamTargetZ', 'f', 1),
    (0x000e8, 'userCamHasBaddieScript', 'i', 1),
    (0x002dc, 'userCameraNear', 'f', 1),
    (0x006f0, 'cameraLightStateBase', 'i', 1),
    (0x006f4, 'cameraLightListStart', 'i', 1),
    (0x008b4, 'cameraLightStateEntry0ListHead', 'I', 1),
    (0x008b8, 'userCamViewTargetX', 'f', 1),
    (0x008bc, 'userCamViewTargetY', 'f', 1),
    (0x008c0, 'userCamViewTargetZ', 'f', 1),
    (0x008c4, 'userCamSavedEyeX', 'f', 1),
    (0x008c8, 'userCamSavedEyeY', 'f', 1),
    (0x008cc, 'userCamSavedEyeZ', 'f', 1),
    (0x008d0, 'userCamOrbitRadius', 'f', 1),
    (0x008d4, 'userCameraType', 'i', 1),
    (0x008d8, 'userCamStateCountdown', 'i', 1),
    (0x008dc, 'phaseStartClearFlagB', 'I', 1),
    (0x008e0, 'localPlayerDeathTriggered', 'I', 1),
    (0x008e8, 'controlRecMode', 'I', 1),
    (0x008ec, 'controlRecFlags', 'I', 1),
    (0x008f0, 'controlRecAxisX', 'I', 1),
    (0x008f4, 'controlRecAxisY', 'I', 1),
    (0x00948, 'userCameraMatrix', 'i', 12),
    (0x00978, 'cellArray', 'I', 2),
    (0x00980, 'replayStateA', 'I', 1),
    (0x00d94, 'userCameraFlags', 'I', 1),
    (0x00d9c, 'secondaryHeroScriptRec', 'I', 1),
    (0x00da0, 'secondaryScriptRecSelector', 'H', 1),
    (0x00da2, 'replayCamFlag', 'H', 1),
    (0x00da4, 'secondaryHeroRec', 'I', 1),
    (0x00da8, 'replayStateB', 'I', 1),
    (0x00dac, 'worldPoolConfigA', 'I', 12),
    (0x00ddc, 'worldPoolConfigB', 'I', 423),
    (0x01478, 'cameraLightStateEntry1Count', 'I', 1),
    (0x0147c, 'cameraLightStateEntry1ListStart', 'I', 1),
    (0x0163c, 'cameraLightStateEntry1ListHead', 'I', 1),
    (0x01640, 'replayCamViewTargetX', 'f', 1),
    (0x01644, 'replayCamViewTargetY', 'f', 1),
    (0x01648, 'replayCamViewTargetZ', 'f', 1),
    (0x01658, 'replayCamOrbitRadius', 'f', 1),
    (0x01660, 'replayCamStateCountdown', 'i', 1),
    (0x01664, 'phaseStartClearFlagA', 'I', 1),
    (0x01670, 'controlAxisLoOut', 'I', 1),
    (0x01674, 'controlStateWord', 'I', 1),
    (0x01678, 'controlStateWord2', 'I', 1),
    (0x0167c, 'controlStateWord3', 'I', 1),
    (0x01b1c, 'hudOverlayFlags', 'I', 1),
    (0x01b24, 'scriptRuntimeRec', 'I', 1),
    (0x01b28, 'scriptLabelRange', 'I', 1),
    (0x01b2c, 'scriptLabelCount', 'I', 1),
    (0x01b30, 'backdropCfgActive', 'I', 1),
    (0x01b34, 'directLightCurY', 'f', 1),
    (0x01b38, 'directLightCurZ', 'f', 1),
    (0x01b3c, 'viewLightDirX', 'f', 1),
    (0x01b40, 'viewLightDirY', 'f', 1),
    (0x01b44, 'fogGradientSrc0', 'f', 1),
    (0x01b48, 'fogGradientSrc1', 'f', 1),
    (0x01b4c, 'fogGradientSrc2', 'f', 1),
    (0x01b50, 'directLightZ', 'f', 1),
    (0x01b54, 'baseLightColorG', 'i', 2),
    (0x01b5c, 'baseLightColorB', 'i', 1),
    (0x01b60, 'smoothAccum1X', 'f', 1),
    (0x01b64, 'smoothAccum1Y', 'f', 1),
    (0x01b68, 'smoothAccum1Z', 'f', 1),
    (0x01b6c, 'smoothAccum2X', 'f', 1),
    (0x01b70, 'smoothAccum2Y', 'f', 1),
    (0x01b74, 'smoothAccum2Z', 'f', 1),
    (0x01b78, 'smoothGroup2Ready', 'I', 1),
    (0x01b7c, 'smoothResult2X', 'f', 1),
    (0x01b80, 'smoothResult2Y', 'f', 1),
    (0x01b84, 'smoothResult2Z', 'f', 1),
    (0x01b88, 'smoothGroup1Ready', 'I', 1),
    (0x01b8c, 'smoothResult1X', 'f', 1),
    (0x01b90, 'smoothResult1Y', 'f', 1),
    (0x01b94, 'smoothResult1Z', 'f', 1),
    (0x01b98, 'smoothResult1bX', 'f', 1),
    (0x01b9c, 'smoothResult1bY', 'f', 1),
    (0x01ba0, 'smoothResult1bZ', 'f', 1),
    (0x01ba4, 'fogColorPacked', 'I', 1),
    (0x01ba8, 'worldSizeX', 'I', 1),
    (0x01bac, 'worldSizeZ', 'I', 1),
    (0x01bb0, 'hasEarthLayer', 'I', 1),
    (0x01bb4, 'smoothGroup3Ready', 'I', 1),
    (0x01bb8, 'dirLightSmoothAccum', 'f', 1),
    (0x01bbc, 'cloudLevelTable', 'f', 1),
    (0x01c18, 'smoothGroup3ZeroA', 'f', 1),
    (0x01c1c, 'smoothGroup3ZeroB', 'f', 1),
    (0x01c20, 'smoothGroup3ZeroC', 'f', 1),
    (0x01c24, 'dirLightSmoothDelta', 'f', 1),
    (0x01c28, 'smoothGroup3ResultsAnchor', 'f', 1),
    (0x01c84, 'smoothGroup3Divisor', 'f', 1),
    (0x01c88, 'smoothGroup3Scale2', 'f', 1),
    (0x01c8c, 'smoothGroup3Scale3', 'f', 1),
    (0x01c90, 'scoreStatsLive', 'i', 4),
    (0x01ca0, 'scriptScoreTotal', 'I', 1),
    (0x01ca4, 'scoreStatsLiveTail', 'i', 8),
    (0x01cc4, 'scriptProcInstrTotal', 'I', 1),
    (0x01cc8, 'savedProcInstrValid', 'I', 1),
    (0x01ccc, 'inScriptStep', 'I', 1),
    (0x01cd0, 'currentProcCursor', 'I', 1),
    (0x01cd4, 'scriptFlagBits', 'I', 1),
    (0x01cd8, 'worldPoolTail', 'I', 1),
    (0x01cdc, 'effectFreeListHead', 'I', 1),
    (0x01ce0, 'activeCellCount', 'I', 1),
    (0x01ce4, 'worldSlotCount', 'I', 1),
    (0x01ce8, 'debrisSimPhase', 'I', 1),
    (0x01cec, 'scriptInstrCount', 'i', 1),
    (0x01cf0, 'scriptActiveProcSlot', 'i', 1),
    (0x01cf4, 'scriptLoadedLabelCount', 'i', 1),
    (0x01cf8, 'scriptLabelTotal', 'i', 1),
    (0x01cfc, 'missionCountdownActive', 'I', 1),
    (0x01d00, 'missionCountdownTimer', 'i', 1),
    (0x01d04, 'radarFlashTimer', 'I', 1),
    (0x01d08, 'frameCounter', 'I', 1),
    (0x01d0c, 'simTickCounter', 'I', 1),
    (0x01d10, 'frameSequence', 'I', 1),
    (0x01d14, 'scriptTimerMode', 'I', 1),
    (0x01d18, 'levelMsgValue', 'i', 1),
    (0x01d1c, 'playerRecord', 'I', 1),
    (0x01d20, 'playerHitFlashTimer', 'I', 1),
    (0x01d24, 'debrisViewTargetX', 'f', 1),
    (0x01d28, 'debrisViewTargetY', 'f', 1),
    (0x01d2c, 'debrisViewTargetZ', 'f', 1),
    (0x01d30, 'snapshotCdTrack', 'I', 1),
    (0x01d34, 'scriptDataSize', 'I', 1),
    (0x01d38, 'lastEmittedCmdNode', 'I', 1),
    (0x01d40, 'inProcedureFlag', 'I', 1),
    (0x01d44, 'lastSpawnedObject', 'I', 1),
    (0x01d48, 'currentWeaponRec', 'I', 1),
    (0x01d4c, 'currentLabelObject', 'I', 1),
    (0x01d50, 'hasWaypoint', 'I', 1),
    (0x01d54, 'waypointData', 'I', 7),
    (0x01d70, 'worldPoolActiveEndAlias', 'I', 1),
    (0x01d74, 'effectSlotStateArray', 'I', 1),
    (0x01d78, 'effectSlotPoolBase', 'I', 1),
    (0x01d88, 'effectSlotField14', 'i', 1),
    (0x01d9c, 'effectSlotField28', 'i', 1),
    (0x01da4, 'effectSlotTorqueX', 'f', 1),
    (0x01da8, 'effectSlotTorqueY', 'f', 1),
    (0x01dac, 'effectSlotTorqueZ', 'f', 1),
    (0x01db8, 'effectSlotAuxArray', 'I', 1),
    (0x01dd0, 'effectSlotVelX', 'f', 1),
    (0x01dd4, 'effectSlotVelZ', 'f', 1),
    (0x01dd8, 'effectSlotVelY', 'f', 1),
    (0x01e00, 'effectSlotDynamics', 'i', 1),
    (0x01e0c, 'effectSlotField98', 'I', 1),
    (0x01e1c, 'buildingTable', 'i', 1),
    (0x01e20, 'effectSlotField80', 'I', 1),
    (0x01e24, 'effectSlotXformBase', 'f', 1),
    (0x01e30, 'effectSlotMinImpact', 'I', 1),
    (0x01e34, 'playerRecordField3', 'I', 1),
    (0x01e38, 'playerRecordField2', 'I', 1),
    (0x01e3c, 'playerRecordScanBase', 'I', 1),
    (0x01e40, 'playerRecordField1', 'I', 1),
    (0x01e44, 'playerRecordPackedField', 'H', 1),
    (0x01e48, 'playerRecordField0', 'I', 1),
    (0x01f08, 'playerRecordNextField3', 'I', 1),
    (0x01f0c, 'playerRecordNextField2', 'I', 1),
    (0x01f10, 'playerRecordNextField1', 'I', 1),
    (0x01f14, 'playerRecordNextField0', 'I', 1),
    (0x02204, 'cameraLightListEnd', 'i', 1),
    (0x03724, 'effectSlotPoolEndMarker', 'I', 1),
    (0x037f4, 'worldGrid', 'I', 16384),
    (0x137f4, 'worldObjectPool', 'GameObject', 1700),
    (0x682a4, 'colorKeyRefCount', 'i', 30),
    (0x6831c, 'scriptProcTable', 'ScriptProcRecord', 5),
    (0x68510, 'scriptLabelTable', 'ScriptLabelEntry', 120),
    (0x68c90, 'missionScriptDataPool', 'B', 98304),
    (0x80c90, 'scriptDataBuffer', 'B', 32),
    (0x80cb0, 'debrisLeadVelX', 'f', 1),
    (0x80cb4, 'debrisLeadVelY', 'f', 1),
    (0x80cb8, 'debrisLeadVelZ', 'f', 1),
    (0x80cbc, 'debrisLeadPosX', 'f', 1),
    (0x80cc0, 'debrisLeadPosY', 'f', 1),
    (0x80cc4, 'debrisLeadPosZ', 'f', 1),
    (0x80cc8, 'debrisLeadDeltaX', 'f', 1),
    (0x80ccc, 'debrisLeadDeltaY', 'f', 1),
    (0x80cd0, 'debrisLeadDeltaZ', 'f', 1),
    (0x80cd4, 'debrisLeadResidualX', 'f', 1),
    (0x80cd8, 'debrisLeadResidualY', 'f', 1),
    (0x80cdc, 'debrisLeadResidualZ', 'f', 1),
    (0x80d08, 'debrisParticleArray', 'f', 1),
    (0x80f2c, 'debrisLeadColor0', 'I', 1),
    (0x80f30, 'debrisLeadColor1', 'I', 1),
    (0x80f34, 'debrisLeadColor2', 'I', 1),
    (0x80f54, 'debrisLeadReseed0', 'I', 1),
    (0x80f5c, 'debrisLeadReseed1', 'I', 1),
    (0x80f7c, 'debrisParticleArrayEnd', 'f', 1),
    (0x80f84, 'debrisParticleScale', 'f', 1),
    (0x80fbc, 'generationPointsList', 'I', 1),
    (0x80fc0, 'activeObjectList', 'I', 30),
    (0x81038, 'activeObjectCount', 'i', 1),
    (0x8103c, 'worldStateFlags', 'I', 1),
    (0x81040, 'cameraPosX', 'f', 1),
    (0x81044, 'cameraPosY', 'f', 1),
    (0x81048, 'cameraPosZ', 'f', 1),
    (0x8104c, 'cameraTargetX', 'f', 1),
    (0x81050, 'cameraDefaultY', 'f', 1),
    (0x81054, 'cameraTargetZ', 'f', 1),
    (0x81058, 'cameraEyeX', 'f', 1),
    (0x8105c, 'cameraEyeY', 'f', 1),
    (0x81060, 'cameraEyeZ', 'f', 1),
    (0x81064, 'cameraLookAtX', 'f', 1),
    (0x81068, 'cameraLookAtY', 'f', 1),
    (0x8106c, 'cameraLookAtZ', 'f', 1),
    (0x81070, 'cameraYaw', 'f', 1),
    (0x81074, 'cameraPitch', 'f', 1),
    (0x8107c, 'viewRenderMode', 'I', 1),
    (0x81080, 'reticleLockState', 'i', 1),
    (0x81084, 'cameraFollowMode', 'I', 1),
    (0x81088, 'globalStateFlags', 'I', 1),
    (0x8108c, 'lockedTargetObjects', 'I', 32),
    (0x8110c, 'reticleStateObject', 'I', 1),
    (0x81110, 'replayTrackedHumanObject', 'I', 1),
    (0x81114, 'replayTrackedFlag400Object', 'I', 1),
    (0x81118, 'reticleBlinkActive', 'I', 1),
    (0x8111c, 'replayCameraObject', 'I', 1),
    (0x81120, 'savedReplayCameraObject', 'I', 1),
    (0x81124, 'activeCameraLightCount', 'i', 1),
    (0x81128, 'lockCameraTargetId', 'I', 1),
    (0x8112c, 'lastDeviceCreateFrame', 'I', 1),
    (0x81130, 'sparkDebrisMatrixPool', 'f', 576),
)

# The .sav/.xxx region begins 12 bytes before the .lev region (the leading mission-id fields), so
# both end at the same global; .lev shares this field table shifted by this prefix.
_LEVEL_PREFIX = 12
_MISSION_SNAPSHOT_SIZE = 0x81a30
_LEVEL_SNAPSHOT_SIZE = 0x81a24


def _write_json(source: Path, dest_dir: Path, obj: dict[str, Any]) -> Path:
    destination = dest_dir / f'{source.stem}.json'
    destination.write_text(json.dumps(obj, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return destination


def _unpack(data: bytes, pos: int, fmt: str, count: int) -> Any:
    if fmt == 'str':
        return data[pos:pos + count].split(b'\x00', 1)[0].decode('latin-1')
    if fmt in _STRUCT_TYPES:
        size, fields = _STRUCT_TYPES[fmt]
        return [
            _decode_region(data[pos + i * size:pos + (i + 1) * size], fields, 0)
            for i in range(count)
        ]
    values = struct.unpack_from(f'<{count}{fmt}', data, pos)
    return values[0] if count == 1 else list(values)


def _merge_hi_lo(decoded: dict[str, Any]) -> dict[str, Any]:
    # Combine ``<base>Lo`` / ``<base>Hi`` dword pairs into a single 64-bit ``<base>`` field.
    bases = {k[:-2] for k in decoded if k.endswith('Lo') and isinstance(decoded[k], int)}
    bases &= {k[:-2] for k in decoded if k.endswith('Hi') and isinstance(decoded[k], int)}
    if not bases:
        return decoded
    merged: dict[str, Any] = {}
    for key, value in decoded.items():
        if key.endswith('Lo') and key[:-2] in bases:
            base = key[:-2]
            merged[base] = (decoded[f'{base}Hi'] << 32) | (value & 0xFFFFFFFF)
        elif not (key.endswith('Hi') and key[:-2] in bases):
            merged[key] = value
    return merged


def _decode_flags(value: int, names: Mapping[int, str]) -> dict[str, bool]:
    # A bitfield global ending in ``Flags`` is broken out into one boolean per bit, using the
    # reverse-engineered bit name where known and ``bit<n>`` otherwise.
    unsigned = value & 0xFFFFFFFF
    return {names.get(i, f'bit{i}'): bool((unsigned >> i) & 1) for i in range(32)}


def _decode_gap(data: bytes, start: int, end: int) -> Any:
    # Every byte must be decoded, never left as an opaque blob. The region is a 32-bit-aligned RAM
    # image, so an aligned, word-multiple span decodes as unsigned 32-bit words; anything else
    # decodes as raw byte values.
    span = data[start:end]
    if start % 4 == 0 and len(span) % 4 == 0:
        return list(struct.unpack(f'<{len(span) // 4}I', span))
    return list(span)


def _decode_region(data: bytes, fields: Sequence[tuple[int, str, str, int]],
                   base: int) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    items = sorted(
        ((off - base, name, fmt, count) for off, name, fmt, count in fields if off - base >= 0),
        key=operator.itemgetter(0))
    cursor = 0
    for pos, name, fmt, count in items:
        size = _cfg_block_size(fmt, count)
        if pos + size > len(data):
            break
        if pos > cursor:
            decoded[f'unknownAt_{cursor:06x}'] = _decode_gap(data, cursor, pos)
        value = _unpack(data, pos, fmt, count)
        if count == 1 and fmt in {'i', 'I'} and name.endswith('Flags'):
            value = _decode_flags(value, _FLAG_BIT_NAMES.get(name, {}))
        decoded[name] = value
        cursor = pos + size
    if cursor < len(data):
        decoded[f'unknownAt_{cursor:06x}'] = _decode_gap(data, cursor, len(data))
    return _merge_hi_lo(decoded)


def _snapshot_to_json(source: Path, dest_dir: Path, fmt: str, base: int,
                      expected_size: int) -> Path:
    data = source.read_bytes()
    obj = {
        'format': fmt,
        'size': len(data),
        'expected_size': expected_size,
        'fields': _decode_region(data, _SNAPSHOT_FIELDS, base),
    }
    return _write_json(source, dest_dir, obj)


def sav_to_json(source: Path, dest_dir: Path) -> Path:
    """
    Convert an Incoming ``.sav`` save game to JSON.

    The mission-state snapshot region (``SaveMissionStateSnapshot``) is decoded into named fields;
    bytes not covered by a known field are kept as base64 ``raw_regions``.

    Parameters
    ----------
    source : Path
        The source ``.sav`` file.
    dest_dir : Path
        The directory the JSON is written to.

    Returns
    -------
    Path
        The written JSON path.
    """
    return _snapshot_to_json(source, dest_dir, 'incoming-save', 0, _MISSION_SNAPSHOT_SIZE)


def xxx_to_json(source: Path, dest_dir: Path) -> Path:
    """
    Convert an Incoming ``.xxx`` debug mission snapshot to JSON.

    The ``.xxx`` file uses the same mission-state snapshot format as ``.sav``, so it shares that
    decoder; bytes not covered by a known field are kept as base64 ``raw_regions``.

    Parameters
    ----------
    source : Path
        The source ``.xxx`` file.
    dest_dir : Path
        The directory the JSON is written to.

    Returns
    -------
    Path
        The written JSON path.
    """
    return _snapshot_to_json(source, dest_dir, 'incoming-debug-snapshot', 0, _MISSION_SNAPSHOT_SIZE)


def lev_to_json(source: Path, dest_dir: Path) -> Path:
    """
    Convert an Incoming ``.lev`` level-state snapshot to JSON.

    The level snapshot (``SaveLevelStateSnapshot``) shares the mission-snapshot field table without
    its 12-byte mission-id prefix; bytes not covered by a known field are kept as base64
    ``raw_regions``.

    Parameters
    ----------
    source : Path
        The source ``.lev`` file.
    dest_dir : Path
        The directory the JSON is written to.

    Returns
    -------
    Path
        The written JSON path.
    """
    return _snapshot_to_json(source, dest_dir, 'incoming-level-snapshot', _LEVEL_PREFIX,
                             _LEVEL_SNAPSHOT_SIZE)


def _decode_keybind(scancode: int) -> dict[str, Any]:
    if scancode == 0:
        name = ''
    elif scancode >= _KEYBIND_SPECIAL_BASE:
        name = f'special{scancode - _KEYBIND_SPECIAL_BASE + 1}'
    else:
        name = _DIK_KEY_NAMES.get(scancode, f'scancode_{scancode:#04x}')
    return {'directInputScancode': scancode, 'name': name}


def _decode_keybinds(values: Sequence[int]) -> list[list[dict[str, Any]]]:
    return [[
        _decode_keybind(values[page * _KEYBIND_SLOTS_PER_PAGE + slot])
        for slot in range(_KEYBIND_SLOTS_PER_PAGE)
    ] for page in range(_KEYBIND_PAGES)]


def _option_label(options: Sequence[str], index: int) -> str | int:
    return options[index] if 0 <= index < len(options) else index


def _decode_serial_options(values: Sequence[int]) -> dict[str, Any]:
    com_port, baud, stop_bits, parity, flow_control = values
    return {
        'comPort': com_port + 1,
        'baudRate': _CFG_BAUD_RATES[baud] if 0 <= baud < len(_CFG_BAUD_RATES) else baud,
        'stopBits': _option_label(_CFG_STOP_BITS, stop_bits),
        'parity': _option_label(_CFG_PARITY, parity),
        'flowControl': _option_label(_CFG_FLOW_CONTROL, flow_control),
    }


def _decode_high_score_tables(raw: bytes) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for start in range(0, len(raw) - _HIGH_SCORE_RECORD_SIZE + 1, _HIGH_SCORE_RECORD_SIZE):
        record = raw[start:start + _HIGH_SCORE_RECORD_SIZE]
        category_id = int.from_bytes(record[108:112], 'little', signed=True)
        if category_id == -1:
            break
        entries = [{
            'score':
                int.from_bytes(record[entry:entry + 4], 'little'),
            'name':
                record[entry + 4:entry + _HIGH_SCORE_ENTRY_SIZE].split(b'\x00', 1)
                [0].decode('latin-1'),
        } for entry in range(0, _HIGH_SCORE_ENTRY_SIZE *
                             _HIGH_SCORE_ENTRY_COUNT, _HIGH_SCORE_ENTRY_SIZE)]
        tables.append({
            'categoryId': category_id,
            'subIndex': int.from_bytes(record[112:116], 'little', signed=True),
            'entries': entries,
        })
    return tables


def _decode_mission_slots(raw: bytes) -> list[dict[str, Any]]:
    slots = []
    for i in range(_MISSION_SLOT_COUNT):
        record = raw[i * _MISSION_SLOT_SIZE:(i + 1) * _MISSION_SLOT_SIZE]
        slots.append({
            'name': record[0:0x35].split(b'\x00', 1)[0].decode('latin-1'),
            'missionSlot': record[0x35],
            'levelValue': record[0x36],
        })
    return slots


def cfg_to_json(source: Path, dest_dir: Path) -> Path:
    """
    Convert an Incoming ``.cfg`` configuration file to JSON.

    The file (``SaveGameConfigFile``) is a concatenation of fixed-size blocks. Each block is decoded
    into a human-readable value: the build stamp and trailing buffers as text; the keybind block as
    four control-config pages of ten slots, each a DirectInput scancode with its key name; the
    options block as the serial/modem connection settings (COM port, baud rate, stop bits, parity,
    and flow control); the high-score block as a list of tables of ``{score, name}`` entries; the
    force-feedback flag as a boolean; and the checksum as an object that recomputes and verifies it.
    Nothing is left as an opaque blob.

    Parameters
    ----------
    source : Path
        The source ``.cfg`` file.
    dest_dir : Path
        The directory the JSON is written to.

    Returns
    -------
    Path
        The written JSON path.
    """
    data = source.read_bytes()
    obj: dict[str, Any] = {
        'format': 'incoming-config',
        'size': len(data),
        'expected_size': _CFG_TOTAL
    }
    if len(data) != _CFG_TOTAL:
        log.warning('Config `%s` is %d bytes, expected %d; decoding as raw words.', source,
                    len(data), _CFG_TOTAL)
        obj['raw'] = _decode_gap(data, 0, len(data))
        return _write_json(source, dest_dir, obj)
    blocks: dict[str, Any] = {}
    offsets: dict[str, tuple[int, int]] = {}
    cursor = 0
    for name, kind, count in _CFG_BLOCKS:
        size = _cfg_block_size(kind, count)
        offsets[name] = (cursor, size)
        if kind == 'str':
            blocks[name] = data[cursor:cursor + size].split(b'\x00', 1)[0].decode('latin-1')
        else:
            blocks[name] = _unpack(data, cursor, kind, count)
        cursor += size
    # Decode specific blocks into human-readable forms.
    blocks['forceFeedbackDevicePresent'] = bool(blocks['forceFeedbackDevicePresent'])
    blocks['keybindOffsets'] = _decode_keybinds(blocks['keybindOffsets'])
    blocks['optionValues'] = _decode_serial_options(blocks['optionValues'])
    slot_offset, slot_size = offsets['savedMissionSlotTable']
    blocks['savedMissionSlotTable'] = _decode_mission_slots(
        data[slot_offset:slot_offset + slot_size])
    for name, fields in _CFG_SUBFIELDS.items():
        block_offset, block_size = offsets[name]
        blocks[name] = _decode_region(data[block_offset:block_offset + block_size], fields, 0)
    check_offset, check_size = offsets[_CFG_CHECKSUM_BLOCK]
    blocks['highScoreTables'] = _decode_high_score_tables(
        data[check_offset:check_offset + check_size])
    stored = blocks['checksum']
    computed = sum(struct.unpack_from(f'<{check_size}b', data, check_offset)) & 0xFFFFFFFF
    blocks['checksum'] = {'stored': stored, 'computed': computed, 'valid': stored == computed}
    obj['blocks'] = blocks
    return _write_json(source, dest_dir, obj)
