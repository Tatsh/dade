"""Worker-count helpers shared by the games' conversion pipelines."""
from __future__ import annotations

import os

__all__ = ('default_jobs',)


def default_jobs() -> int:
    """
    Return the default worker count.

    Returns
    -------
    int
        The machine's CPU count, or ``1`` if it cannot be determined.
    """
    return os.cpu_count() or 1
