# psarc-converter

Standalone converter for turning `.psarc` sources into `.feedpak` packages.

## Current state

This repo is intentionally standalone and converter-focused.

Right now it provides:
- a working **CLI** for inspect / extract / convert / validate
- a simple **desktop GUI** that wraps the same converter core
- real conversion coverage against multiple sample `.psarc` files
- packaging for **macOS, Linux, and Windows** executables
- self-contained release builds that bundle the converter helper tools

## What is bundled in release builds

Release executables now bundle:
- `ffmpeg`
- `vgmstream-cli`
- `RsCli`

That means the packaged app/CLI can convert songs without requiring those tools to already be installed on the target machine.

## What is still not done

- multi-stem separation (current output is a single full-song stem)
- GUI polish beyond the first usable local window
- notarization/signing/distribution polish for consumer-facing macOS releases

## Install

### Python / editable dev install

```bash
pip install -e .
```

### Build dependencies

```bash
pip install -e '.[build]'
```

## Usage

### CLI

```bash
psarc-converter --help
psarc-converter inspect song.psarc
psarc-converter extract song.psarc --work-root ./work/song
psarc-converter convert song.psarc ./out/song.feedpak
psarc-converter validate ./out/song.feedpak
```

### GUI

```bash
psarc-converter-gui
```

The GUI currently gives you:
- PSARC file picker
- output file picker
- optional work-folder picker
- Convert button
- Validate Output button
- activity log
- Open Output Folder button

## Click-to-launch builds

Build local executables with:

```bash
python scripts/build_release.py
```

That produces:
- **GUI app**
  - macOS: `psarc-converter.app`
  - Linux: `psarc-converter/`
  - Windows: `psarc-converter/`
- **CLI executable**
  - `psarc-converter-cli/`

under:

```text
release/dist/<platform-arch>/
```

Examples:
- `release/dist/darwin-arm64/psarc-converter.app`
- `release/dist/darwin-arm64/psarc-converter-cli/psarc-converter-cli`

Notes:
- the GUI build is the click-to-launch desktop app
- the CLI build is for terminal-only use
- helper binaries are staged automatically during the build
- GitHub Actions also builds zipped artifacts for macOS / Linux / Windows

## GitHub Actions release flow

The repo includes:
- `.github/workflows/build-release.yml`

It will:
- run tests
- prepare bundled runtime tools for the runner OS
- build GUI + CLI artifacts on macOS, Linux, and Windows
- upload zipped artifacts
- attach them to tagged releases like `v0.1.0`

## Design

This tool is built as a 3-stage pipeline:
1. **extract** proprietary source assets into `raw/`
2. **normalize** those assets into a debuggable loose song folder
3. **package** the normalized folder into `.feedpak`

That intermediate normalized folder is the point — it keeps the converter inspectable and fixable instead of turning into a black box.

The GUI is just a wrapper around the same core conversion code used by the CLI.
