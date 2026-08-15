"""
Reading of the ``SC_Info`` directory Apple puts inside a purchased ``.app`` bundle.

An App Store download carries its FairPlay bookkeeping in ``Payload/<App>.app/SC_Info``, beside the
encrypted executable. This reads that directory and describes it, either from an unpacked tree or
from inside an ``.ipa`` without unpacking it; it decrypts nothing, and none of the material it
prints is a key.

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
from what independently obtained bundles agree on. Every length prefix in them accounts for the
whole file with nothing left over, in every bundle, which is what the layouts above rest on.

What genuinely cannot be broken down further is the cryptographic material itself: the RSA
signatures, the ``.supf`` key blob, the ``.supp`` records, the ``.supx`` entry values, and the body
of ``priv``, which is ciphertext. What the two supplements count, on the other hand, is now known:
both size a table against the executable's encrypted region, one 32-byte entry per 4096-byte page.

An ``.ipa`` holds more than the application: an app extension under ``PlugIns`` and a watch app
under ``Watch`` are bundles in their own right, each with its own ``SC_Info``, and every one of
them is read. The application is the one bundle at ``Payload/<name>.app`` and nothing else is,
which is how it is told apart. The application's own ``Manifest.plist`` corroborates this, since
its ``SinfReplicationPaths`` names the sub-bundles' records by path and its own without one.

Much of what is asserted here was measured against the 1,935 purchased applications of a private
archive, covering 3,401 bundles, and checked against each one's ``iTunesMetadata.plist``. Where a
claim rests on that corpus the docstring says what was counted, so that a later sample can
contradict it.

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
import zipfile

from .certificate import (
    CertificateSummary,
    certificate_lines,
    certificate_to_json,
    load_certificate,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence
    from pathlib import Path

__all__ = (
    'APP_STORE_REGION_URL',
    'APP_STORE_URL',
    'ATOM_DESCRIPTIONS',
    'QUICKTIME_EPOCH',
    'RIGHTS_TAGS',
    'STOREFRONTS',
    'Atom',
    'Right',
    'ScInfo',
    'Sinf',
    'Supf',
    'Supp',
    'Supx',
    'SupxEntry',
    'find_atom',
    'is_main_bundle',
    'iter_atoms',
    'parse_atoms',
    'parse_sinf',
    'parse_supf',
    'parse_supp',
    'parse_supx',
    'read_bundles',
    'read_sc_info',
    'render_text',
    'sc_info_to_json',
)

APP_STORE_URL = 'https://apps.apple.com/app/id{item}'
"""Template a store item identifier is turned into a link with when the storefront is unknown.

Apple resolves this form from wherever the reader is, which finds the item when it is sold there
and not otherwise, so a regional link is preferred whenever the storefront can be established.

:meta hide-value:
"""
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
    'aver': 'Version restrictions',
    'medi': 'Media',
    'mode': 'Mode',
    'plat': 'Platform',
    'song': 'Store item ID',
    'tool': 'Tool version',
    'tran': 'Transaction',
    'veID': 'Vendor ID',
}
"""Rights tag to a readable description.

A ``righ`` block carries these eight tags, always in the order ``veID plat aver tran song tool
medi mode``, and then sixteen zero bytes.

Two of them are certain, having been checked against the ``iTunesMetadata.plist`` of 1,935
purchased applications covering 3,385 bundles, agreeing in every one:

- ``song`` is ``itemId``, the store item, over 187 distinct values.
- ``veID`` is ``vendorId``, the seller, over 138 distinct values.

``tran`` is a timestamp rather than an opaque transaction number: from tool ``P512`` onward a
``crdt`` atom sits beside it, and the two agree to the second in 1,878 of 2,021 bundles and differ
by exactly one second in the rest.

``aver`` is not the application version. It never varies: every one of those 3,385 bundles carries
``0x01010100``, across 187 applications and hundreds of releases. That is the value the metadata
calls ``versionRestrictions``, which is likewise constant, so the two agree everywhere without that
proving anything. ``medi`` (always ``0x00000080``) and ``mode`` (always zero, as is the metadata's
``drmVersionNumber``) are constant for the same reason and named only by convention.

