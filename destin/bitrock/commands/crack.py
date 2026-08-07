"""The ``ibpwcrk`` command: recover an encrypted installer's password by brute force."""
from __future__ import annotations

from importlib import import_module
from itertools import islice
from pathlib import Path
from typing import TYPE_CHECKING, cast
import os
import signal
import string
import sys
import time

from bascom import setup_logging
from destin.bitrock.exceptions import BitrockError
from destin.bitrock.password_cracker import Mask, combine, crack, iter_wordlist, mangle
import click

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from destin.bitrock.password_cracker import Backend, Rule

__all__ = ('crack_main',)

_SIGINT_EXIT_CODE = 128 + signal.SIGINT
"""Conventional exit code for a process terminated by ``SIGINT`` (128 plus the signal number).

:meta hide-value:
"""
_CHARSET_PRESETS = {
    'digits': string.digits,
    'lower': string.ascii_lowercase,
    'upper': string.ascii_uppercase,
    'alpha': string.ascii_letters,
    'alnum': string.ascii_letters + string.digits,
    'printable': string.digits + string.ascii_letters + string.punctuation,
}
"""Named character-set presets accepted by ``--charset``.

:meta hide-value:
"""
RULE_CHOICES = ('none', 'capitalize', 'upper', 'lower', 'leet', 'append_digits', 'append_years')
"""Word-mangling rule names accepted by ``--rule``.

:meta hide-value:
"""


def _resolve_charset(charset: str) -> bytes:
    """
    Resolve a ``--charset`` value, expanding a named preset or taking it literally.

    Parameters
    ----------
    charset : str
        A preset name from :py:data:`_CHARSET_PRESETS`, or the literal characters to use.

    Returns
    -------
    bytes
        The character set as bytes.
    """
    return _CHARSET_PRESETS.get(charset, charset).encode()


def _build_source(wordlist: Path | None, charset: str, min_length: int, max_length: int,
                  rules: tuple[Rule, ...], combinator: int | None,
                  separator: str) -> tuple[Iterable[str | bytes], int | None]:
    """
    Build the candidate source and its size from the CLI options.

    Parameters
    ----------
    wordlist : :py:class:`~pathlib.Path` | None
        A wordlist to draw from, or ``None`` for charset brute force.
    charset : str
        The ``--charset`` value (used only without ``wordlist``).
    min_length : int
        Shortest brute-force candidate length.
    max_length : int
        Longest brute-force candidate length.
    rules : tuple[Rule, ...]
        Word-mangling rules to apply to wordlist entries.
    combinator : int | None
        Number of words to join per candidate, or ``None`` to not combine.
    separator : str
        Separator inserted between joined words.

    Returns
    -------
    tuple[Iterable[str | bytes], int | None]
        The candidate iterable and the total candidate count when known, else ``None``.
    """
    if wordlist is None:
        mask = Mask(_resolve_charset(charset), min_length, max_length)
        return mask, mask.count()
    words = list(iter_wordlist(wordlist))
    if combinator is not None:
        rule_list = list(rules) or None
        pool = len(list(mangle(words, rules))) if rule_list else len(words)
        return combine(words, combinator, rules=rule_list,
                       separator=separator.encode()), pool ** combinator
    if rules:
        return mangle(words, list(rules)), None
    return words, len(words)


_YEAR_SECONDS = 31_557_600
"""Seconds in a Julian year (365.25 days).

:meta hide-value:
"""
_DURATION_UNITS: tuple[tuple[str, int], ...] = (
    ('Gy', 1_000_000_000 * _YEAR_SECONDS),
    ('My', 1_000_000 * _YEAR_SECONDS),
    ('millennia', 1000 * _YEAR_SECONDS),
    ('y', _YEAR_SECONDS),
    ('d', 86400),
    ('h', 3600),
    ('m', 60),
    ('s', 1),
)
"""Duration units from gigayears down to seconds, each in seconds, for the full breakdown.

:meta hide-value:
"""


