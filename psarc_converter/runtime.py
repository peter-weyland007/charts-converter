from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def bundled_path(*parts: str) -> Path:
    return app_root().joinpath(*parts)


def default_user_cache_dir(app_name: str) -> Path:
    system = platform.system().lower()
    home = Path.home()
    if system == "darwin":
        root = home / "Library" / "Caches"
    elif system == "windows":
        root = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME", home / ".cache"))
    return root / app_name


def executable_names(base_name: str) -> list[str]:
    names = [base_name]
    if os.name == "nt" and not base_name.lower().endswith(".exe"):
        names.insert(0, f"{base_name}.exe")
    return names


def find_bundled_executable(*dir_parts: str, base_name: str) -> str | None:
    tool_dir = bundled_path(*dir_parts)
    for name in executable_names(base_name):
        candidate = tool_dir / name
        if candidate.exists():
            return str(candidate)
    return None


def find_command(name: str, bundled_subdir: str | None = None, bundled_name: str | None = None) -> str | None:
    env_name = f"{name.upper().replace('-', '_')}_PATH"
    env_value = os.environ.get(env_name, "").strip()
    if env_value and Path(env_value).exists():
        return env_value
    if bundled_subdir and bundled_name:
        found = find_bundled_executable(*bundled_subdir.split("/"), base_name=bundled_name)
        if found:
            return found
    return shutil.which(name)
