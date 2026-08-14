"""
Reading of the ``SC_Info`` directory Apple puts inside a purchased ``.app`` bundle.

An App Store download carries its FairPlay bookkeeping in ``Payload/<App>.app/SC_Info``, beside the
encrypted executable. This reads that directory and describes it; it decrypts nothing, and none of
the material it prints is a key.

- ``Manifest.plist`` lists the supporting files, normally under ``SinfPaths`` and
  ``SinfReplicationPaths``.
- ``<App>.sinf`` is a QuickTime atom tree, the same ``sinf`` protection-scheme box a FairPlay MP4
  carries. Its ``schi`` holds the purchase record: the buying account's numeric identifier and
  name, the purchase and transaction times, an initialisation vector, a ``righ`` block of
  four-character tags, and the encrypted ``priv`` blob, with a signature over the lot in ``sign``.
- ``<App>.supf`` is a run of length-prefixed blocks: a four-byte magic, a 72-byte body carrying an
  identifier and a 32-byte key blob, a DER-encoded Apple FairPlay certificate, and a signature.
- ``<App>.supp`` mirrors it, with the same identifier, a counted table of 32-byte records whose
  last entry is the ``.supf`` key blob, a second and different Apple FairPlay certificate, and a
  signature.
- ``<App>.supx`` is a length-prefixed run of tagged entries closed by a zero terminator.

The ``.sinf`` is the only one of these with a published shape; the three supplements are described
from what two independently purchased bundles agree on. Every length prefix in them accounts for
the whole file with nothing left over, in both bundles, which is what the layouts above rest on.

What genuinely cannot be broken down further is the cryptographic material itself: the RSA
signatures, the ``.supf`` key blob, the ``.supp`` records, the ``.supx`` entry values, and the body
of ``priv``, which is ciphertext. Those are reported with their length and digest beside their
bytes. Two things are reported without being named: the four header words opening a ``.supf`` body,
and the eight bytes trailing ``righ``, which are byte for byte identical across both bundles.

Times are seconds since the QuickTime epoch of 1904-01-01 UTC, which is the only one of the usual
candidates that puts the sample bundles' purchase dates in the plausible past.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, NamedTuple
import hashlib
import plistlib
import re
import string
import struct

from .certificate import (
    CertificateSummary,
    certificate_lines,
    certificate_to_json,
    load_certificate,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence
    from pathlib import Path

__all__ = ('APP_STORE_REGION_URL', 'ATOM_DESCRIPTIONS', 'QUICKTIME_EPOCH', 'RIGHTS_TAGS',
           'STOREFRONTS', 'Atom', 'Right', 'ScInfo', 'Sinf', 'Supf', 'Supp', 'Supx', 'SupxEntry',
           'find_atom', 'iter_atoms', 'parse_atoms', 'parse_sinf', 'parse_supf', 'parse_supp',
           'parse_supx', 'read_sc_info', 'render_text', 'sc_info_to_json')

APP_STORE_REGION_URL = 'https://apps.apple.com/{region}/app/id{item}'
"""Template a regional store item identifier is turned into a link with.

:meta hide-value:
"""
STOREFRONTS: Mapping[int, str] = {
    143441: 'us',
    143442: 'fr',
    143443: 'de',
    143444: 'gb',
    143445: 'at',
    143446: 'be',
    143447: 'fi',
    143448: 'gr',
    143449: 'ie',
    143450: 'it',
    143451: 'lu',
    143452: 'nl',
    143453: 'pt',
    143454: 'es',
    143455: 'ca',
    143456: 'se',
    143457: 'no',
    143458: 'dk',
    143459: 'ch',
    143460: 'au',
    143461: 'nz',
    143462: 'jp',
    143463: 'hk',
    143464: 'sg',
    143465: 'cn',
    143466: 'kr',
    143467: 'in',
    143468: 'mx',
    143469: 'ru',
    143470: 'tw',
    143471: 'vn',
    143472: 'za',
    143473: 'my',
    143474: 'ph',
    143475: 'th',
    143476: 'id',
    143477: 'pk',
    143478: 'pl',
    143479: 'sa',
    143480: 'tr',
    143481: 'ae',
    143482: 'hu',
    143483: 'cl',
    143484: 'np',
    143485: 'pa',
    143486: 'lk',
    143487: 'ro',
    143489: 'cz',
    143491: 'il',
    143492: 'ua',
    143493: 'kw',
    143494: 'hr',
    143495: 'cr',
    143496: 'sk',
    143497: 'lb',
    143498: 'qa',
    143499: 'si',
    143501: 'co',
    143502: 've',
    143503: 'br',
    143504: 'gt',
    143505: 'ar',
    143506: 'sv',
    143507: 'pe',
    143508: 'do',
    143509: 'ec',
    143510: 'hn',
    143511: 'jm',
    143512: 'ni',
    143513: 'py',
    143514: 'uy',
    143515: 'mo',
    143516: 'eg',
    143517: 'kz',
    143518: 'ee',
    143519: 'lv',
    143520: 'lt',
    143521: 'mt',
    143523: 'md',
    143524: 'am',
    143525: 'bw',
    143526: 'bg',
    143528: 'jo',
    143529: 'ke',
    143530: 'mk',
    143531: 'mg',
    143532: 'ml',
    143533: 'mu',
    143534: 'ne',
    143535: 'sn',
    143536: 'tn',
    143537: 'ug',
    143538: 'ai',
    143539: 'bs',
    143540: 'ag',
    143541: 'bb',
    143542: 'bm',
    143543: 'vg',
    143544: 'ky',
    143545: 'dm',
    143546: 'gd',
    143547: 'ms',
    143548: 'kn',
    143549: 'lc',
    143550: 'vc',
    143551: 'tt',
    143552: 'tc',
    143553: 'gy',
    143554: 'sr',
    143555: 'bz',
    143556: 'bo',
    143557: 'cy',
    143558: 'is',
    143559: 'bh',
    143560: 'bn',
    143561: 'ng',
    143562: 'om',
    143563: 'dz',
    143564: 'ao',
    143565: 'by',
    143566: 'uz',
    143568: 'az',
    143571: 'ye',
    143572: 'tz',
    143573: 'gh',
    143575: 'al',
    143576: 'bj',
    143577: 'bt',
    143578: 'bf',
    143579: 'kh',
    143580: 'cv',
    143581: 'td',
    143582: 'cg',
    143583: 'fj',
    143584: 'gm',
    143585: 'gw',
    143586: 'kg',
    143587: 'la',
    143588: 'lr',
    143589: 'mw',
    143590: 'mr',
    143591: 'fm',
    143592: 'mn',
    143593: 'mz',
    143594: 'na',
    143595: 'pw',
    143597: 'pg',
    143598: 'st',
    143599: 'sc',
    143600: 'sl',
    143601: 'sb',
    143602: 'sz',
    143603: 'tj',
    143604: 'tm',
    143605: 'zw',
}
"""Apple storefront identifier to the country code its App Store links use.

