"""Shared helpers for the command-line utilities."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
import functools

from bascom import setup_logging
import click

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ('debug_option',)


def debug_option(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Attach ``-d/--debug`` to a leaf command and route it through :py:func:`bascom.setup_logging`.

    The decorator pops ``debug`` from the keyword arguments before delegating, so the wrapped
    callback does not need to declare it.

    Parameters
    ----------
    func : Callable[..., Any]
        The Click callback to decorate.

    Returns
    -------
    Callable[..., Any]
        A new Click callback that adds ``-d/--debug`` to the command.
    """
    @click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
    @functools.wraps(func)
    def wrapper(*args: Any, debug: bool = False, **kwargs: Any) -> Any:
        setup_logging(debug=debug, loggers={'incoming_extractor': {}})
        return func(*args, **kwargs)

    return wrapper
