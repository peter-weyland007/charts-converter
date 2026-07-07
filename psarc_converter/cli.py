from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .core import inspect_psarc, package_loose_song, validate_feedpak, write_scaffold_plan


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=False))


def cmd_inspect(args: argparse.Namespace) -> int:
    report = inspect_psarc(args.input)
    data = asdict(report)
    _print_json(data)
    return 0 if report.exists else 1


def cmd_extract(args: argparse.Namespace) -> int:
    plan, plan_path = write_scaffold_plan(
        args.input,
        work_root=args.work_root,
        output_path=None,
        input_kind="psarc",
        plan_name="extract-plan.json",
    )
    _print_json(
        {
            "status": plan.status,
            "plan_path": str(plan_path),
            "message": "Extraction scaffold created. Proprietary PSARC decoding is not wired yet.",
            "next_steps": plan.next_steps,
        }
    )
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    src = Path(args.input)
    out = Path(args.output)
    if src.is_dir():
        packaged = package_loose_song(src, out)
        _print_json(
            {
                "status": "packaged",
                "input_kind": "loose-song-dir",
                "output": str(packaged.resolve()),
            }
        )
        return 0

    plan, plan_path = write_scaffold_plan(
        src,
        work_root=args.work_root,
        output_path=out,
        input_kind="psarc",
        plan_name="convert-plan.json",
    )
    _print_json(
        {
            "status": plan.status,
            "plan_path": str(plan_path),
            "message": "PSARC→feedpak conversion has been scaffolded, but proprietary extraction is not implemented yet.",
            "next_steps": plan.next_steps,
        }
    )
    return 2


def cmd_validate(args: argparse.Namespace) -> int:
    report = validate_feedpak(args.input)
    _print_json(asdict(report))
    return 0 if report.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="psarc-converter",
        description="Standalone scaffold and validator for a PSARC conversion pipeline.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_p = sub.add_parser("inspect", help="Inspect a candidate .psarc file and probe available extractor tools.")
    inspect_p.add_argument("input", help="Path to a .psarc file")
    inspect_p.set_defaults(func=cmd_inspect)

    extract_p = sub.add_parser("extract", help="Create an extraction workspace plan for a .psarc file.")
    extract_p.add_argument("input", help="Path to a .psarc file")
    extract_p.add_argument("--work-root", help="Workspace root for raw/ normalized/ build/ folders")
    extract_p.set_defaults(func=cmd_extract)

    convert_p = sub.add_parser("convert", help="Package a loose song dir, or scaffold a .psarc→feedpak conversion plan.")
    convert_p.add_argument("input", help="Path to a loose song dir or .psarc file")
    convert_p.add_argument("output", help="Destination .feedpak path")
    convert_p.add_argument("--work-root", help="Workspace root for staged .psarc conversion data")
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
