from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml
from PIL import Image

from .psarc import list_entries, unpack_psarc
from .runtime import find_command
from .song_xml import arrangement_to_wire, load_song, parse_lyrics


@dataclass
class ToolProbe:
    name: str
    command: str
    found: bool


@dataclass
class PsarcInspection:
    path: str
    exists: bool
    size_bytes: int
    sha256: str
    magic_hex: str
    suffix: str
    looks_like_psarc: bool
    entry_count: int
    entries_preview: list[str]
    extractor_candidates: list[ToolProbe]


@dataclass
class ExtractionReport:
    input_path: str
    raw_dir: str
    extracted_files: int
    entries_preview: list[str]


@dataclass
class ValidationReport:
    path: str
    ok: bool
    manifest_path: str | None
    issues: list[str]
    warnings: list[str]
    arrangement_count: int
    feedpak_version: str | None
    title: str | None
    artist: str | None


@dataclass
class ConversionReport:
    input_path: str
    output_path: str
    title: str
    artist: str
    arrangement_count: int
    arrangement_names: list[str]
    stem_files: list[str]
    work_root: str
    manifest_path: str
    used_cover: bool
    used_lyrics: bool


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _probe_extractors() -> list[ToolProbe]:
    candidates = [
        ("vgmstream-cli", "vgmstream-cli"),
        ("ffmpeg", "ffmpeg"),
        ("psarc", "psarc"),
        ("psarcutil", "psarcutil"),
    ]
    return [ToolProbe(name=name, command=cmd, found=shutil.which(cmd) is not None) for name, cmd in candidates]


def inspect_psarc(path: str | Path) -> PsarcInspection:
    p = Path(path)
    exists = p.exists()
    size = p.stat().st_size if exists else 0
    sha = _sha256_file(p) if exists and p.is_file() else ""
    magic = ""
    entries: list[str] = []
    if exists and p.is_file():
        with p.open("rb") as fh:
            magic = fh.read(16).hex()
        try:
            entries = list_entries(p)
        except Exception:
            entries = []
    looks_like_psarc = magic.startswith("50534152") or p.suffix.lower() == ".psarc"
    return PsarcInspection(
        path=str(p.resolve()) if exists else str(p),
        exists=exists,
        size_bytes=size,
        sha256=sha,
        magic_hex=magic,
        suffix=p.suffix.lower(),
        looks_like_psarc=looks_like_psarc,
        entry_count=len(entries),
        entries_preview=entries[:20],
        extractor_candidates=_probe_extractors(),
    )


def _default_work_root(input_path: Path) -> Path:
    return Path(".cache") / "psarc-converter" / input_path.stem.replace(" ", "_")


def _find_manifest_in_dir(src: Path) -> Path:
    for name in ("manifest.yaml", "manifest.yml"):
        candidate = src / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"manifest.yaml not found in {src}")


def _read_manifest_from_dir(src: Path) -> tuple[dict, str]:
    manifest_path = _find_manifest_in_dir(src)
    with manifest_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError("Manifest root must be a mapping")
    return data, str(manifest_path.resolve())


