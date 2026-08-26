<!-- markdownlint-configure-file {"MD024": { "siblings_only": true } } -->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.1/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [unreleased]

## [0.0.2] - 2026-08-26

### Fixed

- A release now carries every binary that was built for it. The PyInstaller workflow builds one
  binary per platform and architecture, each under the same name, so the release job's flattening
  download kept only one file per extension and dropped the rest: v0.0.1 advertised four platforms
  and shipped two binaries, `dade` and `dade.exe`, neither of which said which architecture it was,
  and both of which turned out to be the x86_64 builds. The workflow already built an archive per
  job carrying the version and the architecture in its name, and already attested it, but nothing
  ever uploaded it. The release job takes those archives instead, so the assets are now
  `dade-vX.Y.Z-mac-x86_64.zip`, `dade-vX.Y.Z-mac-arm64.zip`, `dade-vX.Y.Z-win-x86_64.zip`, and
  `dade-vX.Y.Z-win-arm64.zip`. An archive also keeps the executable bit and any macOS notarisation,
  both of which a bare release asset loses.

## [0.0.1] - 2026-08-26

### Added

- Merged a collection of separate game asset extractors into a single `dade` package, each exposed
  as a sub-command: `amplitude` (Amplitude/FreQuency), `bit192` (Tone Sphere), `bitrock`
  (InstallBuilder installers), `i76` (Interstate '76), `incoming` (Incoming), `marmalade` (Marmalade
  SDK), `monopoly08` (Monopoly 2008), `thps2pc` (Tony Hawk's Pro Skater 2 PC), and `xg2` (Extreme-G
  and Extreme-G 2).
- A single multi-command entry point, invoked as `dade <game> <subcommand>`.
- `dade jubeatplus` group for the Konami iOS game _jubeat plus_: `unpack` converts a whole
  download to formats that open outside iOS. It accepts an `.ipa`, the `.app` bundle, the `Payload`
  directory, or a directory holding `Payload`, never writes to the source, and mirrors the bundle
  into the output directory. Apple-optimised (`CgBI`) PNGs are rewritten by `pngdefry`; enciphered
  `.tex` textures are deciphered and rewritten the same way; `.caf` sound effects are rewrapped as
  WAV by `ffmpeg`; `.jbt` tune packages and the marker and share-image ZIPs are unpacked into
  directories named after themselves, with every entry deciphered and decoded; note charts become
  JSON with every event's panel, hold length, tempo, and time; and property lists, localisation
  tables, Core Data models, the `SC_Info` bookkeeping, and the executable's properties all become
  JSON. Every other file is copied unchanged. The assets use the same `BFCodec` cipher as
  _pop'n rhythmin_, under seven keys of their own. `--no-png` and `--no-audio` skip the two
  conversions that need a helper tool, and `-j`/`--jobs` sets the pool size.
- `dade rbplus` group for the Konami iOS game _REFLEC BEAT plus_: `unpack` converts a whole
  download to formats that open outside iOS, `extract-assets` unpacks one of the three
  downloadable texture archives, and `dump-chart` writes a single note chart. `unpack` accepts an
  `.ipa`, the `.app` bundle, the `Payload` directory, or a directory holding `Payload`, never
  writes to the source, and mirrors the bundle into the output directory. A `%09d.rb` tune package
  becomes a directory: its metadata as JSON, its artwork and name strips as ordinary PNGs, each of
  its three note charts as both JSON and a rendered strip image, and its two audio streams as
  `.m4a`. Loose Apple-optimised PNGs are rewritten by `pngdefry`, `.caf` sound effects become WAV,
  and property lists, localisation tables, Core Data models, and the `SC_Info` bookkeeping all
  become JSON. Mach-O images are left behind entirely. Every other file is copied unchanged. The
  assets use the same `BFCodec` cipher as _pop'n rhythmin_ and _jubeat plus_, under two keys of
  their own, neither of which appears in the executable as a passphrase.
- The RBFF note chart, versions 10 to 14: a header giving the scroll speed, end time, and record
  counts, then variable-length note records carrying an inline path-point array and an optional
  chain block, then thirty-six byte tempo events, then sixteen-byte slide records. A note's hit
  time is its two stored times added, which is also what makes two notes simultaneous. A chain is
  the note record's own doubly linked list: its chain block names the note before it and the note
  after it by identifier, with -1 at each end. Every one of the five flag bits a note carries is
  exactly redundant with another field: two mark a note struck at the same moment as one on its own
  or the other side, and the rest mark a chain block, a free note, and a note that travels to the
  other side to be swiped back, which the engine counts as a side object and which is the same bit
  as the one marking a path.
- A note's route selector, derived from its second target coordinate the way the engine derives it,
  says whether the chart names the note's lane. One naming a lane, 0 to 6, comes straight down into
  that lane and no randomness touches it: that is every slide and every vertical note. One naming
  7, 8, or 9 is aimed at one of the three alternative targets beyond the lanes. Only a note naming
  nothing is laid out at run time, from a generator seeded with `rand()`, so that part of a chart
  falls differently on every play.
