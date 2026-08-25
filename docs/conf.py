"""See https://www.sphinx-doc.org/en/master/usage/configuration.html."""
from __future__ import annotations

from datetime import datetime, timezone
from operator import itemgetter
from pathlib import Path
from typing import Any
import sys

import tomlkit

with (Path(__file__).parent.parent / 'pyproject.toml').open(newline='\n', encoding='utf-8') as f:
    project_ = tomlkit.load(f).unwrap()['project']
    authors_list, name, version = itemgetter('authors', 'name', 'version')(project_)
authors = [f'{d["name"]} <{d["email"]}>' for d in authors_list]
# region Path setup
# If extensions (or modules to document with autodoc) are in another directory, add these
# directories to sys.path here. If the directory is relative to the documentation root, use
# str(Path().parent.parent) to make it absolute, like shown here.
sys.path.insert(0, str(Path(__file__).parent.parent))
# endregion
author = f'{authors_list[0]["name"]} <{authors_list[0]["email"]}>'
copyright = str(datetime.now(timezone.utc).year)  # ruff:ignore[builtin-variable-shadowing]
project = name
release = f'v{version}'
extensions = [
    'sphinx.ext.autodoc', 'sphinx.ext.graphviz', 'sphinx.ext.intersphinx', 'sphinx.ext.napoleon',
    'sphinx_datatables', 'sphinx_immaterial', 'sphinxcontrib.autodoc_pydantic',
    'sphinxcontrib.jquery'
]
extensions += ['sphinx_click']
graphviz_output_format = 'svg'
datatables_class = 'sphinx-datatable'
datatables_options = {'paging': False}
datatables_version = '1.13.4'
html_theme = 'sphinx_immaterial'
html_theme_options = {
    'edit_uri': '/tree/master/docs',
    'features': [
        'announce.dismiss', 'content.action.edit', 'content.action.view', 'content.code.copy',
        'content.tabs.link', 'content.tooltips', 'navigation.expand', 'navigation.footer',
        'navigation.sections', 'navigation.top', 'search.share', 'search.suggest', 'toc.follow',
        'toc.sticky'
    ],
    'font': False,
    'globaltoc_collapse': True,
    'icon': {
        'edit': 'material/file-edit-outline',
        'repo': 'fontawesome/brands/github'
    },
    'palette': [{
        'media': '(prefers-color-scheme)',
        'toggle': {
            'icon': 'material/brightness-auto',
            'name': 'Switch to light mode'
        }
    }, {
        'accent': 'light-blue',
        'media': '(prefers-color-scheme: light)',
        'primary': 'teal',
        'scheme': 'default',
        'toggle': {
            'icon': 'material/lightbulb',
            'name': 'Switch to dark mode'
        }
    }, {
        'accent': 'blue',
        'media': '(prefers-color-scheme: dark)',
        'primary': 'black',
        'scheme': 'slate',
        'toggle': {
            'icon': 'material/lightbulb-outline',
            'name': 'Switch to system preference'
        }
    }],
    'repo_name': 'dade',
    'repo_url': 'https://github.com/Tatsh/dade',
    'site_url': 'https://dade2.readthedocs.org',
    'toc_title_is_page_title': True
}
intersphinx_mapping = {
    'PIL': ('https://pillow.readthedocs.io/en/stable/', None),
    'click': ('https://click.palletsprojects.com/en/stable/', None),
    'cryptography': ('https://cryptography.io/en/stable/', None),
    'python': ('https://docs.python.org/3', None)
}

_MAX_DEFAULT_LENGTH = 20
"""Longest rendered parameter default kept verbatim before it is elided to ``...``."""


def _split_arguments(rendered: str) -> list[str]:
    """
    Split a rendered argument list on its top-level commas.

    Commas inside brackets or quotes (for example within a default value) do not split.

    Parameters
    ----------
    rendered : str
        The argument list without its surrounding parentheses.

    Returns
    -------
    list[str]
        One string per argument.
    """
    arguments: list[str] = []
    depth = 0
    quote = ''
    start = 0
    for index, char in enumerate(rendered):
        if quote:
            if char == quote and rendered[index - 1] != '\\':
                quote = ''
        elif char in '\'"':
            quote = char
        elif char in '([{':
            depth += 1
        elif char in ')]}':
            depth -= 1
        elif char == ',' and depth == 0:
            arguments.append(rendered[start:index])
            start = index + 1
    if rendered[start:].strip():
        arguments.append(rendered[start:])
    return arguments


def _default_separator(argument: str) -> int | None:
    """
    Return the index of an argument's default-value ``=``, or ``None`` when it has no default.

    Parameters
    ----------
    argument : str
        A single rendered argument (``name``, ``name: type``, or ``name: type = default``).

    Returns
    -------
    int | None
        The index of the ``=`` that introduces the default, or ``None``.
    """
    depth = 0
    quote = ''
    for index, char in enumerate(argument):
        if quote:
            if char == quote and argument[index - 1] != '\\':
                quote = ''
        elif char in '\'"':
            quote = char
        elif char in '([{':
            depth += 1
        elif char in ')]}':
            depth -= 1
        elif (char == '=' and depth == 0 and argument[index - 1] not in '=!<>'
              and (index + 1 >= len(argument) or argument[index + 1] != '=')):
            return index
    return None


def _elide_long_parameter_defaults(_app: object, _what: str, _name: str, _obj: object,
                                   _options: object, signature: str | None,
                                   return_annotation: str | None) -> tuple[str | None, str | None]:
    """
    Replace a documented signature's long default values with ``...``.

    Short defaults (for example ``1``, ``False``, ``'.txt'``) are kept; only defaults longer than
    :py:data:`_MAX_DEFAULT_LENGTH` (large tuples, byte keys, and the like) are elided. The already
    rendered signature string is edited in place so autodoc's type formatting is preserved.

    Parameters
    ----------
    _app : object
        The Sphinx application (unused).
    _what : str
        The kind of object being documented (unused).
    _name : str
        The object's fully qualified name (unused).
    _obj : object
        The object being documented (unused).
    _options : object
        The autodoc directive options (unused).
    signature : str | None
        The rendered parameter signature, or ``None``.
    return_annotation : str | None
        The rendered return annotation, or ``None``.

    Returns
    -------
    tuple[str | None, str | None]
        The signature with long defaults elided and the unchanged return annotation.
    """
    if not signature or '=' not in signature:
        return signature, return_annotation
    arguments = _split_arguments(signature[1:-1])
    changed = False
    for index, argument in enumerate(arguments):
        separator = _default_separator(argument)
        if separator is None:
            continue
        default = argument[separator + 1:]
        if len(default.strip()) > _MAX_DEFAULT_LENGTH:
            leading = default[:len(default) - len(default.lstrip())]
            arguments[index] = f'{argument[:separator + 1]}{leading}...'
            changed = True
    if not changed:
        return signature, return_annotation
    return f'({",".join(arguments)})', return_annotation


def setup(app: Any) -> None:
    """
    Register documentation build customisations.

    Parameters
    ----------
    app : typing.Any
        The Sphinx application to extend.
    """
    app.connect('autodoc-process-signature', _elide_long_parameter_defaults)
