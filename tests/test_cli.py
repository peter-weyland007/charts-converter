from __future__ import annotations

import json
import os
import wave
import zipfile
from pathlib import Path

from charts_converter.cli import build_parser, main as cli_main
from charts_converter.core import (
    INPUT_FORMAT_CLONE_HERO,
    INPUT_FORMAT_LOOSE,
    INPUT_FORMAT_PSARC,
    OUTPUT_FORMAT_FEEDBACK,
    OUTPUT_FORMAT_FOLDER,
    _default_work_root,
    batch_convert_chart_sources,
    convert_chart_source,
    detect_input_format,
    discover_batch_inputs,
    inspect_input_file,
)
from charts_converter.gui import (
    DEFAULT_INPUT_FORMAT,
    DEFAULT_OUTPUT_FORMAT,
    DEFAULT_SOURCE_MODE,
    INPUT_FORMATS,
    OUTPUT_FORMATS,
    SOURCE_MODE_BATCH,
    format_report,
    main as gui_main,
    selected_input_format,
    selected_output_extension,
    suggest_output_path,
    suggested_output_name,
    summarize_batch_report,
)

PSARC_SAMPLE = Path("/Users/itadmin/Desktop/psarc test/Paramore_Hallelujah_v1_DD_p.psarc")
PACKAGE_SAMPLE = Path("/Users/itadmin/Desktop/psarc test/Paramore_Hallelujah.feedpak")
PSARC_FOLDER = Path("/Users/itadmin/Desktop/psarc test")
CH_HELPER_ROOT = Path("/tmp/repo-inspect/ch2feedpak/ch2feedpak")


def _make_clone_hero_song(tmp_path: Path, name: str = "clone-song") -> Path:
    song_dir = tmp_path / name
    song_dir.mkdir(parents=True, exist_ok=True)
    (song_dir / "song.ini").write_text(
        "[song]\n"
        "name = Test Clone Song\n"
        "artist = Hermes\n"
        "charter = Hermes\n"
        "delay = 0\n"
        "diff_guitar = 3\n",
        encoding="utf-8",
    )
    (song_dir / "notes.chart").write_text(
        "[Song]\n"
        "{\n"
        "  Name = \"Test Clone Song\"\n"
        "  Artist = \"Hermes\"\n"
        "  Charter = \"Hermes\"\n"
        "  Resolution = 192\n"
        "  Offset = 0\n"
        "}\n"
        "[SyncTrack]\n"
        "{\n"
        "  0 = B 120000\n"
        "}\n"
        "[Events]\n"
        "{\n"
        "  0 = E \"section Intro\"\n"
        "  0 = E \"lyric la\"\n"
        "}\n"
        "[ExpertSingle]\n"
        "{\n"
        "  0 = N 0 0\n"
        "  192 = N 1 0\n"
        "  384 = N 2 0\n"
        "  576 = N 3 0\n"
        "  768 = N 4 0\n"
        "}\n",
        encoding="utf-8",
    )
    wav_path = song_dir / "song.wav"
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(44100)
        wav.writeframes(b"\x00\x00" * 44100)
    return song_dir


def _enable_clone_hero_helper() -> None:
    assert CH_HELPER_ROOT.exists(), "Expected local ch2feedpak helper clone at /tmp/repo-inspect/ch2feedpak/ch2feedpak"
    os.environ["CH2FEEDPAK_ROOT"] = str(CH_HELPER_ROOT)


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
    assert suggest_output_path("/tmp/test-song.psarc", OUTPUT_FORMATS[DEFAULT_OUTPUT_FORMAT], DEFAULT_SOURCE_MODE).endswith(".feedpak")


def test_batch_mode_suggests_output_folder() -> None:
    suggested = suggest_output_path("/tmp/song-inputs", OUTPUT_FORMATS[DEFAULT_OUTPUT_FORMAT], SOURCE_MODE_BATCH)
    assert suggested.endswith("song-inputs-converted")


def test_single_file_output_uses_input_basename_in_same_folder() -> None:
    suggested = suggest_output_path("/tmp/Weezer.psarc", OUTPUT_FORMATS[DEFAULT_OUTPUT_FORMAT], DEFAULT_SOURCE_MODE)
    assert suggested == "/tmp/Weezer.feedpak"
    assert suggested_output_name("/tmp/Weezer.psarc", OUTPUT_FORMATS[DEFAULT_OUTPUT_FORMAT]) == "Weezer.feedpak"


def test_clone_hero_single_file_output_uses_folder_name() -> None:
    suggested = suggest_output_path("/tmp/My Song", OUTPUT_FORMATS[DEFAULT_OUTPUT_FORMAT], DEFAULT_SOURCE_MODE)
    assert suggested == "/tmp/My Song/My Song.feedpak"
    assert suggested_output_name("/tmp/My Song", OUTPUT_FORMATS[DEFAULT_OUTPUT_FORMAT]) == "My Song.feedpak"


def test_single_folder_output_uses_input_basename() -> None:
    suggested = suggest_output_path("/tmp/Weezer.psarc", OUTPUT_FORMATS["Loose chart folder"], DEFAULT_SOURCE_MODE)
    assert suggested == "/tmp/Weezer-charts"


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
    ch_song = _make_clone_hero_song(tmp_path, "clone-hero-detect")
    assert detect_input_format(ch_song) == INPUT_FORMAT_CLONE_HERO