``plat`` is not the platform. Every application in the corpus is an iOS application, yet ``plat``
is 2 in 2,115 bundles, 5 in 1,213, and 0 in 57. It is a property of the download rather than of the
binary, being the same for every bundle of a download in 1,923 of 1,924 of them, and it tracks the
era of the store client: ``plat`` 2 accompanies the iOS 7 and 8 SDKs and ``plat`` 5 the iOS 9 ones.
It is not the device, which is mixed across all three values, nor the architecture, since 1,354
``plat`` 2 bundles and 1,029 ``plat`` 5 bundles alike carry arm64.

``tool`` is text: ``P454`` through ``P516`` in this corpus.

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
_APPLICATION_DEPTH = 1
_SUB_BUNDLE_DIRECTORIES = ('PlugIns', 'Watch')
_MAX_LISTED_RECORDS = 10
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
    def decoded(self) -> Any:
        """
        The value in its natural type.

        A timestamp tag comes back as an ISO 8601 string, a text tag as the text, a version tag as
        a dotted quad, and anything else as the unsigned integer.

        Returns
        -------
        Any
            The decoded value.
        """
        if self.tag in _DATE_RIGHTS:
            return _quicktime_time(self.value).isoformat()
        if self.tag in _TEXT_RIGHTS and all(byte in _PRINTABLE for byte in self.raw):
            return self.raw.decode('latin1')
        if self.tag in _VERSION_RIGHTS:
            return '.'.join(str(byte) for byte in self.raw)
        return self.value

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
    """When the purchase was recorded.

    This is the ``crdt`` atom, which only newer records carry: it appears from tool ``P512``
    onward and never before, in all 3,385 bundles of the corpus. Where it is absent the same
    instant is still in the ``righ`` block's ``tran``, which it agrees with to the second.
    """
    asset_type: int | None
    """The ``asdt`` value."""
    key_index: int | None
    """The ``key`` value, which selects a key rather than being one.

    It follows the tool generation rather than the title: 2 for tools ``P454`` to ``P501``, 21 for
    ``P502`` to ``P509``, and 29 for ``P510`` to ``P516``.
    """
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
    """The three printable bytes after it, which run from ``309`` to ``325`` in the corpus."""
    header_words: tuple[int, ...]
    """The four ``uint32`` opening the body.

    The second is the size in bytes of a table of 32-byte entries covering the encrypted region:
    ``32 * (ceil(cryptsize / 4096) + 1)``, exactly, in all 2,562 bundles of the corpus that carry a
    ``.supf``. The other three barely move: the first is 2 (2,443 bundles), 3 (78), or 1 (25); the
    third is 12 and the fourth 9 in all but a handful.
    """
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

    There is one record per 4096-byte page of the bundle's executable, counting from the start of
    the file through the end of the encrypted region its Mach-O header declares. That is,
    ``len(records) == ceil((cryptoff + cryptsize) / 4096)`` for a single-architecture executable,
    and for a fat one the same measured to the end of the last slice's encrypted region. Checked
    against 1,935 purchased applications: exact for all 647 single-architecture executables and for
    2,109 of the 2,226 fat ones, the exceptions all being executables carrying an appended slice
    their fat header does not declare.

    So the count is a function of how big the encrypted code is, not of anything about the
    purchase, and it runs from 8 to 26,000 across the corpus. Each record is still 256 bits with
    nothing inside it to read: no record repeats, none is shared between bundles, and none is
    derivable from another or from anything else in the directory.
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
    bundle: str
    """Which bundle this is, as its path inside the container, such as ``Payload/Example.app``."""
    is_main: bool
    """Whether this is the application rather than an extension or watch app beside it."""
    @property
    def app_store_url(self) -> str | None:
        """
        The bundle's App Store link.

        A store item is only reachable in the storefront it was sold in, so the link is regional
        wherever the storefront can be established. Without one it falls back to the region-less
        form, which Apple resolves from wherever the reader is.

        Returns
        -------
        str | None
            The link, or ``None`` when there is no item identifier to build it from.
        """
        item, region = self.store_item_id, self.region
        if item is None:
            return None
        if region is None:
            return APP_STORE_URL.format(item=item)
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


