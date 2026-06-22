#!/usr/bin/env python3
"""
MD Converter — Bulk convert DOCX and PDF files to Markdown.

Usage:
  GUI mode (default):  python3 MD-Converter.py
  CLI mode:            python3 MD-Converter.py -w ./source -o ./output
  CLI with debug:      python3 MD-Converter.py -w ./source -o ./output --debug
"""

import argparse
import logging
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

try:
    from markitdown import MarkItDown
except ImportError:
    print('Error: "markitdown" not found. Run: pip install "markitdown[all]"')
    sys.exit(1)

VALID_EXTENSIONS = {".docx", ".pdf"}


class QueueHandler(logging.Handler):
    """Sends log records to a thread-safe queue for the GUI log panel."""

    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(self.format(record))


def setup_logging(debug_mode: bool, handler: logging.Handler | None = None):
    level = logging.DEBUG if debug_mode else logging.INFO
    handlers = [handler] if handler else [logging.StreamHandler(sys.stdout)]
    logging.basicConfig(
        level=level,
        format="%(asctime)s - [%(levelname)s] - %(message)s",
        handlers=handlers,
        force=True,
    )


def gather_files(input_dir: Path) -> list[Path]:
    """Collect .docx and .pdf files from the input folder and its subfolders."""
    files = [
        f
        for f in input_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in VALID_EXTENSIONS
    ]
    return sorted(files, key=lambda path: path.name.lower())