:meta hide-value:
"""
QUICKTIME_EPOCH = datetime(1904, 1, 1, tzinfo=timezone.utc)
"""Epoch the ``sinf`` timestamps count seconds from.

:meta hide-value:
"""
ATOM_DESCRIPTIONS: Mapping[str, str] = {
    'asdt': 'Asset type',
    'crdt': 'Purchased',
    'frma': 'Original format',
    'iviv': 'Initialisation vector',
    'key ': 'Key index',
    'name': 'Account name',
    'priv': 'Private data',
    'righ': 'Rights',
    'schi': 'Scheme information',
    'schm': 'Scheme',
    'sign': 'Signature',
    'sinf': 'Protection scheme information',
    'user': 'Apple account ID',
}
"""Atom type to a readable description, for the ones an ``SC_Info`` ``.sinf`` carries.

:meta hide-value:
"""
RIGHTS_TAGS: Mapping[str, str] = {
    'aver': 'Application version',
    'plat': 'Platform',
    'song': 'Store item ID',
    'tool': 'Tool version',
    'tran': 'Transaction',
}
"""Rights tag to a readable description.

Only the tags two independently purchased bundles agree on the meaning of are described. The rest
are real tags whose meaning is not established here, and are reported without a gloss.

``plat`` is 5 in both sample bundles, which are both iOS applications, so 5 plausibly means iOS.
Two samples of the same platform cannot establish that, so the value is reported as it stands.

:meta hide-value:
"""

_ATOM_HEADER = 8
_MINIMUM_ATOM_SIZE = 8
_RIGHTS_PAIR_SIZE = 8
_TAG_SIZE = 4
_DATE_RIGHTS = ('tran',)
_TEXT_RIGHTS = ('tool',)
_VERSION_RIGHTS = ('aver',)
_PRINTABLE = frozenset(string.printable[:-5].encode())
_SUPX_HEADER = 8
_SUPF_BODY_LENGTH_OFFSET = 4
_SUPF_BODY_OFFSET = 8
_SUPF_BODY_SIZE = 72
_SUPF_HEADER_WORDS = 4
_SUPF_IDENTIFIER_IN_BODY = slice(0x10, 0x24)
_SUPF_KEY_BLOB_IN_BODY = slice(0x28, 0x48)
_SUPP_IDENTIFIER = slice(0x04, 0x18)
_SUPP_COUNT_OFFSET = 0x18
_SUPP_RECORDS_OFFSET = 0x1C
_SUPP_RECORD_SIZE = 32
_PRIVATE_BLOCK_SIZE = 16
_STORE_ITEM_TAG = 'song'
_DATE_ATOMS = ('crdt',)
_STOREFRONT_IN_COHORT = re.compile(r'sf=(\d+)')
_METADATA_NAME = 'iTunesMetadata.plist'
_METADATA_SEARCH_DEPTH = 5
_SC_INFO_NAME = 'SC_Info'
_PAYLOAD_NAME = 'Payload'
_APP_SUFFIX = '.app'
_TAG_TEXT_SIZE = 3
_SCHEME_TYPE = slice(4, 8)


class Atom(NamedTuple):
    """One QuickTime-style atom."""

    kind: str
    """The four-character type, trailing space included where the format has one."""
    offset: int
    """Where the atom starts in the file."""
    size: int
    """How many bytes the atom occupies, its eight-byte header included."""
    body: bytes
    """The atom's payload, header stripped."""
    children: tuple[Atom, ...]
    """Nested atoms, empty for a leaf."""
    @property
    def description(self) -> str | None:
        """
        A readable description of the atom's type.

        Returns
        -------
        str | None
            The description, or ``None`` for a type not described here.
        """
        return ATOM_DESCRIPTIONS.get(self.kind)


class Right(NamedTuple):
    """One tagged entry of a ``righ`` atom."""

    tag: str
    """The four-character tag."""
    raw: bytes
    """The four value bytes, exactly as stored."""
    @property
    def description(self) -> str | None:
        """
        A readable description of the tag.

        Returns
        -------
        str | None
            The description, or ``None`` for a tag whose meaning is not established here.
        """
        return RIGHTS_TAGS.get(self.tag)

    @property
    def rendered(self) -> str:
        """
        The value in the most informative form the tag allows.

        Returns
        -------
        str
            A date for a timestamp tag, quoted text for a text tag, a dotted quad for a version
            tag, and the unsigned integer otherwise.
        """
        if self.tag in _DATE_RIGHTS:
            return _quicktime_time(self.value).isoformat()
        if self.tag in _TEXT_RIGHTS and all(byte in _PRINTABLE for byte in self.raw):
            return repr(self.raw.decode('latin1'))
        if self.tag in _VERSION_RIGHTS:
            return '.'.join(str(byte) for byte in self.raw)
        return str(self.value)

    @property
    def value(self) -> int:
        """
        The value read as a big-endian unsigned integer.

        Returns
        -------
        int
            The value.
        """
        return int.from_bytes(self.raw, 'big')


class Sinf(NamedTuple):
    """A parsed ``.sinf`` purchase record."""

    atoms: tuple[Atom, ...]
    """The whole atom tree, for anything this does not surface directly."""
    original_format: str | None
    """The ``frma`` format the protection wraps, which is ``game`` for an application."""
    scheme: str | None
    """The ``schm`` scheme type, which is ``itun`` for a store purchase."""
    account_id: int | None
    """The buying Apple account's numeric identifier."""
    account_name: str | None
    """The buying Apple account's name, as it was at purchase time."""
    purchased: datetime | None
    """When the purchase was recorded."""
    asset_type: int | None
    """The ``asdt`` value."""
    key_index: int | None
    """The ``key`` value, which selects a key rather than being one."""
    initialisation_vector: bytes | None
    """The ``iviv`` block."""
    rights: tuple[Right, ...]
    """The decoded ``righ`` entries."""
    rights_trailer: bytes
    """Bytes after the last whole ``righ`` entry, reported rather than interpreted."""
    private: bytes | None
    """The opaque ``priv`` blob."""
    signature: bytes | None
    """The ``sign`` blob covering the record."""