def _find_metadata_path(directory: Path) -> Path | None:
    """
    Locate the ``iTunesMetadata.plist`` sitting beside the bundle, if there is one.

    In an unpacked ``.ipa`` the file sits next to ``Payload``, two levels above the ``.app``, so
    the search walks up from the ``SC_Info`` directory rather than looking in one fixed place.

    Parameters
    ----------
    directory : pathlib.Path
        The ``SC_Info`` directory.

    Returns
    -------
    pathlib.Path | None
        The file, or ``None`` when there is none.
    """
    return next((candidate for parent in [directory, *directory.parents][:_METADATA_SEARCH_DEPTH]
                 if (candidate := parent / _METADATA_NAME).is_file()), None)


def _build(path: Path, contents: dict[str, bytes], metadata: bytes | None, region: str | None,
           bundle: str, *, is_main: bool) -> ScInfo:
    """
    Assemble the reading of one ``SC_Info`` directory from its files' bytes.

    The bytes come from a directory or from inside an ``.ipa``, and everything after that is the
    same, so both routes end here.

    Parameters
    ----------
    path : pathlib.Path
        Where the directory is, for the report to name.
    contents : dict[str, bytes]
        File name to contents, for the files in the ``SC_Info`` directory.
    metadata : bytes | None
        The ``iTunesMetadata.plist`` beside the bundle, when there is one.
    region : str | None
        A country code supplied by the caller.
    bundle : str
        Which bundle this is, as its path inside the container.
    is_main : bool
        Whether this is the application rather than something beside it.

    Returns
    -------
    ScInfo
        Everything that could be read. A file that is absent, and a file that is present but
        unreadable, both leave their field ``None``, so a partial directory still describes itself.
    """
    files = tuple((name, len(data), hashlib.sha256(data).hexdigest())
                  for name, data in sorted(contents.items()))
    return ScInfo(path, _load_plist(contents.get('Manifest.plist')),
                  _parse_one(contents, '.sinf', parse_sinf),
                  _parse_one(contents, '.supf', parse_supf),
                  _parse_one(contents, '.supp', parse_supp),
                  _parse_one(contents, '.supx', parse_supx), files, _load_plist(metadata), region,
                  bundle, is_main)


def _load_plist(data: bytes | None) -> dict[str, Any] | None:
    """
    Parse a property list, tolerating one that is absent or unreadable.

    Parameters
    ----------
    data : bytes | None
        The plist's bytes, or ``None``.

    Returns
    -------
    dict[str, Any] | None
        The parsed mapping, or ``None`` when there is none or its root is not a mapping.
    """
    if data is None:
        return None
    try:
        loaded = plistlib.loads(data)
    except plistlib.InvalidFileException:
        return None
    return loaded if isinstance(loaded, dict) else None


def _parse_one(contents: dict[str, bytes], suffix: str, parse: Callable[[bytes], Any]) -> Any:
    """
    Parse the single file carrying a suffix, if there is one.

    Parameters
    ----------
    contents : dict[str, bytes]
        File name to contents.
    suffix : str
        The suffix to match, such as ``.sinf``.
    parse : Callable[[bytes], Any]
        The parser to hand the bytes to. The return type follows the parser, which is why this is
        annotated loosely; each call site knows what it asked for.

    Returns
    -------
    Any
        The parsed file, or ``None`` when it is absent or does not parse.
    """
    found = sorted(name for name in contents if name.endswith(suffix))
    if not found:
        return None
    try:
        return parse(contents[found[0]])
    except ValueError:
        return None


