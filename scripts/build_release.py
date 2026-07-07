from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = ROOT / "release" / "dist"
BUILD_ROOT = ROOT / "release" / "build"
RUNTIME_ROOT = BUILD_ROOT / "runtime"


def _platform_tag() -> str:
    machine = platform.machine().lower()
    aliases = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}
    return f"{platform.system().lower()}-{aliases.get(machine, machine)}"


def _data_sep() -> str:
    return ";" if os.name == "nt" else ":"


def _pyinstaller() -> list[str]:
    return [sys.executable, "-m", "PyInstaller"]


def _rmtree_safe(path: Path) -> None:
    def onerror(func, value, _exc_info):
        try:
            os.chmod(value, stat.S_IRWXU)
        except Exception:
            pass
        func(value)

    shutil.rmtree(path, onerror=onerror)


def _prepare_runtime_tools() -> Path:
    out_dir = RUNTIME_ROOT / _platform_tag()
    if out_dir.exists():
        _rmtree_safe(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        sys.executable,
        "scripts/prepare_runtime_tools.py",
        "--output-dir",
        str(out_dir),
    ], cwd=ROOT, check=True)
    return out_dir


def _tool_add_data_args(runtime_dir: Path) -> list[str]:
    args: list[str] = []
    for tool_name in ["rscli", "ffmpeg", "vgmstream"]:
        tool_dir = runtime_dir / "tools" / tool_name
        if tool_dir.exists():
            args.extend(["--add-data", f"{tool_dir}{_data_sep()}tools/{tool_name}"])
    return args


def _common_args(name: str, dist_dir: Path, console: bool, runtime_dir: Path) -> list[str]:
    args = [
        *_pyinstaller(),
        "--noconfirm",
        "--clean",
        "--name",
        name,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(BUILD_ROOT / name),
        "--specpath",
        str(BUILD_ROOT / "specs"),
        *(_tool_add_data_args(runtime_dir)),
    ]
    if not console:
        args.append("--windowed")
    return args


def build_cli(dist_dir: Path, runtime_dir: Path) -> Path:
    name = "charts-converter-cli"
    cmd = _common_args(name, dist_dir, console=True, runtime_dir=runtime_dir) + ["scripts/pyinstaller_cli_entry.py"]
    subprocess.run(cmd, cwd=ROOT, check=True)
    return dist_dir / name


def build_gui(dist_dir: Path, runtime_dir: Path) -> Path:
    name = "charts-converter"
    cmd = _common_args(name, dist_dir, console=False, runtime_dir=runtime_dir) + ["scripts/pyinstaller_gui_entry.py"]
    subprocess.run(cmd, cwd=ROOT, check=True)
    if sys.platform == "darwin":
        return dist_dir / f"{name}.app"
    return dist_dir / name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build charts-converter desktop/CLI executables with PyInstaller")
    parser.add_argument("--cli-only", action="store_true", help="Build only the CLI executable")
    parser.add_argument("--gui-only", action="store_true", help="Build only the GUI executable")
    parser.add_argument("--output-dir", default=None, help="Override release output directory")
    args = parser.parse_args(argv)

    if args.cli_only and args.gui_only:
        parser.error("Choose only one of --cli-only or --gui-only")

    dist_dir = Path(args.output_dir) if args.output_dir else DIST_ROOT / _platform_tag()
    if dist_dir.exists():
        _rmtree_safe(dist_dir)
    dist_dir.mkdir(parents=True, exist_ok=True)
    (BUILD_ROOT / "specs").mkdir(parents=True, exist_ok=True)

    runtime_dir = _prepare_runtime_tools()

    built: list[Path] = []
    if not args.gui_only:
        built.append(build_cli(dist_dir, runtime_dir))
    if not args.cli_only:
        built.append(build_gui(dist_dir, runtime_dir))

    print("Built artifacts:")
    for path in built:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