class Supf(NamedTuple):
    """A parsed ``.supf`` supplement.

    The file is a run of length-prefixed blocks: a four-byte magic, then a body holding the
    identifier and key blob, then the certificate, then the signature over it.
    """

    version: int
    """The leading byte, 3 in every sample seen."""
    tag: str
    """The three printable bytes after it, such as ``507``."""
    header_words: tuple[int, ...]
    """The four ``uint32`` opening the body, whose meaning is not established here."""
    identifier: bytes
    """The 20-byte identifier the ``.supp`` repeats."""
    key_blob: bytes
    """The 32-byte block closing the body. Key material, so there is nothing inside it to read."""
    certificate: CertificateSummary | None
    """The embedded certificate's summary, when one could be read."""
    certificate_der: bytes | None
    """The embedded certificate, DER-encoded."""
    certificate_offset: int | None
    """Where the certificate starts in the file."""
    signature: bytes
    """The length-prefixed signature closing the file, 128 bytes for the 1024-bit keys seen."""
    trailer: bytes
    """Anything after the signature, which is empty in every sample seen."""


class Supp(NamedTuple):
    """A parsed ``.supp`` supplement.

    The layout mirrors the ``.supf``: the same identifier, then a counted table of fixed-size
    records, then a certificate and a signature.
    """

    version: int
    """The leading byte, 1 in every sample seen."""
    tag: str
    """The three printable bytes after it, matching the ``.supf``."""
    identifier: bytes
    """The 20-byte identifier the ``.supf`` carries too."""
    records: tuple[bytes, ...]
    """The 32-byte records, of which the last is the ``.supf`` key blob.

    Each is 256 bits of key material with nothing inside it to read: across both sample bundles no
    record repeats, none is shared between the two, and none is derivable from another or from
    anything else in the directory. Only their count varies, 17 against 8, which would fit one per
    entitled item with the app's own key last, though nothing in the files settles that.
    """
    certificate: CertificateSummary | None
    """The embedded certificate's summary, which is a different one from the ``.supf``'s."""
    certificate_der: bytes | None
    """The embedded certificate, DER-encoded."""
    certificate_offset: int | None
    """Where the certificate starts in the file."""
    signature: bytes
    """The signature closing the file, 128 bytes for the 1024-bit keys seen."""


class SupxEntry(NamedTuple):
    """One tagged entry of a ``.supx``."""

    tag: int
    """The entry's numeric tag."""
    value: bytes
    """The entry's bytes."""


class Supx(NamedTuple):
    """A parsed ``.supx`` supplement."""

    version: int
    """The leading ``uint32``."""
    length: int
    """The declared body length, which excludes the eight-byte header."""
    entries: tuple[SupxEntry, ...]
    """The tagged entries, up to the zero terminator."""
    trailer: bytes
    """Everything after the declared body."""


class ScInfo(NamedTuple):
    """Everything read out of one ``SC_Info`` directory."""

    path: Path
    """The directory itself."""
    manifest: dict[str, Any] | None
    """The parsed ``Manifest.plist``, when there is one."""
    sinf: Sinf | None
    """The parsed ``.sinf``, when there is one."""
    supf: Supf | None
    """The parsed ``.supf``, when there is one."""
    supp: Supp | None
    """The parsed ``.supp``, when there is one."""
    supx: Supx | None
    """The parsed ``.supx``, when there is one."""
    files: tuple[tuple[str, int, str], ...]
    """Every file in the directory as its name, size, and SHA-256, in name order."""
    metadata: dict[str, Any] | None
    """The bundle's ``iTunesMetadata.plist``, when one was found beside it."""
    region_override: str | None
    """A country code the caller supplied, for when nothing beside the bundle carries one."""
    @property
    def app_store_url(self) -> str | None:
        """
        The bundle's App Store link.

        A store item is only reachable in the storefront it was sold in, so the link needs the
        region and there is no valid region-less form of it. Without a storefront to read there is
        no link, and :attr:`store_item_id` is the most that can be said.

        Returns
        -------
        str | None
            The link, or ``None`` without both an item identifier and a known region.
        """
        item, region = self.store_item_id, self.region
        if item is None or region is None:
            return None
        return APP_STORE_REGION_URL.format(region=region, item=item)

    @property
    def region(self) -> str | None:
        """
        Country code of the storefront the bundle was bought from.

        A code the caller supplied wins, since only they can know it when nothing beside the
        bundle records it.

        Returns
        -------
        str | None
            The code, or ``None`` when the storefront is unknown or not one listed here.
        """
        if self.region_override is not None:
            return self.region_override
        return None if (front := self.storefront) is None else STOREFRONTS.get(front)

    @property
    def metadata_item_id(self) -> int | None:
        """
        The store item identifier the ``iTunesMetadata.plist`` carries.

        Returns
        -------
        int | None
            The identifier, or ``None`` without metadata carrying one.
        """
        if self.metadata is not None and isinstance(self.metadata.get('itemId'), int):
            return int(self.metadata['itemId'])
        return None

    @property
    def record_item_id(self) -> int | None:
        """
        The store item identifier the purchase record's ``song`` tag carries.

        Returns
        -------
        int | None
            The identifier, or ``None`` without a record carrying one.
        """
        if self.sinf is None:
            return None
        return next((right.value for right in self.sinf.rights if right.tag == _STORE_ITEM_TAG),
                    None)

    @property
    def store_item_id(self) -> int | None:
        """
        The store item identifier.

        The purchase record wins over the metadata, because it sits inside the bundle and so is
        bound to it, whereas the metadata sits outside and could belong to something else. Where
        both are present and disagree, the cross-references say so.

        Returns
        -------
        int | None
            The identifier, or ``None`` when neither carries one.
        """
        return self.record_item_id if self.record_item_id is not None else self.metadata_item_id

    @property
    def storefront(self) -> int | None:
        """
        The Apple storefront identifier the bundle was bought from.

        This comes from the ``iTunesMetadata.plist`` beside the bundle; the ``SC_Info`` directory
        itself carries no storefront anywhere.

        Returns
        -------
        int | None
            The identifier, or ``None`` without metadata to read it from.
        """
        if self.metadata is None:
            return None
        if isinstance(value := self.metadata.get('s'), int):
            return value
        # Older metadata puts it only in the cohort string, as ``sf=<id>``.
        cohort = self.metadata.get('storeCohort')
        if isinstance(cohort, str) and (match := _STOREFRONT_IN_COHORT.search(cohort)):
            return int(match.group(1))
        return None


def _quicktime_time(seconds: int) -> datetime:
    """
    Convert a QuickTime timestamp to a date.

    The whole ``uint32`` range these fields hold lands between 1904 and 2040, so no value one can
    carry falls outside what :py:mod:`datetime` covers.

    Parameters
    ----------
    seconds : int
        Seconds since 1904-01-01 UTC.

    Returns
    -------
    datetime.datetime
        The date.
    """
    return QUICKTIME_EPOCH + timedelta(seconds=seconds)