- A slide's records are its waypoints, one per point the finger passes through. Each gives the lane
  to be in and, in the same shape a note's own timing takes, a spawn time and a travel time whose
  sum is the moment to be there. The travel time is one constant per chart, the scroll lead-in, and
  the waypoints land on musical divisions of the tune's own tempo.
- `dade rhythmin` group for the Konami iOS game _pop'n rhythmin_: the `BFCodec` cipher (Blowfish
  with one deviation in its F function), `dump-chara` for downloaded character data, `dump-idx` for
  AEP animation indexes, `dump-map` for sugoroku boards (JSON, a text board, or a rendered PNG),
  `dump-sheet` for note charts from `.orb` and `.acv` song packages (JSON or a DDR-style strip
  image), and `extract-dialogue` for the board dialogue pools inside an app binary.
- `dade misc` group for formats that belong to no single game: `coredata` deserialises a compiled
  Core Data mapping (`.cdm`) or managed object (`.mom`) model to JSON, dumps the raw keyed archive,
  or emits the effective SQLite migration script; `strings` reads an Xcode `.strings` table in
  either the compiled or the old-style text form.
- `dade misc macho dump`, which writes the properties of a Mach-O image as JSON: the header and
  its flags, the segments and their sections, the libraries it links against, its UUID and source
  version, the minimum OS it declares, the entitlements inside its code signature, and, for an
  image bought from the App Store, the `LC_ENCRYPTION_INFO` command that says its text is still
  enciphered. It accepts an application's executable, a framework, or a dynamic library, thin or
  universal, and reads every architecture slice. It decrypts nothing and disassembles no code.
- `dade misc sc-info dump`, which describes the `SC_Info` FairPlay bookkeeping in a purchased
  application bundle: the store item ID and App Store link, the manifest, the `.sinf` purchase
  record and its atom tree, the `.supf` and `.supp` supplements broken into their length-prefixed
  parts, the two Apple FairPlay certificates they embed with every extension broken out, the
  `.supx` tagged entries, and cross-checks between the parts. It accepts an `.ipa`, read in place
  without being unpacked, or the `SC_Info` directory, the bundle, the `Payload` directory, or a
  directory holding `Payload`. Every bundle in the download is read, including the app extensions
  under `PlugIns` and the watch app under `Watch`; `--main-bundle` keeps only the application and
  `--bundle NAME` keeps one named bundle. Every set of protection files in an `SC_Info` is read,
  not only the first, since a directory can hold one set per executable. `--json` prints the same
  information as JSON, one entry per bundle, and `--region` supplies the storefront when no
  `iTunesMetadata.plist` sits beside the bundle. It decrypts nothing and prints no key material.
- `ian2obj` and `extract-pvr-pack` command-line utilities, now `dade incoming ian2obj` and
  `dade incoming extract-pvr-pack`.
- `ian2obj` converts Dreamcast `*_M.BIN` model packs in addition to PC `.ian` meshes.
- `-j`/`--jobs` option to run Incoming file conversions concurrently, defaulting to the CPU count.
- Three more shared modules under `dade.common`, each lifted from a game package once a second
  consumer appeared: `apple_png` for the `pngdefry` conversion of Apple-optimised PNGs, `audio` for
  the `ffmpeg` rewrap, and `fonts` for the fontconfig lookup that picks a font with Japanese
  coverage. `dade.jubeatplus.images`, `dade.jubeatplus.audio`, and `dade.rhythmin.render` keep
  every name they exported.
- Shared format code used by more than one game lives in a single `dade.common` package: WAV, PNG,
  and PPM writers, an LZSS decompressor, a Twofish cipher, the `BFCodec` Blowfish variant shared by
  _pop'n rhythmin_ and _jubeat plus_, a CookFS reader, memory-mapped and byte-range readers,
  native-tool location, a converter registry, worker-pool helpers, per-run context, and text and
  filename utilities.

### Changed

- Renamed the project from `incoming-extractor` to `dade`. The Incoming extractor is now the
  `dade incoming` sub-command and its package moved from `incoming_extractor` to
  `dade.incoming`.
- File conversions now run concurrently across a pool of worker tasks instead of one at a time.
- The `.cfg`, `.sav`, `.xxx`, and `.lev` converters now decode the files into fully structured JSON
  using schemas reverse-engineered from `incoming.exe`, with named fields and a verified config
  checksum, instead of emitting the body as base64.
- Ported the asset-format reference into the Sphinx documentation under `docs/formats/` and
  expanded the documentation into separate, well-organised pages.

[unreleased]: https://github.com/Tatsh/dade/compare/v0.0.2...HEAD
[0.0.2]: https://github.com/Tatsh/dade/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/Tatsh/dade/releases/tag/v0.0.1
