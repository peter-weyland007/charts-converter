from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import yaml
from PIL import Image

from .clonehero import clone_hero_to_loose_chart_folder, is_clone_hero_folder, iter_clone_hero_folders
from .psarc import list_entries, unpack_psarc
from .runtime import default_user_cache_dir, find_command
from .song_xml import arrangement_to_wire, load_song, parse_lyrics


@dataclass(frozen=True)
class ToolProbe:
    name: str
    command: str
    found: bool


@dataclass(frozen=True)
class InputInspection:
    path: str
    exists: bool
    is_dir: bool
    size_bytes: int
    sha256: str
    magic_hex: str
    suffix: str
    format_id: str
    format_label: str
    looks_like_supported_input: bool
    entry_count: int
    entries_preview: list[str]
    extractor_candidates: list[ToolProbe]


@dataclass(frozen=True)
class ExtractionReport:
    input_path: str
    raw_dir: str
    extracted_files: int
    entries_preview: list[str]


@dataclass(frozen=True)
class ValidationReport:
    path: str
    ok: bool
    manifest_path: str | None
    issues: list[str]
    warnings: list[str]
    arrangement_count: int
    package_version: str | None
    title: str | None
    artist: str | None


@dataclass(frozen=True)
class ConversionReport:
    input_path: str
    output_path: str
    input_format: str
    output_format: str
    title: str
    artist: str
    arrangement_count: int
    arrangement_names: list[str]
    stem_files: list[str]
    work_root: str
    manifest_path: str
    used_cover: bool
    used_lyrics: bool


@dataclass(frozen=True)
class BatchItemResult:
    input_path: str
    output_path: str | None
    ok: bool
    error: str | None
    report: ConversionReport | None


@dataclass(frozen=True)
class BatchConversionReport:
    input_root: str
    output_root: str
    input_format: str
    output_format: str
    discovered_inputs: int
    converted_count: int
    failed_count: int
    items: list[BatchItemResult]


INPUT_FORMAT_PSARC = "psarc"
INPUT_FORMAT_LOOSE = "loose-chart-folder"
INPUT_FORMAT_CLONE_HERO = "clone-hero-folder"
OUTPUT_FORMAT_FEEDPAK = "feedpak-package"
OUTPUT_FORMAT_FOLDER = "loose-chart-folder"

INPUT_FORMAT_LABELS = {
    INPUT_FORMAT_PSARC: "PSARC archive",
    INPUT_FORMAT_LOOSE: "Loose chart folder",
    INPUT_FORMAT_CLONE_HERO: "Clone Hero song folder",
}

OUTPUT_FORMAT_LABELS = {
    OUTPUT_FORMAT_FEEDPAK: "Feedpak package",
    OUTPUT_FORMAT_FOLDER: "Loose chart folder",
}

OUTPUT_EXTENSIONS = {
    OUTPUT_FORMAT_FEEDPAK: ".feedpak",
    OUTPUT_FORMAT_FOLDER: "",
}


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


def detect_input_format(path: str | Path) -> str:
    p = Path(path)
    if p.is_dir():
        if is_clone_hero_folder(p):
            return INPUT_FORMAT_CLONE_HERO
        return INPUT_FORMAT_LOOSE
    if p.suffix.lower() == ".psarc":
        return INPUT_FORMAT_PSARC
    try:
        with p.open("rb") as fh:
            magic = fh.read(4)
        if magic == b"PSAR":
            return INPUT_FORMAT_PSARC
    except Exception:
        pass
    return INPUT_FORMAT_PSARC