def parse_atoms(data: bytes, base: int = 0) -> tuple[Atom, ...]:
    """
    Parse a QuickTime-style atom tree.

    An atom is a big-endian ``uint32`` size then a four-byte type, and the walk stops at the first
    header that cannot be one rather than guessing past it.

    Parameters
    ----------
    data : bytes
        The buffer to parse.
    base : int
        File offset the buffer starts at, so that reported offsets are absolute.

    Returns
    -------
    tuple[Atom, ...]
        The atoms at this level, each carrying whatever nested atoms it holds.
    """
    atoms: list[Atom] = []
    offset = 0
    while offset + _ATOM_HEADER <= len(data):
        size, raw_kind = struct.unpack_from('>I4s', data, offset)
        if size < _MINIMUM_ATOM_SIZE or offset + size > len(data):
            break
        kind = raw_kind.decode('latin1')
        if not all(byte in _PRINTABLE for byte in raw_kind):
            break
        body = data[offset + _ATOM_HEADER:offset + size]
        atoms.append(
            Atom(kind, base + offset, size, body,
                 parse_atoms(body, base + offset + _ATOM_HEADER) if _looks_nested(body) else ()))
        offset += size
    return tuple(atoms)


def _looks_nested(body: bytes) -> bool:
    """
    Decide whether an atom's payload starts with another atom.

    Parameters
    ----------
    body : bytes
        The payload.

    Returns
    -------
    bool
        ``True`` when the first eight bytes are a plausible atom header that fits.
    """
    if len(body) < _ATOM_HEADER:
        return False
    size, raw_kind = struct.unpack_from('>I4s', body, 0)
    return (_MINIMUM_ATOM_SIZE <= size <= len(body)
            and all(byte in _PRINTABLE for byte in raw_kind))


def iter_atoms(atoms: Sequence[Atom]) -> Iterator[Atom]:
    """
    Walk an atom tree depth first.

    Parameters
    ----------
    atoms : Sequence[Atom]
        The atoms to walk.

    Yields
    ------
    Atom
        Every atom, parents before their children.
    """
    for atom in atoms:
        yield atom
        yield from iter_atoms(atom.children)


def find_atom(atoms: Sequence[Atom], kind: str) -> Atom | None:
    """
    Find the first atom of a given type anywhere in a tree.

    Parameters
    ----------
    atoms : Sequence[Atom]
        The atoms to search.
    kind : str
        The four-character type, trailing space included where the format has one.

    Returns
    -------
    Atom | None
        The atom, or ``None`` when the tree holds none of that type.
    """
    return next((atom for atom in iter_atoms(atoms) if atom.kind == kind), None)


def _atom_uint32(atoms: Sequence[Atom], kind: str) -> int | None:
    """
    Read an atom whose whole payload is one big-endian ``uint32``.

    Parameters
    ----------
    atoms : Sequence[Atom]
        The atoms to search.
    kind : str
        The atom's type.

    Returns
    -------
    int | None
        The value, or ``None`` when the atom is absent or the wrong size.
    """
    atom = find_atom(atoms, kind)
    if atom is None or len(atom.body) < _TAG_SIZE:
        return None
    return int(struct.unpack_from('>I', atom.body, 0)[0])


def _parse_rights(body: bytes) -> tuple[tuple[Right, ...], bytes]:
    """
    Split a ``righ`` payload into its tagged entries.

    Parsing stops at the first tag that is not printable, because the eight bytes at the end of
    every sample are not a tagged entry.

    Parameters
    ----------
    body : bytes
        The atom's payload.

    Returns
    -------
    tuple[tuple[Right, ...], bytes]
        The entries and whatever followed them.
    """
    rights: list[Right] = []
    offset = 0
    while offset + _RIGHTS_PAIR_SIZE <= len(body):
        tag = body[offset:offset + _TAG_SIZE]
        if not all(byte in _PRINTABLE for byte in tag):
            break
        rights.append(
            Right(tag.decode('latin1'), body[offset + _TAG_SIZE:offset + _RIGHTS_PAIR_SIZE]))
        offset += _RIGHTS_PAIR_SIZE
    return tuple(rights), body[offset:]


def parse_sinf(data: bytes) -> Sinf:
    """
    Parse a ``.sinf`` purchase record.

    Parameters
    ----------
    data : bytes
        The file's contents.

    Returns
    -------
    Sinf
        The parsed record. Fields whose atoms are absent come back as ``None``, so a truncated or
        unfamiliar record still yields whatever it does carry.

    Raises
    ------
    ValueError
        If the file holds no atoms at all, so it is not a ``.sinf``.
    """
    atoms = parse_atoms(data)
    if not atoms:
        msg = f'Not a sinf: no atom header at the start of {len(data)} bytes.'
        raise ValueError(msg)
    frma = find_atom(atoms, 'frma')
    schm = find_atom(atoms, 'schm')
    name = find_atom(atoms, 'name')
    iviv = find_atom(atoms, 'iviv')
    priv = find_atom(atoms, 'priv')
    sign = find_atom(atoms, 'sign')
    righ = find_atom(atoms, 'righ')
    rights, trailer = _parse_rights(righ.body) if righ is not None else ((), b'')
    created = _atom_uint32(atoms, 'crdt')
    return Sinf(
        atoms,
        frma.body.decode('latin1').strip('\0') if frma is not None else None,
        (schm.body[_SCHEME_TYPE].decode('latin1')
         if schm is not None and len(schm.body) >= _SCHEME_TYPE.stop else None),
        _atom_uint32(atoms, 'user'),
        name.body.split(b'\0', 1)[0].decode('utf-8', errors='replace')
        if name is not None else None,
        _quicktime_time(created) if created is not None else None, _atom_uint32(atoms, 'asdt'),
        _atom_uint32(atoms, 'key '), iviv.body if iviv is not None else None, rights, trailer,
        priv.body if priv is not None else None, sign.body if sign is not None else None)


def _leading_tag(data: bytes) -> tuple[int, str]:
    """
    Read the one-byte version and three-byte tag a supplement file starts with.

    Parameters
    ----------
    data : bytes
        The file's contents.

    Returns
    -------
    tuple[int, str]
        The version byte and the tag, the latter empty when it is not printable.
    """
    if len(data) < 1 + _TAG_TEXT_SIZE:
        return (data[0] if data else 0), ''
    tag = data[1:1 + _TAG_TEXT_SIZE]
    return data[0], tag.decode('latin1') if all(byte in _PRINTABLE for byte in tag) else ''


