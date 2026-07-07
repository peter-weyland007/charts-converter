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
    INPUT_FORMAT_CLONE_HERO,
    INPUT_FORMAT_LOOSE,
    INPUT_FORMAT_PSARC,
    OUTPUT_FORMAT_FEEDPAK,
    OUTPUT_FORMAT_FOLDER,
    BatchConversionReport,
    batch_convert_chart_sources,
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


SOURCE_MODE_SINGLE = "Single input"
SOURCE_MODE_BATCH = "Input folder batch"

INPUT_FORMATS: dict[str, InputFormat] = {
    INPUT_FORMAT_LABELS[INPUT_FORMAT_PSARC]: InputFormat(
        id=INPUT_FORMAT_PSARC,
        label=INPUT_FORMAT_LABELS[INPUT_FORMAT_PSARC],
        browse_kind="file",
        filetypes=[("PSARC archives", "*.psarc"), ("All files", "*")],
        preferred_suffixes=(".psarc",),
        description="Single-file path for one PSARC archive.",
    ),
    INPUT_FORMAT_LABELS[INPUT_FORMAT_LOOSE]: InputFormat(
        id=INPUT_FORMAT_LOOSE,
        label=INPUT_FORMAT_LABELS[INPUT_FORMAT_LOOSE],
        browse_kind="directory",
        filetypes=[("All files", "*")],
        preferred_suffixes=(),
        description="Single normalized chart folder with manifest.yaml.",
    ),
    INPUT_FORMAT_LABELS[INPUT_FORMAT_CLONE_HERO]: InputFormat(
        id=INPUT_FORMAT_CLONE_HERO,
        label=INPUT_FORMAT_LABELS[INPUT_FORMAT_CLONE_HERO],
        browse_kind="directory",
        filetypes=[("All files", "*")],
        preferred_suffixes=(),
        description="Clone Hero song folder with notes.chart or notes.mid plus audio files.",
    ),
}

