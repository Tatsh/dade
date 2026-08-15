<!-- markdownlint-configure-file {"MD024": { "siblings_only": true } } -->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.1/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [unreleased]

### Added

- Merged a collection of separate game asset extractors into a single `destin` package, each exposed
  as a sub-command: `amplitude` (Amplitude/FreQuency), `bit192` (Tone Sphere), `bitrock`
  (InstallBuilder installers), `i76` (Interstate '76), `incoming` (Incoming), `marmalade` (Marmalade
  SDK), `monopoly08` (Monopoly 2008), `thps2pc` (Tony Hawk's Pro Skater 2 PC), and `xg2` (Extreme-G
  and Extreme-G 2).
- A single multi-command entry point, invoked as `destin <game> <subcommand>`.
- `destin rhythmin` group for the Konami iOS game _pop'n rhythmin_: the `BFCodec` cipher (Blowfish
  with one deviation in its F function), `dump-chara` for downloaded character data, `dump-idx` for
  AEP animation indexes, `dump-map` for sugoroku boards (JSON, a text board, or a rendered PNG),
  `dump-sheet` for note charts from `.orb` and `.acv` song packages (JSON or a DDR-style strip
  image), and `extract-dialogue` for the board dialogue pools inside an app binary.
- `destin misc` group for formats that belong to no single game: `coredata` deserialises a compiled
  Core Data mapping (`.cdm`) or managed object (`.mom`) model to JSON, dumps the raw keyed archive,
  or emits the effective SQLite migration script; `strings` reads an Xcode `.strings` table in
  either the compiled or the old-style text form.
- `destin misc sc-info dump`, which describes the `SC_Info` FairPlay bookkeeping in a purchased
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
- `ian2obj` and `extract-pvr-pack` command-line utilities, now `destin incoming ian2obj` and
  `destin incoming extract-pvr-pack`.
- `ian2obj` converts Dreamcast `*_M.BIN` model packs in addition to PC `.ian` meshes.
- `-j`/`--jobs` option to run Incoming file conversions concurrently, defaulting to the CPU count.
- Shared format code used by more than one game lives in a single `destin.common` package: WAV, PNG,
  and PPM writers, an LZSS decompressor, a Twofish cipher, a CookFS reader, memory-mapped and
  byte-range readers, native-tool location, a converter registry, worker-pool helpers, per-run
  context, and text and filename utilities.

### Changed

- Renamed the project from `incoming-extractor` to `destin`. The Incoming extractor is now the
  `destin incoming` sub-command and its package moved from `incoming_extractor` to
  `destin.incoming`.
- File conversions now run concurrently across a pool of worker tasks instead of one at a time.
- The `.cfg`, `.sav`, `.xxx`, and `.lev` converters now decode the files into fully structured JSON
  using schemas reverse-engineered from `incoming.exe`, with named fields and a verified config
  checksum, instead of emitting the body as base64.
- Ported the asset-format reference into the Sphinx documentation under `docs/formats/` and
  expanded the documentation into separate, well-organised pages.

## [0.0.1] - 2026-00-00

First version.

[unreleased]: https://github.com/Tatsh/destin/compare/v0.0.0...HEAD
[0.0.1]: https://github.com/Tatsh/destin/releases/tag/v0.0.0