def _bundles_in_tree(payload: Path) -> list[tuple[str, Path]]:
    """
    Find every bundle under an unpacked ``Payload`` that carries an ``SC_Info``.

    An application's extensions live under ``PlugIns`` and its watch app under ``Watch``, each a
    bundle with its own FairPlay record. Only those two places are looked in, so this stays a few
    directory listings rather than a walk of the whole application.

    Parameters
    ----------
    payload : pathlib.Path
        The ``Payload`` directory.

    Returns
    -------
    list[tuple[str, pathlib.Path]]
        Each bundle's path relative to the payload's parent, and its ``SC_Info`` directory, with
        the application first.
    """
    root = payload.parent
    found: list[tuple[str, Path]] = []
    for application in sorted(payload.glob(f'*{_APP_SUFFIX}')):
        if not application.is_dir():
            continue
        if (directory := application / _SC_INFO_NAME).is_dir():
            found.append((application.relative_to(root).as_posix(), directory))
        found += [(candidate.parent.relative_to(root).as_posix(), candidate)
                  for holder in _SUB_BUNDLE_DIRECTORIES
                  for candidate in sorted((application / holder).glob(f'*/{_SC_INFO_NAME}'))
                  if candidate.is_dir()]
    return found


def _directory_contents(directory: Path) -> dict[str, bytes]:
    """
    Read every file in a directory.

    Parameters
    ----------
    directory : pathlib.Path
        The directory to read.

    Returns
    -------
    dict[str, bytes]
        File name to contents, skipping anything that cannot be read.
    """
    contents: dict[str, bytes] = {}
    for entry in sorted(directory.iterdir()):
        if not entry.is_file():
            continue
        try:
            contents[entry.name] = entry.read_bytes()
        except OSError:
            continue
    return contents


def is_main_bundle(bundle: str) -> bool:
    """
    Decide whether a bundle path names the application rather than something beside it.

    An application is ``Payload/<Name>.app`` and nothing else is. Everything nested deeper is a
    sub-bundle: an app extension under ``PlugIns``, a watch app under ``Watch``, and so on. Each
    carries its own FairPlay record, which is why several turn up in one download.

    Parameters
    ----------
    bundle : str
        The bundle's path inside its container.

    Returns
    -------
    bool
        ``True`` for the application.
    """
    parts = bundle.split('/')
    return (len(parts) == _APPLICATION_DEPTH + 1 and parts[0] == _PAYLOAD_NAME
            and parts[-1].endswith(_APP_SUFFIX))


def _select(bundles: Sequence[str], where: Path, wanted: str | None, *,
            main_only: bool) -> list[str]:
    """
    Narrow the bundles found to those the caller asked for.

    Parameters
    ----------
    bundles : Sequence[str]
        Every bundle carrying an ``SC_Info``, in the order found.
    where : pathlib.Path
        The container, for the message when the request matches nothing.
    wanted : str | None
        One bundle to keep, named in full or by its final component.
    main_only : bool
        Keep only the application.

    Returns
    -------
    list[str]
        The bundles to read, in the order found.

    Raises
    ------
    ValueError
        If nothing matches what was asked for.
    """
    if wanted is not None:
        chosen = [
            bundle for bundle in bundles if bundle == wanted or bundle.rsplit('/', 1)[-1] == wanted
        ]
        if not chosen:
            msg = (f'No bundle named {wanted!r} in {where}; it holds {", ".join(bundles)}.')
            raise ValueError(msg)
        return chosen
    if main_only:
        chosen = [bundle for bundle in bundles if is_main_bundle(bundle)]
        if not chosen:
            msg = (f'No {_PAYLOAD_NAME}/<name>{_APP_SUFFIX} in {where}, so there is no application '
                   f'to read; it holds {", ".join(bundles)}.')
            raise ValueError(msg)
        return chosen
    return list(bundles)


def _archive_bundles(archive: zipfile.ZipFile) -> tuple[list[str], list[str]]:
    """
    List the bundles in an archive that carry an ``SC_Info``.

    Parameters
    ----------
    archive : zipfile.ZipFile
        The opened archive.

    Returns
    -------
    tuple[list[str], list[str]]
        The bundle paths, application first, and the archive's entry names normalised.
    """
    marker = f'/{_SC_INFO_NAME}/'
    names = [name.removeprefix('./') for name in archive.namelist()]
    found = sorted({name.rsplit(marker, 1)[0] for name in names if marker in name})
    return sorted(found, key=lambda bundle: (not is_main_bundle(bundle), bundle)), names


