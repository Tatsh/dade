<!-- markdownlint-configure-file {"MD024": { "siblings_only": true } } -->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.1/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [unreleased]

### Added

- `ian2obj` and `extract-pvr-pack` standalone command-line utilities.
- `ian2obj` converts Dreamcast `*_M.BIN` model packs in addition to PC `.ian` meshes.
- `-j`/`--jobs` option to run file conversions concurrently, defaulting to the CPU count.

### Changed

- File conversions now run concurrently across a pool of worker tasks instead of one at a time.
- The `.cfg`, `.sav`, `.xxx`, and `.lev` converters now decode the files into fully structured JSON
  using schemas reverse-engineered from `incoming.exe`, with named fields and a verified config
  checksum, instead of emitting the body as base64.
- Ported the asset-format reference into the Sphinx documentation under `docs/formats/` and
  expanded the documentation into separate, well-organised pages.

## [0.0.1] - 2026-00-00

First version.

[unreleased]: https://github.com/Tatsh/incoming-extractor/compare/v0.0.0...HEAD
[0.0.1]: https://github.com/Tatsh/incoming-extractor/releases/tag/v0.0.0
