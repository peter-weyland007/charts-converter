from __future__ import annotations

import argparse
import json
import queue
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .core import (
    INPUT_FORMAT_LABELS,
    INPUT_FORMAT_LOOSE,
    INPUT_FORMAT_PSARC,
    OUTPUT_FORMAT_FEEDBACK,
    OUTPUT_FORMAT_FOLDER,
    convert_chart_source,
    validate_chart_package,
)


@dataclass(frozen=True)
class InputFormat:
    id: str
    label: str
    browse_kind: str
    filetypes: list[tuple[str, str]]
    preferred_suffixes: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class OutputFormat:
    id: str
    label: str
    extension: str
    browse_kind: str
    filetypes: list[tuple[str, str]]
    description: str


INPUT_FORMATS: dict[str, InputFormat] = {
    INPUT_FORMAT_LABELS[INPUT_FORMAT_PSARC]: InputFormat(
        id=INPUT_FORMAT_PSARC,
        label=INPUT_FORMAT_LABELS[INPUT_FORMAT_PSARC],
        browse_kind="file",
        filetypes=[("PSARC archives", "*.psarc"), ("All files", "*")],
        preferred_suffixes=(".psarc",),
        description="Current implemented source archive path.",
    ),
    INPUT_FORMAT_LABELS[INPUT_FORMAT_LOOSE]: InputFormat(
        id=INPUT_FORMAT_LOOSE,
        label=INPUT_FORMAT_LABELS[INPUT_FORMAT_LOOSE],
        browse_kind="directory",
        filetypes=[("All files", "*")],
        preferred_suffixes=(),
        description="Use an already-normalized chart folder with manifest.yaml.",
    ),
}

OUTPUT_FORMATS: dict[str, OutputFormat] = {
    "Feedback package": OutputFormat(
        id=OUTPUT_FORMAT_FEEDBACK,
        label="Feedback package",
        extension=".feedback",
        browse_kind="file",
        filetypes=[("Feedback packages", "*.feedback"), ("All files", "*")],
        description="Create a packaged output file.",
    ),
    "Loose chart folder": OutputFormat(
        id=OUTPUT_FORMAT_FOLDER,
        label="Loose chart folder",
        extension="",
        browse_kind="directory",
        filetypes=[("All files", "*")],
        description="Create a readable folder output for inspection and follow-up tooling.",
    ),
}

DEFAULT_INPUT_FORMAT = INPUT_FORMAT_LABELS[INPUT_FORMAT_PSARC]
DEFAULT_OUTPUT_FORMAT = "Feedback package"


def selected_input_format(label: str) -> InputFormat:
    return INPUT_FORMATS.get(label, INPUT_FORMATS[DEFAULT_INPUT_FORMAT])


def selected_output_format(label: str) -> OutputFormat:
    return OUTPUT_FORMATS.get(label, OUTPUT_FORMATS[DEFAULT_OUTPUT_FORMAT])


def selected_output_extension(label: str) -> str:
    return selected_output_format(label).extension


def suggest_output_path(input_path: str, output_format: OutputFormat | None = None) -> str:
    if not input_path:
        return ""
    output_format = output_format or OUTPUT_FORMATS[DEFAULT_OUTPUT_FORMAT]
    src = Path(input_path)
    if output_format.browse_kind == "directory":
        base = src.stem if src.is_file() else src.name
        return str(src.parent / f"{base}-charts") if src.is_file() else str(src.parent / f"{src.name}-export")
    extension = output_format.extension or ".feedback"
    if src.is_dir():
        return str(src / f"{src.name}{extension}")
    return str(src.with_suffix(extension))


def format_report(report: Any) -> str:
    return json.dumps(asdict(report), indent=2)


class ConverterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("charts-converter")
        self.root.geometry("920x700")
        self.root.minsize(800, 580)

        self.input_format_var = tk.StringVar(value=DEFAULT_INPUT_FORMAT)
        self.input_var = tk.StringVar()
        self.output_format_var = tk.StringVar(value=DEFAULT_OUTPUT_FORMAT)
        self.output_var = tk.StringVar()
        self.work_root_var = tk.StringVar()
        self.input_help_var = tk.StringVar(value=selected_input_format(DEFAULT_INPUT_FORMAT).description)
        self.output_help_var = tk.StringVar(value=selected_output_format(DEFAULT_OUTPUT_FORMAT).description)
        self.status_var = tk.StringVar(value="Choose input/output types, then pick files and click Convert.")
        self._last_suggested_output = ""
        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._worker: threading.Thread | None = None

        self._build_ui()
        self.input_var.trace_add("write", self._sync_output_path)
        self.input_format_var.trace_add("write", self._on_input_format_changed)
        self.output_format_var.trace_add("write", self._on_output_format_changed)
        self.root.after(100, self._drain_queue)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        top = ttk.Frame(self.root, padding=14)
        top.grid(row=0, column=0, sticky="nsew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Input type").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=(0, 8))
        input_type = ttk.Combobox(top, textvariable=self.input_format_var, state="readonly", values=list(INPUT_FORMATS.keys()))
        input_type.grid(row=0, column=1, sticky="ew", pady=(0, 8))
        ttk.Label(top, textvariable=self.input_help_var, wraplength=760, foreground="#666666").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )

        ttk.Label(top, text="Input file").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=(0, 8))
        ttk.Entry(top, textvariable=self.input_var).grid(row=2, column=1, sticky="ew", pady=(0, 8))
        ttk.Button(top, text="Browse…", command=self.choose_input).grid(row=2, column=2, sticky="ew", padx=(10, 0), pady=(0, 8))

        ttk.Label(top, text="Output type").grid(row=3, column=0, sticky="w", padx=(0, 10), pady=(0, 8))
        output_type = ttk.Combobox(top, textvariable=self.output_format_var, state="readonly", values=list(OUTPUT_FORMATS.keys()))
        output_type.grid(row=3, column=1, sticky="ew", pady=(0, 8))
        ttk.Label(top, textvariable=self.output_help_var, wraplength=760, foreground="#666666").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )

        ttk.Label(top, text="Output file").grid(row=5, column=0, sticky="w", padx=(0, 10), pady=(0, 8))
        ttk.Entry(top, textvariable=self.output_var).grid(row=5, column=1, sticky="ew", pady=(0, 8))
        ttk.Button(top, text="Save As…", command=self.choose_output).grid(row=5, column=2, sticky="ew", padx=(10, 0), pady=(0, 8))

        ttk.Label(top, text="Scratch folder (optional)").grid(row=6, column=0, sticky="w", padx=(0, 10), pady=(0, 8))
        ttk.Entry(top, textvariable=self.work_root_var).grid(row=6, column=1, sticky="ew", pady=(0, 8))
        ttk.Button(top, text="Folder…", command=self.choose_work_root).grid(row=6, column=2, sticky="ew", padx=(10, 0), pady=(0, 8))

        help_text = (
            "Leave Scratch folder blank to use your system cache. "
            "PSARC → Feedback is working now. Loose folder input/output is also wired for inspection and packaging flows."
        )
        ttk.Label(top, text=help_text, wraplength=760, foreground="#666666").grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )

        button_row = ttk.Frame(top)
        button_row.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.convert_btn = ttk.Button(button_row, text="Convert", command=self.start_convert)
        self.convert_btn.pack(side="left")
        self.validate_btn = ttk.Button(button_row, text="Validate Output", command=self.validate_output)
        self.validate_btn.pack(side="left", padx=(8, 0))
        self.open_btn = ttk.Button(button_row, text="Open Output Folder", command=self.open_output_folder)
        self.open_btn.pack(side="left", padx=(8, 0))

        status = ttk.Label(top, textvariable=self.status_var)
        status.grid(row=9, column=0, columnspan=3, sticky="w", pady=(12, 0))

        main = ttk.Frame(self.root, padding=(14, 0, 14, 14))
        main.grid(row=1, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        ttk.Label(main, text="Activity log").grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.log = tk.Text(main, wrap="word", height=22)
        self.log.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(main, orient="vertical", command=self.log.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)
        self.log.insert("end", "Ready.\n")
        self.log.configure(state="disabled")

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.convert_btn.configure(state=state)
        self.validate_btn.configure(state=state)
        self.open_btn.configure(state=state)

    def _on_input_format_changed(self, *_args: object) -> None:
        self.input_help_var.set(selected_input_format(self.input_format_var.get().strip()).description)
        self._sync_output_path()

    def _on_output_format_changed(self, *_args: object) -> None:
        self.output_help_var.set(selected_output_format(self.output_format_var.get().strip()).description)
        self._sync_output_path()

    def _sync_output_path(self, *_args: object) -> None:
        suggested = suggest_output_path(
            self.input_var.get().strip(),
            selected_output_format(self.output_format_var.get().strip()),
        )
        current = self.output_var.get().strip()
        if not current or current == self._last_suggested_output:
            self.output_var.set(suggested)
        self._last_suggested_output = suggested

    def choose_input(self) -> None:
        input_format = selected_input_format(self.input_format_var.get().strip())
        if input_format.browse_kind == "directory":
            path = filedialog.askdirectory()
        else:
            path = filedialog.askopenfilename(filetypes=input_format.filetypes)
        if path:
            self.input_var.set(path)

    def choose_output(self) -> None:
        output_format = selected_output_format(self.output_format_var.get().strip())
        initial = self.output_var.get().strip() or suggest_output_path(self.input_var.get().strip(), output_format)
        if output_format.browse_kind == "directory":
            path = filedialog.askdirectory(initialdir=str(Path(initial).parent) if initial else None)
        else:
            extension = output_format.extension
            path = filedialog.asksaveasfilename(
                defaultextension=extension,
                initialfile=Path(initial).name if initial else f"output{extension}",
                initialdir=str(Path(initial).parent) if initial else None,
                filetypes=output_format.filetypes,
            )
        if path:
            self.output_var.set(path)

    def choose_work_root(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.work_root_var.set(path)

    def start_convert(self) -> None:
        input_path = self.input_var.get().strip()
        output_path = self.output_var.get().strip()
        input_format = selected_input_format(self.input_format_var.get().strip())
        output_format = selected_output_format(self.output_format_var.get().strip())
        if not input_path:
            messagebox.showerror("Missing input", "Pick an input file first.")
            return
        if not output_path:
            messagebox.showerror("Missing output", "Choose where to save the output file.")
            return
        src = Path(input_path)
        if not src.exists():
            messagebox.showerror("Missing input", f"Path not found:\n{src}")
            return
        self._append_log(f"Starting conversion: {src.name or src}")
        self.status_var.set("Converting…")
        self._set_busy(True)
        work_root = self.work_root_var.get().strip() or None
        self._worker = threading.Thread(
            target=self._run_convert,
            args=(input_path, output_path, input_format.id, output_format.id, work_root),
            daemon=True,
        )
        self._worker.start()

    def _run_convert(self, input_path: str, output_path: str, input_format_id: str, output_format_id: str, work_root: str | None) -> None:
        try:
            report = convert_chart_source(
                input_path,
                output_path,
                input_format=input_format_id,
                output_format=output_format_id,
                work_root=work_root,
            )
            self._queue.put(("convert_ok", report))
        except Exception as exc:  # pragma: no cover
            self._queue.put(("convert_err", exc))

    def validate_output(self) -> None:
        output_path = self.output_var.get().strip()
        if not output_path:
            messagebox.showerror("Missing output", "Choose or generate an output file first.")
            return
        report = validate_chart_package(output_path)
        self._append_log("Validation result:\n" + format_report(report))
        if report.ok:
            self.status_var.set("Validation passed.")
        else:
            self.status_var.set("Validation failed.")
            messagebox.showwarning("Validation failed", format_report(report))

    def open_output_folder(self) -> None:
        output_path = self.output_var.get().strip()
        if not output_path:
            messagebox.showerror("Missing output", "Choose an output path first.")
            return
        out = Path(output_path)
        target = out if out.is_dir() else out.parent
        if not target.exists():
            target = out.parent
        try:
            import subprocess

            subprocess.run(["open", str(target)], check=False)
        except Exception as exc:  # pragma: no cover
            messagebox.showerror("Open failed", str(exc))

    def _drain_queue(self) -> None:
        while True:
            try:
                kind, payload = self._queue.get_nowait()
            except queue.Empty:
                break
            if kind == "convert_ok":
                report = payload
                self._append_log("Conversion finished:\n" + format_report(report))
                self.status_var.set(f"Done: {Path(report.output_path).name or report.output_path}")
                self._set_busy(False)
                messagebox.showinfo("Conversion complete", f"Created:\n{report.output_path}")
            elif kind == "convert_err":
                exc = payload
                self._append_log(f"Conversion failed:\n{exc}")
                self.status_var.set("Conversion failed.")
                self._set_busy(False)
                messagebox.showerror("Conversion failed", str(exc))
        self.root.after(100, self._drain_queue)


def build_root() -> tk.Tk:
    root = tk.Tk()
    ConverterApp(root)
    return root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="charts-converter-gui")
    parser.add_argument("--smoke-test", action="store_true", help="Create the GUI and exit immediately")
    args = parser.parse_args(argv)

    root = build_root()
    if args.smoke_test:
        root.update_idletasks()
        root.destroy()
        return 0
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