def _archive_contents(archive: zipfile.ZipFile, names: Sequence[str],
                      bundle: str) -> dict[str, bytes]:
    """
    Read one bundle's ``SC_Info`` files out of an archive.

    Parameters
    ----------
    archive : zipfile.ZipFile
        The opened archive.
    names : Sequence[str]
        The archive's entry names, normalised, in the archive's own order.
    bundle : str
        The bundle to read.

    Returns
    -------
    dict[str, bytes]
        File name to contents.
    """
    prefix = f'{bundle}/{_SC_INFO_NAME}/'
    return {
        name[len(prefix):]: archive.read(original)
        for original, name in zip(archive.namelist(), names, strict=True)
        if name.startswith(prefix) and not name.endswith('/')
    }


def _payload_of(path: Path) -> Path | None:
    """
    Find the ``Payload`` directory a path stands for, when it stands for one.

    Naming the ``SC_Info`` directory or a bundle picks that bundle alone, so neither yields a
    payload; naming ``Payload`` or the directory holding it means every bundle inside.

    Parameters
    ----------
    path : pathlib.Path
        The directory the caller named.

    Returns
    -------
    pathlib.Path | None
        The payload, or ``None`` when the caller picked one bundle.
    """
    if path.name == _SC_INFO_NAME or (path / _SC_INFO_NAME).is_dir():
        return None
    if path.name == _PAYLOAD_NAME:
        return path
    return payload if (payload := path / _PAYLOAD_NAME).is_dir() else None


def read_bundles(path: Path,
                 region: str | None = None,
                 bundle: str | None = None,
                 *,
                 main_only: bool = False) -> tuple[ScInfo, ...]:
    """
    Read every bundle's ``SC_Info``, from a directory tree or from inside an ``.ipa``.

    A download holds more than the application: an app extension under ``PlugIns`` and a watch app
    under ``Watch`` are bundles in their own right, each with its own record, and all of them are
    read unless the caller narrows it. Naming the ``SC_Info`` directory or one bundle picks that
    one on its own.

    Parameters
    ----------
    path : pathlib.Path
        An ``.ipa``, or the ``SC_Info`` directory, the ``.app`` bundle holding it, the ``Payload``
        directory holding that, or a directory holding ``Payload``.
    region : str | None
        A country code to build the App Store link with, for a bundle with no
        ``iTunesMetadata.plist`` beside it to read the storefront from.
    bundle : str | None
        One bundle to read, named in full or by its final component.
    main_only : bool
        Read only the application.

    Returns
    -------
    tuple[ScInfo, ...]
        One reading per bundle, the application first.

    Raises
    ------
    ValueError
        If no ``SC_Info`` directory can be reached, or nothing matches what was asked for.
    """
    if path.is_file():
        if not zipfile.is_zipfile(path):
            msg = f'{path} is a file but not an .ipa; name an .ipa or an unpacked directory.'
            raise ValueError(msg)
        with zipfile.ZipFile(path) as archive:
            found, names = _archive_bundles(archive)
            if not found:
                msg = f'No {_SC_INFO_NAME} directory in {path}.'
                raise ValueError(msg)
            metadata = next((archive.read(original)
                             for original, name in zip(archive.namelist(), names, strict=True)
                             if name.rsplit('/', 1)[-1] == _METADATA_NAME), None)
            return tuple(
                _build(path / chosen / _SC_INFO_NAME,
                       _archive_contents(archive, names, chosen),
                       metadata,
                       region,
                       chosen,
                       is_main=is_main_bundle(chosen))
                for chosen in _select(found, path, bundle, main_only=main_only))
    if (payload := _payload_of(path)) is None:
        directory = _locate(path)
        found_path = _find_metadata_path(directory)
        name = directory.parent.name
        return (_build(directory,
                       _directory_contents(directory),
                       found_path.read_bytes() if found_path is not None else None,
                       region,
                       name,
                       is_main=name.endswith(_APP_SUFFIX)),)
    in_tree = _bundles_in_tree(payload)
    if not in_tree:
        msg = f'No {_SC_INFO_NAME} directory below {payload}.'
        raise ValueError(msg)
    directories = dict(in_tree)
    chosen_names = _select([name for name, _ in in_tree], payload, bundle, main_only=main_only)
    metadata_path = _find_metadata_path(directories[chosen_names[0]])
    metadata = metadata_path.read_bytes() if metadata_path is not None else None
    return tuple(
        _build(directories[name],
               _directory_contents(directories[name]),
               metadata,
               region,
               name,
               is_main=is_main_bundle(name)) for name in chosen_names)