def _format_duration(seconds: float) -> str:
    """
    Break a duration into every unit from the largest applicable down to seconds.

    Units above years (millennia, megayears, gigayears) let enormous keyspaces read as the absurd
    spans they are; the age of the universe is about 13.8 Gy for reference.

    Parameters
    ----------
    seconds : float
        The duration in seconds.

    Returns
    -------
    str
        A breakdown such as ``'45s'``, ``'2h 05m 30s'``, or
        ``'114,811,912,369 Gy 470 My 12 millennia 84y 41d 05h 20m 00s'``.
    """
    remaining = int(seconds)
    parts: list[str] = []
    for label, size in _DURATION_UNITS:
        if remaining < size and not parts and label != 's':
            continue
        value, remaining = divmod(remaining, size)
        if label in {'Gy', 'My', 'millennia'}:
            parts.append(f'{value:,} {label}')  # A space reads better before a word-like unit.
        elif parts and label in {'h', 'm', 's'}:
            parts.append(f'{value:02d}{label}')  # Zero-pad trailing clock units.
        else:
            parts.append(f'{value}{label}')
    return ' '.join(parts)


def _format_rate(rate: float) -> str:
    """
    Format a candidates-per-second rate, keeping precision for slow rates.

    Parameters
    ----------
    rate : float
        Candidates per second.

    Returns
    -------
    str
        The rate with two decimals below 100/s, otherwise a thousands-separated integer.
    """
    return f'{rate:,.2f}' if rate < 100 else f'{rate:,.0f}'  # noqa: PLR2004


def _progress_printer(total: int | None, start: float) -> Callable[[int, bytes], None]:
    """
    Build a progress callback that rewrites a single status line on standard error.

    Parameters
    ----------
    total : int | None
        Total number of candidates in the keyspace, or ``None`` when it is unknown.
    start : float
        Monotonic start time from :py:func:`time.monotonic`.

    Returns
    -------
    Callable[[int, bytes], None]
        A callback taking the running count and the latest candidate tried.
    """
    def report(tested: int, latest: bytes) -> None:
        rate = tested / elapsed if (elapsed := time.monotonic() - start) > 0 else 0.0
        shown = latest.decode(errors='backslashreplace')
        line = f'\r{tested:,} tried, {_format_rate(rate)}/s, latest: {shown}'
        if total is not None and rate > 0:
            line += (f' | {100 * tested / total:.2f}% '
                     f'ETA {_format_duration((total - tested) / rate)}')
        click.echo(f'{line}\x1b[K', nl=False, err=True)
        sys.stderr.flush()

    return report


def _print_devices(ctx: click.Context, _param: click.Parameter,
                   value: bool) -> None:  # noqa: FBT001
    """
    Print each backend's devices and exit, when ``--list-devices`` is given.

    Parameters
    ----------
    ctx : click.Context
        The Click context, used to exit early.
    _param : click.Parameter
        The triggering parameter (unused).
    value : bool
        Whether ``--list-devices`` was passed.
    """
    if not value or ctx.resilient_parsing:
        return
    for label, module in (('cuda', 'destin.bitrock.password_cracker.cuda'),
                          ('opencl', 'destin.bitrock.password_cracker.opencl')):
        try:
            names = import_module(module).list_devices()
        except Exception as e:  # noqa: BLE001  # A missing backend or driver must not abort listing.
            click.echo(f'{label}: unavailable ({e})')
            continue
        if not names:
            click.echo(f'{label}: no devices')
        for index, name in enumerate(names):
            click.echo(f'{label} {index}: {name}')
    ctx.exit()