def parse_supf(data: bytes) -> Supf:
    """
    Parse a ``.supf`` supplement.

    Parameters
    ----------
    data : bytes
        The file's contents.

    Returns
    -------
    Supf
        The parsed supplement, with the embedded certificate summarised when one is present.

    Raises
    ------
    ValueError
        If the file is too short, or its length prefixes do not agree with its size.
    """
    if len(data) < _SUPF_BODY_OFFSET + _SUPF_BODY_SIZE + 4:
        msg = f'Too short for a supf: {len(data)} bytes.'
        raise ValueError(msg)
    version, tag = _leading_tag(data)
    body_length = struct.unpack_from('>I', data, _SUPF_BODY_LENGTH_OFFSET)[0]
    certificate_length_offset = _SUPF_BODY_OFFSET + body_length
    if certificate_length_offset + 4 > len(data):
        msg = (f'Body length {body_length} runs past the end of a supf of {len(data)} bytes.')
        raise ValueError(msg)
    body = data[_SUPF_BODY_OFFSET:certificate_length_offset]
    words = (struct.unpack_from('>4I', body, 0) if len(body) >= _SUPF_HEADER_WORDS * 4 else ())
    certificate_length = struct.unpack_from('>I', data, certificate_length_offset)[0]
    certificate_offset = certificate_length_offset + 4
    der = data[certificate_offset:certificate_offset + certificate_length]
    certificate = None
    if len(der) == certificate_length and certificate_length:
        try:
            certificate = load_certificate(der)
        except ValueError:
            der = b''
    signature_offset = certificate_offset + certificate_length
    signature = b''
    if signature_offset + 4 <= len(data):
        signature_length = struct.unpack_from('>I', data, signature_offset)[0]
        signature = data[signature_offset + 4:signature_offset + 4 + signature_length]
    return Supf(version, tag, words, body[_SUPF_IDENTIFIER_IN_BODY], body[_SUPF_KEY_BLOB_IN_BODY],
                certificate, der or None, certificate_offset if der else None, signature,
                data[signature_offset + 4 + len(signature):] if signature else b'')


def parse_supp(data: bytes) -> Supp:
    """
    Parse a ``.supp`` supplement.

    Parameters
    ----------
    data : bytes
        The file's contents.

    Returns
    -------
    Supp
        The parsed supplement.

    Raises
    ------
    ValueError
        If the file is too short, or its record count runs past the end of it.
    """
    if len(data) < _SUPP_RECORDS_OFFSET:
        msg = f'Too short for a supp: {len(data)} bytes.'
        raise ValueError(msg)
    version, tag = _leading_tag(data)
    count = struct.unpack_from('>I', data, _SUPP_COUNT_OFFSET)[0]
    records_end = _SUPP_RECORDS_OFFSET + count * _SUPP_RECORD_SIZE
    if records_end > len(data):
        msg = (f'{count} records of {_SUPP_RECORD_SIZE} bytes run past the end of a supp of '
               f'{len(data)} bytes.')
        raise ValueError(msg)
    records = tuple(data[_SUPP_RECORDS_OFFSET + index * _SUPP_RECORD_SIZE:_SUPP_RECORDS_OFFSET +
                         (index + 1) * _SUPP_RECORD_SIZE] for index in range(count))
    certificate = None
    der = b''
    certificate_offset = None
    signature = b''
    if records_end + 4 <= len(data):
        certificate_length = struct.unpack_from('>I', data, records_end)[0]
        candidate = data[records_end + 4:records_end + 4 + certificate_length]
        if len(candidate) == certificate_length and certificate_length:
            try:
                certificate = load_certificate(candidate)
            except ValueError:
                certificate = None
            else:
                der = candidate
                certificate_offset = records_end + 4
                signature = data[records_end + 4 + certificate_length:]
    return Supp(version, tag, data[_SUPP_IDENTIFIER], records, certificate, der or None,
                certificate_offset, signature)


def parse_supx(data: bytes) -> Supx:
    """
    Parse a ``.supx`` supplement, which is a header then tagged entries.

    Parameters
    ----------
    data : bytes
        The file's contents.

    Returns
    -------
    Supx
        The parsed supplement.

    Raises
    ------
    ValueError
        If the file is too short to hold the header.
    """
    if len(data) < _SUPX_HEADER:
        msg = f'Too short for a supx: {len(data)} bytes.'
        raise ValueError(msg)
    version, length = struct.unpack_from('>II', data, 0)
    entries: list[SupxEntry] = []
    offset = _SUPX_HEADER
    end = min(_SUPX_HEADER + length, len(data))
    while offset + _SUPX_HEADER <= end:
        tag, size = struct.unpack_from('>II', data, offset)
        if tag == 0 and size == 0:
            offset += _SUPX_HEADER
            break
        if offset + _SUPX_HEADER + size > end:
            break
        entries.append(SupxEntry(tag, data[offset + _SUPX_HEADER:offset + _SUPX_HEADER + size]))
        offset += _SUPX_HEADER + size
    return Supx(version, length, tuple(entries), data[offset:])


def _locate(path: Path) -> Path:
    """
    Resolve whatever the caller pointed at to an ``SC_Info`` directory.

    The ``SC_Info`` directory, the ``.app`` bundle holding it, the ``Payload`` directory holding
    that, and a directory holding ``Payload`` all work, so an unpacked ``.ipa`` can be named at
    whichever level is to hand.

    Parameters
    ----------
    path : pathlib.Path
        The directory to start from.

    Returns
    -------
    pathlib.Path
        The ``SC_Info`` directory.

    Raises
    ------
    ValueError
        If no ``SC_Info`` directory can be reached from there, or a ``Payload`` directory holds
        anything other than exactly one bundle.
    """
    if path.name == _SC_INFO_NAME and path.is_dir():
        return path
    if (direct := path / _SC_INFO_NAME).is_dir():
        return direct
    payload = path if path.name == _PAYLOAD_NAME else path / _PAYLOAD_NAME
    if payload.is_dir():
        bundles = sorted(
            entry for entry in payload.iterdir() if entry.is_dir() and entry.suffix == _APP_SUFFIX)
        if not bundles:
            msg = f'No {_APP_SUFFIX} bundle in {payload}.'
            raise ValueError(msg)
        if len(bundles) > 1:
            names = ', '.join(bundle.name for bundle in bundles)
            msg = f'{payload} holds {len(bundles)} bundles, not one: {names}.'
            raise ValueError(msg)
        if (found := bundles[0] / _SC_INFO_NAME).is_dir():
            return found
        msg = f'No {_SC_INFO_NAME} directory in {bundles[0]}.'
        raise ValueError(msg)
    msg = (f'No {_SC_INFO_NAME} directory at or below {path}; name the SC_Info directory, the '
           f'bundle, the {_PAYLOAD_NAME} directory, or the directory holding it.')
    raise ValueError(msg)


def _find_metadata(directory: Path) -> dict[str, Any] | None:
    """
    Read the ``iTunesMetadata.plist`` sitting beside the bundle, if there is one.

    In an unpacked ``.ipa`` the file sits next to ``Payload``, two levels above the ``.app``, so
    the search walks up from the ``SC_Info`` directory rather than looking in one fixed place.

    Parameters
    ----------
    directory : pathlib.Path
        The ``SC_Info`` directory.

    Returns
    -------
    dict[str, Any] | None
        The parsed plist, or ``None`` when there is none or it does not parse.
    """
    for parent in [directory, *directory.parents][:_METADATA_SEARCH_DEPTH]:
        candidate = parent / _METADATA_NAME
        if not candidate.is_file():
            continue
        try:
            loaded = plistlib.loads(candidate.read_bytes())
        except (OSError, plistlib.InvalidFileException):
            return None
        return loaded if isinstance(loaded, dict) else None
    return None


