# dade

<!-- WISWA-GENERATED-README:START -->

[![Python versions](https://img.shields.io/pypi/pyversions/dade.svg?color=blue&logo=python&logoColor=white)](https://www.python.org/)
[![PyPI - Version](https://img.shields.io/pypi/v/dade)](https://pypi.org/project/dade/)
[![GitHub tag (with filter)](https://img.shields.io/github/v/tag/Tatsh/dade)](https://github.com/Tatsh/dade/tags)
[![License](https://img.shields.io/github/license/Tatsh/dade)](https://github.com/Tatsh/dade/blob/master/LICENSE.txt)
[![GitHub commits since latest release (by SemVer including pre-releases)](https://img.shields.io/github/commits-since/Tatsh/dade/v0.0.2/master)](https://github.com/Tatsh/dade/compare/v0.0.2...master)
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
of one `dade` command. Every tool is therefore invoked the same way:

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
| `dade maxpayne`   | _Max Payne_ and _Max Payne 2_ (PC)          | Remedy Entertainment          |
| `dade misc`       | Formats belonging to no single game         | None                          |
| `dade monopoly08` | _Monopoly_ (2008, multi-platform)           | Electronic Arts               |
| `dade rbplus`     | _REFLEC BEAT plus_ (iOS)                    | Konami                        |
| `dade rhythmin`   | _pop'n rhythmin_ (iOS)                      | Konami                        |
| `dade sopranos`   | _The Sopranos: Road to Respect_ (PS2)       | 7 Studios / THQ               |
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

`SOURCE` may be a PC disc directory or ISO that has `DATA1.CAB` (or the `DATA1.CAB` itself), a
Dreamcast `.gdi` file, or a directory of already extracted PC or GD-ROM content. Recognised assets
are converted (PVR and PPM to PNG, IAN and `*_M.BIN` to OBJ and MTL, terrain, saves, and `.ctl` to
JSON, CDDA `.raw` and `.OSB` to WAV, Shift-JIS or ISO-8859-15 `.TXT` to UTF-8) and every other file
is copied verbatim. The source is never modified.

An installed copy works as the source too. Point at the game's directory, such as the
`Incoming 3DFX` folder of the
[Zoom Platform _Incoming Trilogy_](https://www.zoom-platform.com/product/incoming-trilogy)
(`…/Incoming Trilogy/Incoming 3DFX`). The _Incoming 3DFX_, _Incoming USA_, and _Incoming Subversion_
(an expansion pack) titles share the original engine and are supported; _Incoming Forces_ is not
supported.

Pass `--gdiextract-path`, `--spvr2png-path`, or `--unshield-path` to point at the native tools when
they are not on `PATH`, `-j`/`--jobs` to set the number of concurrent conversion jobs (defaults to
the CPU count), and `--debug` for verbose logging.

Two further subcommands convert a single asset without mirroring a whole source tree:

- `dade incoming ian2obj MODEL OUTDIR` converts one model to Wavefront OBJ and MTL. Both the PC
  `.ian` mesh and the Dreamcast `*_M.BIN` model pack are accepted (the format is detected from the
  file name); a Dreamcast pack needs its matching `*_ML.BIN` index beside it and yields one OBJ and
  MTL per object. The texture is resolved from the game root, auto-detected from `MODEL` or set with
  `--game-root`, unless `--no-texture` is given.
- `dade incoming extract-pvr-pack PACK OUTDIR` unpacks a Dreamcast `*_T.PVR` texture pack,
  writing each texture as a separate `.pvr` file, or as a PNG with `--png` (requires `spvr2png`).

### Native tools

Some Incoming conversions shell out to native helpers. Each must be on `PATH` or supplied with the
matching `--*-path` option:

- [7z](https://www.7-zip.org/) extracts `DATA1.CAB` from a PC ISO (used when `isodump` is absent).
- [gdiextract](https://github.com/MachXNU/gdiextract) extracts the ISO 9660 file system from a
  Dreamcast GDI.
- [isodump](https://sourceforge.net/projects/cdrtools/) extracts `DATA1.CAB` from a PC ISO.
- [spvr2png](https://github.com/nextgeniuspro/spvr2png) converts Sega Dreamcast PVR images to PNG.
- [unshield](https://github.com/twogood/unshield) unpacks the InstallShield `DATA1.CAB` cabinet on
  the PC disc.

## Amplitude and FreQuency

```shell
dade amplitude unpack DISC -o OUT
dade frequency unpack DISC -o OUT
```

_Amplitude_ and _FreQuency_ (Harmonix) share one PS2 engine but are separate commands, one per game.
Point either at its disc directory (`DISC`). Every ARK is unpacked mirroring its location, disc
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
`SOURCE` may be an `.ipa`, the `.app` bundle, the `Payload` directory, or a directory with
`Payload` inside; it is only read, and the converted bundle is written under `-o`/`--output-dir`
into a directory that takes its name.

Every encrypted asset uses the same Blowfish variant as `dade rhythmin`, differing only in the
key. There are seven, each the MD5 of a passphrase the binary assembles on the stack. The
passphrase therefore never appears whole in the executable, and two of the seven include the
shipped assets.

| Input                           | Output              | Notes                                                                                                                            |
| ------------------------------- | ------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `.png`                          | `.png`              | Apple-optimised (`CgBI`); rewritten by `pngdefry`.                                                                               |
| `.tex`                          | `.png`              | Enciphered, a four-byte header, then an Apple-optimised PNG.                                                                     |
| `.caf`                          | `.wav`              | Rewrapped by `ffmpeg`; the samples are copied, not re-encoded.                                                                   |
| `.jbt`                          | a directory         | One tune: metadata, artwork, title plates, three charts, and two audio streams, all enciphered, with an MD5 of the ZIP after it. |
| `.zip`                          | a directory         | Marker, hold-marker, and share images; enciphered entries with the header, plain ones unmodified.                                |
| `seq_bas`, `seq_adv`, `seq_ext` | `.json`             | Note charts: header, music bar, and every event with its panel, hold length, tempo, and time.                                    |
| `.plist`, `.xcent`              | `.json`             | Data values are reported as hex; the two that are enciphered URLs are decoded as well.                                           |
| `.strings`                      | `.json`             | Read by the `dade misc strings` parser.                                                                                          |
| `.mom`, `.cdm`                  | `.json`             | Read by the `dade misc coredata` parser.                                                                                         |
| `SC_Info`                       | `SC_Info.json`      | Read by the `dade misc sc-info` parser, and written only when the directory still has records.                                   |
| the executable                  | `<name>.macho.json` | Read by the `dade misc macho` reader.                                                                                            |

Every other file is copied unchanged. The output is therefore a complete bundle rather than a
selection. Nothing is decrypted beyond the game's asset cipher. An App Store executable stays
enciphered, and its `LC_ENCRYPTION_INFO` command records that.

`pngdefry` and `ffmpeg` must be on `PATH` or given with `--pngdefry-path` and `--ffmpeg-path`. Pass
`--no-png` or `--no-audio` to skip either conversion and copy those files instead, `-j`/`--jobs` to
set the number of concurrent conversion jobs (defaults to the CPU count), and `--debug` for verbose
logging.

## REFLEC BEAT plus

```shell
dade rbplus unpack "REFLEC BEAT plus.app" -o out/
dade rbplus extract-assets iPhone@2x.zip -o out/
dade rbplus dump-chart 100000109.rb har --image chart.png
dade rbplus site *.rb -o site/
```

Convert a whole _REFLEC BEAT plus_ (`jp.konami.reflecbeatplus`) download to formats that open
outside iOS. `SOURCE` may be an `.ipa`, the `.app` bundle, the `Payload` directory, or a directory
with `Payload` inside; it is only read, and the converted bundle is written under `-o`/`--output-dir`
into a directory that takes its name.

A tune ships as a `%09d.rb` package, an ordinary ZIP whose every entry is enciphered with the same
Blowfish variant as `dade rhythmin` and `dade jubeatplus`, differing only in the key. There are two
keys, and neither appears in the executable as a passphrase. Each is stored with every byte reduced
by its index. Adding the index back yields `Konami ReflecBeat For iOS.` and
`Konami ReflecBeatplus.`, whose MD5s are the keys. A package does not record which one it uses. The
first is tried, and the second used when the metadata does not parse.

| Input                                | Output           | Notes                                                                                      |
| ------------------------------------ | ---------------- | ------------------------------------------------------------------------------------------ |
| `.rb`                                | a directory      | One tune: metadata, artwork, title and artist strips, three charts, and two audio streams. |
| ↳ `info`                             | `.json`          | Title and artist with their readings, the three levels, and the tempo range.               |
| ↳ `artwork`, `title_*`, `artist_*`   | `.png`           | Apple-optimised (`CgBI`); rewritten by `pngdefry`. Each also ships at `2x`.                |
| ↳ `note_bas`, `note_med`, `note_har` | `.json` + `.png` | RBFF charts, as data and as a rendered strip image.                                        |
| ↳ `bgm`, `pre`                       | `.m4a`           | Already a portable container, and written out rather than transcoded.                      |
| `.png`                               | `.png`           | Apple-optimised; rewritten by `pngdefry`.                                                  |
| `.caf`                               | `.wav`           | Rewrapped by `ffmpeg`; the samples are copied, not re-encoded.                             |
| `.m4a`                               | `.m4a`           | Copied.                                                                                    |
| `.plist`, `.xcent`                   | `.json`          | Read by the `dade misc` property list reader.                                              |
| `.strings`                           | `.json`          | Read by the `dade misc strings` parser.                                                    |
| `.mom`                               | `.json`          | Read by the `dade misc coredata` parser.                                                   |
| `SC_Info`                            | `SC_Info.json`   | Read by the `dade misc sc-info` parser.                                                    |

Mach-O images are omitted entirely. Neither the executable nor the debug copy under `.dSYM` is
read, converted, or copied. Every other file is copied unchanged, and the output is therefore a
complete bundle rather than a selection.

A chart is drawn as a strip. _REFLEC BEAT_ is a versus game, and the two sides are separate sets of
notes rather than one set divided. Each side is therefore drawn as a separate panel, side 0 (pink)
on the left and side 1 (blue) on the right, and counted separately.

Whether a note's lane is drawn from the chart or invented depends on its route selector. One
specifying a lane, 0 to 6, comes straight down into that lane and no randomness touches it. Slides
and vertical notes are all positioned from the chart. One specifying 7, 8, or 9 is aimed at one of
the three alternative targets. Those targets sit beyond the seven lanes. Only a note specifying
nothing is positioned at run time, from a generator seeded with `rand()` when play starts. That
part of a chart therefore falls differently on every play. Those notes are positioned here from a
seed, fresh on each run unless `--seed` pins one, under the engine's two rules. A chain member
inherits the lane of the segment before it, and a chain therefore runs straight up a single lane.
Notes one side strikes together cannot share a lane, and they take neighbouring lanes instead. A
hold retains its lane until it is released.

Time runs upward, the way the notes fall, wrapped into columns and ruled on every quarter note when
the tune's tempo is known. A hold extends as a bar to the moment it is released, a note aimed at an
alternative target is green, one that travels to the other side to be swiped back is half gold, a
vertical note is marked with a V, each note of a chain is joined to the next by a line, a slide
draws the track the finger takes from the note across to each of its waypoints, and a speed change
rules its column across. Every image includes a drawn legend that documents these conventions.

`--speed`, from 1.0 to 2.0 as the game offers it, spreads the notes further apart without changing
how much time a column covers. `--scale`, from 1.0 to 3.0, writes the image larger for a display
that would otherwise have to enlarge it.

The suffix given to `--image` chooses the form the strip is written in, and the picture is the same
in both:

- `.png` is a raster image, drawn at three times its size and reduced once. Every edge is therefore
  smoothed.
- `.svg` is the same drawing as vectors, and it enlarges without loss.

A chart to be read in a browser is a whole site rather than one picture; see
[the chart browser](#chart-browser) below.

`dade rbplus dump-chart` also reads one note chart from a separate file, either as the package
stores it or already deciphered, in which case the difficulty is taken from the file name when the
name states one and must be given otherwise. `--key` and `--iv`, both hex, read a chart enciphered
under neither of the game's keys.

`dade rbplus extract-assets` unpacks one of the three texture archives the game downloads (`iPad`,
`iPad2x`, and `iPhone@2x`), each with a little over two thousand PNGs under ZipCrypto. The
archive's index, a second encrypted ZIP stored as its `list` entry, is written out as
`manifest.json`. Each texture is examined and only the Apple-optimised ones go through `pngdefry`.

`pngdefry` and `ffmpeg` must be on `PATH` or given with `--pngdefry-path` and `--ffmpeg-path`. Pass
`--no-png`, `--no-audio`, or `--no-images` to skip a conversion, `-j`/`--jobs` to set the number of
concurrent jobs (defaults to the CPU count), and `--debug` for verbose logging.

### Chart browser

```shell
dade rbplus site *.rb -o site/
dade rbplus site packages/ -o site/ --base /rbpcharts/
```

`dade rbplus site` builds a page that browses a whole collection. Pick a tune and a difficulty and
the chart is drawn. `SOURCES` may list `.rb` packages, directories with packages inside, or both,
and a directory is searched all the way down.

Each tune's charts are written as JSON under `data/` and the page draws them. The site is therefore
static and needs nothing running to serve it. The drawing is the same one `--image` makes. The
columns, the lanes, the holds, the chains, and the slides are worked out in the browser from the
notes. Working them out in the browser is also what lets a chart file you supply be opened from the
page. That file is read where it is and sent nowhere. Only a deciphered chart is read. The key
belongs to the game.

The site ships as an installable app. A web app manifest, a service worker, and the icons are
written beside the page. A browser therefore offers to install it and, once a tune has been looked
at, opens it again with no network. Every address in the manifest is relative, and it installs the
same whether the site is served from a dedicated domain or from a subdirectory under `--base`.

Tunes are filed A-Z or by gojūon row, and searched by title or artist in kana or in Latin letters.
The shipped packages omit the metadata's romanised fields and give the kana reading instead. The
reading is therefore romanised here, and a Latin keyboard is matched against the romanisation. How
a reading is written and how it is typed are both accepted, and `愛を` resolves to `aio` and to
`aiwo`.

A package with one chart in the basic entry and nothing in the other two is an **extend note**, a
SPECIAL chart, harder than hard, that the game sold for a tune that already exists. It is filed
under that tune rather than listed separately, the tune being the one whose identifier is 50000
lower.

Given `--base`, the site addresses tunes by path and writes a `404.html` beside the page. The
`404.html` is what lets a link to one tune be opened directly on GitHub Pages. Without `--base`,
tunes are addressed by fragment. A fragment needs no extra file and works from any directory.

## pop'n rhythmin

```shell
dade rhythmin dump-chara chara001.chr
dade rhythmin dump-idx music_select.idx
dade rhythmin dump-map map_042.map
dade rhythmin dump-sheet 000000007.orb n
dade rhythmin extract-dialogue pools.inc --binary PopnRhythmin
```

Decrypt and decode the data files of the Konami iOS rhythm game _pop'n rhythmin_. Every encrypted
file uses `BFCodec`. `BFCodec` is Blowfish with one deviation in its F function; the key is derived
from a constant in the binary, and nothing needs to be supplied. Each `dump-*` subcommand writes
JSON to standard output:

- `dump-chara` reads downloaded `chara_%03d.chr` character data.
- `dump-idx` reads AEP `.idx` animation indexes, with sprite records, layer chains, and decoded
  position and colour channels. `--names`, `--layer NAME`, and `--find NAME` narrow the output.
- `dump-map` reads sugoroku `map_%03d.map` boards. `--ascii` prints a text board and
  `--image OUT.png` renders a pictorial one.
- `dump-sheet` reads note charts from a `.orb` or `.acv` song package, given the difficulty suffix
  (`es`, `n`, `h`, or `ex`). `--summary` drops the per-record list, `--raw` writes the decrypted
  bytes, and `--image OUT.png` renders a DDR-style strip chart.
- `extract-dialogue` reads the sugoroku board dialogue pools inside a 32-bit app binary, as either
  the compiled-in C header or the runtime binary asset. The dialogue is copyrighted game content and
  is not shipped here; without `--binary` the tables are written out empty.

## Miscellaneous

```shell
dade misc coredata MODEL
dade misc macho dump BINARY
dade misc sc-info dump PATH
dade misc strings STRINGS
```

Converters and readers for platform-level formats that belong to no single game. `coredata`
deserialises a compiled Core Data model (a `.cdm` mapping model or a `.mom` managed object model)
to JSON, optionally dumping the raw keyed archive (`--archive`) or emitting the SQLite script the
migration amounts to (`--sql`, with `--mom` supplying the destination model's column types).
`strings` reads an Xcode `.strings` localisation table in either the compiled binary plist form or
the old-style text form and writes it as JSON.

`macho dump` writes the properties of a Mach-O executable as JSON: the header and its flags, the
segments and their sections, the libraries it links (weakly or otherwise), its UUID and source
version, the minimum OS it declares, the entitlements inside its code signature, and, for an image
bought from the App Store, the `LC_ENCRYPTION_INFO` command reporting its text as still enciphered.
`BINARY` may be an application's executable, a framework, or a dynamic library, thin or universal;
every architecture slice is read. Nothing is decrypted and no code is disassembled.

`sc-info dump` describes the `SC_Info` directory an App Store download includes beside its
encrypted executable:

- the store item ID and, given a storefront, the App Store link;
- the `Manifest.plist`;
- the `.sinf` purchase record, with buying account, purchase and transaction times, initialisation
  vector, the `righ` tag block with all eight tags identified (the store item, the vendor, the tool
  that built it, and the rest), and the atom tree with every leaf's value decoded;
- the `.supf` and `.supp` supplements, each broken into its length-prefixed parts, including the
  two different Apple FairPlay certificates they embed (subject, issuer, validity, key, and every
  extension broken out field by field);
- the `.supx` tagged entries, and cross-checks between the parts.

`PATH` may be an `.ipa`, read in place without being unpacked, or the `SC_Info` directory, the
`.app` bundle around it, the `Payload` directory above the bundle, or a directory with `Payload`
inside. `--json` prints the same information as JSON, one entry per bundle.

An `SC_Info` can include more than one set of files, one per executable, and every set is read. The
extra set is either architecture-specific (`BofA_armv7.sinf` beside `BofA.sinf`) or a remnant of a
renamed executable, and it need not be complete. A set often has a `.supp` but no `.supf`. The set
the bundle's executable uses is identified by the manifest's `SinfPaths`, and it is reported first.

A download often includes more than the application. An app extension under `PlugIns` and a watch
app under `Watch` each have an `SC_Info`, and every one is read. Narrow the selection with
`--main-bundle`, retaining only the application (`Payload/<name>.app`, the only bundle at that
depth), or with `--bundle NAME`, accepting a bundle identified in full or by its last component such
as `NotificationService.appex`. Specifying the `SC_Info` directory or one bundle directly reads only
that bundle.

The App Store link is regional wherever the storefront can be established. A store item is available
only in the store it was sold in. The storefront comes from an `iTunesMetadata.plist` beside the
bundle when there is one; otherwise pass `--region`, as in `--region jp`. Without a storefront, the
link is written without a region, and the store resolves it by the reader's storefront.

Nothing is decrypted. The signatures, the key blobs, and the encrypted `priv` body remain whole, and
each is reported with its length, digest, and bytes. The report lists the first ten `.supp` records
and counts the rest; `--json` always includes all of them.

## The Sopranos: Road to Respect

```shell
dade sopranos unpack SOPRANOS.ISO -o extracted --convert
```

One command takes the PlayStation 2 disc apart and converts everything it recognises. The argument
may be a disc image, a directory (searched recursively for `.FS` archives, however they are cased),
or any number of archives specified directly:

```shell
dade sopranos unpack DATA_P.FS AUDIO_P.FS POKER_P.FS SLOTS_P.FS -o extracted --convert
```

Each archive lands in a directory titled after it with the region suffix dropped. `DATA_P.FS`
therefore unpacks into `extracted/data`. With `--convert`, the `.LVL` containers are split first and
the assets inside them are converted by the same pass, and then:

| Input                         | Output                                                     |
| ----------------------------- | ---------------------------------------------------------- |
| `.TEX2` texture banks         | PNG, with PlayStation 2 alpha rescaled to `0..255`         |
| `.EGP2` level geometry        | a `.glb` with the level's props placed in it, plus OBJ/MTL |
| `.SGP2` prop libraries        | the PNGs they embed                                        |
| `.MSH` / `.MSB` sound banks   | one WAV per sound                                          |
| `.MIH` / `.MIB` music streams | WAV, de-interleaved back to stereo                         |
| `.VO2` dialogue               | WAV, stitched from the `AUDO` blocks                       |

The level `.glb` is the most involved output. Props are read from the `.SGP2` libraries belonging to
the level, positioned and turned according to the `.OLV` file that records where each one stands, and
written into the same file as the level geometry. Characters with interchangeable wardrobe pieces are
given one of each, rather than all of them at once.

The retail disc converts clean, and `--ignore-failures` is not needed for it. Pass the flag to log
and skip an asset that will not convert instead of stopping.

## Max Payne and Max Payne 2

```shell
dade maxpayne ras-list MAXPAYNE.ISO
dade maxpayne ras-extract MAXPAYNE.ISO -o extracted
```

Readers for the RAS (Remedy Archive System) containers both games load everything from. An argument
may be a `.ras` archive, a `.mpm` mod package, a directory (searched recursively), an InstallShield
`DATA1.CAB`, an ISO, the `.cue` of a cue/bin pair, or a bare `.bin`. A raw BIN with no cue sheet is
unwrapped by its sector sync patterns, and a rip that lost its cue still reads.

A retail disc needs both routes at once, and the extractor handles that. The level archives sit
loose on the disc, while the shared game database is inside `DATA1.CAB` and is unpacked with
[`unshield`](https://github.com/twogood/unshield). A cabinet is skipped with a warning when
`unshield` is missing, and the loose archives still come out.

Both commands take as many sources as a game shipped discs. A cabinet does not have to fit on one.
Max Payne 2 splits its cabinet across two discs: `data1.cab`, `data1.hdr` and `data2.cab` are on the
install disc and `data3.cab` is on the play disc, and `unshield` needs all four together. The parts
are gathered from every source given before it is unpacked once. The discs may therefore be given in
any order and in whatever mixture of formats they were ripped to.

```shell
dade maxpayne ras-extract "MP2 (Install).iso" "MP2 (Play).bin" -o extracted
dade maxpayne ras-extract MAXPAYNE.ISO -p '*/levels/*' -o levels
```

`ras-extract` takes `--pattern` rather than a trailing glob, and it is repeatable; the sources are
the variadic argument.

Members are stored back to back with no offset field, and the directory therefore doubles as an
integrity check. `ras-list` reports an archive as `intact` when the header, both tables, and every
stored size account for the file exactly.

Every member is LZSS-compressed and the archive tables are encrypted, both handled transparently.
Pass `--raw` to `ras-extract` to retain the `RA->` and `RC->` wrappers.

```shell
dade maxpayne inspect-tags extracted/data/database/levels/part1/Part1_Level6.ldb
```

`inspect-tags` decodes the tagged `R_MemoryFile` stream that every custom asset is built from,
identifying each value's type. The walk stops where a level exits tagged territory, at the point its
first untagged string begins.

```shell
dade maxpayne ldb2glb extracted/data/database/levels -o glb
dade maxpayne ldb-textures extracted/data/database/levels -o textures
```

```shell
dade maxpayne ldb2glb extracted/data/database/levels -D extracted/data/database -o glb
```

`ldb2glb` converts levels to binary glTF, one `.glb` per `.ldb`, in parallel across every core.
Pass `--database` and the NPCs and pickups are drawn with their models, read from the game's
`skins` and `level_items` directories; without `--database` they are written as empty nodes with
names.
Each file includes the level's architecture, its props, the game's texture coordinates, and every
embedded image.

Both games are read, and which one a level came from does not have to be given. A Max Payne 2 level
opens with `LDB2` and is recognised by it. `--database` applies to the first game only, the game
whose `skins` and `level_items` directories exist. A Max Payne 2 level includes its props inside
itself.

Every clip a prop can play (a door swinging either way, a lift rising, a fan turning) comes out as a
glTF animation with a name, and a viewer can list and play them. A level stores a clip as two poses
and two curves, one giving the distance travelled in world units and the other how far the prop has
turned; both are baked into keyframes on the way out, and a clip that moves nothing is dropped.

The baked lighting is written too. Each level's atlases are embedded, each face identifies the atlas
that lights it, and the second coordinate set addresses the atlas. The lightmap goes in glTF's
occlusion slot, the closest the format has to a lightmap. A viewer wanting the game's look should
multiply the occlusion texture's colour into the base rather than treat it as ambient occlusion.

The sky is written out. A level's `skybox` faces are what closes it off wherever it opens to the
air, and omitting them puts a hole through every street. They get a flat unlit colour. The sky the
game drew came from the renderer rather than from the level. Their placeholder image is never used,
and `dummy`'s placeholder stays dropped as well.

Graffiti, signage and switchable surfaces come off their walls slightly. A level places each of them
in exactly the plane of what it covers, and nothing in the file marks which is which. The engine
walked its BSP and never drew both at once. A viewer draws the whole level and has only a depth
buffer, and `dade.maxpayne.decals` therefore works the layering out from the geometry and lifts each
covered face about eight millimetres along its normal.

Four properties of the format are easy to get backwards. A face's corner count is not its number of
sides. The editor drops extra corners along edges it shares with other faces, and triangulating from
corner nought can therefore start with a straight line. Taking the winding from that start turns 822
of the shipped faces inside out. A material's second string is the material's _name_, not a
filename, and only the level's category table records which image it draws with. Matching on
filename instead renders a fifth of a level's faces untextured. Level architecture is already in
world space, retaining its transform only as the editor's pivot, while an animated prop is placed by
its transform. Applying both the same way moves the architecture twice. A model's texture
coordinates are stored with V running negative and are meant to be used exactly as written,
Direct3D's wrapping doing the rest. Negating them to get a tidy `0..1` range turns every skin upside
down, and the effect shows on a face and nowhere else.

The sequel retains the tagged stream and the archives and rearranges everything above them, and
`dade.maxpayne.ldb2` is therefore a separate reader feeding the same exporter. Its strings live in
one pool addressed by byte offset, its textures are DDS in five groups rather than one, its vertices
are packed float arrays behind a sixteen-bit index buffer, and its collision is Havok. A room
includes the transform that puts it in the world, where the first game deferred placement to the
exit graph and had to be assembled by walking it. Geometry an artist placed more than once is
written once and referred to afterwards. A reader that always expects a mesh therefore loses its
place on the second copy and every byte after it.

Two of the sequel's records beat working the values out. The sequel states each surface's draw
order, and decals are therefore lifted from what the level records rather than from the geometry.
Deriving them instead moves 3917 faces of `21_The_Manor` where the level marks 1761. The sequel
duplicates a material per lightmap, neighbouring floor tiles end up with different material IDs, and
the floor cracks along the seams. A prop is also placed by the state machine it identifies, the only
world-space transform it has. Its clips cannot stand in for the state machine. A door's first clip
is a `Close`, and the door therefore _starts_ open. A clip belonging to a parented prop is written
in the parent's space. Props 50 to 54 of `03_First_Hospital` each have one whose rotation matches
its state machine exactly while its translation does not, the first of them reading
`(-0.03, -0.51, -0.27)` against the state machine's `(-1.24, -4.31, -25.58)`. Pose a level from clip
transforms and its doors hang open and its parented props collapse towards the origin.

The state machine is only half of a prop's placement. Its vertices are written about their midpoint,
and 582 of `09_Upper_East_Side`'s 594 props sit exactly on that midpoint. The mesh container states,
ahead of its batches, where the midpoint falls in the state machine's space. Both are needed. Take
the state machine alone and `10_Police_Station`'s vending machine stands with its front panel out of
the recess it closes, and a cell door floats 1.5 units over the floor. The state machine is the
hinge at the top rather than the panel hanging off it.

The sequel's animation curves state a time with every sample and rarely space them evenly. Of the
2454 curves in the first six levels, 898 are uneven. They are Catmull-Rom splines, evaluated with
the outer control values pulled onto each span. The shape therefore survives the uneven spacing.
Read them as evenly spaced straight lines instead and a clip that eases hard runs at the wrong speed
for most of its length. Measured against the game's evaluation, the worst of the first five levels
is most of its motion out of step.

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

The `dade rbplus site` chart browser is written as Sass and TypeScript under `assets/site` and built
with webpack:

```shell
yarn build
```

The result is written to `dade/rbplus/site` and is committed. An install from PyPI has no Node to
build it with. Rebuild and commit the bundle alongside any change to `assets/site`;
`yarn build:check` fails if the sources and the bundle have drifted apart. `yarn build:dev` builds
the same bundle whole, without minifying, and with source maps.
