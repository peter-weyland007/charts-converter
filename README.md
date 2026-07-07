# charts-converter

Standalone converter for turning supported chart input sources into either packaged files or loose chart folders.

## Current state

This repo is intentionally standalone and converter-focused.

Right now it provides:
- a working **CLI** for inspect / extract / convert / validate
- a simple **desktop GUI** that wraps the same converter core
- real conversion coverage against multiple sample input files
- packaging for **macOS, Linux, and Windows** executables
- self-contained release builds that bundle the converter helper tools

## What is bundled in release builds

Release executables now bundle:
- `ffmpeg`
- `vgmstream-cli`
- `RsCli`

That means the packaged app/CLI can convert songs without requiring those tools to already be installed on the target machine.

## Supported flows right now

### Input formats
- **PSARC archive**
- **Loose chart folder**

### Output formats
- **Feedback package** (`.feedback` by default; legacy package extensions still validate)
- **Loose chart folder**

## What is still not done

- multi-stem separation (current output is a single full-song stem)
- broader source families beyond the current first real path
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
charts-converter --help
charts-converter inspect song.psarc
charts-converter extract song.psarc --work-root ./work/song
charts-converter convert song.psarc ./out/song.feedback
charts-converter convert song.psarc ./out/song-charts --output-format loose-chart-folder
charts-converter convert ./normalized/song ./out/song.feedback --input-format loose-chart-folder
charts-converter convert ./input-folder ./out-folder --batch --input-format psarc --output-format feedback-package
charts-converter validate ./out/song.feedback
charts-converter validate ./out/song-charts
```

### GUI

```bash
charts-converter-gui
```

The GUI currently gives you:
- source mode selector (single input or input-folder batch)
- input type selector
- input file/folder picker
- output type selector
- output file/folder picker
- optional scratch-folder picker
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
  - macOS: `charts-converter.app`
  - Linux: `charts-converter/`
  - Windows: `charts-converter/`
- **CLI executable**
  - `charts-converter-cli/`

under:

```text
release/dist/<platform-arch>/
```

Examples:
- `release/dist/darwin-arm64/charts-converter.app`
- `release/dist/darwin-arm64/charts-converter-cli/charts-converter-cli`

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

## Publish hygiene

The repo is set up to keep generated artifacts out of git:
- `.cache/`
- `build/`
- `dist/`
- `release/build/`
- `release/dist/`
- `*.egg-info/`

That keeps the GitHub repo source-only while still allowing local packaged handoff builds.

## Design

This tool is built as a 3-stage pipeline:
1. **extract** proprietary source assets into `raw/`
2. **normalize** those assets into a debuggable loose chart folder
3. **package or export** the normalized folder into the chosen output shape

That intermediate normalized folder is the point — it keeps the converter inspectable and fixable instead of turning into a black box.

The GUI is just a wrapper around the same core conversion code used by the CLI.
