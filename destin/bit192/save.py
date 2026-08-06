"""
``save.bin`` reader/editor for Tone Sphere.

``save.bin`` is a raw little-endian dump of the in-memory save struct, a fixed 0x3cd08 bytes with no
header or compression (reverse-engineered from ``Game_WriteSaveBin`` @ 0x4a079ba0). DLC ownership is
a per-pack **token** = ``MD5(device_id + dlc_name)`` (32 lowercase-hex chars) written at a fixed
offset; the game derives the runtime unlock from the token on load.

The whole-file integrity hash at 0x3c488 (``SHA1("An83"+checksum+"A")``) is *written only, never
verified on load*, so local edits need no checksum fix-up. ``device_id`` is ``s3eDeviceGetString``
cached at 0x3ca38 (the literal ``"iOS"`` on iOS, making iOS tokens universal); because tokens are
device-bound, edit a save taken from the target device so its id matches.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import logging

__all__ = ('DLC_OFFSETS', 'SAVE_SIZE', 'SaveFile', 'dlc_token')

log = logging.getLogger(__name__)

SAVE_SIZE = 0x3CD08
"""Exact size of ``save.bin`` in bytes."""
_DEVICE_ID_OFFSET = 0x3CA38
_DEVICE_ID_LIMIT = 0x3CA9C
"""Offset of the next field after the device id; the id (plus NUL) must fit before it."""

UNLOCK_FLAGS_OFFSET = 0x3C088
"""Base of the song unlock-flag array. A song with ``UnlockNum = n`` is unlocked when the byte at
``UNLOCK_FLAGS_OFFSET + n`` is non-zero (a song with ``UnlockNum = 0`` has no gate)."""
UNLOCK_FLAGS_COUNT = 0x400
"""Length of the unlock-flag array (it ends exactly at the integrity hash at ``0x3c488``)."""

DLC_OFFSETS = {
    'darksphere': 0x3C520,
    'sunandmoon': 0x3C988,
    'empy': 0x3CA9C,
    'sixsec': 0x3CB80,
    'lgr': 0x3CBE8,
    'gnl': 0x3CC48,
    'vvv': 0x3CCA8
}
"""DLC pack name to the offset of its ownership-token field in ``save.bin``."""


def dlc_token(device_id: str, dlc_name: str) -> bytes:
    """
    Compute the DLC ownership token for a pack.

    Parameters
    ----------
    device_id : str
        The device id cached in the save (``"iOS"`` on iOS).
    dlc_name : str
        DLC pack name, e.g. ``'darksphere'``.

    Returns
    -------
    bytes
        The 32-character lowercase-hex MD5 of ``device_id + dlc_name``.
    """
    return hashlib.md5((device_id + dlc_name).encode()).hexdigest().encode()  # noqa: S324


@dataclass
class SaveFile:
    """An in-memory Tone Sphere ``save.bin``."""

    data: bytearray
    """The raw 0x3cd08-byte save buffer."""
    @classmethod
    def load(cls, path: str | Path) -> SaveFile:
        """
        Read a ``save.bin`` from disk.

        Parameters
        ----------
        path : str or pathlib.Path
            Path to ``save.bin``.

        Returns
        -------
        SaveFile
            The loaded save.

        Raises
        ------
        ValueError
            If the file is not exactly :data:`SAVE_SIZE` bytes.
        """
        data = Path(path).read_bytes()
        if len(data) != SAVE_SIZE:
            msg = f'Unexpected save size {len(data)} bytes (expected {SAVE_SIZE}).'
            raise ValueError(msg)
        return cls(bytearray(data))

    @classmethod
    def blank(cls) -> SaveFile:
        """
        Create a zero-initialised save (the game's fresh-install state).

        Returns
        -------
        SaveFile
            A new all-zero save of :data:`SAVE_SIZE` bytes.
        """
        return cls(bytearray(SAVE_SIZE))

    @property
    def device_id(self) -> str:
        """
        The device id cached in the save (empty if the game never ran).

        Returns
        -------
        str
            The NUL-terminated ASCII device id at offset 0x3ca38.
        """
        end = self.data.index(b'\x00', _DEVICE_ID_OFFSET)
        return self.data[_DEVICE_ID_OFFSET:end].decode('latin-1')

    def set_device_id(self, device_id: str) -> None:
        """
        Write the cached device id (the salt for DLC tokens).

        Use ``"iOS"`` for an iOS-universal save, or the device's ``Settings.Secure.ANDROID_ID`` on
        Android. Call this *before* :meth:`unlock_dlc` / :meth:`unlock_all_dlc`, since those derive
        tokens from it.

        Parameters
        ----------
        device_id : str
            The device id to cache at offset 0x3ca38.

        Raises
        ------
        ValueError
            If *device_id* is too long for the field.
        """
        raw = device_id.encode('latin-1')
        if _DEVICE_ID_OFFSET + len(raw) + 1 > _DEVICE_ID_LIMIT:
            limit = _DEVICE_ID_LIMIT - _DEVICE_ID_OFFSET - 1
            msg = f'Device id is too long ({len(raw)} bytes; max {limit}).'
            raise ValueError(msg)
        self.data[_DEVICE_ID_OFFSET:_DEVICE_ID_OFFSET + len(raw) + 1] = raw + b'\x00'

    def unlock_dlc(self, dlc_name: str) -> None:
        """
        Write the ownership token for one DLC pack.

        Parameters
        ----------
        dlc_name : str
            DLC pack name; must be a key of :data:`DLC_OFFSETS` (raises ``KeyError`` otherwise).
        """
        off = DLC_OFFSETS[dlc_name]
        token = dlc_token(self.device_id, dlc_name)
        self.data[off:off + len(token) + 1] = token + b'\x00'
        log.debug('Unlocked %s at %#06x with token %s.', dlc_name, off, token.decode())

    def unlock_all_dlc(self) -> list[str]:
        """
        Write ownership tokens for every known DLC pack.

        Returns
        -------
        list[str]
            The DLC names that were unlocked.
        """
        for name in DLC_OFFSETS:
            self.unlock_dlc(name)
        return list(DLC_OFFSETS)

    def unlock_song(self, unlock_num: int) -> None:
        """
        Mark one song unlocked by setting its unlock flag.

        Parameters
        ----------
        unlock_num : int
            The song's ``UnlockNum`` (from its config). Must be in
            ``1..UNLOCK_FLAGS_COUNT - 1``; ``0`` means the song has no gate and is ignored.

        Raises
        ------
        ValueError
            If *unlock_num* is outside the unlock-flag array.
        """
        if not 0 < unlock_num < UNLOCK_FLAGS_COUNT:
            msg = f'UnlockNum {unlock_num} is out of range (1..{UNLOCK_FLAGS_COUNT - 1}).'
            raise ValueError(msg)
        self.data[UNLOCK_FLAGS_OFFSET + unlock_num] = 1

    def unlock_all_songs(self) -> int:
        """
        Unlock every song by setting the whole unlock-flag array.

        Sets ``UnlockNum`` flags ``1`` through ``UNLOCK_FLAGS_COUNT - 1``; the array ends exactly at
        the integrity hash, so no other field is touched. Does not affect DLC episodes, which need
        device-bound tokens (see :meth:`unlock_all_dlc`).

        Returns
        -------
        int
            The number of unlock flags set.
        """
        start = UNLOCK_FLAGS_OFFSET + 1
        end = UNLOCK_FLAGS_OFFSET + UNLOCK_FLAGS_COUNT
        self.data[start:end] = b'\x01' * (end - start)
        log.debug('Set %d song unlock flags at %#x.', end - start, start)
        return end - start

    def unlock_everything(self) -> None:
        """
        Unlock every regular song and every DLC pack.

        Combines :meth:`unlock_all_songs` and :meth:`unlock_all_dlc`. The DLC tokens are derived
        from the current :attr:`device_id`, so set that first (see :meth:`set_device_id`) for the
        tokens to be valid on the target device.
        """
        self.unlock_all_songs()
        self.unlock_all_dlc()

    def save(self, path: str | Path) -> None:
        """
        Write the save buffer to disk.

        Parameters
        ----------
        path : str or pathlib.Path
            Destination path.
        """
        Path(path).write_bytes(bytes(self.data))
        log.debug('Wrote %d bytes to %s.', len(self.data), path)