def _read_manifest_from_zip(src: Path) -> tuple[dict, str]:
    with zipfile.ZipFile(src, "r") as zf:
        for name in ("manifest.yaml", "manifest.yml"):
            try:
                raw = zf.read(name)
            except KeyError:
                continue
            data = yaml.safe_load(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Manifest root must be a mapping")
            return data, name
    raise FileNotFoundError("manifest.yaml not found in archive")


def package_loose_song(loose_dir: str | Path, output_path: str | Path) -> Path:
    src = Path(loose_dir)
    if not src.is_dir():
        raise FileNotFoundError(f"Loose song directory not found: {src}")
    _find_manifest_in_dir(src)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for child in sorted(src.rglob("*")):
            if child.is_file():
                zf.write(child, child.relative_to(src).as_posix())
    return out


def validate_feedpak(path: str | Path) -> ValidationReport:
    p = Path(path)
    if not p.exists():
        return ValidationReport(str(p), False, None, [f"Path does not exist: {p}"], [], 0, None, None, None)
    try:
        manifest, manifest_path = _read_manifest_from_dir(p) if p.is_dir() else _read_manifest_from_zip(p)
    except Exception as exc:
        return ValidationReport(str(p.resolve()), False, None, [f"Failed to load manifest: {exc}"], [], 0, None, None, None)

    issues: list[str] = []
    warnings: list[str] = []
    title = manifest.get("title") if isinstance(manifest.get("title"), str) else None
    artist = manifest.get("artist") if isinstance(manifest.get("artist"), str) else None
    feedpak_version = manifest.get("feedpak_version") if isinstance(manifest.get("feedpak_version"), str) else None
    arrangements = manifest.get("arrangements")
    arrangement_count = len(arrangements) if isinstance(arrangements, list) else 0

    if not title:
        issues.append("Missing manifest.title")
    if not artist:
        warnings.append("Missing manifest.artist")
    if not feedpak_version:
        warnings.append("Missing manifest.feedpak_version")
    if not isinstance(arrangements, list):
        issues.append("Manifest arrangements must be a list")
    elif not arrangements:
        issues.append("Manifest arrangements list is empty")

    return ValidationReport(str(p.resolve()), not issues, manifest_path, issues, warnings, arrangement_count, feedpak_version, title, artist)


def extract_psarc(input_path: str | Path, work_root: str | Path | None = None) -> ExtractionReport:
    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(src)
    workdir = Path(work_root) if work_root else _default_work_root(src)
    raw_dir = workdir / "raw"
    if raw_dir.exists():
        shutil.rmtree(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    extracted = unpack_psarc(src, raw_dir)
    return ExtractionReport(
        input_path=str(src.resolve()),
        raw_dir=str(raw_dir.resolve()),
        extracted_files=len(extracted),
        entries_preview=[str(Path(p).relative_to(raw_dir)) for p in extracted[:20]],
    )


def _require_tool(name: str) -> str:
    bundled = None
    if name == "ffmpeg":
        bundled = "tools/ffmpeg/ffmpeg"
    elif name == "vgmstream-cli":
        bundled = "tools/vgmstream/vgmstream-cli"
    path = find_command(name, bundled)
    if not path:
        raise RuntimeError(f"Required tool not found on PATH: {name}")
    return path


def _find_wem_files(extracted_dir: Path) -> list[Path]:
    return sorted(extracted_dir.rglob("*.wem"), key=lambda p: p.stat().st_size, reverse=True)


def _wem_to_ogg(wem_path: Path, out_ogg: Path) -> None:
    vgmstream = _require_tool("vgmstream-cli")
    ffmpeg = _require_tool("ffmpeg")
    with tempfile.TemporaryDirectory(prefix="psarc_converter_audio_") as td:
        wav = Path(td) / "full.wav"
        r = subprocess.run([vgmstream, "-o", str(wav), str(wem_path)], capture_output=True, text=True)
        if r.returncode != 0 or not wav.exists() or wav.stat().st_size < 100:
            raise RuntimeError(f"vgmstream-cli failed: {r.stderr.strip()}")
        out_ogg.parent.mkdir(parents=True, exist_ok=True)
        r2 = subprocess.run([
            ffmpeg, "-y", "-i", str(wav), "-c:a", "libvorbis", "-q:a", "5", str(out_ogg)
        ], capture_output=True, text=True)
        if r2.returncode != 0 or not out_ogg.exists() or out_ogg.stat().st_size < 100:
            fallback = subprocess.run([
                ffmpeg, "-y", "-i", str(wav), "-c:a", "vorbis", "-strict", "-2", "-q:a", "5", str(out_ogg)
            ], capture_output=True, text=True)
            if fallback.returncode != 0 or not out_ogg.exists() or out_ogg.stat().st_size < 100:
                raise RuntimeError(f"ffmpeg OGG encode failed: {(fallback.stderr or r2.stderr).strip()}")


def _extract_cover(extracted_dir: Path, out_jpg: Path) -> bool:
    dds_files = sorted(extracted_dir.rglob("*.dds"), key=lambda p: p.stat().st_size, reverse=True)
    if not dds_files:
        return False
    try:
        img = Image.open(dds_files[0]).convert("RGB")
        out_jpg.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out_jpg), "JPEG", quality=88)
        return True
    except Exception:
        return False