@click.command(name='ibpwcrk', context_settings={'help_option_names': ('-h', '--help')})
@click.argument('archive', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('-w',
              '--wordlist',
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help='Try each line of this wordlist instead of a generated keyspace.')
@click.option('-c',
              '--charset',
              default='alnum',
              help='Character set for brute force: a preset (digits, lower, upper, alpha, alnum, '
              'printable) or literal characters.')
@click.option('--min-length', default=1, show_default=True, help='Shortest candidate length.')
@click.option('--max-length', default=16, show_default=True, help='Longest candidate length.')
@click.option('-r',
              '--rule',
              'rules',
              multiple=True,
              type=click.Choice(RULE_CHOICES),
              help='Word-mangling rule to apply to each wordlist entry. Repeatable. Requires '
              '--wordlist.')
@click.option('--combinator',
              type=click.IntRange(min=2),
              help='Join this many words from --wordlist into each candidate (dictionary '
              'combinator). Requires --wordlist.')
@click.option('--separator',
              default='',
              help='Separator inserted between joined words when using --combinator.')
@click.option('--limit',
              type=click.IntRange(min=1),
              help='Stop after trying this many candidates, even if the keyspace is larger.')
@click.option('-b',
              '--backend',
              type=click.Choice(('auto', 'cpu', 'cuda', 'opencl')),
              default='auto',
              show_default=True,
              help='Which backend to use: auto prefers CUDA, then OpenCL, then the CPU.')
@click.option('--device',
              type=click.IntRange(min=0),
              default=0,
              show_default=True,
              help='Ordinal of the GPU device to use, as numbered by --list-devices. Ignored by '
              'the CPU backend.')
@click.option('--list-devices',
              is_flag=True,
              is_eager=True,
              expose_value=False,
              callback=_print_devices,
              help='List the CUDA and OpenCL devices with their ordinals and exit.')
@click.option('-j',
              '--jobs',
              type=click.IntRange(min=1),
              default=None,
              help='CPU worker processes (default: all cores). Ignored by the GPU backends.')
@click.option('-d', '--debug', is_flag=True, help='Enable debug logging of the search progress.')
@click.option('-q',
              '--quiet',
              is_flag=True,
              help='Suppress progress and status output; print only the password. Cannot be '
              'combined with --debug.')
@click.version_option()
def crack_main(archive: Path, wordlist: Path | None, charset: str, min_length: int, max_length: int,
               rules: tuple[str, ...], combinator: int | None, separator: str, limit: int | None,
               backend: str, device: int, jobs: int | None, *, debug: bool, quiet: bool) -> None:
    """
    Recover the password of an encrypted InstallBuilder installer by brute force.

    Prints the password and exits 0 when found, or exits 1 when the keyspace is exhausted. Without
    ``--wordlist`` the keyspace is every string over ``--charset`` from ``--min-length`` to
    ``--max-length``. With ``--wordlist`` the entries are tried directly, optionally expanded by
    ``--rule`` transforms and/or joined by ``--combinator``.
    """  # noqa: DOC501
    if debug and quiet:
        msg = '--debug and --quiet are mutually exclusive.'
        raise click.UsageError(msg)
    setup_logging(debug=debug,
                  loggers={
                      'destin.bitrock': {
                          'level': 'CRITICAL'
                      } if quiet else {},
                      'destin.common': {},
                  })
    if (rules or combinator is not None) and wordlist is None:
        msg = '--rule and --combinator require --wordlist.'
        raise click.UsageError(msg)
    source, total = _build_source(wordlist, charset, min_length, max_length,
                                  cast('tuple[Rule, ...]', rules), combinator, separator)
    if limit is not None:
        source = islice(source, limit)
        total = limit if total is None else min(total, limit)
    if total is not None and not quiet:
        click.echo(f'Searching {total:,} candidates.', err=True)
    # Track the running count for the final summary; also drive the live line unless debug or quiet.
    counter = {'tested': 0}

    def on_progress(tested: int, latest: bytes) -> None:
        counter['tested'] = tested
        if display is not None:
            display(tested, latest)

    display = None if (debug or quiet) else _progress_printer(total, time.monotonic())
    start = time.monotonic()
    resolved_jobs = jobs if jobs is not None else (os.cpu_count() or 1)
    try:
        found = crack(archive,
                      source,
                      backend=cast('Backend', backend),
                      on_progress=on_progress,
                      jobs=resolved_jobs,
                      device=device)
    except BitrockError as e:
        raise click.ClickException(str(e)) from e
    except KeyboardInterrupt:
        if display is not None:
            click.echo('', err=True)
        if not quiet:
            click.echo('Interrupted.', err=True)
        sys.stderr.flush()
        sys.stdout.flush()
        if backend == 'cpu':
            # The CPU pool has already torn down cleanly, so exit normally.
            raise click.exceptions.Exit(_SIGINT_EXIT_CODE) from None
        # A running CUDA kernel cannot be aborted, and normal shutdown blocks on the GPU context
        # teardown until the in-flight batch drains (tens of seconds). Exit immediately instead.
        os._exit(_SIGINT_EXIT_CODE)
    if display is not None:
        click.echo('', err=True)
    if found is None:
        if not quiet:
            click.echo('Password not found.', err=True)
        raise click.exceptions.Exit(1)
    if not quiet:
        elapsed = time.monotonic() - start
        rate = counter['tested'] / elapsed if elapsed > 0 else 0.0
        click.echo(
            f'Found after {counter["tested"]:,} candidates in {_format_duration(elapsed)} '
            f'({_format_rate(rate)}/s).',
            err=True)
    click.echo(found.decode(errors='backslashreplace'))
