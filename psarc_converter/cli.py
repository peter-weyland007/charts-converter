from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .core import (
    convert_psarc_to_feedpak,
    extract_psarc,
    inspect_psarc,
    package_loose_song,
    validate_feedpak,
)


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=False))


def cmd_inspect(args: argparse.Namespace) -> int:
    report = inspect_psarc(args.input)
    _print_json(asdict(report))
    return 0 if report.exists else 1


def cmd_extract(args: argparse.Namespace) -> int:
    report = extract_psarc(args.input, work_root=args.work_root)
    _print_json(asdict(report))
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    src = Path(args.input)
    out = Path(args.output)
    if src.is_dir():
        packaged = package_loose_song(src, out)
        _print_json({"status": "packaged", "input_kind": "loose-song-dir", "output": str(packaged.resolve())})
        return 0
    report = convert_psarc_to_feedpak(src, out, work_root=args.work_root)
    _print_json(asdict(report))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    report = validate_feedpak(args.input)
    _print_json(asdict(report))
    return 0 if report.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="psarc-converter",
        description="Convert Rocksmith PSARC files into feedpak packages.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_p = sub.add_parser("inspect", help="Inspect a candidate .psarc file and list archive contents.")
    inspect_p.add_argument("input", help="Path to a .psarc file")
    inspect_p.set_defaults(func=cmd_inspect)

    extract_p = sub.add_parser("extract", help="Extract a .psarc into a raw workspace folder.")
    extract_p.add_argument("input", help="Path to a .psarc file")
    extract_p.add_argument("--work-root", help="Workspace root for raw/ normalized/ build/ folders")
    extract_p.set_defaults(func=cmd_extract)

    convert_p = sub.add_parser("convert", help="Convert a .psarc to .feedpak, or package an existing loose song dir.")
    convert_p.add_argument("input", help="Path to a .psarc file or loose song dir")
    convert_p.add_argument("output", help="Destination .feedpak path")
    convert_p.add_argument("--work-root", help="Workspace root for staged conversion data")
    convert_p.set_defaults(func=cmd_convert)

    validate_p = sub.add_parser("validate", help="Validate a .feedpak or loose package by checking its manifest.")
    validate_p.add_argument("input", help="Path to a .feedpak/.sloppak file or loose directory")
    validate_p.set_defaults(func=cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