def read_sc_info(path: Path, region: str | None = None) -> ScInfo:
    """
    Read an ``SC_Info`` directory.

    Parameters
    ----------
    path : pathlib.Path
        The ``SC_Info`` directory, the ``.app`` bundle holding it, the ``Payload`` directory
        holding that, or a directory holding ``Payload``.
    region : str | None
        A country code to build the App Store link with, for a bundle with no
        ``iTunesMetadata.plist`` beside it to read the storefront from.

    Returns
    -------
    ScInfo
        Everything that could be read. A file that is absent, and a file that is present but
        unreadable, both leave their field ``None``, so a partial directory still describes itself.

    Notes
    -----
    A path with no ``SC_Info`` directory at or below it raises the :py:class:`ValueError` the
    lookup raises.
    """
    directory = _locate(path)
    files = tuple((entry.name, entry.stat().st_size, hashlib.sha256(entry.read_bytes()).hexdigest())
                  for entry in sorted(directory.iterdir()) if entry.is_file())
    manifest = None
    if (plist := directory / 'Manifest.plist').is_file():
        try:
            loaded = plistlib.loads(plist.read_bytes())
        except plistlib.InvalidFileException:
            loaded = None
        manifest = loaded if isinstance(loaded, dict) else None
    return ScInfo(directory, manifest, _read_one(directory, '*.sinf', parse_sinf),
                  _read_one(directory, '*.supf', parse_supf),
                  _read_one(directory, '*.supp', parse_supp),
                  _read_one(directory, '*.supx', parse_supx), files, _find_metadata(directory),
                  region)


def _read_one(directory: Path, pattern: str, parse: Callable[[bytes], Any]) -> Any:
    """
    Read and parse the single file matching a pattern, if there is one.

    Parameters
    ----------
    directory : pathlib.Path
        The directory to look in.
    pattern : str
        The glob to match.
    parse : Callable[[bytes], Any]
        The parser to hand the bytes to. The return type follows the parser, which is why this is
        annotated loosely; each call site knows what it asked for.

    Returns
    -------
    Any
        The parsed file, or ``None`` when it is absent or does not parse.
    """
    found = sorted(directory.glob(pattern))
    if not found:
        return None
    try:
        return parse(found[0].read_bytes())
    except (OSError, ValueError):
        return None


def _digest(data: bytes) -> str:
    """
    Summarise an opaque blob for the text report.

    Parameters
    ----------
    data : bytes
        The blob.

    Returns
    -------
    str
        Its length and the start of its SHA-256.
    """
    return f'{len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()}'


def _split_private(private: bytes) -> tuple[bytes, bytes]:
    """
    Split the ``priv`` blob into its ciphertext and the zero bytes after it.

    Both sample bundles carry 432 bytes, a whole number of 16-byte cipher blocks matching the
    record's own initialisation vector, inside a 440-byte field. What is inside the ciphertext
    cannot be read without the key, but where it ends can be.

    Parameters
    ----------
    private : bytes
        The whole ``priv`` payload.

    Returns
    -------
    tuple[bytes, bytes]
        The ciphertext rounded up to a whole block, and the zero bytes filling the rest.
    """
    body = len(private.rstrip(b'\0'))
    aligned = min(body + (-body % _PRIVATE_BLOCK_SIZE), len(private))
    return private[:aligned], private[aligned:]


def _lines(pairs: Sequence[tuple[str, str]], indent: str = '  ') -> list[str]:
    """
    Lay out label and value pairs in an aligned column.

    Parameters
    ----------
    pairs : Sequence[tuple[str, str]]
        The pairs to lay out.
    indent : str
        Text put before each label.

    Returns
    -------
    list[str]
        One line per pair.
    """
    if not pairs:
        return []
    width = max(len(label) for label, _ in pairs)
    return [f'{indent}{label.ljust(width)}  {value}' for label, value in pairs]


def _sinf_lines(sinf: Sinf) -> list[str]:
    """
    Render a purchase record.

    Parameters
    ----------
    sinf : Sinf
        The record.

    Returns
    -------
    list[str]
        The report's lines for it.
    """
    pairs: list[tuple[str, str]] = []
    if sinf.original_format is not None:
        pairs.append(('Original format', sinf.original_format))
    if sinf.scheme is not None:
        pairs.append(('Scheme', sinf.scheme))
    if sinf.account_id is not None:
        pairs.append(('Apple account ID', f'{sinf.account_id} ({sinf.account_id:#010x})'))
    if sinf.account_name:
        pairs.append(('Account name', sinf.account_name))
    if sinf.purchased is not None:
        pairs.append(('Purchased', sinf.purchased.isoformat()))
    if sinf.asset_type is not None:
        pairs.append(('Asset type', str(sinf.asset_type)))
    if sinf.key_index is not None:
        pairs.append(('Key index', str(sinf.key_index)))
    if sinf.initialisation_vector is not None:
        pairs.append(('Initialisation vector', sinf.initialisation_vector.hex()))
    if sinf.private is not None:
        body, padding = _split_private(sinf.private)
        blocks = len(body) // _PRIVATE_BLOCK_SIZE
        pairs.extend((('Private data', (f'{len(sinf.private)} bytes: {len(body)} of ciphertext '
                                        f'({blocks} blocks) then {len(padding)} zero')),
                      ('Private ciphertext', _digest(body))))
    if sinf.signature is not None:
        pairs.append(('Signature', _digest(sinf.signature)))
    lines = _lines(pairs)
    if sinf.rights:
        lines.append('  Rights')
        width = max(len(right.description or '') for right in sinf.rights)
        for right in sinf.rights:
            gloss = (right.description or '').ljust(width)
            lines.append(f'    {right.tag}  {gloss}  {right.raw.hex()}  {right.rendered}')
        if sinf.rights_trailer:
            lines.append(f'    (trailing {len(sinf.rights_trailer)} bytes: '
                         f'{sinf.rights_trailer.hex()})')
    lines.append('  Atoms')
    lines += _atom_lines(sinf.atoms)
    return lines