def inspect_input_file(path: str | Path) -> InputInspection:
    p = Path(path)
    exists = p.exists()
    is_dir = p.is_dir() if exists else False
    size = p.stat().st_size if exists and p.is_file() else 0
    sha = _sha256_file(p) if exists and p.is_file() else ""
    magic = ""
    entries: list[str] = []
    format_id = detect_input_format(p) if exists else INPUT_FORMAT_PSARC

    if exists and p.is_file():
        with p.open("rb") as fh:
            magic = fh.read(16).hex()
        if format_id == INPUT_FORMAT_PSARC:
            try:
                entries = list_entries(p)
            except Exception:
                entries = []
    elif exists and p.is_dir():
        entries = [child.relative_to(p).as_posix() for child in sorted(p.rglob("*"))[:20]]

    looks_supported = format_id in INPUT_FORMAT_LABELS and exists
    return InputInspection(
        path=str(p.resolve()) if exists else str(p),
        exists=exists,
        is_dir=is_dir,
        size_bytes=size,
        sha256=sha,
        magic_hex=magic,
        suffix=p.suffix.lower(),
        format_id=format_id,
        format_label=INPUT_FORMAT_LABELS.get(format_id, format_id),
        looks_like_supported_input=looks_supported,
        entry_count=len(entries),
        entries_preview=entries[:20],
        extractor_candidates=_probe_extractors(),
    )


def _default_work_root(input_path: Path) -> Path:
    return default_user_cache_dir("charts-converter") / input_path.stem.replace(" ", "_")


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
        raise FileNotFoundError(f"Loose chart directory not found: {src}")
    _find_manifest_in_dir(src)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for child in sorted(src.rglob("*")):
            if child.is_file():
                zf.write(child, child.relative_to(src).as_posix())
    return out


def copy_loose_chart_folder(loose_dir: str | Path, output_dir: str | Path) -> Path:
    src = Path(loose_dir)
    if not src.is_dir():
        raise FileNotFoundError(f"Loose chart directory not found: {src}")
    _find_manifest_in_dir(src)
    out = Path(output_dir)
    if out.exists():
        if out.is_file():
            raise RuntimeError(f"Output path is a file, expected directory: {out}")
        shutil.rmtree(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, out)
    return out


def validate_chart_package(path: str | Path) -> ValidationReport:
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
    package_version = manifest.get("feedpak_version") if isinstance(manifest.get("feedpak_version"), str) else None
    arrangements = manifest.get("arrangements")
    arrangement_count = len(arrangements) if isinstance(arrangements, list) else 0

    if not title:
        issues.append("Missing manifest.title")
    if not artist:
        warnings.append("Missing manifest.artist")
    if not package_version:
        warnings.append("Missing manifest.feedpak_version")
    if not isinstance(arrangements, list):
        issues.append("Manifest arrangements must be a list")
    elif not arrangements:
        issues.append("Manifest arrangements list is empty")

    return ValidationReport(str(p.resolve()), not issues, manifest_path, issues, warnings, arrangement_count, package_version, title, artist)


def extract_input_archive(input_path: str | Path, work_root: str | Path | None = None) -> ExtractionReport:
    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(src)
    if detect_input_format(src) != INPUT_FORMAT_PSARC:
        raise RuntimeError("Raw extraction is currently implemented only for PSARC input.")
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
    bundled_subdir = None
    bundled_name = None
    if name == "ffmpeg":
        bundled_subdir = "tools/ffmpeg"
        bundled_name = "ffmpeg"
    elif name == "vgmstream-cli":
        bundled_subdir = "tools/vgmstream"
        bundled_name = "vgmstream-cli"
    path = find_command(name, bundled_subdir=bundled_subdir, bundled_name=bundled_name)
    if not path:
        raise RuntimeError(f"Required tool not found on PATH: {name}")
    return path


def _find_wem_files(extracted_dir: Path) -> list[Path]:
    return sorted(extracted_dir.rglob("*.wem"), key=lambda p: p.stat().st_size, reverse=True)