def read_sc_info(path: Path, region: str | None = None) -> ScInfo:
    """
    Read one bundle's ``SC_Info``, the application's where there is a choice.

    Parameters
    ----------
    path : pathlib.Path
        An ``.ipa``, or the ``SC_Info`` directory, the ``.app`` bundle holding it, the ``Payload``
        directory holding that, or a directory holding ``Payload``.
    region : str | None
        A country code to build the App Store link with.

    Returns
    -------
    ScInfo
        The reading.

    Notes
    -----
    A path with nothing to read raises the :py:class:`ValueError` :func:`read_bundles` raises.
    """
    return read_bundles(path, region, main_only=_payload_of(path) is not None or path.is_file())[0]


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
    lines = [
        f'Bundle: {info.bundle}' + ('' if info.is_main else ' (not the application)'),
        f'SC_Info: {info.path}',
    ]
    if (item := info.store_item_id) is not None:
        lines.append(f'Store item ID: {item}')
    if (front := info.storefront) is not None:
        lines.append(f'Storefront: {front} ({info.region or "unknown region"})')
    if (url := info.app_store_url) is not None:
        lines.append(f'App Store URL: {url}')
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
        # A widely released title carries hundreds of these, which would bury the rest of the
        # report; the JSON still carries every one.
        for index, record in enumerate(info.supp.records[:_MAX_LISTED_RECORDS]):
            lines.append(f'    [{index:3d}]  {record.hex()}')
        if (remaining := len(info.supp.records) - _MAX_LISTED_RECORDS) > 0:
            lines.append(f'    ...    ({remaining} remaining)')
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
        The tag, its description where there is one, and the value in its natural type.
    """
    rendered: dict[str, Any] = {'tag': right.tag}
    if right.description is not None:
        rendered['description'] = right.description
    rendered['value'] = right.decoded
    return rendered


def _atom_value(atom: Atom) -> Any:
    """
    Decode a leaf atom's payload into its natural type.

    Parameters
    ----------
    atom : Atom
        The leaf atom.

    Returns
    -------
    Any
        A mapping for the atoms with named fields, a list of integers for the initialisation
        vector, an ISO 8601 string for a timestamp, the text or the unsigned integer where it is
        one of those, and the hexadecimal bytes when it is none of them.
    """
    if atom.kind == 'righ':
        rights, trailer = _parse_rights(atom.body)
        value: dict[str, Any] = {'rights': [_right_to_json(right) for right in rights]}
        if trailer:
            value['trailer'] = trailer.hex()
        return value
    if atom.kind == 'schm' and len(atom.body) >= _SCHEME_TYPE.stop:
        return {
            'version': int.from_bytes(atom.body[:4], 'big'),
            'schemeType': atom.body[_SCHEME_TYPE].decode('latin1'),
            'schemeVersion': int.from_bytes(atom.body[_SCHEME_TYPE.stop:], 'big'),
        }
    if atom.kind == 'iviv':
        return list(atom.body)
    if (as_text := _atom_text(atom.body)) is not None:
        return as_text
    if len(atom.body) == _TAG_SIZE:
        number = int.from_bytes(atom.body, 'big')
        return _quicktime_time(number).isoformat() if atom.kind in _DATE_ATOMS else number
    return atom.body.hex()


def _atom_to_json(atom: Atom) -> dict[str, Any]:
    """
    Render one atom as JSON-ready values.

    A container carries its children; a leaf carries one ``value`` in whatever type the payload
    turns out to be, so a reader never has to know which key to look under.

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
    else:
        rendered['value'] = _atom_value(atom)
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
        'bundle': info.bundle,
        'isMain': info.is_main,
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