def _atom_lines(atoms: Sequence[Atom], depth: int = 0) -> list[str]:
    """
    Render an atom tree, indenting each level.

    Parameters
    ----------
    atoms : Sequence[Atom]
        The atoms at this level.
    depth : int
        How deep this level is, which sets the indent.

    Returns
    -------
    list[str]
        One line per atom, children following their parent.
    """
    lines: list[str] = []
    for atom in atoms:
        gloss = f'  {atom.description}' if atom.description else ''
        value = ''
        if not atom.children:
            number = (int.from_bytes(atom.body, 'big') if len(atom.body) == _TAG_SIZE else None)
            if (as_text := _atom_text(atom.body)) is not None:
                value = f' = {as_text!r}'
            elif number is not None and atom.kind in _DATE_ATOMS:
                value = f' = {_quicktime_time(number).isoformat()}'
            elif number is not None:
                value = f' = {number} ({number:#010x})'
        lines.append(f'    {"  " * depth}{atom.kind!r} at {atom.offset:#06x}, '
                     f'{atom.size} bytes{gloss}{value}')
        lines += _atom_lines(atom.children, depth + 1)
    return lines


def _cross_references(info: ScInfo) -> list[tuple[str, str, bool]]:
    """
    Check the relationships the parts of a bundle have with each other.

    Both sample bundles agree on all of these, so a mismatch means the files do not belong
    together.

    Parameters
    ----------
    info : ScInfo
        The directory to check.

    Returns
    -------
    list[tuple[str, str, bool]]
        A key, a description, and the result, for each relationship both sides are present for.
    """
    references: list[tuple[str, str, bool]] = []
    if info.supf is not None and info.supp is not None:
        references += [
            ('identifiersMatch', '.supf and .supp identifiers match',
             info.supf.identifier == info.supp.identifier),
            ('keyBlobIsLastRecord', '.supf key blob is the last .supp record',
             bool(info.supp.records) and info.supp.records[-1] == info.supf.key_blob),
        ]
    if info.metadata_item_id is not None and info.record_item_id is not None:
        references.append(
            ('metadataItemIdMatchesRecord', 'metadata item ID matches the purchase record',
             info.metadata_item_id == info.record_item_id))
    return references


def _header_lines(info: ScInfo) -> list[str]:
    """
    Render the report's opening lines.

    Parameters
    ----------
    info : ScInfo
        The directory to render.

    Returns
    -------
    list[str]
        The path, the store item, the storefront, and the App Store link, as far as each is known.
    """
    lines = [f'SC_Info: {info.path}']
    if (item := info.store_item_id) is not None:
        lines.append(f'Store item ID: {item}')
    if (front := info.storefront) is not None:
        lines.append(f'Storefront: {front} ({info.region or "unknown region"})')
    if (url := info.app_store_url) is not None:
        lines.append(f'App Store URL: {url}')
    elif item is not None:
        lines.append(
            'App Store URL: unknown; no storefront was found, so pass a country code to build one')
    return lines


def render_text(info: ScInfo) -> str:
    """
    Render an ``SC_Info`` directory as a human-readable report.

    Parameters
    ----------
    info : ScInfo
        The directory to render.

    Returns
    -------
    str
        The report, ending in a newline.
    """
    lines = _header_lines(info)
    lines += ['', 'Files']
    lines += _lines([(name, f'{size} bytes, sha256 {digest}') for name, size, digest in info.files])
    if info.manifest is not None:
        lines += ['', 'Manifest.plist']
        lines += _lines([(key, ', '.join(value) if isinstance(value, list) else str(value))
                         for key, value in sorted(info.manifest.items())])
    if info.sinf is not None:
        lines += ['', 'Purchase record (.sinf)']
        lines += _sinf_lines(info.sinf)
    if info.supf is not None:
        lines += ['', 'Supplement (.supf)']
        pairs = [
            ('Version', str(info.supf.version)),
            ('Tag', info.supf.tag),
            ('Header words', ', '.join(f'{word:#x}' for word in info.supf.header_words)),
            ('Identifier', info.supf.identifier.hex()),
            ('Key blob', _digest(info.supf.key_blob)),
        ]
        if info.supf.certificate_der is not None and info.supf.certificate_offset is not None:
            pairs.append(('Certificate', (f'{len(info.supf.certificate_der)} bytes at '
                                          f'{info.supf.certificate_offset:#06x}')))
        if info.supf.signature:
            pairs.append(('Signature', _digest(info.supf.signature)))
        if info.supf.trailer:
            pairs.append(('Trailer', _digest(info.supf.trailer)))
        lines += _lines(pairs)
        if (certificate := info.supf.certificate) is not None:
            lines.append('  Certificate')
            lines += certificate_lines(certificate)
    if info.supp is not None:
        lines += ['', 'Supplement (.supp)']
        pairs = [('Version', str(info.supp.version)), ('Tag', info.supp.tag),
                 ('Identifier', info.supp.identifier.hex()),
                 ('Records', f'{len(info.supp.records)} of {_SUPP_RECORD_SIZE} bytes')]
        if info.supp.certificate_der is not None and info.supp.certificate_offset is not None:
            pairs.append(('Certificate', (f'{len(info.supp.certificate_der)} bytes at '
                                          f'{info.supp.certificate_offset:#06x}')))
        if info.supp.signature:
            pairs.append(('Signature', _digest(info.supp.signature)))
        lines += _lines(pairs)
        for index, record in enumerate(info.supp.records):
            lines.append(f'    [{index:3d}]  {record.hex()}')
        if (certificate := info.supp.certificate) is not None:
            lines.append('  Certificate')
            lines += certificate_lines(certificate)
    if info.supx is not None:
        lines += ['', 'Supplement (.supx)']
        lines += _lines([('Version', str(info.supx.version)),
                         ('Body length', str(info.supx.length))])
        for entry in info.supx.entries:
            lines.append(f'    tag {entry.tag}  {len(entry.value)} bytes  {entry.value.hex()}')
        if info.supx.trailer:
            lines += _lines([('Trailer', info.supx.trailer.hex())])
    if references := _cross_references(info):
        lines += ['', 'Cross-references']
        lines += _lines(
            [(description, 'yes' if held else 'no') for _, description, held in references])
    return '\n'.join(lines) + '\n'


def _private_to_json(private: bytes | None) -> dict[str, Any] | None:
    """
    Render the ``priv`` blob as its ciphertext and the zero bytes after it.

    Parameters
    ----------
    private : bytes | None
        The whole payload, or ``None`` when the record has no ``priv`` atom.

    Returns
    -------
    dict[str, Any] | None
        The two parts and the ciphertext's block count, or ``None``.
    """
    if private is None:
        return None
    body, padding = _split_private(private)
    return {
        'length': len(private),
        'blockSize': _PRIVATE_BLOCK_SIZE,
        'blocks': len(body) // _PRIVATE_BLOCK_SIZE,
        'ciphertext': body.hex(),
        'zeroPadding': padding.hex(),
    }