def test_discover_batch_inputs_finds_psarc_samples() -> None:
    hits = discover_batch_inputs(PSARC_FOLDER, INPUT_FORMAT_PSARC)
    assert len(hits) >= 3
    assert all(path.suffix.lower() == ".psarc" for path in hits)


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
    out_file = tmp_path / "repacked.feedpak"
    report = convert_chart_source(loose_dir, out_file, input_format=INPUT_FORMAT_LOOSE, output_format=OUTPUT_FORMAT_FEEDBACK)
    assert report.input_format == INPUT_FORMAT_LOOSE
    assert out_file.exists()


def test_batch_convert_psarc_folder_to_feedback(tmp_path: Path) -> None:
    out_root = tmp_path / "batch-feedback"
    report = batch_convert_chart_sources(
        PSARC_FOLDER,
        out_root,
        input_format=INPUT_FORMAT_PSARC,
        output_format=OUTPUT_FORMAT_FEEDBACK,
    )
    assert report.discovered_inputs >= 3
    assert report.failed_count == 0
    assert report.converted_count == report.discovered_inputs
    assert (out_root / "Paramore_Hallelujah_v1_DD_p.feedpak").exists()


def test_batch_convert_psarc_folder_to_loose_folders(tmp_path: Path) -> None:
    out_root = tmp_path / "batch-folders"
    report = batch_convert_chart_sources(
        PSARC_FOLDER,
        out_root,
        input_format=INPUT_FORMAT_PSARC,
        output_format=OUTPUT_FORMAT_FOLDER,
    )
    assert report.failed_count == 0
    assert (out_root / "Paramore_Hallelujah_v1_DD_p" / "manifest.yaml").exists()


def test_cli_batch_convert_reports_results(capsys, tmp_path: Path) -> None:
    out_root = tmp_path / "cli-batch"
    code = cli_main([
        "convert",
        str(PSARC_FOLDER),
        str(out_root),
        "--batch",
        "--input-format",
        "psarc",
        "--output-format",
        "feedback-package",
    ])
    captured = capsys.readouterr().out
    data = json.loads(captured)
    assert code == 0
    assert data["converted_count"] >= 3
    assert data["failed_count"] == 0


def test_clone_hero_convert_to_feedback_package(tmp_path: Path) -> None:
    _enable_clone_hero_helper()
    song_dir = _make_clone_hero_song(tmp_path, "clone-hero-single")
    out_file = tmp_path / "clone-hero.feedpak"
    report = convert_chart_source(song_dir, out_file, input_format=INPUT_FORMAT_CLONE_HERO, output_format=OUTPUT_FORMAT_FEEDBACK)
    assert report.input_format == INPUT_FORMAT_CLONE_HERO
    assert out_file.exists()
    validation = cli_main(["validate", str(out_file)])
    assert validation == 0


def test_clone_hero_convert_to_loose_folder(tmp_path: Path) -> None:
    _enable_clone_hero_helper()
    song_dir = _make_clone_hero_song(tmp_path, "clone-hero-loose")
    out_dir = tmp_path / "clone-hero-loose-output"
    report = convert_chart_source(song_dir, out_dir, input_format=INPUT_FORMAT_CLONE_HERO, output_format=OUTPUT_FORMAT_FOLDER)
    assert report.output_format == OUTPUT_FORMAT_FOLDER
    assert (out_dir / "manifest.yaml").exists()
    assert any((out_dir / "arrangements").glob("*.json"))


def test_clone_hero_batch_discovery_and_conversion(tmp_path: Path) -> None:
    _enable_clone_hero_helper()
    root = tmp_path / "clone-batch"
    _make_clone_hero_song(root, "song-one")
    _make_clone_hero_song(root, "nested/song-two")
    hits = discover_batch_inputs(root, INPUT_FORMAT_CLONE_HERO)
    assert len(hits) == 2
    out_root = tmp_path / "clone-batch-out"
    report = batch_convert_chart_sources(root, out_root, input_format=INPUT_FORMAT_CLONE_HERO, output_format=OUTPUT_FORMAT_FEEDBACK)
    assert report.failed_count == 0
    assert report.converted_count == 2
    assert len(list(out_root.glob("*.feedpak"))) == 2


def test_format_report_is_pretty_json() -> None:
    report = inspect_input_file(PSARC_SAMPLE)
    rendered = format_report(report)
    assert '"entry_count"' in rendered
    assert rendered.startswith("{")


def test_batch_summary_mentions_counts(tmp_path: Path) -> None:
    out_root = tmp_path / "summary-batch"
    report = batch_convert_chart_sources(
        PSARC_FOLDER,
        out_root,
        input_format=INPUT_FORMAT_PSARC,
        output_format=OUTPUT_FORMAT_FEEDBACK,
    )
    summary = summarize_batch_report(report)
    assert "Discovered:" in summary
    assert "Converted:" in summary


def test_gui_smoke_test_returns_zero() -> None:
    code = gui_main(["--smoke-test"])
    assert code == 0
