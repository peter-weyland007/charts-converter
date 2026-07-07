from __future__ import annotations

import json
import zipfile
from pathlib import Path

from psarc_converter.cli import main as cli_main
from psarc_converter.core import _default_work_root, inspect_psarc
from psarc_converter.gui import format_report, main as gui_main, suggest_output_path


def test_inspect_reports_real_psarc_shape() -> None:
    psarc_path = Path("/Users/itadmin/Desktop/psarc test/Paramore_Hallelujah_v1_DD_p.psarc")
    report = inspect_psarc(psarc_path)
    assert report.exists is True
    assert report.looks_like_psarc is True
    assert report.entry_count > 0


def test_validate_cli_accepts_generated_feedpak(capsys) -> None:
    feedpak_path = Path("/Users/itadmin/Desktop/psarc test/Paramore_Hallelujah.feedpak")
    code = cli_main(["validate", str(feedpak_path)])
    captured = capsys.readouterr().out
    data = json.loads(captured)
    assert code == 0
    assert data["ok"] is True
    assert data["title"] == "Hallelujah"


def test_generated_feedpak_contains_manifest_and_audio() -> None:
    feedpak_path = Path("/Users/itadmin/Desktop/psarc test/Paramore_Hallelujah.feedpak")
    with zipfile.ZipFile(feedpak_path, "r") as zf:
        names = set(zf.namelist())
    assert "manifest.yaml" in names
    assert "stems/full.ogg" in names


def test_suggest_output_path_uses_feedpak_suffix() -> None:
    assert suggest_output_path("/tmp/test-song.psarc") == "/tmp/test-song.feedpak"


def test_default_work_root_uses_user_cache_dir() -> None:
    path = _default_work_root(Path("/Volumes/Media/Games/rocksmith-dlc/Some Song.psarc"))
    assert "psarc-converter" in str(path)
    assert str(path).startswith(str(Path.home()))
    assert "/.cache/" in str(path) or "/Library/Caches/" in str(path) or "AppData" in str(path)


def test_format_report_is_pretty_json() -> None:
    report = inspect_psarc("/Users/itadmin/Desktop/psarc test/Paramore_Hallelujah_v1_DD_p.psarc")
    rendered = format_report(report)
    assert '"entry_count"' in rendered
    assert rendered.startswith("{")


def test_gui_smoke_test_returns_zero() -> None:
    code = gui_main(["--smoke-test"])
    assert code == 0