def _atom_text(body: bytes) -> str | None:
    """
    Read an atom's payload as text, when the whole of it is text.

    The trailing NUL padding a fixed-size field carries is stripped first, but a payload with bytes
    that are not printable anywhere inside it is not text at all and yields nothing.

    Parameters
    ----------
    body : bytes
        The payload.

    Returns
    -------
    str | None
        The text, or ``None`` when the payload is not wholly printable.
    """
    stripped = body.rstrip(b'\0')
    if not stripped or not all(byte in _PRINTABLE for byte in stripped):
        return None
    return stripped.decode('latin1')


def _right_to_json(right: Right) -> dict[str, Any]:
    """
    Render one rights entry as JSON-ready values.

    Parameters
    ----------
    right : Right
        The entry.

    Returns
    -------
    dict[str, Any]
        The tag, its description where there is one, the value, and a readable rendering of
        the value where that says more than the integer does.
    """
    rendered: dict[str, Any] = {'tag': right.tag}
    if right.description is not None:
        rendered['description'] = right.description
    rendered['uint32'] = right.value
    # Only worth giving where it says something the integer does not, such as a date or a string.
    if right.rendered != str(right.value):
        rendered['rendered'] = right.rendered
    return rendered


def _decoded_atom_body(atom: Atom) -> dict[str, Any] | None:
    """
    Break down the atoms whose payload is neither plain text nor one unsigned integer.

    Parameters
    ----------
    atom : Atom
        The leaf atom.

    Returns
    -------
    dict[str, Any] | None
        The decoded fields, or ``None`` for an atom with nothing to break down.
    """
    if atom.kind == 'righ':
        rights, trailer = _parse_rights(atom.body)
        decoded: dict[str, Any] = {'rights': [_right_to_json(right) for right in rights]}
        if trailer:
            decoded['trailer'] = trailer.hex()
        return decoded
    if atom.kind == 'schm' and len(atom.body) >= _SCHEME_TYPE.stop:
        return {
            'version': int.from_bytes(atom.body[:4], 'big'),
            'schemeType': atom.body[_SCHEME_TYPE].decode('latin1'),
            'schemeVersion': int.from_bytes(atom.body[_SCHEME_TYPE.stop:], 'big'),
        }
    if atom.kind == 'iviv':
        return {'bytes': list(atom.body)}
    return None


def _atom_to_json(atom: Atom) -> dict[str, Any]:
    """
    Render one atom as JSON-ready values.

    A container carries its children. A leaf carries its payload read as text or as an unsigned
    integer where it is one of those, and the raw bytes only where it is neither, since the hex
    would otherwise just repeat the decoded value.

    Offsets and sizes are left to :func:`render_text`, whose tree is the structural map; here they
    would only restate where the walk already put each atom.

    Parameters
    ----------
    atom : Atom
        The atom.

    Returns
    -------
    dict[str, Any]
        The rendered atom.
    """
    rendered: dict[str, Any] = {'type': atom.kind}
    if atom.description is not None:
        rendered['description'] = atom.description
    if atom.children:
        rendered['children'] = [_atom_to_json(child) for child in atom.children]
        return rendered
    if (decoded := _decoded_atom_body(atom)) is not None:
        rendered.update(decoded)
    elif (as_text := _atom_text(atom.body)) is not None:
        rendered['text'] = as_text
    elif len(atom.body) == _TAG_SIZE:
        number = int.from_bytes(atom.body, 'big')
        rendered['uint32'] = number
        if atom.kind in _DATE_ATOMS:
            rendered['iso8601'] = _quicktime_time(number).isoformat()
    else:
        # Nothing was decoded, so the bytes themselves are all there is to give, and their count
        # is worth stating beside them.
        rendered['bodySize'] = len(atom.body)
        rendered['body'] = atom.body.hex()
    return rendered


def sc_info_to_json(info: ScInfo) -> dict[str, Any]:
    """
    Render an ``SC_Info`` directory as JSON-ready values.

    Opaque blobs are hex-encoded in full, so the output carries everything the report summarises.

    Parameters
    ----------
    info : ScInfo
        The directory to render.

    Returns
    -------
    dict[str, Any]
        The rendered directory.
    """
    rendered: dict[str, Any] = {
        'path': str(info.path),
        'appStoreURL': info.app_store_url,
        'storeItemId': info.store_item_id,
        'storefront': info.storefront,
        'region': info.region,
        'files': [{
            'name': name,
            'size': size,
            'sha256': digest
        } for name, size, digest in info.files],
        'manifest': info.manifest,
        'sinf': None,
        'supf': None,
        'supp': None,
        'supx': None,
    }
    if (sinf := info.sinf) is not None:
        rendered['sinf'] = {
            'originalFormat':
                sinf.original_format,
            'scheme':
                sinf.scheme,
            'accountId':
                sinf.account_id,
            'accountName':
                sinf.account_name,
            'purchased':
                sinf.purchased.isoformat() if sinf.purchased else None,
            'assetType':
                sinf.asset_type,
            'keyIndex':
                sinf.key_index,
            'initialisationVector':
                sinf.initialisation_vector.hex() if sinf.initialisation_vector else None,
            'rights': [_right_to_json(right) for right in sinf.rights],
            'rightsTrailer':
                sinf.rights_trailer.hex(),
            'private':
                _private_to_json(sinf.private),
            'signature':
                sinf.signature.hex() if sinf.signature is not None else None,
            'atoms': [_atom_to_json(atom) for atom in sinf.atoms],
        }
    if (supf := info.supf) is not None:
        rendered['supf'] = {
            'version':
                supf.version,
            'tag':
                supf.tag,
            'headerWords':
                list(supf.header_words),
            'identifier':
                supf.identifier.hex(),
            'keyBlob':
                supf.key_blob.hex(),
            'certificateOffset':
                supf.certificate_offset,
            'certificate':
                certificate_to_json(supf.certificate) if supf.certificate is not None else None,
            'signature':
                supf.signature.hex(),
            'trailer':
                supf.trailer.hex(),
        }
    if (supp := info.supp) is not None:
        rendered['supp'] = {
            'version':
                supp.version,
            'tag':
                supp.tag,
            'identifier':
                supp.identifier.hex(),
            'recordSize':
                _SUPP_RECORD_SIZE,
            'records': [record.hex() for record in supp.records],
            'certificateOffset':
                supp.certificate_offset,
            'certificate':
                certificate_to_json(supp.certificate) if supp.certificate is not None else None,
            'signature':
                supp.signature.hex(),
        }
    rendered['crossReferences'] = {
        'identifiersMatch': None,
        'keyBlobIsLastRecord': None,
    }
    rendered['crossReferences'] = {key: held for key, _, held in _cross_references(info)}
    if (supx := info.supx) is not None:
        rendered['supx'] = {
            'version': supx.version,
            'length': supx.length,
            'entries': [{
                'tag': entry.tag,
                'value': entry.value.hex()
            } for entry in supx.entries],
            'trailer': supx.trailer.hex(),
        }
    return rendered
