"""Exceptions raised by :py:mod:`bitrock`."""
from __future__ import annotations

__all__ = ('BitrockError', 'CorruptArchiveError', 'DecryptionError', 'MemberNotFoundError',
           'NotEncryptedError', 'SignatureNotFoundError', 'UnsupportedCompressionError')


class BitrockError(Exception):
    """Base class for every error raised by :py:mod:`bitrock`."""


class DecryptionError(BitrockError):
    """Raised when a password-protected page fails to decrypt (wrong password or corrupt data)."""


class NotEncryptedError(BitrockError):
    """Raised when a password operation is attempted on an installer that is not encrypted."""


class SignatureNotFoundError(BitrockError):
    """Raised when the cookfs signature cannot be located, so the source is not an installer."""


class CorruptArchiveError(BitrockError):
    """Raised when the cookfs structure is present but internally inconsistent or truncated."""


class UnsupportedCompressionError(BitrockError):
    """Raised when a page uses a compression method this reader cannot decode."""


class MemberNotFoundError(BitrockError):
    """Raised when a requested member is not present in the archive."""
