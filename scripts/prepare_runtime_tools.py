from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THIRD_PARTY_RSCLI = ROOT / "third_party" / "rscli-source"
ROCKSMITH_REPO = "https://github.com/iminashi/Rocksmith2014.NET.git"
VGMSTREAM_VERSION = "r2117"
CH2FEEDPAK_REPO = "https://github.com/zaibach333/ch2feedpak.git"


def platform_tag() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    aliases = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "aarch64": "arm64",
    }
    return f"{system}-{aliases.get(machine, machine)}"


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    mode = dst.stat().st_mode
    dst.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as response, open(dest, "wb") as f:
        shutil.copyfileobj(response, f)


def prepare_ffmpeg(out_root: Path) -> Path:
    import imageio_ffmpeg

    ffmpeg_src = Path(imageio_ffmpeg.get_ffmpeg_exe())
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    dest = out_root / "tools" / "ffmpeg" / exe_name
    _copy_file(ffmpeg_src, dest)
    return dest


def _vgmstream_asset_name() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "vgmstream-mac.zip"
    if system == "linux":
        return "vgmstream-linux.zip"
    if system == "windows":
        return "vgmstream-win64.zip"
    raise RuntimeError(f"Unsupported platform for vgmstream: {system}")


def prepare_vgmstream(out_root: Path) -> Path:
    asset = _vgmstream_asset_name()
    url = f"https://github.com/vgmstream/vgmstream/releases/download/{VGMSTREAM_VERSION}/{asset}"
    with tempfile.TemporaryDirectory(prefix="psarc_vgmstream_") as td:
        archive = Path(td) / asset
        _download(url, archive)
        extract_dir = Path(td) / "extract"
        extract_dir.mkdir()
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(extract_dir)
        dest_dir = out_root / "tools" / "vgmstream"
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        shutil.copytree(extract_dir, dest_dir)
        exe_name = "vgmstream-cli.exe" if os.name == "nt" else "vgmstream-cli"
        exe = dest_dir / exe_name
        if exe.exists():
            exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return exe


def _dotnet_runtime_id() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        return "osx-arm64" if machine in {"arm64", "aarch64"} else "osx-x64"
    if system == "linux":
        return "linux-arm64" if machine in {"arm64", "aarch64"} else "linux-x64"
    if system == "windows":
        return "win-arm64" if machine in {"arm64", "aarch64"} else "win-x64"
    raise RuntimeError(f"Unsupported platform for RsCli build: {system}/{machine}")


def prepare_rscli(out_root: Path) -> Path:
    if not shutil.which("git"):
        raise RuntimeError("git is required to build bundled RsCli")
    if not shutil.which("dotnet"):
        raise RuntimeError("dotnet is required to build bundled RsCli")

    with tempfile.TemporaryDirectory(prefix="psarc_rscli_") as td:
        td_path = Path(td)
        repo_dir = td_path / "Rocksmith2014.NET"
        subprocess.run(["git", "clone", "--depth", "1", ROCKSMITH_REPO, str(repo_dir)], check=True)
        tool_dir = repo_dir / "tools" / "RsCli"
        tool_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(THIRD_PARTY_RSCLI / "Program.fs", tool_dir / "Program.fs")
        shutil.copy2(THIRD_PARTY_RSCLI / "RsCli.fsproj", tool_dir / "RsCli.fsproj")

        publish_dir = td_path / "publish"
        subprocess.run([
            "dotnet", "publish", str(tool_dir / "RsCli.fsproj"),
            "-c", "Release",
            "-r", _dotnet_runtime_id(),
            "--self-contained", "true",
            "-o", str(publish_dir),
        ], check=True)

        dest_dir = out_root / "tools" / "rscli"
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        shutil.copytree(publish_dir, dest_dir)
        exe_name = "RsCli.exe" if os.name == "nt" else "RsCli"
        exe = dest_dir / exe_name
        if exe.exists():
            exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return exe


def prepare_ch2feedpak(out_root: Path) -> Path:
    if not shutil.which("git"):
        raise RuntimeError("git is required to bundle ch2feedpak")
    with tempfile.TemporaryDirectory(prefix="charts_converter_ch2feedpak_") as td:
        repo_dir = Path(td) / "ch2feedpak"
        subprocess.run(["git", "clone", "--depth", "1", CH2FEEDPAK_REPO, str(repo_dir)], check=True)
        src_dir = repo_dir / "ch2feedpak"
        if not (src_dir / "ch2feedpak.py").exists():
            raise RuntimeError(f"ch2feedpak helper layout unexpected: {src_dir}")
        dest_dir = out_root / "tools" / "ch2feedpak"
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        shutil.copytree(src_dir, dest_dir)
        return dest_dir / "ch2feedpak.py"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare bundled runtime tools for the current platform")
    parser.add_argument("--output-dir", required=True, help="Directory where tools/ will be staged")
    args = parser.parse_args(argv)

    out_root = Path(args.output_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    ffmpeg = prepare_ffmpeg(out_root)
    vgmstream = prepare_vgmstream(out_root)
    rscli = prepare_rscli(out_root)
    ch2feedpak = prepare_ch2feedpak(out_root)

    print("Prepared runtime tools:")
    print(ffmpeg)
    print(vgmstream)
    print(rscli)
    print(ch2feedpak)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
