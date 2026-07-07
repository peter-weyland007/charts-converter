from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml


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
    extractor_candidates: list[ToolProbe]


@dataclass
class ScaffoldPlan:
    input_path: str
    input_kind: str
    work_root: str
    output_path: str | None
    created_at: str
    status: str
    next_steps: list[str]
    extractor_candidates: list[ToolProbe]


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


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _probe_extractors() -> list[ToolProbe]:
    candidates = [
        ("psarc", "psarc"),
        ("psarcutil", "psarcutil"),
        ("psarc-extractor", "psarc-extractor"),
        ("rsrtools", "rsrtools"),
    ]
    return [
        ToolProbe(name=name, command=cmd, found=shutil.which(cmd) is not None)
        for name, cmd in candidates
    ]


def inspect_psarc(path: str | Path) -> PsarcInspection:
    p = Path(path)
    exists = p.exists()
    size = p.stat().st_size if exists else 0
    sha = _sha256_file(p) if exists and p.is_file() else ""
    magic = ""
    if exists and p.is_file():
        with p.open("rb") as fh:
            magic = fh.read(16).hex()
    looks_like_psarc = magic.startswith("50534152") or p.suffix.lower() == ".psarc"
    return PsarcInspection(
        path=str(p.resolve()) if exists else str(p),
        exists=exists,
        size_bytes=size,
        sha256=sha,
        magic_hex=magic,
        suffix=p.suffix.lower(),
        looks_like_psarc=looks_like_psarc,
        extractor_candidates=_probe_extractors(),
    )


def _default_work_root(input_path: Path) -> Path:
    safe_name = input_path.stem.replace(" ", "_")
    return Path(".cache") / "psarc-converter" / safe_name


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_scaffold_plan(
    input_path: str | Path,
    *,
    work_root: str | Path | None = None,
    output_path: str | Path | None = None,
    input_kind: str = "psarc",
    plan_name: str = "plan.json",
) -> tuple[ScaffoldPlan, Path]:
    src = Path(input_path)
    workdir = Path(work_root) if work_root else _default_work_root(src)
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "raw").mkdir(exist_ok=True)
    (workdir / "normalized").mkdir(exist_ok=True)
    (workdir / "build").mkdir(exist_ok=True)

    plan = ScaffoldPlan(
        input_path=str(src.resolve() if src.exists() else src),
        input_kind=input_kind,
        work_root=str(workdir.resolve()),
        output_path=str(Path(output_path).resolve()) if output_path else None,
        created_at=_utc_now(),
        status="scaffolded",
        next_steps=[
            "Run an external PSARC extractor into the raw/ folder.",
            "Normalize extracted XML/audio/metadata into normalized/song/.",
            "Package normalized/song/ into a .feedpak once the proprietary extraction step is wired up.",
        ],
        extractor_candidates=_probe_extractors(),
    )
    plan_path = workdir / plan_name
    plan_path.write_text(json.dumps(asdict(plan), indent=2) + "\n", encoding="utf-8")
    return plan, plan_path


def _find_manifest_in_dir(src: Path) -> Path:
    for name in ("manifest.yaml", "manifest.yml"):
        candidate = src / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"manifest.yaml not found in {src}")


def package_loose_song(loose_dir: str | Path, output_path: str | Path) -> Path:
    src = Path(loose_dir)
    if not src.is_dir():
        raise FileNotFoundError(f"Loose song directory not found: {src}")
    _find_manifest_in_dir(src)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for child in sorted(src.rglob("*")):
            if child.is_dir():
                continue
            zf.write(child, child.relative_to(src).as_posix())
    return out


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


def validate_feedpak(path: str | Path) -> ValidationReport:
    p = Path(path)
    issues: list[str] = []
    warnings: list[str] = []
    manifest_path: str | None = None
    title: str | None = None
    artist: str | None = None
    feedpak_version: str | None = None
    arrangement_count = 0

    if not p.exists():
        return ValidationReport(
            path=str(p),
            ok=False,
            manifest_path=None,
            issues=[f"Path does not exist: {p}"],
            warnings=[],
            arrangement_count=0,
            feedpak_version=None,
            title=None,
            artist=None,
        )

    try:
        manifest, manifest_path = _read_manifest_from_dir(p) if p.is_dir() else _read_manifest_from_zip(p)
    except Exception as exc:
        return ValidationReport(
            path=str(p.resolve()),
            ok=False,
            manifest_path=None,
            issues=[f"Failed to load manifest: {exc}"],
            warnings=[],
            arrangement_count=0,
            feedpak_version=None,
            title=None,
            artist=None,
        )

    title = manifest.get("title") if isinstance(manifest.get("title"), str) else None
    artist = manifest.get("artist") if isinstance(manifest.get("artist"), str) else None
    feedpak_version = manifest.get("feedpak_version") if isinstance(manifest.get("feedpak_version"), str) else None
    arrangements = manifest.get("arrangements")

    if not title:
        issues.append("Missing manifest.title")
    if not artist:
        warnings.append("Missing manifest.artist")
    if not feedpak_version:
        warnings.append("Missing manifest.feedpak_version")
    if not isinstance(arrangements, list):
        issues.append("Manifest arrangements must be a list")
    else:
        arrangement_count = len(arrangements)
        if arrangement_count == 0:
            issues.append("Manifest arrangements list is empty")

    return ValidationReport(
        path=str(p.resolve()),
        ok=not issues,
        manifest_path=manifest_path,
        issues=issues,
        warnings=warnings,
        arrangement_count=arrangement_count,
        feedpak_version=feedpak_version,
        title=title,
        artist=artist,
    )