def _wem_to_ogg(wem_path: Path, out_ogg: Path) -> None:
    vgmstream = _require_tool("vgmstream-cli")
    ffmpeg = _require_tool("ffmpeg")
    with tempfile.TemporaryDirectory(prefix="charts_converter_audio_") as td:
        wav = Path(td) / "full.wav"
        r = subprocess.run([vgmstream, "-o", str(wav), str(wem_path)], capture_output=True, text=True)
        if r.returncode != 0 or not wav.exists() or wav.stat().st_size < 100:
            raise RuntimeError(f"vgmstream-cli failed: {r.stderr.strip()}")
        out_ogg.parent.mkdir(parents=True, exist_ok=True)
        r2 = subprocess.run(
            [ffmpeg, "-y", "-i", str(wav), "-c:a", "libvorbis", "-q:a", "5", str(out_ogg)],
            capture_output=True,
            text=True,
        )
        if r2.returncode != 0 or not out_ogg.exists() or out_ogg.stat().st_size < 100:
            fallback = subprocess.run(
                [ffmpeg, "-y", "-i", str(wav), "-c:a", "vorbis", "-strict", "-2", "-q:a", "5", str(out_ogg)],
                capture_output=True,
                text=True,
            )
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


def _build_loose_chart_folder(extracted_dir: Path, normalized_dir: Path, input_format: str) -> ConversionReport:
    song = load_song(extracted_dir)
    if not song.arrangements:
        if input_format == INPUT_FORMAT_PSARC:
            raise RuntimeError("no playable arrangements found in PSARC")
        raise RuntimeError("no playable arrangements found in input source")

    if normalized_dir.exists():
        shutil.rmtree(normalized_dir)
    normalized_dir.mkdir(parents=True, exist_ok=True)

    used_ids: set[str] = set()
    arrangement_manifest: list[dict] = []
    arrangement_names: list[str] = []
    include_global_sections = True
    for arr in song.arrangements:
        base = "".join(ch.lower() if ch.isalnum() else "_" for ch in arr.name).strip("_") or "arr"
        arrangement_id = base
        n = 2
        while arrangement_id in used_ids:
            arrangement_id = f"{base}{n}"
            n += 1
        used_ids.add(arrangement_id)
        arrangement_names.append(arr.name)
        wire = arrangement_to_wire(arr)
        if include_global_sections:
            wire["beats"] = [{"time": round(b.time, 3), "measure": b.measure} for b in song.beats]
            wire["sections"] = [{"name": s.name, "number": s.number, "time": round(s.start_time, 3)} for s in song.sections]
            include_global_sections = False
        arrangement_file = normalized_dir / "arrangements" / f"{arrangement_id}.json"
        arrangement_file.parent.mkdir(parents=True, exist_ok=True)
        arrangement_file.write_text(json.dumps(wire, separators=(",", ":")), encoding="utf-8")
        arrangement_manifest.append(
            {
                "id": arrangement_id,
                "name": arr.name,
                "file": f"arrangements/{arrangement_id}.json",
                "tuning": list(arr.tuning),
                "capo": arr.capo,
            }
        )

    wems = _find_wem_files(extracted_dir)
    if not wems:
        if input_format == INPUT_FORMAT_PSARC:
            raise RuntimeError("no WEM audio found in PSARC")
        raise RuntimeError("no WEM audio found in input source")
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
        "arrangements": arrangement_manifest,
        "generated_at": datetime_to_iso8601(),
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
        input_format=input_format,
        output_format=OUTPUT_FORMAT_FOLDER,
        title=manifest["title"],
        artist=manifest["artist"],
        arrangement_count=len(arrangement_manifest),
        arrangement_names=arrangement_names,
        stem_files=stem_files,
        work_root=str(normalized_dir.parent.parent.resolve()),
        manifest_path=str(manifest_path.resolve()),
        used_cover=used_cover,
        used_lyrics=used_lyrics,
    )


