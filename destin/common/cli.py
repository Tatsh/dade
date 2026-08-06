"""
Click helpers shared by the games' command layers.

Every game exposes the same ``-d/--debug`` flag on its leaf commands, differing only in which
loggers it switches to ``DEBUG`` and in the flag's help text, so the decorator is built here from
those two parameters.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
import functools

from bascom import setup_logging
import click

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from logging.config import _LoggerConfiguration

__all__ = ('DEFAULT_DEBUG_HELP', 'make_debug_option')

DEFAULT_DEBUG_HELP = 'Enable debug level logging.'
"""Help text used for ``-d/--debug`` when a game does not override it.

:meta hide-value:
"""


def make_debug_option(
        loggers: Iterable[str],
        help_text: str = DEFAULT_DEBUG_HELP) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Build a decorator that attaches ``-d/--debug`` to a leaf command.

    The decorator routes the flag through :py:func:`bascom.setup_logging` and pops ``debug`` from
    the keyword arguments before delegating, so the wrapped callback does not need to declare it.

    Parameters
    ----------
    loggers : Iterable[str]
        Names of the loggers switched to ``DEBUG`` when the flag is set. A game passes its own
        logger alongside ``destin.common``.
    help_text : str
        Help text shown for the flag.

    Returns
    -------
    Callable[[Callable[..., Any]], Callable[..., Any]]
        A decorator that adds ``-d/--debug`` to a Click callback.
    """
    configuration: dict[str, _LoggerConfiguration] = {name: {} for name in loggers}

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @click.option('-d', '--debug', is_flag=True, help=help_text)
        @functools.wraps(func)
        def wrapper(*args: Any, debug: bool = False, **kwargs: Any) -> Any:
            setup_logging(debug=debug, loggers=configuration)
            return func(*args, **kwargs)

        return wrapper

    return decorator