OUTPUT_FORMATS: dict[str, OutputFormat] = {
    "Feedpak package": OutputFormat(
        id=OUTPUT_FORMAT_FEEDPAK,
        label="Feedpak package",
        extension=".feedpak",
        browse_kind="file",
        filetypes=[("Feedpak packages", "*.feedpak"), ("All files", "*")],
        description="Create a packaged output file with a .feedpak extension.",
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

DEFAULT_SOURCE_MODE = SOURCE_MODE_SINGLE
DEFAULT_INPUT_FORMAT = INPUT_FORMAT_LABELS[INPUT_FORMAT_PSARC]
DEFAULT_OUTPUT_FORMAT = "Feedpak package"


def selected_input_format(label: str) -> InputFormat:
    return INPUT_FORMATS.get(label, INPUT_FORMATS[DEFAULT_INPUT_FORMAT])


def selected_output_format(label: str) -> OutputFormat:
    return OUTPUT_FORMATS.get(label, OUTPUT_FORMATS[DEFAULT_OUTPUT_FORMAT])


def selected_output_extension(label: str) -> str:
    return selected_output_format(label).extension


def suggested_output_name(input_path: str, output_format: OutputFormat | None = None) -> str:
    if not input_path:
        return ""
    output_format = output_format or OUTPUT_FORMATS[DEFAULT_OUTPUT_FORMAT]
    src = Path(input_path)
    looks_like_file = src.is_file() or bool(src.suffix)
    if output_format.browse_kind == "directory":
        base = src.stem if looks_like_file else src.name
        return f"{base}-charts" if looks_like_file else f"{src.name}-export"
    extension = output_format.extension or ".feedpak"
    base = src.stem if looks_like_file else src.name
    return f"{base}{extension}"


def suggest_output_path(input_path: str, output_format: OutputFormat | None = None, source_mode: str = DEFAULT_SOURCE_MODE) -> str:
    if not input_path:
        return ""
    output_format = output_format or OUTPUT_FORMATS[DEFAULT_OUTPUT_FORMAT]
    src = Path(input_path)
    looks_like_file = src.is_file() or bool(src.suffix)
    if source_mode == SOURCE_MODE_BATCH:
        parent = src.parent if src.parent != Path("") else Path.cwd()
        name = src.name or src.stem or "batch-inputs"
        return str(parent / f"{name}-converted")
    if output_format.browse_kind == "directory":
        return str(src.parent / suggested_output_name(input_path, output_format))
    if looks_like_file:
        return str(src.parent / suggested_output_name(input_path, output_format))
    return str(src / suggested_output_name(input_path, output_format))


def format_report(report: Any) -> str:
    return json.dumps(asdict(report), indent=2)


def summarize_batch_report(report: BatchConversionReport) -> str:
    lines = [
        f"Discovered: {report.discovered_inputs}",
        f"Converted: {report.converted_count}",
        f"Failed: {report.failed_count}",
    ]
    for item in report.items:
        status = "OK" if item.ok else "FAIL"
        target = item.output_path or "(no output)"
        if item.ok:
            lines.append(f"{status}: {Path(item.input_path).name} -> {Path(target).name}")
        else:
            lines.append(f"{status}: {Path(item.input_path).name} -> {Path(target).name}: {item.error}")
    return "\n".join(lines)


class ConverterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("charts-converter")
        self.root.geometry("940x740")
        self.root.minsize(820, 620)

        self.source_mode_var = tk.StringVar(value=DEFAULT_SOURCE_MODE)
        self.input_format_var = tk.StringVar(value=DEFAULT_INPUT_FORMAT)
        self.input_var = tk.StringVar()
        self.output_format_var = tk.StringVar(value=DEFAULT_OUTPUT_FORMAT)
        self.output_var = tk.StringVar()
        self.work_root_var = tk.StringVar()
        self.input_label_var = tk.StringVar(value="Input file")
        self.output_label_var = tk.StringVar(value="Output file")
        self.output_button_var = tk.StringVar(value="Save As…")
        self.input_help_var = tk.StringVar(value=selected_input_format(DEFAULT_INPUT_FORMAT).description)
        self.output_help_var = tk.StringVar(value=selected_output_format(DEFAULT_OUTPUT_FORMAT).description)
        self.status_var = tk.StringVar(value="Choose a source mode, then pick input/output targets and click Convert.")
        self._last_suggested_output = ""
        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._worker: threading.Thread | None = None

        self._build_ui()
        self.input_var.trace_add("write", self._sync_output_path)
        self.input_format_var.trace_add("write", self._on_input_format_changed)
        self.output_format_var.trace_add("write", self._on_output_format_changed)
        self.source_mode_var.trace_add("write", self._on_source_mode_changed)
        self.root.after(100, self._drain_queue)
        self._refresh_mode_labels()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        top = ttk.Frame(self.root, padding=14)
        top.grid(row=0, column=0, sticky="nsew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Source mode").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=(0, 8))
        source_mode = ttk.Combobox(top, textvariable=self.source_mode_var, state="readonly", values=[SOURCE_MODE_SINGLE, SOURCE_MODE_BATCH])
        source_mode.grid(row=0, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(top, text="Input type").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(0, 8))
        input_type = ttk.Combobox(top, textvariable=self.input_format_var, state="readonly", values=list(INPUT_FORMATS.keys()))
        input_type.grid(row=1, column=1, sticky="ew", pady=(0, 8))
        ttk.Label(top, textvariable=self.input_help_var, wraplength=780, foreground="#666666").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )

        ttk.Label(top, textvariable=self.input_label_var).grid(row=3, column=0, sticky="w", padx=(0, 10), pady=(0, 8))
        ttk.Entry(top, textvariable=self.input_var).grid(row=3, column=1, sticky="ew", pady=(0, 8))
        ttk.Button(top, text="Browse…", command=self.choose_input).grid(row=3, column=2, sticky="ew", padx=(10, 0), pady=(0, 8))

        ttk.Label(top, text="Output type").grid(row=4, column=0, sticky="w", padx=(0, 10), pady=(0, 8))
        output_type = ttk.Combobox(top, textvariable=self.output_format_var, state="readonly", values=list(OUTPUT_FORMATS.keys()))
        output_type.grid(row=4, column=1, sticky="ew", pady=(0, 8))
        ttk.Label(top, textvariable=self.output_help_var, wraplength=780, foreground="#666666").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )

        ttk.Label(top, textvariable=self.output_label_var).grid(row=6, column=0, sticky="w", padx=(0, 10), pady=(0, 8))
        ttk.Entry(top, textvariable=self.output_var).grid(row=6, column=1, sticky="ew", pady=(0, 8))
        ttk.Button(top, textvariable=self.output_button_var, command=self.choose_output).grid(row=6, column=2, sticky="ew", padx=(10, 0), pady=(0, 8))

        ttk.Label(top, text="Scratch folder (optional)").grid(row=7, column=0, sticky="w", padx=(0, 10), pady=(0, 8))
        ttk.Entry(top, textvariable=self.work_root_var).grid(row=7, column=1, sticky="ew", pady=(0, 8))
        ttk.Button(top, text="Folder…", command=self.choose_work_root).grid(row=7, column=2, sticky="ew", padx=(10, 0), pady=(0, 8))

        help_text = (
            "Leave Scratch folder blank to use system cache. "
            "Batch mode scans the chosen input folder for supported sources of the selected input type and writes every result into the chosen output folder."
        )
        ttk.Label(top, text=help_text, wraplength=780, foreground="#666666").grid(
            row=8, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )

        button_row = ttk.Frame(top)
        button_row.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.convert_btn = ttk.Button(button_row, text="Convert", command=self.start_convert)
        self.convert_btn.pack(side="left")
        self.validate_btn = ttk.Button(button_row, text="Validate Output", command=self.validate_output)
        self.validate_btn.pack(side="left", padx=(8, 0))
        self.open_btn = ttk.Button(button_row, text="Open Output Folder", command=self.open_output_folder)
        self.open_btn.pack(side="left", padx=(8, 0))

        status = ttk.Label(top, textvariable=self.status_var)
        status.grid(row=10, column=0, columnspan=3, sticky="w", pady=(12, 0))

        main = ttk.Frame(self.root, padding=(14, 0, 14, 14))
        main.grid(row=1, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        ttk.Label(main, text="Activity log").grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.log = tk.Text(main, wrap="word", height=24)
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

    def _refresh_mode_labels(self) -> None:
        batch_mode = self.source_mode_var.get().strip() == SOURCE_MODE_BATCH
        input_format = selected_input_format(self.input_format_var.get().strip())
        if batch_mode:
            if input_format.id == INPUT_FORMAT_CLONE_HERO:
                self.input_label_var.set("Input library folder")
            else:
                self.input_label_var.set("Input folder")
        else:
            if input_format.id == INPUT_FORMAT_CLONE_HERO:
                self.input_label_var.set("Song folder")
            elif input_format.id == INPUT_FORMAT_LOOSE:
                self.input_label_var.set("Chart folder")
            else:
                self.input_label_var.set("Input file")
        self.output_label_var.set("Output folder" if batch_mode else "Output target")
        self.output_button_var.set("Choose Folder…")
        self._sync_output_path()

    def _on_source_mode_changed(self, *_args: object) -> None:
        input_format = selected_input_format(self.input_format_var.get().strip())
        batch_mode = self.source_mode_var.get().strip() == SOURCE_MODE_BATCH
        if batch_mode and input_format.id == INPUT_FORMAT_LOOSE:
            self.input_help_var.set("Batch mode will scan subfolders for manifest.yaml and convert each loose chart folder it finds.")
        elif batch_mode and input_format.id == INPUT_FORMAT_CLONE_HERO:
            self.input_help_var.set("Batch mode will scan subfolders for Clone Hero songs containing notes.chart or notes.mid and convert each one it finds.")
        else:
            self.input_help_var.set(input_format.description)
        self._refresh_mode_labels()

    def _on_input_format_changed(self, *_args: object) -> None:
        self._on_source_mode_changed()

    def _on_output_format_changed(self, *_args: object) -> None:
        output_format = selected_output_format(self.output_format_var.get().strip())
        batch_mode = self.source_mode_var.get().strip() == SOURCE_MODE_BATCH
        if batch_mode:
            self.output_help_var.set(f"Batch mode writes one {output_format.label.lower()} per discovered input into the chosen output folder.")
        elif output_format.browse_kind == "directory":
            self.output_help_var.set(output_format.description)
        else:
            self.output_help_var.set("Choose an output folder. The converter will reuse the input filename automatically and only change the extension.")
        self._refresh_mode_labels()

    def _sync_output_path(self, *_args: object) -> None:
        output_format = selected_output_format(self.output_format_var.get().strip())
        source_mode = self.source_mode_var.get().strip()
        suggested = suggest_output_path(
            self.input_var.get().strip(),
            output_format,
            source_mode,
        )
        current = self.output_var.get().strip()
        if not current or current == self._last_suggested_output:
            self.output_var.set(suggested)
        elif source_mode != SOURCE_MODE_BATCH and output_format.browse_kind != "directory":
            current_path = Path(current)
            folder = current_path if current_path.is_dir() else current_path.parent
            if str(folder).strip():
                self.output_var.set(str(folder / suggested_output_name(self.input_var.get().strip(), output_format)))
        self._last_suggested_output = self.output_var.get().strip() or suggested

    def choose_input(self) -> None:
        batch_mode = self.source_mode_var.get().strip() == SOURCE_MODE_BATCH
        input_format = selected_input_format(self.input_format_var.get().strip())
        if batch_mode or input_format.browse_kind == "directory":
            path = filedialog.askdirectory()
        else:
            path = filedialog.askopenfilename(filetypes=input_format.filetypes)
        if path:
            self.input_var.set(path)

    def choose_output(self) -> None:
        output_format = selected_output_format(self.output_format_var.get().strip())
        batch_mode = self.source_mode_var.get().strip() == SOURCE_MODE_BATCH
        input_path = self.input_var.get().strip()
        initial = self.output_var.get().strip() or suggest_output_path(input_path, output_format, self.source_mode_var.get().strip())
        initial_dir = str(Path(initial).parent) if initial else None
        if batch_mode or output_format.browse_kind == "directory":
            path = filedialog.askdirectory(initialdir=initial_dir)
            if path:
                self.output_var.set(path)
            return
        folder = filedialog.askdirectory(initialdir=initial_dir)
        if folder:
            self.output_var.set(str(Path(folder) / suggested_output_name(input_path, output_format)))

    def choose_work_root(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.work_root_var.set(path)

    def start_convert(self) -> None:
        source_mode = self.source_mode_var.get().strip()
        input_path = self.input_var.get().strip()
        output_path = self.output_var.get().strip()
        input_format = selected_input_format(self.input_format_var.get().strip())
        output_format = selected_output_format(self.output_format_var.get().strip())
        if not input_path:
            messagebox.showerror("Missing input", "Pick an input path first.")
            return
        if not output_path:
            messagebox.showerror("Missing output", "Choose an output target first.")
            return
        src = Path(input_path)
        if not src.exists():
            messagebox.showerror("Missing input", f"Path not found:\n{src}")
            return
        batch_mode = source_mode == SOURCE_MODE_BATCH
        if batch_mode and not src.is_dir():
            messagebox.showerror("Batch mode requires folder", "Choose an input folder for batch conversion.")
            return
        if not batch_mode and output_format.browse_kind != "directory":
            out_candidate = Path(output_path)
            if out_candidate.is_dir() or (not out_candidate.suffix and output_format.extension):
                output_path = str(out_candidate / suggested_output_name(input_path, output_format))
                self.output_var.set(output_path)
        self._append_log(f"Starting conversion: {src}")
        self.status_var.set("Converting…")
        self._set_busy(True)
        work_root = self.work_root_var.get().strip() or None
        self._worker = threading.Thread(
            target=self._run_convert,
            args=(source_mode, input_path, output_path, input_format.id, output_format.id, work_root),
            daemon=True,
        )
        self._worker.start()

    def _run_convert(
        self,
        source_mode: str,
        input_path: str,
        output_path: str,
        input_format_id: str,
        output_format_id: str,
        work_root: str | None,
    ) -> None:
        try:
            if source_mode == SOURCE_MODE_BATCH:
                report = batch_convert_chart_sources(
                    input_path,
                    output_path,
                    input_format=input_format_id,
                    output_format=output_format_id,
                    work_root=work_root,
                )
                self._queue.put(("batch_ok", report))
            else:
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
        if self.source_mode_var.get().strip() == SOURCE_MODE_BATCH:
            messagebox.showinfo("Batch mode", "Validate Output is for a single output path. For batch mode, open the output folder and validate individual results as needed.")
            return
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
            elif kind == "batch_ok":
                report = payload
                self._append_log("Batch conversion finished:\n" + format_report(report))
                self._append_log("Batch summary:\n" + summarize_batch_report(report))
                self.status_var.set(f"Batch done: {report.converted_count} converted, {report.failed_count} failed")
                self._set_busy(False)
                messagebox.showinfo(
                    "Batch conversion complete",
                    f"Discovered: {report.discovered_inputs}\nConverted: {report.converted_count}\nFailed: {report.failed_count}\n\nOutput folder:\n{report.output_root}",
                )
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