def datetime_to_iso8601() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_output_path(output_path: str | Path, output_format: str) -> Path:
    out = Path(output_path)
    if output_format == OUTPUT_FORMAT_FEEDPAK:
        out = out.with_suffix(OUTPUT_EXTENSIONS[OUTPUT_FORMAT_FEEDPAK])
        return out
    return out


def _stage_input_as_loose_chart_folder(input_path: Path, workdir: Path, input_format: str) -> ConversionReport:
    normalized_dir = workdir / "normalized" / "song"
    if input_format == INPUT_FORMAT_LOOSE:
        return _summarize_existing_loose_chart_folder(input_path, normalized_dir)
    if input_format == INPUT_FORMAT_CLONE_HERO:
        clone_hero_to_loose_chart_folder(input_path, normalized_dir)
        return _summarize_existing_loose_chart_folder(normalized_dir, normalized_dir)

    raw_dir = workdir / "raw"
    build_dir = workdir / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    if raw_dir.exists():
        shutil.rmtree(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    unpack_psarc(input_path, raw_dir)
    return _build_loose_chart_folder(raw_dir, normalized_dir, input_format=input_format)


def _summarize_existing_loose_chart_folder(input_dir: Path, normalized_dir: Path) -> ConversionReport:
    manifest, manifest_path = _read_manifest_from_dir(input_dir)
    arrangements_raw = manifest.get("arrangements")
    arrangements: list[dict] = [item for item in arrangements_raw if isinstance(item, dict)] if isinstance(arrangements_raw, list) else []
    arrangement_names = [str(item.get("name", "")) for item in arrangements]
    stems_raw = manifest.get("stems")
    stem_files = [str(item.get("file", "")) for item in stems_raw if isinstance(item, dict)] if isinstance(stems_raw, list) else []
    return ConversionReport(
        input_path=str(input_dir.resolve()),
        output_path="",
        input_format=INPUT_FORMAT_LOOSE,
        output_format=OUTPUT_FORMAT_FOLDER,
        title=str(manifest.get("title") or input_dir.name),
        artist=str(manifest.get("artist") or ""),
        arrangement_count=len(arrangements),
        arrangement_names=arrangement_names,
        stem_files=stem_files,
        work_root=str(normalized_dir.parent.parent.resolve()),
        manifest_path=manifest_path,
        used_cover=(input_dir / "cover.jpg").exists(),
        used_lyrics=(input_dir / "lyrics.json").exists(),
    )


def convert_chart_source(
    input_path: str | Path,
    output_path: str | Path,
    *,
    input_format: str | None = None,
    output_format: str = OUTPUT_FORMAT_FEEDPAK,
    work_root: str | Path | None = None,
) -> ConversionReport:
    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(src)

    detected_input_format = input_format or detect_input_format(src)
    if detected_input_format not in INPUT_FORMAT_LABELS:
        raise RuntimeError(f"Unsupported input format: {detected_input_format}")
    if output_format not in OUTPUT_FORMAT_LABELS:
        raise RuntimeError(f"Unsupported output format: {output_format}")

    workdir = Path(work_root) if work_root else _default_work_root(src)
    staged = _stage_input_as_loose_chart_folder(src, workdir, detected_input_format)

    out = _normalize_output_path(output_path, output_format)
    if output_format == OUTPUT_FORMAT_FEEDPAK:
        package_loose_song(Path(staged.manifest_path).parent, out)
    elif output_format == OUTPUT_FORMAT_FOLDER:
        copy_loose_chart_folder(Path(staged.manifest_path).parent, out)
    else:
        raise RuntimeError(f"Unsupported output format: {output_format}")

    return ConversionReport(
        input_path=str(src.resolve()),
        output_path=str(out.resolve()),
        input_format=detected_input_format,
        output_format=output_format,
        title=staged.title,
        artist=staged.artist,
        arrangement_count=staged.arrangement_count,
        arrangement_names=staged.arrangement_names,
        stem_files=staged.stem_files,
        work_root=staged.work_root,
        manifest_path=staged.manifest_path,
        used_cover=staged.used_cover,
        used_lyrics=staged.used_lyrics,
    )


def discover_batch_inputs(input_root: str | Path, input_format: str) -> list[Path]:
    root = Path(input_root)
    if not root.is_dir():
        raise NotADirectoryError(root)
    if input_format == INPUT_FORMAT_PSARC:
        return sorted(p for p in root.rglob("*.psarc") if p.is_file())
    if input_format == INPUT_FORMAT_CLONE_HERO:
        return iter_clone_hero_folders(root)
    if input_format == INPUT_FORMAT_LOOSE:
        hits: list[Path] = []
        for manifest in sorted(root.rglob("manifest.y*ml")):
            parent = manifest.parent
            if parent.is_dir() and parent not in hits:
                hits.append(parent)
        return hits
    raise RuntimeError(f"Unsupported input format for batch discovery: {input_format}")


def _sanitize_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value.strip())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    cleaned = cleaned.strip("-_")
    return cleaned or "converted"


