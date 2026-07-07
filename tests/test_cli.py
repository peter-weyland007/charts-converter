from __future__ import annotations

import json
import zipfile
from pathlib import Path

from charts_converter.cli import build_parser, main as cli_main
from charts_converter.core import (
    INPUT_FORMAT_LOOSE,
    INPUT_FORMAT_PSARC,
    OUTPUT_FORMAT_FEEDBACK,
    OUTPUT_FORMAT_FOLDER,
    _default_work_root,
    convert_chart_source,
    detect_input_format,
    inspect_input_file,
)
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


PSARC_SAMPLE = Path("/Users/itadmin/Desktop/psarc test/Paramore_Hallelujah_v1_DD_p.psarc")
PACKAGE_SAMPLE = Path("/Users/itadmin/Desktop/psarc test/Paramore_Hallelujah.feedpak")


def test_inspect_reports_real_archive_shape() -> None:
    report = inspect_input_file(PSARC_SAMPLE)
    assert report.exists is True
    assert report.format_id == INPUT_FORMAT_PSARC
    assert report.looks_like_supported_input is True
    assert report.entry_count > 0


def test_validate_cli_accepts_generated_feedback_package(capsys) -> None:
    code = cli_main(["validate", str(PACKAGE_SAMPLE)])
    captured = capsys.readouterr().out
    data = json.loads(captured)
    assert code == 0
    assert data["ok"] is True
    assert data["title"] == "Hallelujah"


def test_generated_package_contains_manifest_and_audio() -> None:
    with zipfile.ZipFile(PACKAGE_SAMPLE, "r") as zf:
        names = set(zf.namelist())
    assert "manifest.yaml" in names
    assert "stems/full.ogg" in names


def test_input_and_output_format_defaults_are_configured() -> None:
    assert selected_input_format(DEFAULT_INPUT_FORMAT) == INPUT_FORMATS[DEFAULT_INPUT_FORMAT]
    assert selected_output_extension(DEFAULT_OUTPUT_FORMAT) == OUTPUT_FORMATS[DEFAULT_OUTPUT_FORMAT].extension
    assert suggest_output_path("/tmp/test-song.psarc", OUTPUT_FORMATS[DEFAULT_OUTPUT_FORMAT]).endswith(".feedback")


def test_default_work_root_uses_user_cache_dir() -> None:
    path = _default_work_root(Path("/Volumes/Media/Games/rocksmith-dlc/Some Song.psarc"))
    assert "charts-converter" in str(path)
    assert str(path).startswith(str(Path.home()))
    assert "/.cache/" in str(path) or "/Library/Caches/" in str(path) or "AppData" in str(path)


def test_cli_prog_uses_charts_converter_name() -> None:
    parser = build_parser()
    assert parser.prog == "charts-converter"


def test_detect_input_format_handles_file_and_dir(tmp_path: Path) -> None:
    assert detect_input_format(PSARC_SAMPLE) == INPUT_FORMAT_PSARC
    loose = tmp_path / "loose-song"
    loose.mkdir()
    assert detect_input_format(loose) == INPUT_FORMAT_LOOSE


def test_convert_psarc_to_loose_chart_folder(tmp_path: Path) -> None:
    out_dir = tmp_path / "hallelujah-charts"
    report = convert_chart_source(PSARC_SAMPLE, out_dir, output_format=OUTPUT_FORMAT_FOLDER)
    assert report.output_format == OUTPUT_FORMAT_FOLDER
    assert out_dir.is_dir()
    assert (out_dir / "manifest.yaml").exists()
    assert (out_dir / "stems" / "full.ogg").exists()


def test_convert_loose_chart_folder_to_feedback_package(tmp_path: Path) -> None:
    loose_dir = tmp_path / "source-charts"
    convert_chart_source(PSARC_SAMPLE, loose_dir, output_format=OUTPUT_FORMAT_FOLDER)
    out_file = tmp_path / "repacked.feedback"
    report = convert_chart_source(loose_dir, out_file, input_format=INPUT_FORMAT_LOOSE, output_format=OUTPUT_FORMAT_FEEDBACK)
    assert report.input_format == INPUT_FORMAT_LOOSE
    assert out_file.exists()


def test_format_report_is_pretty_json() -> None:
    report = inspect_input_file(PSARC_SAMPLE)
    rendered = format_report(report)
    assert '"entry_count"' in rendered
    assert rendered.startswith("{")


def test_gui_smoke_test_returns_zero() -> None:
    code = gui_main(["--smoke-test"])
    assert code == 0
