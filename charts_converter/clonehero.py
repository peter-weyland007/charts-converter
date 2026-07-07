from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Iterator

from .runtime import bundled_path, find_command

CH2FEEDPAK_ENV = "CH2FEEDPAK_ROOT"


def is_clone_hero_folder(path: str | Path) -> bool:
    p = Path(path)
    if not p.is_dir():
        return False
    lower = {child.name.lower() for child in p.iterdir() if child.is_file()}
    return "notes.chart" in lower or "notes.mid" in lower


def iter_clone_hero_folders(root: str | Path) -> list[Path]:
    base = Path(root)
    if not base.is_dir():
        raise NotADirectoryError(base)
    hits: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(base):
        lower = {name.lower() for name in filenames}
        if "notes.chart" in lower or "notes.mid" in lower:
            hits.append(Path(dirpath))
            dirnames[:] = []
    return sorted(hits)


def helper_root() -> Path:
    env = os.environ.get(CH2FEEDPAK_ENV, "").strip()
    if env:
        candidate = Path(env).expanduser().resolve()
        if (candidate / "ch2feedpak.py").exists():
            return candidate
    bundled = bundled_path("tools", "ch2feedpak")
    if (bundled / "ch2feedpak.py").exists():
        return bundled
    raise RuntimeError(
        "Clone Hero conversion helper not found. Set CH2FEEDPAK_ROOT to a folder containing ch2feedpak.py, or use a packaged build that bundles the helper."
    )


@contextmanager
def _prep_helper_env() -> Iterator[None]:
    old_path = os.environ.get("PATH", "")
    ffmpeg = find_command("ffmpeg", bundled_subdir="tools/ffmpeg", bundled_name="ffmpeg")
    prepend: list[str] = []
    if ffmpeg:
        prepend.append(str(Path(ffmpeg).resolve().parent))
    if prepend:
        os.environ["PATH"] = os.pathsep.join(prepend + ([old_path] if old_path else []))
    try:
        yield
    finally:
        os.environ["PATH"] = old_path


def _load_helper_module() -> ModuleType:
    root = helper_root()
    script = root / "ch2feedpak.py"
    spec = importlib.util.spec_from_file_location("charts_converter_ch2feedpak", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load Clone Hero helper from {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("charts_converter_ch2feedpak", module)
    root_str = str(root)
    inserted = False
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
        inserted = True
    try:
        spec.loader.exec_module(module)
    finally:
        if inserted:
            try:
                sys.path.remove(root_str)
            except ValueError:
                pass
    return module


def convert_clone_hero_folder(song_dir: str | Path, output_path: str | Path, *, verbose: bool = False) -> Path:
    module = _load_helper_module()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with _prep_helper_env():
        written = module.convert(str(Path(song_dir).resolve()), output_path=str(out), verbose=verbose)
    if isinstance(written, list):
        if len(written) != 1:
            raise RuntimeError("Split-drums Clone Hero output is not supported by this wrapper")
        written = written[0]
    result = Path(written)
    if not result.exists():
        raise RuntimeError(f"Clone Hero helper reported success but output was not created: {result}")
    return result.resolve()


def clone_hero_to_loose_chart_folder(song_dir: str | Path, output_dir: str | Path) -> Path:
    out_dir = Path(output_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="charts_converter_ch_") as td:
        package_path = Path(td) / "song.feedpak"
        written = convert_clone_hero_folder(song_dir, package_path, verbose=False)
        import zipfile

        with zipfile.ZipFile(written, "r") as zf:
            zf.extractall(out_dir)
    return out_dir.resolve()
