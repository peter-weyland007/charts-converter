from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .core import (
    INPUT_FORMAT_LABELS,
    OUTPUT_FORMAT_LABELS,
    batch_convert_chart_sources,
    convert_chart_source,
    extract_input_archive,
    inspect_input_file,
    validate_chart_package,
)


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=False))


def cmd_inspect(args: argparse.Namespace) -> int:
    report = inspect_input_file(args.input)
    _print_json(asdict(report))
    return 0 if report.exists else 1


def cmd_extract(args: argparse.Namespace) -> int:
    report = extract_input_archive(args.input, work_root=args.work_root)
    _print_json(asdict(report))
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    if args.batch:
        report = batch_convert_chart_sources(
            args.input,
            args.output,
            input_format=args.input_format,
            output_format=args.output_format,
            work_root=args.work_root,
        )
        _print_json(asdict(report))
        return 0 if report.failed_count == 0 else 1

    report = convert_chart_source(
        args.input,
        args.output,
        input_format=args.input_format,
        output_format=args.output_format,
        work_root=args.work_root,
    )
    _print_json(asdict(report))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    report = validate_chart_package(args.input)
    _print_json(asdict(report))
    return 0 if report.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="charts-converter",
        description="Convert supported chart inputs into packaged files or loose chart folders.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_p = sub.add_parser("inspect", help="Inspect an input source and report what it looks like.")
    inspect_p.add_argument("input", help="Path to an input file or directory")
    inspect_p.set_defaults(func=cmd_inspect)

    extract_p = sub.add_parser("extract", help="Extract a PSARC input archive into a raw workspace folder.")
    extract_p.add_argument("input", help="Path to a PSARC input file")
    extract_p.add_argument("--work-root", help="Workspace root for raw/ normalized/ build/ folders")
    extract_p.set_defaults(func=cmd_extract)

    convert_p = sub.add_parser("convert", help="Convert an input source into either a packaged file or a loose chart folder.")
    convert_p.add_argument("input", help="Path to an input file, loose chart folder, or batch input folder")
    convert_p.add_argument("output", help="Destination output path or batch output folder")
    convert_p.add_argument("--input-format", choices=sorted(INPUT_FORMAT_LABELS.keys()), default="psarc", help="Override detected input format")
    convert_p.add_argument("--output-format", choices=sorted(OUTPUT_FORMAT_LABELS.keys()), default="feedback-package", help="Choose the output shape")
    convert_p.add_argument("--batch", action="store_true", help="Treat input as a folder and batch-convert all discovered inputs of the selected input format")
    convert_p.add_argument("--work-root", help="Workspace root for staged conversion data")
    convert_p.set_defaults(func=cmd_convert)

    validate_p = sub.add_parser("validate", help="Validate a packaged output file or loose chart folder by checking its manifest.")
    validate_p.add_argument("input", help="Path to a packaged output file or loose chart directory")
    validate_p.set_defaults(func=cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