def _batch_output_path(output_root: Path, source_path: Path, output_format: str) -> Path:
    base_name = _sanitize_name(source_path.stem if source_path.is_file() else source_path.name)
    if output_format == OUTPUT_FORMAT_FEEDPAK:
        return output_root / f"{base_name}{OUTPUT_EXTENSIONS[OUTPUT_FORMAT_FEEDPAK]}"
    if output_format == OUTPUT_FORMAT_FOLDER:
        return output_root / base_name
    raise RuntimeError(f"Unsupported output format: {output_format}")


def batch_convert_chart_sources(
    input_root: str | Path,
    output_root: str | Path,
    *,
    input_format: str,
    output_format: str,
    work_root: str | Path | None = None,
) -> BatchConversionReport:
    root = Path(input_root)
    out_root = Path(output_root)
    if not root.is_dir():
        raise NotADirectoryError(root)
    if output_format not in OUTPUT_FORMAT_LABELS:
        raise RuntimeError(f"Unsupported output format: {output_format}")

    discovered = discover_batch_inputs(root, input_format)
    out_root.mkdir(parents=True, exist_ok=True)
    items: list[BatchItemResult] = []

    for source in discovered:
        target = _batch_output_path(out_root, source, output_format)
        item_work_root = (Path(work_root) / _sanitize_name(source.stem if source.is_file() else source.name)) if work_root else None
        try:
            report = convert_chart_source(
                source,
                target,
                input_format=input_format,
                output_format=output_format,
                work_root=item_work_root,
            )
            items.append(
                BatchItemResult(
                    input_path=str(source.resolve()),
                    output_path=report.output_path,
                    ok=True,
                    error=None,
                    report=report,
                )
            )
        except Exception as exc:
            items.append(
                BatchItemResult(
                    input_path=str(source.resolve()),
                    output_path=str(target.resolve()),
                    ok=False,
                    error=str(exc),
                    report=None,
                )
            )

    converted_count = sum(1 for item in items if item.ok)
    failed_count = len(items) - converted_count
    return BatchConversionReport(
        input_root=str(root.resolve()),
        output_root=str(out_root.resolve()),
        input_format=input_format,
        output_format=output_format,
        discovered_inputs=len(discovered),
        converted_count=converted_count,
        failed_count=failed_count,
        items=items,
    )


# Backward-compatible wrappers while the tool grows beyond the original path.
def convert_input_to_chart_package(input_path: str | Path, output_path: str | Path, work_root: str | Path | None = None) -> ConversionReport:
    return convert_chart_source(input_path, output_path, output_format=OUTPUT_FORMAT_FEEDPAK, work_root=work_root)


# Older exported names kept for compatibility.
PsarcInspection = InputInspection
extract_psarc = extract_input_archive
convert_psarc_to_feedpak = convert_input_to_chart_package
validate_feedpak = validate_chart_package
