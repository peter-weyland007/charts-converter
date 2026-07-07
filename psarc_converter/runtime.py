from __future__ import annotations

import os
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


def find_command(name: str, bundled_relpath: str | None = None) -> str | None:
    env_name = f"{name.upper().replace('-', '_')}_PATH"
    env_value = os.environ.get(env_name, "").strip()
    if env_value and Path(env_value).exists():
        return env_value
    if bundled_relpath:
        candidate = bundled_path(*bundled_relpath.split("/"))
        if candidate.exists():
            return str(candidate)
    return shutil.which(name)
