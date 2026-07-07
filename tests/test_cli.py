from __future__ import annotations

import json
import zipfile
from pathlib import Path

from charts_converter.cli import build_parser, main as cli_main
from charts_converter.core import _default_work_root, inspect_input_file
from charts_converter.gui import (
    DEFAULT_INPUT_FORMAT,
    DEFAULT_OUTPUT_FORMAT,
    INPUT_FORMATS,
    OUTPUT_FORMATS,
    format_report,
    main as gui_main,
    selected_input_format,
    selected_output_extension,
    suggest_output_path,
)


def test_inspect_reports_real_archive_shape() -> None:
    input_path = Path("/Users/itadmin/Desktop/psarc test/Paramore_Hallelujah_v1_DD_p.psarc")
    report = inspect_input_file(input_path)
    assert report.exists is True
    assert report.looks_like_psarc is True
    assert report.entry_count > 0


def test_validate_cli_accepts_generated_feedback_package(capsys) -> None:
    package_path = Path("/Users/itadmin/Desktop/psarc test/Paramore_Hallelujah.feedpak")
    code = cli_main(["validate", str(package_path)])
    captured = capsys.readouterr().out
    data = json.loads(captured)
    assert code == 0
    assert data["ok"] is True
    assert data["title"] == "Hallelujah"


def test_generated_package_contains_manifest_and_audio() -> None:
    package_path = Path("/Users/itadmin/Desktop/psarc test/Paramore_Hallelujah.feedpak")
    with zipfile.ZipFile(package_path, "r") as zf:
        names = set(zf.namelist())
    assert "manifest.yaml" in names
    assert "stems/full.ogg" in names


def test_input_and_output_format_defaults_are_configured() -> None:
    assert selected_input_format(DEFAULT_INPUT_FORMAT) == INPUT_FORMATS[DEFAULT_INPUT_FORMAT]
    assert selected_output_extension(DEFAULT_OUTPUT_FORMAT) == OUTPUT_FORMATS[DEFAULT_OUTPUT_FORMAT].extension
    assert suggest_output_path("/tmp/test-song.psarc", ".feedback") == "/tmp/test-song.feedback"


def test_default_work_root_uses_user_cache_dir() -> None:
    path = _default_work_root(Path("/Volumes/Media/Games/rocksmith-dlc/Some Song.psarc"))
    assert "charts-converter" in str(path)
    assert str(path).startswith(str(Path.home()))
    assert "/.cache/" in str(path) or "/Library/Caches/" in str(path) or "AppData" in str(path)


def test_cli_prog_uses_charts_converter_name() -> None:
    parser = build_parser()
    assert parser.prog == "charts-converter"


def test_format_report_is_pretty_json() -> None:
    report = inspect_input_file("/Users/itadmin/Desktop/psarc test/Paramore_Hallelujah_v1_DD_p.psarc")
    rendered = format_report(report)
    assert '"entry_count"' in rendered
    assert rendered.startswith("{")


def test_gui_smoke_test_returns_zero() -> None:
    code = gui_main(["--smoke-test"])
    assert code == 0
