# psarc-converter

Standalone converter for turning `.psarc` sources into `.feedpak` packages.

## Current state

This repo is intentionally standalone and converter-focused.

Right now it provides:
- a working **CLI** for inspect / extract / convert / validate
- a simple **desktop GUI** that wraps the same converter core
- real conversion coverage against multiple sample `.psarc` files

What is currently expected on the host:
- `ffmpeg`
- `vgmstream-cli`

What is not done yet:
- multi-stem separation (current output is a single full-song stem)
- broader source-format normalization beyond the Rocksmith PSARC path implemented here
- GUI polish beyond the first usable local window

## Install

```bash
pip install -e .
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

## Design

This tool is built as a 3-stage pipeline:
1. **extract** proprietary source assets into `raw/`
2. **normalize** those assets into a debuggable loose song folder
3. **package** the normalized folder into `.feedpak`

That intermediate normalized folder is the point — it keeps the converter inspectable and fixable instead of turning into a black box.

The GUI is just a wrapper around the same core conversion code used by the CLI.
