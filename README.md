# psarc-converter

Standalone converter scaffold for turning `.psarc` sources into `.feedpak` packages.

## Current state

This repo is intentionally standalone and converter-focused.

Right now it provides a working CLI for:
- `inspect` — inspect a candidate `.psarc`, fingerprint it, and list archive contents
- `extract` — unpack a `.psarc` into a staged raw workspace
- `convert` — convert a `.psarc` to `.feedpak`, or package an already-normalized loose song folder
- `validate` — validate a `.feedpak` or loose package by checking its manifest and package shape

What is currently expected on the host:
- `ffmpeg`
- `vgmstream-cli`

What is not done yet:
- multi-stem separation (current output is a single full-song stem)
- broader source-format normalization beyond the Rocksmith PSARC/XML path implemented here

## Install

```bash
pip install -e .
```

## Usage

```bash
psarc-converter --help
psarc-converter inspect song.psarc
psarc-converter extract song.psarc --work-root ./work/song
psarc-converter convert ./normalized-song ./out/song.feedpak
psarc-converter validate ./out/song.feedpak
```

## Design

This tool is built as a 3-stage pipeline:
1. **extract** proprietary source assets into `raw/`
2. **normalize** those assets into a debuggable loose song folder
3. **package** the normalized folder into `.feedpak`

That intermediate normalized folder is the point — it keeps the converter inspectable and fixable instead of turning into a black box.
