# dade

<!-- WISWA-GENERATED-README:START -->

[![Python versions](https://img.shields.io/pypi/pyversions/dade.svg?color=blue&logo=python&logoColor=white)](https://www.python.org/)
[![PyPI - Version](https://img.shields.io/pypi/v/dade)](https://pypi.org/project/dade/)
[![GitHub tag (with filter)](https://img.shields.io/github/v/tag/Tatsh/dade)](https://github.com/Tatsh/dade/tags)
[![License](https://img.shields.io/github/license/Tatsh/dade)](https://github.com/Tatsh/dade/blob/master/LICENSE.txt)
[![GitHub commits since latest release (by SemVer including pre-releases)](https://img.shields.io/github/commits-since/Tatsh/dade/v0.0.0/master)](https://github.com/Tatsh/dade/compare/v0.0.0...master)
[![CodeQL](https://github.com/Tatsh/dade/actions/workflows/codeql.yml/badge.svg)](https://github.com/Tatsh/dade/actions/workflows/codeql.yml)
[![QA](https://github.com/Tatsh/dade/actions/workflows/qa.yml/badge.svg)](https://github.com/Tatsh/dade/actions/workflows/qa.yml)
[![Tests](https://github.com/Tatsh/dade/actions/workflows/tests.yml/badge.svg)](https://github.com/Tatsh/dade/actions/workflows/tests.yml)
[![Coverage Status](https://coveralls.io/repos/github/Tatsh/dade/badge.svg?branch=master)](https://coveralls.io/github/Tatsh/dade?branch=master)
[![Dependabot](https://img.shields.io/badge/Dependabot-enabled-blue?logo=dependabot)](https://github.com/dependabot)
[![Documentation Status](https://readthedocs.org/projects/dade/badge/?version=latest)](https://dade.readthedocs.org/?badge=latest)
[![mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)
[![uv](https://img.shields.io/badge/uv-261230?logo=astral)](https://docs.astral.sh/uv/)
[![numpy](https://img.shields.io/badge/numpy-black?logo=numpy)](https://pypi.org/project/numpy/)
[![pytest](https://img.shields.io/badge/pytest-zz?logo=Pytest&labelColor=black&color=black)](https://docs.pytest.org/en/stable/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Downloads](https://static.pepy.tech/badge/dade/month)](https://pepy.tech/project/dade)
[![Stargazers](https://img.shields.io/github/stars/Tatsh/dade?logo=github&style=flat)](https://github.com/Tatsh/dade/stargazers)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/Tatsh/dade/master.svg)](https://results.pre-commit.ci/latest/github/Tatsh/dade/master)
[![Prettier](https://img.shields.io/badge/Prettier-black?logo=prettier)](https://prettier.io/)

[![@Tatsh](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fpublic.api.bsky.app%2Fxrpc%2Fapp.bsky.actor.getProfile%2F%3Factor=did%3Aplc%3Auq42idtvuccnmtl57nsucz72&query=%24.followersCount&label=Follow+%40Tatsh&logo=bluesky&style=social)](https://bsky.app/profile/Tatsh.bsky.social)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-Tatsh-black?logo=buymeacoffee)](https://buymeacoffee.com/Tatsh)
[![Libera.Chat](https://img.shields.io/badge/Libera.Chat-Tatsh-black?logo=liberadotchat)](irc://irc.libera.chat/Tatsh)
[![Mastodon Follow](https://img.shields.io/mastodon/follow/109370961877277568?domain=hostux.social&style=social)](https://hostux.social/@Tatsh)
[![Patreon](https://img.shields.io/badge/Patreon-Tatsh2-F96854?logo=patreon)](https://www.patreon.com/Tatsh2)

<!-- WISWA-GENERATED-README:STOP -->

**Dade** (Decompress, Analyse, Decode, Export) is a single package that bundles a collection of
asset extractors and converters for a set of PC and console video games. Each game is a sub-command
of one `dade` command, so every tool is invoked the same way:

```shell
dade <game> <subcommand> [ARGS]
```

Run `dade --help` to list the games, and `dade <game> --help` to list a game's subcommands.

## Games

| Sub-command       | Game(s)                                     | Publisher / developer         |
| ----------------- | ------------------------------------------- | ----------------------------- |
| `dade amplitude`  | _Amplitude_ (PS2)                           | Harmonix                      |
| `dade bit192`     | _Tone Sphere_                               | bit192labs                    |
| `dade bitrock`    | BitRock / InstallBuilder installers         | BitRock / VMware              |
| `dade frequency`  | _FreQuency_ (PS2)                           | Harmonix                      |
| `dade i76`        | _Interstate '76_ and _Interstate '82_       | Activision                    |
| `dade incoming`   | _Incoming_ (PC and Dreamcast)               | Rage Software / Interplay     |
| `dade jubeatplus` | _jubeat plus_ (iOS)                         | Konami                        |
| `dade marmalade`  | Any Marmalade SDK title (Derbh, IwResGroup) | Marmalade / Ideaworks         |
| `dade misc`       | Formats belonging to no single game         | —                             |
| `dade monopoly08` | _Monopoly_ (2008, multi-platform)           | Electronic Arts               |
| `dade rhythmin`   | _pop'n rhythmin_ (iOS)                      | Konami                        |
| `dade thps2pc`    | _Tony Hawk's Pro Skater 2_ (PC)             | Neversoft / Activision        |
| `dade xg2`        | _Extreme-G_ and _Extreme-G 2_ (N64 and PC)  | Probe Entertainment / Acclaim |

## Installation

```shell
pip install dade
```

## Incoming

```shell
dade incoming extract --output OUTPUT_DIR SOURCE
```

`SOURCE` may be a PC disc directory or ISO containing `DATA1.CAB` (or the `DATA1.CAB` itself), a
Dreamcast `.gdi` file, or a directory of already extracted PC or GD-ROM content. Recognised assets
are converted (PVR and PPM to PNG, IAN and `*_M.BIN` to OBJ and MTL, terrain, saves, and `.ctl` to
JSON, CDDA `.raw` and `.OSB` to WAV, Shift-JIS or ISO-8859-15 `.TXT` to UTF-8) and every other file
is copied verbatim. The source is never modified.

An installed copy works as the source too — point at the game's directory, such as the
`Incoming 3DFX` folder of the
[Zoom Platform _Incoming Trilogy_](https://www.zoom-platform.com/product/incoming-trilogy)
(`…/Incoming Trilogy/Incoming 3DFX`). The _Incoming 3DFX_, _Incoming USA_, and _Incoming Subversion_
(an expansion pack) titles share the original engine and are supported; _Incoming Forces_ is not
supported.

Pass `--gdiextract-path`, `--spvr2png-path`, or `--unshield-path` to point at the native tools when
they are not on `PATH`, `-j`/`--jobs` to set the number of concurrent conversion jobs (defaults to
the CPU count), and `--debug` for verbose logging.

Two further subcommands convert a single asset without mirroring a whole source tree:

- `dade incoming ian2obj MODEL OUTDIR` — convert one model to Wavefront OBJ and MTL. Both the PC
  `.ian` mesh and the Dreamcast `*_M.BIN` model pack are accepted (the format is detected from the
  file name); a Dreamcast pack needs its matching `*_ML.BIN` index beside it and yields one OBJ and
  MTL per object. The texture is resolved from the game root, auto-detected from `MODEL` or set with
  `--game-root`, unless `--no-texture` is given.
- `dade incoming extract-pvr-pack PACK OUTDIR` — unpack a Dreamcast `*_T.PVR` texture pack,
  writing each texture as a separate `.pvr` file, or as a PNG with `--png` (which requires
  `spvr2png`).

### Native tools

Some Incoming conversions shell out to native helpers, which must be on `PATH` or supplied with the
matching `--*-path` option:

- [7z](https://www.7-zip.org/) — extracts `DATA1.CAB` from a PC ISO (used when `isodump` is absent).
- [gdiextract](https://github.com/MachXNU/gdiextract) — extracts the ISO 9660 file system from a
  Dreamcast GDI.
- [isodump](https://sourceforge.net/projects/cdrtools/) — extracts `DATA1.CAB` from a PC ISO.
- [spvr2png](https://github.com/nextgeniuspro/spvr2png) — converts Sega Dreamcast PVR images to PNG.
- [unshield](https://github.com/twogood/unshield) — unpacks the InstallShield `DATA1.CAB` cabinet on
  the PC disc.

## Amplitude and FreQuency

```shell
dade amplitude unpack DISC -o OUT
dade frequency unpack DISC -o OUT
```

_Amplitude_ and _FreQuency_ (Harmonix) share one PS2 engine but are separate commands, one per game.
Point either at its disc directory (`DISC`): every ARK is unpacked mirroring its location, disc
streaming songs are converted to WAV, and assets are converted in place (bitmaps to PNG, DataArray
to JSON, Milo scenes to object folders, meshes to OBJ, audio to WAV). The output directory defaults
to the current directory; set it with `-o`/`--output-dir`.

## Tone Sphere

```shell
dade bit192 extract "Tone Sphere.xapk" -o out/
dade bit192 decrypt-cz gamedata_sub.cz gamedata_sub.dz
dade bit192 save …
```

Tools for the [bit192labs](https://bit192.com/) rhythm game _Tone Sphere_: `.cz` decryption, full
asset extraction, and `save.bin` editing. This is the game-specific layer on top of the generic
Marmalade support in `dade marmalade`.

## Marmalade SDK

```shell
dade marmalade extract-dz ARCHIVE.dz OUTDIR
dade marmalade extract-group RESOURCES.group.bin OUTDIR
```

Unpack and decode assets built with the Marmalade SDK: Derbh (`.dz`) archives, IwResGroup
(`.group.bin`) resources, and `CIwTexture`, `CIwGxFont`, `CIwMaterial`, and `CIwModel` resources to
PNG, JSON, and Wavefront OBJ.

## BitRock / InstallBuilder

```shell
dade bitrock extract INSTALLER OUTDIR
dade bitrock crack INSTALLER
```

Extract (and, for encrypted installers, brute-force the password of) BitRock / InstallBuilder
installers. Optional `cuda` and `opencl` extras accelerate password cracking on a GPU.

## Monopoly 2008

```shell
dade monopoly08 extract ROOT
```

Unpack and convert an extracted _Monopoly_ (2008, Electronic Arts) disc for Xbox 360, PS3, PS2, or
Wii. The platform is auto-detected and every output is written next to its source inside `ROOT`.

## jubeat plus

```shell
dade jubeatplus unpack Jubeat.ipa -o out/
```

Convert a whole _jubeat plus_ (`jp.konami.jubeatplus`) download to formats that open outside iOS.
`SOURCE` may be an `.ipa`, the `.app` bundle, the `Payload` directory, or a directory holding
`Payload`; it is only read, and the converted bundle is written under `-o`/`--output-dir` into a
directory named after it.

Every encrypted asset uses the same Blowfish variant as `dade rhythmin`, differing only in the
key. There are seven, each the MD5 of a passphrase the binary assembles on the stack so it never
appears whole in the executable; two of them carry the shipped assets.

| Input                           | Output              | Notes                                                                                                                            |
| ------------------------------- | ------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `.png`                          | `.png`              | Apple-optimised (`CgBI`); rewritten by `pngdefry`.                                                                               |
| `.tex`                          | `.png`              | Enciphered, a four-byte header, then an Apple-optimised PNG.                                                                     |
| `.caf`                          | `.wav`              | Rewrapped by `ffmpeg`; the samples are copied, not re-encoded.                                                                   |
| `.jbt`                          | a directory         | One tune: metadata, artwork, title plates, three charts, and two audio streams, all enciphered, with an MD5 of the ZIP after it. |
| `.zip`                          | a directory         | Marker, hold-marker, and share images; enciphered entries with the header, plain ones left alone.                                |
| `seq_bas`, `seq_adv`, `seq_ext` | `.json`             | Note charts: header, music bar, and every event with its panel, hold length, tempo, and time.                                    |
| `.plist`, `.xcent`              | `.json`             | Data values are reported as hex; the two that are enciphered URLs are decoded as well.                                           |
| `.strings`                      | `.json`             | Read by the `dade misc strings` parser.                                                                                          |
| `.mom`, `.cdm`                  | `.json`             | Read by the `dade misc coredata` parser.                                                                                         |
| `SC_Info`                       | `SC_Info.json`      | Read by the `dade misc sc-info` parser, and written only when the directory still holds records.                                 |
| the executable                  | `<name>.macho.json` | Read by the `dade misc macho` reader.                                                                                            |

Every other file is copied unchanged, so the output is a complete bundle rather than a selection.
Nothing is decrypted beyond the game's own asset cipher: an App Store executable stays enciphered,
and its `LC_ENCRYPTION_INFO` command says so.

`pngdefry` and `ffmpeg` must be on `PATH` or given with `--pngdefry-path` and `--ffmpeg-path`. Pass
`--no-png` or `--no-audio` to skip either conversion and copy those files instead, `-j`/`--jobs` to
set the number of concurrent conversion jobs (defaults to the CPU count), and `--debug` for verbose
logging.

## pop'n rhythmin

```shell
dade rhythmin dump-chara chara001.chr
dade rhythmin dump-idx music_select.idx
dade rhythmin dump-map map_042.map
dade rhythmin dump-sheet 000000007.orb n
dade rhythmin extract-dialogue pools.inc --binary PopnRhythmin
```

Decrypt and decode the data files of the Konami iOS rhythm game _pop'n rhythmin_. Every encrypted
file uses `BFCodec`, which is Blowfish with one deviation in its F function; the key is derived
from a constant in the binary, so nothing needs to be supplied. Each `dump-*` subcommand writes
JSON to standard output:

- `dump-chara` — downloaded `chara_%03d.chr` character data.
- `dump-idx` — AEP `.idx` animation indexes, with sprite records, layer chains, and decoded
  position and colour channels. `--names`, `--layer NAME`, and `--find NAME` narrow the output.
- `dump-map` — sugoroku `map_%03d.map` boards. `--ascii` prints a text board and `--image OUT.png`
  renders a pictorial one.
- `dump-sheet` — note charts from a `.orb` or `.acv` song package, given the difficulty suffix
  (`es`, `n`, `h`, or `ex`). `--summary` drops the per-record list, `--raw` writes the decrypted
  bytes, and `--image OUT.png` renders a DDR-style strip chart.
- `extract-dialogue` — the sugoroku board dialogue pools inside a 32-bit app binary, as either the
  compiled-in C header or the runtime binary asset. The dialogue is copyrighted game content and is
  not shipped here; without `--binary` the tables are written out empty.

## Miscellaneous

```shell
dade misc coredata MODEL
dade misc macho dump BINARY
dade misc sc-info dump PATH
dade misc strings STRINGS
```

Converters and readers for platform-level formats that belong to no single game. `coredata`
deserialises a compiled Core Data model — a `.cdm` mapping model or a `.mom` managed object model —
to JSON, optionally dumping the raw keyed archive (`--archive`) or emitting the SQLite script the
migration amounts to (`--sql`, with `--mom` supplying the destination model's column types).
`strings` reads an Xcode `.strings` localisation table in either the compiled binary plist form or
the old-style text form and writes it as JSON.

`macho dump` writes the properties of a Mach-O executable as JSON: the header and its flags, the
segments and their sections, the libraries it links (weakly or otherwise), its UUID and source
version, the minimum OS it declares, the entitlements inside its code signature, and, for an image
bought from the App Store, the `LC_ENCRYPTION_INFO` command that says its text is still enciphered.
`BINARY` may be an application's executable, a framework, or a dynamic library, thin or universal;
every architecture slice is read. Nothing is decrypted and no code is disassembled.

`sc-info dump` describes the `SC_Info` directory an App Store download carries beside its encrypted
executable:

- the store item ID and, given a storefront, the App Store link;
- the `Manifest.plist`;
- the `.sinf` purchase record — buying account, purchase and transaction times, initialisation
  vector, the `righ` tag block with all eight tags named (the store item, the vendor, the tool that
  built it, and the rest), and the atom tree with every leaf's value decoded;
- the `.supf` and `.supp` supplements, each broken into its length-prefixed parts, including the
  two different Apple FairPlay certificates they embed (subject, issuer, validity, key, and every
  extension broken out field by field);
- the `.supx` tagged entries, and cross-checks between the parts.

`PATH` may be an `.ipa`, which is read in place without being unpacked, or the `SC_Info`
directory, the `.app` bundle holding it, the `Payload` directory holding that, or a directory
holding `Payload`. `--json` prints the same information as JSON, one entry per bundle.

An `SC_Info` can hold more than one set of these files, one per executable, and every set is read.
The extra set is either architecture-specific (`BofA_armv7.sinf` beside `BofA.sinf`) or left behind
by a renamed executable, and it need not be complete — a set often has a `.supp` but no `.supf`.
The set the bundle's own executable uses is named by the manifest's `SinfPaths`, and it is reported
first.

A download often holds more than the application: an app extension under `PlugIns` and a watch app
under `Watch` each carry an `SC_Info` of their own, and every one of them is read. Narrow that with
`--main-bundle`, which keeps only the application (`Payload/<name>.app`, the only bundle at that
depth), or `--bundle NAME`, which takes a bundle named in full or by its last component such as
`NotificationService.appex`. Naming the `SC_Info` directory or one bundle directly reads that one.

The App Store link is regional wherever the storefront can be established, since a store item is
only reachable in the store it was sold in. That comes from an `iTunesMetadata.plist` beside the
bundle when there is one; otherwise pass `--region`, as in `--region jp`. Without either, the link
is written without a region, which the store resolves by the reader's own storefront.

Nothing is decrypted. The only things left whole are the signatures, the key blobs, and the
encrypted `priv` body, which are reported with their length, digest, and bytes. The report lists
the first ten `.supp` records and counts the rest; `--json` always carries all of them.

## Extreme-G, Interstate '76, and Tony Hawk's Pro Skater 2

```shell
dade xg2 --help
dade i76 --help
dade thps2pc --help
```

Asset extractors and converters for _Extreme-G_ / _Extreme-G 2_ (N64 and PC), _Interstate '76_ and
_Interstate '82_, and the PC version of _Tony Hawk's Pro Skater 2_. Run each game's `--help` for its
subcommands.

## Development

```shell
uv sync --all-groups --all-extras
yarn install
```

Run the formatters and checks:

```shell
yarn format
yarn qa
```
