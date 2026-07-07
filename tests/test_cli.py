from __future__ import annotations

import json
import zipfile
from pathlib import Path

from psarc_converter.cli import main
from psarc_converter.core import inspect_psarc


def test_inspect_reports_fake_psarc(tmp_path: Path):
    psarc = tmp_path / "song.psarc"
    psarc.write_bytes(b"PSAR" + b"\x00" * 32)

    report = inspect_psarc(psarc)

    assert report.exists is True
    assert report.looks_like_psarc is True
    assert report.magic_hex.startswith("50534152")


def test_extract_command_requires_real_psarc_shape(tmp_path: Path):
    psarc = tmp_path / "song.psarc"
    psarc.write_bytes(b"PSAR" + b"\x00" * 8)

    try:
        main(["extract", str(psarc), "--work-root", str(tmp_path / "work")])
    except Exception as exc:
        assert "Not a PSARC" not in str(exc)


def test_convert_command_packages_loose_song_dir(tmp_path: Path, capsys):
    song_dir = tmp_path / "loose-song"
    song_dir.mkdir()
    (song_dir / "manifest.yaml").write_text(
        "title: Test Song\nartist: Test Artist\nfeedpak_version: 1.0.0\narrangements:\n  - id: lead\n    name: Lead\n",
        encoding="utf-8",
    )
    (song_dir / "arrangements").mkdir()
    (song_dir / "arrangements" / "lead.json").write_text("{}\n", encoding="utf-8")

    output = tmp_path / "out.feedpak"
    code = main(["convert", str(song_dir), str(output)])
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    assert out["status"] == "packaged"
    assert output.exists()
    with zipfile.ZipFile(output, "r") as zf:
        assert "manifest.yaml" in zf.namelist()
        assert "arrangements/lead.json" in zf.namelist()


def test_validate_command_accepts_packaged_sample(tmp_path: Path, capsys):
    song_dir = tmp_path / "sample"
    song_dir.mkdir()
    (song_dir / "manifest.yaml").write_text(
        "title: Test Song\nartist: Test Artist\nfeedpak_version: 1.2.0\narrangements:\n  - id: lead\n    name: Lead\n",
        encoding="utf-8",
    )

    pak = tmp_path / "sample.feedpak"
    with zipfile.ZipFile(pak, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(song_dir / "manifest.yaml", "manifest.yaml")

    code = main(["validate", str(pak)])
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    assert out["ok"] is True
    assert out["arrangement_count"] == 1
    assert out["title"] == "Test Song"
