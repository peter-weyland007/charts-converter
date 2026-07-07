from __future__ import annotations

import argparse
import json
import queue
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .core import convert_psarc_to_feedpak, validate_feedpak

OUTPUT_FORMATS: dict[str, str] = {
    "Feedback package (*.feedback)": ".feedback",
}
DEFAULT_OUTPUT_FORMAT = next(iter(OUTPUT_FORMATS))


def selected_output_extension(label: str) -> str:
    return OUTPUT_FORMATS.get(label, ".feedback")


def suggest_output_path(input_path: str, output_extension: str = ".feedback") -> str:
    if not input_path:
        return ""
    src = Path(input_path)
    if src.is_dir():
        return str(src / f"{src.name}{output_extension}")
    return str(src.with_suffix(output_extension))


def format_report(report: Any) -> str:
    return json.dumps(asdict(report), indent=2)


class ConverterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("charts-converter")
        self.root.geometry("860x620")
        self.root.minsize(760, 520)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.output_format_var = tk.StringVar(value=DEFAULT_OUTPUT_FORMAT)
        self.work_root_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Pick an input file, then click Convert.")
        self._last_suggested_output = ""
        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._worker: threading.Thread | None = None

        self._build_ui()
        self.input_var.trace_add("write", self._sync_output_path)
        self.output_format_var.trace_add("write", self._sync_output_path)
        self.root.after(100, self._drain_queue)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        top = ttk.Frame(self.root, padding=14)
        top.grid(row=0, column=0, sticky="nsew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Input file").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=(0, 8))
        ttk.Entry(top, textvariable=self.input_var).grid(row=0, column=1, sticky="ew", pady=(0, 8))
        ttk.Button(top, text="Browse…", command=self.choose_input).grid(row=0, column=2, sticky="ew", padx=(10, 0), pady=(0, 8))

        ttk.Label(top, text="Output file").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(0, 8))
        ttk.Entry(top, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", pady=(0, 8))
        ttk.Button(top, text="Save As…", command=self.choose_output).grid(row=1, column=2, sticky="ew", padx=(10, 0), pady=(0, 8))

        ttk.Label(top, text="Output type").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=(0, 8))
        output_type = ttk.Combobox(top, textvariable=self.output_format_var, state="readonly", values=list(OUTPUT_FORMATS.keys()))
        output_type.grid(row=2, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(top, text="Scratch folder (optional)").grid(row=3, column=0, sticky="w", padx=(0, 10), pady=(0, 8))
        ttk.Entry(top, textvariable=self.work_root_var).grid(row=3, column=1, sticky="ew", pady=(0, 8))
        ttk.Button(top, text="Folder…", command=self.choose_work_root).grid(row=3, column=2, sticky="ew", padx=(10, 0), pady=(0, 8))

        button_row = ttk.Frame(top)
        button_row.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.convert_btn = ttk.Button(button_row, text="Convert", command=self.start_convert)
        self.convert_btn.pack(side="left")
        self.validate_btn = ttk.Button(button_row, text="Validate Output", command=self.validate_output)
        self.validate_btn.pack(side="left", padx=(8, 0))
        self.open_btn = ttk.Button(button_row, text="Open Output Folder", command=self.open_output_folder)
        self.open_btn.pack(side="left", padx=(8, 0))

        status = ttk.Label(top, textvariable=self.status_var)
        status.grid(row=5, column=0, columnspan=3, sticky="w", pady=(12, 0))

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

    def _sync_output_path(self, *_args: object) -> None:
        suggested = suggest_output_path(
            self.input_var.get().strip(),
            selected_output_extension(self.output_format_var.get().strip()),
        )
        current = self.output_var.get().strip()
        if not current or current == self._last_suggested_output:
            self.output_var.set(suggested)
        self._last_suggested_output = suggested

    def choose_input(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Supported input files", "*.psarc"), ("All files", "*")])
        if path:
            self.input_var.set(path)

    def choose_output(self) -> None:
        extension = selected_output_extension(self.output_format_var.get().strip())
        initial = self.output_var.get().strip() or suggest_output_path(self.input_var.get().strip(), extension)
        path = filedialog.asksaveasfilename(
            defaultextension=extension,
            initialfile=Path(initial).name if initial else f"output{extension}",
            initialdir=str(Path(initial).parent) if initial else None,
            filetypes=[(self.output_format_var.get().strip(), f"*{extension}"), ("All files", "*")],
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
        if not input_path:
            messagebox.showerror("Missing input", "Pick an input file first.")
            return
        if not output_path:
            messagebox.showerror("Missing output", "Choose where to save the output file.")
            return
        src = Path(input_path)
        if not src.exists():
            messagebox.showerror("Missing input", f"File not found:\n{src}")
            return
        self._append_log(f"Starting conversion: {src.name}")
        self.status_var.set("Converting…")
        self._set_busy(True)
        work_root = self.work_root_var.get().strip() or None
        self._worker = threading.Thread(
            target=self._run_convert,
            args=(input_path, output_path, work_root),
            daemon=True,
        )
        self._worker.start()

    def _run_convert(self, input_path: str, output_path: str, work_root: str | None) -> None:
        try:
            report = convert_psarc_to_feedpak(input_path, output_path, work_root=work_root)
            self._queue.put(("convert_ok", report))
        except Exception as exc:  # pragma: no cover - exercised via manual GUI path
            self._queue.put(("convert_err", exc))

    def validate_output(self) -> None:
        output_path = self.output_var.get().strip()
        if not output_path:
            messagebox.showerror("Missing output", "Choose or generate an output file first.")
            return
        report = validate_feedpak(output_path)
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
        target = out.parent if out.suffix else out
        if not target.exists():
            target = out.parent
        try:
            import subprocess

            subprocess.run(["open", str(target)], check=False)
        except Exception as exc:  # pragma: no cover - OS specific
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
                self.status_var.set(f"Done: {Path(report.output_path).name}")
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