def run_conversion(
    input_dir: Path,
    output_dir: Path,
    progress_callback=None,
    status_callback=None,
) -> tuple[int, int]:
    """Convert all DOCX/PDF files in input_dir. Returns (success_count, failure_count)."""
    files_to_convert = gather_files(input_dir)

    if not files_to_convert:
        logging.warning(f"No valid .docx or .pdf files found in: {input_dir}")
        return 0, 0

    logging.info(f"Found {len(files_to_convert)} files. Initializing MarkItDown...")
    md_engine = MarkItDown()

    if not output_dir.exists():
        logging.info(f"Creating output directory: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)

    success_count = 0
    failure_count = 0
    total = len(files_to_convert)

    for index, file_path in enumerate(files_to_convert, start=1):
        if status_callback:
            status_callback(f"Converting {file_path.name} ({index}/{total})")
        if progress_callback:
            progress_callback(index, total)

        logging.debug(f"Processing: {file_path.name}")

        try:
            result = md_engine.convert(str(file_path))
            relative_path = file_path.relative_to(input_dir)
            target_md_path = output_dir / relative_path.with_suffix(".md")
            target_md_path.parent.mkdir(parents=True, exist_ok=True)
            target_md_path.write_text(result.text_content, encoding="utf-8")
            logging.info(f"Converted: {file_path.name} -> {target_md_path.name}")
            success_count += 1
        except Exception as error:
            logging.error(f"Failed to convert '{file_path.name}': {error}")
            logging.debug("Stack trace:", exc_info=True)
            failure_count += 1

    logging.info(f"Done. Success: {success_count}, Failed: {failure_count}")
    return success_count, failure_count


class MDConverterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("MD Converter")
        self.root.minsize(640, 520)
        self.root.geometry("720x600")

        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.debug_mode = tk.BooleanVar(value=False)
        self.file_count = tk.StringVar(value="No input folder selected")
        self.status_text = tk.StringVar(value="Ready")

        self.log_queue: queue.Queue = queue.Queue()
        self.conversion_thread: threading.Thread | None = None
        self.is_converting = False

        self._build_ui()
        self._setup_gui_logging()
        self._poll_log_queue()
        self.input_dir.trace_add("write", self._on_input_dir_changed)

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(main, text="MD Converter", font=("", 18, "bold"))
        title.pack(anchor=tk.W)

        subtitle = ttk.Label(
            main,
            text="Convert DOCX and PDF files to Markdown",
            foreground="#555555",
        )
        subtitle.pack(anchor=tk.W, pady=(0, 16))

        # Input folder
        input_frame = ttk.LabelFrame(main, text="Input Folder", padding=10)
        input_frame.pack(fill=tk.X, pady=(0, 10))

        input_row = ttk.Frame(input_frame)
        input_row.pack(fill=tk.X)
        ttk.Entry(input_row, textvariable=self.input_dir).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8)
        )
        ttk.Button(input_row, text="Browse…", command=self._browse_input).pack(side=tk.RIGHT)

        ttk.Label(input_frame, textvariable=self.file_count, foreground="#555555").pack(
            anchor=tk.W, pady=(8, 0)
        )

        # Output folder
        output_frame = ttk.LabelFrame(main, text="Output Folder", padding=10)
        output_frame.pack(fill=tk.X, pady=(0, 10))

        output_row = ttk.Frame(output_frame)
        output_row.pack(fill=tk.X)
        ttk.Entry(output_row, textvariable=self.output_dir).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8)
        )
        ttk.Button(output_row, text="Browse…", command=self._browse_output).pack(side=tk.RIGHT)

        # Options
        options_frame = ttk.Frame(main)
        options_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Checkbutton(
            options_frame,
            text="Enable debug logging",
            variable=self.debug_mode,
            command=self._toggle_debug,
        ).pack(anchor=tk.W)

        # Progress
        progress_frame = ttk.LabelFrame(main, text="Progress", padding=10)
        progress_frame.pack(fill=tk.X, pady=(0, 10))

        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate", maximum=100)
        self.progress_bar.pack(fill=tk.X)
        ttk.Label(progress_frame, textvariable=self.status_text).pack(anchor=tk.W, pady=(8, 0))

        # Log
        log_frame = ttk.LabelFrame(main, text="Log", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=12,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("Menlo", 11) if sys.platform == "darwin" else ("Consolas", 10),
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Actions
        action_frame = ttk.Frame(main)
        action_frame.pack(fill=tk.X)

        self.convert_btn = ttk.Button(
            action_frame, text="Convert", command=self._start_conversion
        )
        self.convert_btn.pack(side=tk.RIGHT)

        ttk.Button(action_frame, text="Clear Log", command=self._clear_log).pack(
            side=tk.RIGHT, padx=(0, 8)
        )

        ttk.Button(action_frame, text="Quit", command=self.root.destroy).pack(side=tk.LEFT)

    def _setup_gui_logging(self):
        self.log_handler = QueueHandler(self.log_queue)
        setup_logging(self.debug_mode.get(), handler=self.log_handler)

    def _toggle_debug(self):
        setup_logging(self.debug_mode.get(), handler=self.log_handler)

    def _show_dialog(self, dialog_func, title: str, message: str):
        """Show a dialog on top of the main window (macOS often hides them otherwise)."""
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.update_idletasks()
        dialog_func(title, message)
        self.root.attributes("-topmost", False)
        self.root.lift()

    def _report_issue(self, level: str, title: str, message: str):
        self.status_text.set(message.split("\n")[0])
        log_line = f"[{level}] {message.replace(chr(10), ' | ')}"
        self._append_log(log_line)
        if level == "ERROR":
            self._show_dialog(messagebox.showerror, title, message)
        else:
            self._show_dialog(messagebox.showwarning, title, message)

    def _on_input_dir_changed(self, *_):
        if self.input_dir.get().strip():
            self._update_file_count()

    def _poll_log_queue(self):
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(message)
        self.root.after(100, self._poll_log_queue)

    def _append_log(self, message: str):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _clear_log(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _browse_input(self):
        selected = filedialog.askdirectory(title="Select Input Folder (DOCX/PDF files)")
        if selected:
            self.input_dir.set(selected)
            self._update_file_count()

    def _browse_output(self):
        selected = filedialog.askdirectory(title="Select Output Folder for Markdown files")
        if selected:
            self.output_dir.set(selected)

    def _suggest_output_dir(self, input_path: Path) -> Path:
        return input_path.parent / f"{input_path.name}_markdown"

    def _update_file_count(self):
        input_value = self.input_dir.get().strip()
        if not input_value:
            self.file_count.set("No input folder selected")
            return

        input_path = Path(input_value)
        if not input_path.exists():
            self.file_count.set("Input folder does not exist")
            return
        if not input_path.is_dir():
            self.file_count.set("Input path is not a folder")
            return

        count = len(gather_files(input_path))
        if count == 0:
            self.file_count.set("No .docx or .pdf files found in this folder or subfolders")
        elif count == 1:
            self.file_count.set("1 file ready to convert")
        else:
            self.file_count.set(f"{count} files ready to convert")

        if not self.output_dir.get().strip():
            self.output_dir.set(str(self._suggest_output_dir(input_path)))

    def _validate_inputs(self) -> tuple[Path, Path] | None:
        input_value = self.input_dir.get().strip()
        output_value = self.output_dir.get().strip()

        if not input_value:
            self._report_issue(
                "ERROR",
                "Missing Input",
                "Please select an input folder using Browse.",
            )
            return None

        input_path = Path(input_value)
        if not input_path.exists() or not input_path.is_dir():
            self._report_issue(
                "ERROR",
                "Invalid Input",
                f"Input folder not found:\n{input_path}",
            )
            return None

        files = gather_files(input_path)
        if not files:
            self._report_issue(
                "WARNING",
                "No Files Found",
                "No .docx or .pdf files were found in the selected folder "
                "or its subfolders.\n\n"
                f"Folder checked:\n{input_path}",
            )
            return None

        if not output_value:
            output_path = self._suggest_output_dir(input_path)
            self.output_dir.set(str(output_path))
            self._append_log(f"Using default output folder: {output_path}")
        else:
            output_path = Path(output_value)

        return input_path, output_path

    def _set_converting(self, active: bool):
        self.is_converting = active
        state = tk.DISABLED if active else tk.NORMAL
        self.convert_btn.configure(state=state)

    def _start_conversion(self):
        if self.is_converting:
            self._append_log("Conversion already in progress.")
            return

        self._update_file_count()
        self.status_text.set("Checking folders…")
        self.root.update_idletasks()

        validated = self._validate_inputs()
        if not validated:
            return

        input_path, output_path = validated
        file_count = len(gather_files(input_path))
        self._append_log(
            f"Starting conversion of {file_count} file(s).\n"
            f"Input: {input_path}\n"
            f"Output: {output_path}"
        )
        self._set_converting(True)
        self.progress_bar["value"] = 0
        self.status_text.set("Starting conversion…")
        self.root.update_idletasks()

        def progress_callback(current: int, total: int):
            percent = (current / total) * 100
            self.root.after(0, lambda: self.progress_bar.configure(value=percent))

        def status_callback(message: str):
            self.root.after(0, lambda: self.status_text.set(message))

        def worker():
            try:
                success, failure = run_conversion(
                    input_path,
                    output_path,
                    progress_callback=progress_callback,
                    status_callback=status_callback,
                )
                self.root.after(
                    0,
                    lambda: self._on_conversion_done(success, failure, output_path),
                )
            except Exception as error:
                logging.critical(f"Conversion failed: {error}", exc_info=True)

                def show_error(err=error):
                    self._show_dialog(
                        messagebox.showerror,
                        "Error",
                        f"Conversion failed:\n{err}",
                    )

                self.root.after(0, show_error)
            finally:
                self.root.after(0, lambda: self._set_converting(False))

        self.conversion_thread = threading.Thread(target=worker, daemon=True)
        self.conversion_thread.start()

    def _on_conversion_done(self, success: int, failure: int, output_path: Path):
        self.progress_bar["value"] = 100
        self.status_text.set("Conversion complete")

        if success == 0 and failure == 0:
            self._show_dialog(messagebox.showinfo, "No Files", "No files were converted.")
        elif failure == 0:
            self._show_dialog(
                messagebox.showinfo,
                "Success",
                f"Converted {success} file{'s' if success != 1 else ''}.\n\n"
                f"Output saved to:\n{output_path}",
            )
        else:
            self._show_dialog(
                messagebox.showwarning,
                "Completed with Errors",
                f"Converted: {success}\nFailed: {failure}\n\n"
                f"Check the log for details.\nOutput: {output_path}",
            )


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Bulk convert DOCX and PDF files to Markdown using MarkItDown."
    )
    parser.add_argument(
        "-w", "--working_dir", type=str, help="Directory containing DOCX and PDF files."
    )
    parser.add_argument(
        "-o", "--output_dir", type=str, help="Directory where converted .md files are saved."
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable verbose debug logging."
    )
    parser.add_argument(
        "--cli", action="store_true", help="Force CLI mode even when no arguments are given."
    )
    return parser.parse_args()


def run_cli(args):
    setup_logging(args.debug)

    if not args.working_dir or not args.output_dir:
        print("CLI mode requires both --working_dir and --output_dir.")
        print("Run without arguments to launch the GUI.")
        sys.exit(1)

    input_dir = Path(args.working_dir)
    output_dir = Path(args.output_dir)

    if not input_dir.exists() or not input_dir.is_dir():
        logging.error(f"Invalid input directory: {input_dir}")
        sys.exit(1)

    success, failure = run_conversion(input_dir, output_dir)
    if success == 0 and failure == 0:
        sys.exit(0)
    sys.exit(1 if failure > 0 else 0)


def run_gui():
    root = tk.Tk()
    if sys.platform == "darwin":
        try:
            root.createcommand("tk::mac::Quit", root.destroy)
        except tk.TclError:
            pass
    MDConverterApp(root)
    root.mainloop()


def main():
    args = parse_arguments()

    if args.cli or (args.working_dir and args.output_dir):
        run_cli(args)
    else:
        run_gui()


if __name__ == "__main__":
    main()