def _write_normalized_song(extracted_dir: Path, normalized_dir: Path) -> ConversionReport:
    song = load_song(extracted_dir)
    if not song.arrangements:
        raise RuntimeError("no playable arrangements found in PSARC")

    if normalized_dir.exists():
        shutil.rmtree(normalized_dir)
    normalized_dir.mkdir(parents=True, exist_ok=True)

    used_ids: set[str] = set()
    arr_manifest: list[dict] = []
    arrangement_names: list[str] = []
    first = True
    for arr in song.arrangements:
        base = "".join(ch.lower() if ch.isalnum() else "_" for ch in arr.name).strip("_") or "arr"
        aid = base
        n = 2
        while aid in used_ids:
            aid = f"{base}{n}"
            n += 1
        used_ids.add(aid)
        arrangement_names.append(arr.name)
        wire = arrangement_to_wire(arr)
        if first:
            wire["beats"] = [{"time": round(b.time, 3), "measure": b.measure} for b in song.beats]
            wire["sections"] = [{"name": s.name, "number": s.number, "time": round(s.start_time, 3)} for s in song.sections]
            first = False
        arr_file = normalized_dir / "arrangements" / f"{aid}.json"
        arr_file.parent.mkdir(parents=True, exist_ok=True)
        arr_file.write_text(json.dumps(wire, separators=(",", ":")), encoding="utf-8")
        arr_manifest.append({"id": aid, "name": arr.name, "file": f"arrangements/{aid}.json", "tuning": list(arr.tuning), "capo": arr.capo})

    wems = _find_wem_files(extracted_dir)
    if not wems:
        raise RuntimeError("no WEM audio found in PSARC")
    stem_out = normalized_dir / "stems" / "full.ogg"
    _wem_to_ogg(wems[0], stem_out)
    stem_files = ["stems/full.ogg"]

    lyrics = parse_lyrics(extracted_dir)
    used_lyrics = False
    if lyrics:
        (normalized_dir / "lyrics.json").write_text(json.dumps(lyrics, separators=(",", ":")), encoding="utf-8")
        used_lyrics = True

    used_cover = _extract_cover(extracted_dir, normalized_dir / "cover.jpg")

    manifest: dict = {
        "feedpak_version": "1.2.0",
        "title": song.title or extracted_dir.stem,
        "artist": song.artist or "",
        "album": song.album or "",
        "year": int(song.year or 0),
        "duration": round(float(song.song_length or 0.0), 3),
        "stems": [{"id": "full", "file": "stems/full.ogg", "default": "on"}],
        "arrangements": arr_manifest,
    }
    if used_cover:
        manifest["cover"] = "cover.jpg"
    if used_lyrics:
        manifest["lyrics"] = "lyrics.json"

    manifest_path = normalized_dir / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return ConversionReport(
        input_path=str(extracted_dir),
        output_path="",
        title=manifest["title"],
        artist=manifest["artist"],
        arrangement_count=len(arr_manifest),
        arrangement_names=arrangement_names,
        stem_files=stem_files,
        work_root=str(normalized_dir.parent.parent.resolve()),
        manifest_path=str(manifest_path.resolve()),
        used_cover=used_cover,
        used_lyrics=used_lyrics,
    )


def convert_psarc_to_feedpak(input_path: str | Path, output_path: str | Path, work_root: str | Path | None = None) -> ConversionReport:
    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(src)
    workdir = Path(work_root) if work_root else _default_work_root(src)
    raw_dir = workdir / "raw"
    normalized_dir = workdir / "normalized" / "song"
    build_dir = workdir / "build"
    build_dir.mkdir(parents=True, exist_ok=True)

    if raw_dir.exists():
        shutil.rmtree(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    unpack_psarc(src, raw_dir)
    report = _write_normalized_song(raw_dir, normalized_dir)

    out = Path(output_path)
    if out.suffix.lower() not in {".feedpak", ".sloppak"}:
        out = out.with_suffix(".feedpak")
    package_loose_song(normalized_dir, out)
    report.output_path = str(out.resolve())
    report.input_path = str(src.resolve())
    return report
