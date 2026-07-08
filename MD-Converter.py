#!/usr/bin/env python3
"""
MD Converter — Bulk convert documents between Markdown, DOCX, and PDF.

Usage:
  Web UI (default):  python3 MD-Converter.py
  CLI mode:          python3 MD-Converter.py -w ./source -o ./output
  MD to DOCX:        python3 MD-Converter.py -w ./source -o ./output --mode to_docx
  CLI with debug:    python3 MD-Converter.py -w ./source -o ./output --debug
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue

try:
    from markitdown import MarkItDown
except ImportError:
    print('Error: "markitdown" not found. Run: pip install "markitdown[all]"')
    sys.exit(1)

try:
    from flask import Flask, Response, jsonify, render_template, request
except ImportError:
    print('Error: "flask" not found. Run: pip install flask')
    sys.exit(1)

from typing import Literal

ConversionMode = Literal["to_markdown", "to_docx", "to_pdf", "to_docx_pdf"]
MARKDOWN_EXTENSIONS = {".md", ".markdown"}
DOCUMENT_EXTENSIONS = {".docx", ".pdf"}

CONVERSION_MODES: dict[ConversionMode, dict[str, object]] = {
    "to_markdown": {
        "input_extensions": {".docx", ".pdf"},
        "output_extension": ".md",
        "output_suffix": "_markdown",
        "empty_message": "No .docx or .pdf files found in this folder or subfolders",
    },
    "to_docx": {
        "input_extensions": {".md", ".markdown"},
        "output_extension": ".docx",
        "output_suffix": "_docx",
        "empty_message": "No .md or .markdown files found in this folder or subfolders",
    },
    "to_pdf": {
        "input_extensions": {".md", ".markdown"},
        "output_extension": ".pdf",
        "output_suffix": "_pdf",
        "empty_message": "No .md or .markdown files found in this folder or subfolders",
    },
    "to_docx_pdf": {
        "input_extensions": {".md", ".markdown"},
        "output_extension": ".docx",
        "output_suffix": "_export",
        "empty_message": "No .md or .markdown files found in this folder or subfolders",
    },
}

DEFAULT_MODE: ConversionMode = "to_markdown"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
APP_DIR = Path(__file__).resolve().parent
PANDOC_TABLE_FILTER = APP_DIR / "filters" / "tables-rules.lua"
DOCX_TABLE_BORDER_COLOR = "333333"
DOCX_TABLE_BORDER_SIZE = "8"
DOCX_DEFAULT_PAGE_WIDTH_TWIPS = 12240  # US Letter
DOCX_DEFAULT_PAGE_MARGIN_TWIPS = 1440  # 1 inch
DOCX_TABLE_WIDTH_PCT = "5000"  # 100% of the text area between page margins

HUMANIZE_DASH_REPLACEMENTS = {
    "—": "-",  # em dash
    "–": "-",  # en dash
    "―": "-",  # horizontal bar
}

HUMANIZE_ARROW_REPLACEMENTS = {
    "⇔": "<=>",
    "⇐": "<=",
    "⇒": "=>",
    "⟷": "<-->",
    "⟶": "-->",
    "⟵": "<--",
    "↔": "<-->",
    "↕": "<-->",
    "➔": "-->",
    "➜": "-->",
    "➡": "-->",
    "⬅": "<--",
    "⬆": "^",
    "⬇": "v",
    "→": "-->",
    "←": "<--",
    "↩": "<-",
    "↪": "->",
    "↑": "^",
    "↓": "v",
    "▶": ">",
    "►": ">",
    "◀": "<",
}


@dataclass(frozen=True)
class TextPreferences:
    normalize_dashes: bool = True
    normalize_arrows: bool = True
    plain_inline_code: bool = False


def parse_text_preferences(payload: dict | None = None) -> TextPreferences:
    data = payload or {}
    return TextPreferences(
        normalize_dashes=data.get("normalize_dashes", True),
        normalize_arrows=data.get("normalize_arrows", True),
        plain_inline_code=data.get("plain_inline_code", False),
    )


class EventBroadcaster:
    """Thread-safe event queue for Server-Sent Events clients."""

    def __init__(self):
        self._subscribers: list[Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> Queue:
        queue: Queue = Queue()
        with self._lock:
            self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: Queue) -> None:
        with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    def publish(self, event_type: str, **payload) -> None:
        message = {"type": event_type, **payload}
        with self._lock:
            subscribers = list(self._subscribers)
        for queue in subscribers:
            queue.put(message)


class QueueLogHandler(logging.Handler):
    def __init__(self, broadcaster: EventBroadcaster):
        super().__init__()
        self.broadcaster = broadcaster

    def emit(self, record: logging.LogRecord) -> None:
        self.broadcaster.publish("log", message=self.format(record), level=record.levelname)


def setup_logging(debug_mode: bool, handler: logging.Handler | None = None) -> None:
    level = logging.DEBUG if debug_mode else logging.INFO
    handlers = [handler] if handler else [logging.StreamHandler(sys.stdout)]
    logging.basicConfig(
        level=level,
        format="%(asctime)s - [%(levelname)s] - %(message)s",
        handlers=handlers,
        force=True,
    )


def normalize_mode(mode: str | None) -> ConversionMode:
    if mode in CONVERSION_MODES:
        return mode  # type: ignore[return-value]
    return DEFAULT_MODE


def get_mode_config(mode: ConversionMode) -> dict[str, object]:
    return CONVERSION_MODES[mode]


def gather_files(input_dir: Path, mode: ConversionMode = DEFAULT_MODE) -> list[Path]:
    """Collect supported input files from the input folder and its subfolders."""
    extensions = get_mode_config(mode)["input_extensions"]
    files = [
        file_path
        for file_path in input_dir.rglob("*")
        if file_path.is_file() and file_path.suffix.lower() in extensions
    ]
    return sorted(files, key=lambda path: path.name.lower())


def is_supported_file(file_path: Path, mode: ConversionMode = DEFAULT_MODE) -> bool:
    extensions = get_mode_config(mode)["input_extensions"]
    return file_path.is_file() and file_path.suffix.lower() in extensions


def resolve_input_files(input_path: Path, mode: ConversionMode = DEFAULT_MODE) -> list[Path]:
    if input_path.is_file():
        return [input_path] if is_supported_file(input_path, mode) else []
    if input_path.is_dir():
        return gather_files(input_path, mode)
    return []


def get_input_root(input_path: Path) -> Path:
    if input_path.is_file():
        return input_path.parent
    return input_path


def suggest_output_for_input(input_path: Path, mode: ConversionMode = DEFAULT_MODE) -> Path:
    if input_path.is_file():
        return input_path.parent
    return suggest_output_dir(input_path, mode)


def detect_input_counts(input_path: Path) -> tuple[int, int]:
    """Return counts of (markdown_files, document_files) under the input path."""
    markdown_count = 0
    document_count = 0

    paths = [input_path] if input_path.is_file() else input_path.rglob("*")
    for file_path in paths:
        if not file_path.is_file():
            continue
        extension = file_path.suffix.lower()
        if extension in MARKDOWN_EXTENSIONS:
            markdown_count += 1
        elif extension in DOCUMENT_EXTENSIONS:
            document_count += 1

    return markdown_count, document_count


def suggest_mode_for_input(
    input_path: Path,
    current_mode: ConversionMode,
) -> ConversionMode | None:
    markdown_count, document_count = detect_input_counts(input_path)

    if markdown_count > 0 and document_count == 0:
        if current_mode == "to_markdown":
            return "to_docx"
        return None

    if document_count > 0 and markdown_count == 0:
        if current_mode != "to_markdown":
            return "to_markdown"
        return None

    if markdown_count > 0 and document_count > 0:
        if document_count >= markdown_count:
            return "to_markdown" if current_mode != "to_markdown" else None
        if current_mode == "to_markdown":
            return "to_docx"
        return None

    return None


def describe_input(input_path: Path, mode: ConversionMode = DEFAULT_MODE) -> str:
    files = resolve_input_files(input_path, mode)
    if input_path.is_file():
        if not files:
            extension = input_path.suffix.lower() or "unknown"
            return f"Unsupported file type: {extension}"
        return f"Ready to convert: {input_path.name}"
    return file_count_message(len(files), mode)


def suggest_output_dir(input_dir: Path, mode: ConversionMode = DEFAULT_MODE) -> Path:
    suffix = get_mode_config(mode)["output_suffix"]
    return input_dir.parent / f"{input_dir.name}_{suffix}"


def file_count_message(count: int, mode: ConversionMode = DEFAULT_MODE) -> str:
    if count == 0:
        return str(get_mode_config(mode)["empty_message"])
    if count == 1:
        return "1 file ready to convert"
    return f"{count} files ready to convert"


def pandoc_available() -> bool:
    return shutil.which("pandoc") is not None


PANDOC_FROM_FORMAT = "markdown+pipe_tables+grid_tables+table_captions+fenced_code_blocks"

PANDOC_TABLE_HEADER = """<style>
table { border-collapse: collapse; width: 100%; margin: 1em 0; }
th, td { border: 1px solid #333333; padding: 6px 8px; text-align: left; vertical-align: top; }
th { background-color: #f0f0f0; font-weight: bold; }
tr:nth-child(even) td { background-color: #fafafa; }
</style>
"""

PANDOC_PDF_ENGINES = (
    "wkhtmltopdf",
    "weasyprint",
    "xelatex",
    "pdflatex",
    "lualatex",
    "tectonic",
    "context",
)


def get_pandoc_version() -> str | None:
    if not pandoc_available():
        return None
    result = subprocess.run(
        ["pandoc", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    first_line = result.stdout.splitlines()[0].strip()
    return first_line or None


def get_detected_pdf_engine() -> str | None:
    for engine in PANDOC_PDF_ENGINES:
        if shutil.which(engine):
            return engine
    return None


def get_pandoc_pdf_engine_flag() -> str | None:
    engine = get_detected_pdf_engine()
    if engine:
        return f"--pdf-engine={engine}"
    return None


def get_engine_status(mode: ConversionMode | None = None) -> dict[str, object]:
    has_pandoc = pandoc_available()
    pandoc_version = get_pandoc_version()
    pdf_engine = get_detected_pdf_engine()

    markdown_import = {
        "engine": "markitdown",
        "label": "MarkItDown",
        "detail": "Used for DOCX / PDF → Markdown",
        "status": "ready",
    }

    if has_pandoc:
        docx_export = {
            "engine": "pandoc",
            "label": "Pandoc → DOCX",
            "detail": "Native Word tables with grid lines",
            "status": "ready",
        }
    else:
        docx_export = {
            "engine": "builtin",
            "label": "Built-in HTML converter",
            "detail": "Install Pandoc for native Word tables",
            "status": "fallback",
        }

    if has_pandoc and pdf_engine:
        pdf_export = {
            "engine": "pandoc",
            "label": f"Pandoc → PDF ({pdf_engine})",
            "detail": "High-quality PDF via Pandoc",
            "status": "ready",
            "pdf_engine": pdf_engine,
        }
    elif has_pandoc:
        pdf_export = {
            "engine": "pandoc_html",
            "label": "Pandoc HTML → built-in PDF",
            "detail": "Install basictex or wkhtmltopdf for direct PDF export",
            "status": "partial",
            "pdf_engine": None,
        }
    else:
        pdf_export = {
            "engine": "builtin",
            "label": "Built-in HTML converter",
            "detail": "Install Pandoc for best PDF quality",
            "status": "fallback",
            "pdf_engine": None,
        }

    effective_mode = normalize_mode(mode)
    active_by_mode = {
        "to_markdown": markdown_import,
        "to_docx": docx_export,
        "to_pdf": pdf_export,
        "to_docx_pdf": {
            "engine": "combined",
            "label": "DOCX + PDF export",
            "detail": "Creates both Word and PDF for each Markdown file",
            "status": (
                "ready"
                if docx_export["status"] == "ready" and pdf_export["status"] == "ready"
                else "partial"
                if docx_export["status"] in {"ready", "partial"}
                or pdf_export["status"] in {"ready", "partial"}
                else "fallback"
            ),
        },
    }

    return {
        "pandoc": {
            "installed": has_pandoc,
            "version": pandoc_version,
        },
        "pdf_engine": {
            "installed": pdf_engine is not None,
            "name": pdf_engine,
        },
        "exports": active_by_mode,
        "active": active_by_mode[effective_mode],
        "mode": effective_mode,
    }


def run_pandoc(args: list[str]) -> None:
    result = subprocess.run(
        ["pandoc", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Pandoc conversion failed").strip()
        raise RuntimeError(detail)


def sanitize_markdown_images(markdown_text: str) -> tuple[str, int]:
    """Replace broken or placeholder embedded images so Pandoc/LaTeX can export."""
    replacements = 0

    def replace_image(match: re.Match[str]) -> str:
        nonlocal replacements
        alt_text = match.group(1).strip()
        source = match.group(2).strip()
        label = alt_text or "Image"

        if source.startswith("data:image"):
            payload = source.split(",", 1)[-1] if "," in source else ""
            is_placeholder = payload in {"", "...", "…"} or payload.endswith("...")
            is_too_short = len(payload) < 100
            decode_ok = False
            if not is_placeholder and not is_too_short:
                try:
                    decoded = base64.b64decode(payload, validate=True)
                    decode_ok = len(decoded) > 0
                except Exception:
                    decode_ok = False

            if is_placeholder or is_too_short or not decode_ok:
                replacements += 1
                return f"\n\n*[{label}: image data missing or invalid in source markdown]*\n\n"

        return match.group(0)

    sanitized = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_image, markdown_text)
    return sanitized, replacements


def _humanize_plain_text(
    text: str, preferences: TextPreferences
) -> str:
    if preferences.normalize_arrows:
        for source, target in sorted(
            HUMANIZE_ARROW_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True
        ):
            text = text.replace(source, target)

    if preferences.normalize_dashes:
        for source, target in HUMANIZE_DASH_REPLACEMENTS.items():
            text = text.replace(source, target)

    return text


def humanize_markdown(text: str, preferences: TextPreferences | None = None) -> str:
    """Replace common LLM-style punctuation with simpler ASCII equivalents."""
    preferences = preferences or TextPreferences()
    if not preferences.normalize_dashes and not preferences.normalize_arrows:
        return text

    parts = re.split(r"(```[\s\S]*?```)", text)
    for index, part in enumerate(parts):
        if part.startswith("```"):
            continue

        inline_parts = re.split(r"(`[^`\n]+`)", part)
        for inline_index, inline_part in enumerate(inline_parts):
            if inline_part.startswith("`") and inline_part.endswith("`"):
                continue
            inline_parts[inline_index] = _humanize_plain_text(inline_part, preferences)
        parts[index] = "".join(inline_parts)

    return "".join(parts)


def plainify_inline_code(text: str) -> str:
    """Remove inline backticks so code spans render as normal body text."""
    parts = re.split(r"(```[\s\S]*?```)", text)
    for index, part in enumerate(parts):
        if part.startswith("```"):
            continue
        parts[index] = re.sub(r"`([^`\n]+)`", r"\1", part)
    return "".join(parts)


def prepare_markdown_text(text: str, preferences: TextPreferences | None = None) -> str:
    """Apply optional text cleanup before markdown import or export."""
    preferences = preferences or TextPreferences()
    if preferences.plain_inline_code:
        text = plainify_inline_code(text)
    return humanize_markdown(text, preferences)


@contextmanager
def prepared_markdown_file(md_path: Path, preferences: TextPreferences | None = None):
    """Yield a markdown path safe for Pandoc, applying text cleanup if needed."""
    preferences = preferences or TextPreferences()
    original_text = md_path.read_text(encoding="utf-8")
    markdown_text = prepare_markdown_text(original_text, preferences)
    sanitized_text, replacement_count = sanitize_markdown_images(markdown_text)

    if replacement_count:
        logging.warning(
            f"Replaced {replacement_count} missing/invalid image(s) in '{md_path.name}' "
            "with placeholder text for export."
        )

    if sanitized_text == original_text:
        yield md_path
        return

    with tempfile.NamedTemporaryFile(
        "w",
        suffix=md_path.suffix or ".md",
        delete=False,
        encoding="utf-8",
    ) as temp_file:
        temp_file.write(sanitized_text)
        temp_path = Path(temp_file.name)

    try:
        yield temp_path
    finally:
        temp_path.unlink(missing_ok=True)


def pandoc_table_border_args() -> list[str]:
    """Enable full grid lines on tables in Pandoc LaTeX/PDF output."""
    if not PANDOC_TABLE_FILTER.is_file():
        return []
    return [
        f"--lua-filter={PANDOC_TABLE_FILTER}",
        "-M",
        "tables-vrules=true",
        "-M",
        "tables-hrules=true",
    ]


def _docx_border_element(tag: str) -> "ET.Element":
    from xml.etree import ElementTree as ET

    word_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    element = ET.Element(f"{{{word_ns}}}{tag}")
    element.set(f"{{{word_ns}}}val", "single")
    element.set(f"{{{word_ns}}}sz", DOCX_TABLE_BORDER_SIZE)
    element.set(f"{{{word_ns}}}space", "0")
    element.set(f"{{{word_ns}}}color", DOCX_TABLE_BORDER_COLOR)
    return element


def _docx_page_content_width(root: "ET.Element", w: str) -> int:
    """Return printable width in twips between the page margins."""
    for section in root.iter(f"{w}sectPr"):
        page_size = section.find(f"{w}pgSz")
        if page_size is None:
            continue
        page_width = int(page_size.get(f"{w}w", DOCX_DEFAULT_PAGE_WIDTH_TWIPS))
        page_margins = section.find(f"{w}pgMar")
        if page_margins is None:
            left_margin = right_margin = DOCX_DEFAULT_PAGE_MARGIN_TWIPS
        else:
            left_margin = int(page_margins.get(f"{w}left", DOCX_DEFAULT_PAGE_MARGIN_TWIPS))
            right_margin = int(page_margins.get(f"{w}right", DOCX_DEFAULT_PAGE_MARGIN_TWIPS))
        return max(page_width - left_margin - right_margin, 1)
    return DOCX_DEFAULT_PAGE_WIDTH_TWIPS - (2 * DOCX_DEFAULT_PAGE_MARGIN_TWIPS)


def _docx_set_table_full_width(
    table: "ET.Element", content_width_twips: int, w: str, ET: "type[ET.ElementTree]"
) -> bool:
    """Stretch a table to the full content width with proportional columns."""
    changed = False
    table_props = table.find(f"{w}tblPr")
    if table_props is None:
        table_props = ET.Element(f"{w}tblPr")
        table.insert(0, table_props)
        changed = True

    table_width = table_props.find(f"{w}tblW")
    if table_width is None:
        table_width = ET.Element(f"{w}tblW")
        table_props.append(table_width)
        changed = True
    if (
        table_width.get(f"{w}type") != "pct"
        or table_width.get(f"{w}w") != DOCX_TABLE_WIDTH_PCT
    ):
        table_width.set(f"{w}type", "pct")
        table_width.set(f"{w}w", DOCX_TABLE_WIDTH_PCT)
        changed = True

    table_indent = table_props.find(f"{w}tblInd")
    if table_indent is not None:
        table_props.remove(table_indent)
        changed = True

    table_layout = table_props.find(f"{w}tblLayout")
    if table_layout is None:
        table_layout = ET.Element(f"{w}tblLayout")
        table_props.append(table_layout)
        changed = True
    if table_layout.get(f"{w}type") != "fixed":
        table_layout.set(f"{w}type", "fixed")
        changed = True

    table_grid = table.find(f"{w}tblGrid")
    if table_grid is not None:
        grid_columns = table_grid.findall(f"{w}gridCol")
        if grid_columns:
            current_widths = [
                int(column.get(f"{w}w")) if column.get(f"{w}w") else 0
                for column in grid_columns
            ]
            total_width = sum(current_widths)
            if total_width <= 0:
                current_widths = [1] * len(grid_columns)
                total_width = len(grid_columns)

            allocated_width = 0
            for index, column in enumerate(grid_columns):
                if index == len(grid_columns) - 1:
                    column_width = content_width_twips - allocated_width
                else:
                    column_width = round(content_width_twips * current_widths[index] / total_width)
                    allocated_width += column_width
                column_width_text = str(column_width)
                if column.get(f"{w}w") != column_width_text:
                    column.set(f"{w}w", column_width_text)
                    changed = True

    for cell in table.iter(f"{w}tc"):
        cell_props = cell.find(f"{w}tcPr")
        if cell_props is None:
            continue
        cell_width = cell_props.find(f"{w}tcW")
        if cell_width is not None:
            cell_props.remove(cell_width)
            changed = True

    return changed


def apply_docx_table_borders(docx_path: Path) -> None:
    """Add solid grid borders and full-width layout to every table in a Word document."""
    import shutil
    import zipfile
    from xml.etree import ElementTree as ET

    word_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    w = f"{{{word_ns}}}"

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        extracted_dir = temp_root / "extracted"
        working_docx = temp_root / "working.docx"
        shutil.copy2(docx_path, working_docx)

        with zipfile.ZipFile(working_docx, "r") as archive:
            archive.extractall(extracted_dir)

        document_xml = extracted_dir / "word" / "document.xml"
        tree = ET.parse(document_xml)
        root = tree.getroot()
        changed = False
        content_width_twips = _docx_page_content_width(root, w)

        for table in root.iter(f"{w}tbl"):
            if _docx_set_table_full_width(table, content_width_twips, w, ET):
                changed = True

            table_props = table.find(f"{w}tblPr")
            if table_props is None:
                table_props = ET.Element(f"{w}tblPr")
                table.insert(0, table_props)
                changed = True

            table_style = table_props.find(f"{w}tblStyle")
            if table_style is None:
                table_style = ET.Element(f"{w}tblStyle")
                table_props.insert(0, table_style)
                changed = True
            if table_style.get(f"{w}val") != "TableGrid":
                table_style.set(f"{w}val", "TableGrid")
                changed = True

            if table_props.find(f"{w}tblBorders") is None:
                borders = ET.Element(f"{w}tblBorders")
                for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
                    borders.append(_docx_border_element(side))
                table_props.append(borders)
                changed = True

            for cell in table.iter(f"{w}tc"):
                cell_props = cell.find(f"{w}tcPr")
                if cell_props is None:
                    cell_props = ET.Element(f"{w}tcPr")
                    cell.insert(0, cell_props)
                    changed = True
                if cell_props.find(f"{w}tcBorders") is None:
                    cell_borders = ET.Element(f"{w}tcBorders")
                    for side in ("top", "left", "bottom", "right"):
                        cell_borders.append(_docx_border_element(side))
                    cell_props.append(cell_borders)
                    changed = True

        if not changed:
            return

        tree.write(document_xml, encoding="UTF-8", xml_declaration=True)
        updated_docx = temp_root / "updated.docx"
        with zipfile.ZipFile(updated_docx, "w", zipfile.ZIP_DEFLATED) as archive:
            for file_path in sorted(extracted_dir.rglob("*")):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(extracted_dir).as_posix())

        shutil.copy2(updated_docx, docx_path)


def pandoc_resource_args(md_path: Path) -> list[str]:
    return [f"--resource-path={md_path.parent}"]


def enhance_html_tables(html: str) -> str:
    """Add explicit borders so tables render as grids in DOCX/PDF fallbacks."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        table["border"] = "1"
        table["cellspacing"] = "0"
        table["cellpadding"] = "6"
        table["rules"] = "all"
        table["frame"] = "border"
        table_style = table.get("style", "")
        table["style"] = (
            "border-collapse: collapse; width: 100%; "
            "border: 2px solid #000000; "
            f"{table_style}"
        ).strip()

        for row in table.find_all("tr"):
            for cell in row.find_all(["th", "td"]):
                cell_style = cell.get("style", "")
                cell["style"] = (
                    "border: 2px solid #000000; padding: 6px 8px; "
                    f"vertical-align: top; {cell_style}"
                ).strip()
                if cell.name == "th":
                    cell["style"] += "; background-color: #f0f0f0; font-weight: bold"

    return str(soup)


def pandoc_markdown_to_html(md_path: Path) -> str:
    with prepared_markdown_file(md_path) as prepared_path:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".html", delete=False, encoding="utf-8"
        ) as header_file:
            header_file.write(PANDOC_TABLE_HEADER)
            header_path = header_file.name

        try:
            result = subprocess.run(
                [
                    "pandoc",
                    str(prepared_path),
                    "-f",
                    PANDOC_FROM_FORMAT,
                    "-t",
                    "html5",
                    "--standalone",
                    f"--include-in-header={header_path}",
                    *pandoc_resource_args(md_path),
                    "-o",
                    "-",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "Pandoc HTML export failed").strip()
                raise RuntimeError(detail)
            return enhance_html_tables(result.stdout)
        finally:
            Path(header_path).unlink(missing_ok=True)


def markdown_file_to_export_html(
    md_path: Path, preferences: TextPreferences | None = None
) -> str:
    """Build PDF-friendly HTML without Pandoc's advanced CSS."""
    with prepared_markdown_file(md_path, preferences) as prepared_path:
        return markdown_to_html(prepared_path.read_text(encoding="utf-8"))


def markdown_to_html(markdown_text: str) -> str:
    import markdown as markdown_lib

    body = markdown_lib.markdown(
        markdown_text,
        extensions=["extra", "tables", "fenced_code", "sane_lists"],
    )
    document = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      line-height: 1.5;
      margin: 40px;
      color: #111827;
    }}
    pre, code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      margin: 1em 0;
      border: 2px solid #000000;
    }}
    th, td {{
      border: 2px solid #000000;
      padding: 8px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background-color: #f0f0f0;
      font-weight: bold;
    }}
  </style>
</head>
<body>
{body}
</body>
</html>"""
    return enhance_html_tables(document)


def _html_to_pdf_pisa(html: str, pdf_path: Path) -> None:
    from xhtml2pdf import pisa

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pdf_path, "wb") as pdf_file:
        result = pisa.CreatePDF(html, dest=pdf_file)
    if result.err:
        raise RuntimeError(f"PDF generation failed: {result.err}")


def convert_md_to_docx(
    md_path: Path, docx_path: Path, preferences: TextPreferences | None = None
) -> None:
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    preferences = preferences or TextPreferences()

    if pandoc_available():
        with prepared_markdown_file(md_path, preferences) as prepared_path:
            run_pandoc(
                [
                    str(prepared_path),
                    "-f",
                    PANDOC_FROM_FORMAT,
                    "-t",
                    "docx",
                    "-o",
                    str(docx_path),
                    "--standalone",
                    *pandoc_resource_args(md_path),
                ]
            )
        apply_docx_table_borders(docx_path)
        logging.info("DOCX created with Pandoc (tables with grid borders).")
        return

    from html2docx import html2docx

    with prepared_markdown_file(md_path, preferences) as prepared_path:
        markdown_text = prepared_path.read_text(encoding="utf-8")
    html = markdown_to_html(markdown_text)
    document_buffer = html2docx(html, title=md_path.stem)
    docx_path.write_bytes(document_buffer.getvalue())
    apply_docx_table_borders(docx_path)
    logging.info("DOCX created with built-in converter (install Pandoc for best table support).")


def convert_md_to_pdf(
    md_path: Path, pdf_path: Path, preferences: TextPreferences | None = None
) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    preferences = preferences or TextPreferences()

    if pandoc_available():
        engine_flag = get_pandoc_pdf_engine_flag()
        if engine_flag:
            try:
                with prepared_markdown_file(md_path, preferences) as prepared_path:
                    run_pandoc(
                        [
                            str(prepared_path),
                            "-f",
                            PANDOC_FROM_FORMAT,
                            "-o",
                            str(pdf_path),
                            engine_flag,
                            "--standalone",
                            "-V",
                            "geometry:margin=1in",
                            *pandoc_table_border_args(),
                            *pandoc_resource_args(md_path),
                        ]
                    )
                logging.info(
                    f"PDF created with Pandoc ({engine_flag.replace('--pdf-engine=', '')})."
                )
                return
            except RuntimeError as error:
                error_text = str(error)
                if "Unable to load picture" in error_text or "Error producing PDF" in error_text:
                    logging.warning(
                        "Direct PDF export failed on images; falling back to HTML PDF converter."
                    )
                else:
                    raise

        html = markdown_file_to_export_html(md_path, preferences)
        _html_to_pdf_pisa(html, pdf_path)
        logging.info("PDF created with HTML + built-in PDF engine.")
        return

    html = markdown_file_to_export_html(md_path, preferences)
    _html_to_pdf_pisa(html, pdf_path)
    logging.info(
        "PDF created with built-in converter. Install Pandoc for best quality: brew install pandoc"
    )


def convert_to_markdown(
    file_path: Path,
    output_path: Path,
    md_engine: MarkItDown,
    preferences: TextPreferences | None = None,
) -> None:
    result = md_engine.convert(str(file_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_text = prepare_markdown_text(result.text_content, preferences)
    output_path.write_text(markdown_text, encoding="utf-8")


def convert_file(
    file_path: Path,
    input_dir: Path,
    output_dir: Path,
    mode: ConversionMode,
    md_engine: MarkItDown | None = None,
    preferences: TextPreferences | None = None,
) -> Path:
    relative_path = file_path.relative_to(input_dir)
    output_extension = str(get_mode_config(mode)["output_extension"])
    output_path = output_dir / relative_path.with_suffix(output_extension)
    preferences = preferences or TextPreferences()

    if mode == "to_markdown":
        if md_engine is None:
            raise ValueError("MarkItDown engine is required for markdown conversion")
        convert_to_markdown(file_path, output_path, md_engine, preferences)
    elif mode == "to_docx":
        convert_md_to_docx(file_path, output_path, preferences)
    elif mode == "to_pdf":
        convert_md_to_pdf(file_path, output_path, preferences)
    elif mode == "to_docx_pdf":
        docx_path = output_dir / relative_path.with_suffix(".docx")
        pdf_path = output_dir / relative_path.with_suffix(".pdf")
        errors: list[str] = []
        try:
            convert_md_to_docx(file_path, docx_path, preferences)
        except Exception as error:
            errors.append(f"DOCX failed: {error}")
        try:
            convert_md_to_pdf(file_path, pdf_path, preferences)
        except Exception as error:
            errors.append(f"PDF failed: {error}")
        if errors:
            raise RuntimeError("; ".join(errors))
        return docx_path
    else:
        raise ValueError(f"Unsupported conversion mode: {mode}")

    return output_path


def port_is_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def find_available_port(host: str, start_port: int, attempts: int = 20) -> int:
    for offset in range(attempts):
        port = start_port + offset
        if port_is_available(host, port):
            return port
    raise RuntimeError(f"No available port found near {start_port}")


def app_is_running(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            return response.status == 200
    except Exception:
        # Port may be occupied by another process, or a stale listener.
        return False


def open_browser_to(url: str) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", url], check=False)
        return
    webbrowser.open(url)


def open_folder_in_file_manager(folder_path: Path) -> None:
    if not folder_path.exists():
        folder_path.mkdir(parents=True, exist_ok=True)

    system = platform.system()
    path_str = str(folder_path)

    if system == "Darwin":
        subprocess.run(["open", path_str], check=False)
        return

    if system == "Windows":
        subprocess.run(["explorer", path_str], check=False)
        return

    subprocess.run(["xdg-open", path_str], check=False)


def pick_folder_native(title: str) -> str | None:
    system = platform.system()

    if system == "Darwin":
        escaped_title = title.replace('"', '\\"')
        script = f'POSIX path of (choose folder with prompt "{escaped_title}")'
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    if system == "Windows":
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askdirectory(title=title, parent=root)
            root.destroy()
            return selected or None
        except Exception:
            return None

    for command in (
        ["zenity", "--file-selection", "--directory", f"--title={title}"],
        ["kdialog", "--getexistingdirectory", ".", "--title", title],
    ):
        try:
            result = subprocess.run(command, capture_output=True, text=True)
        except FileNotFoundError:
            continue
        if result.returncode == 0:
            return result.stdout.strip() or None

    return None


def pick_file_native(title: str) -> str | None:
    system = platform.system()

    if system == "Darwin":
        escaped_title = title.replace('"', '\\"')
        script = f'POSIX path of (choose file with prompt "{escaped_title}")'
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    if system == "Windows":
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askopenfilename(title=title, parent=root)
            root.destroy()
            return selected or None
        except Exception:
            return None

    for command in (
        ["zenity", "--file-selection", f"--title={title}"],
        ["kdialog", "--getopenfilename", ".", "--title", title],
    ):
        try:
            result = subprocess.run(command, capture_output=True, text=True)
        except FileNotFoundError:
            continue
        if result.returncode == 0:
            return result.stdout.strip() or None

    return None


def run_conversion(
    input_path: Path,
    output_dir: Path,
    broadcaster: EventBroadcaster,
    mode: ConversionMode = DEFAULT_MODE,
    preferences: TextPreferences | None = None,
) -> tuple[int, int]:
    files_to_convert = resolve_input_files(input_path, mode)
    input_root = get_input_root(input_path)

    if not files_to_convert:
        logging.warning(str(get_mode_config(mode)["empty_message"]))
        return 0, 0

    mode_labels = {
        "to_markdown": "Markdown",
        "to_docx": "DOCX",
        "to_pdf": "PDF",
        "to_docx_pdf": "DOCX and PDF",
    }
    logging.info(
        f"Found {len(files_to_convert)} files. Converting to {mode_labels[mode]}..."
    )

    md_engine = MarkItDown() if mode == "to_markdown" else None
    if mode == "to_docx":
        if pandoc_available():
            logging.info("Export engine: Pandoc → DOCX (native Word tables with grid lines).")
        else:
            logging.info("Export engine: built-in HTML converter (install Pandoc for best tables).")
    elif mode == "to_pdf":
        if pandoc_available():
            pdf_engine = get_pandoc_pdf_engine_flag()
            if pdf_engine:
                logging.info(
                    "Export engine: Pandoc → PDF "
                    f"({pdf_engine.replace('--pdf-engine=', '')}, grid tables enabled)."
                )
            else:
                logging.info(
                    "Export engine: Pandoc HTML → PDF (install basictex or wkhtmltopdf for direct PDF)."
                )
        else:
            logging.info(
                "Export engine: built-in HTML converter (install Pandoc for best PDF quality)."
            )
    elif mode == "to_docx_pdf":
        if pandoc_available():
            logging.info("Export engine: Pandoc → DOCX (native Word tables with grid lines).")
            pdf_engine = get_pandoc_pdf_engine_flag()
            if pdf_engine:
                logging.info(
                    "Export engine: Pandoc → PDF "
                    f"({pdf_engine.replace('--pdf-engine=', '')}, grid tables enabled)."
                )
            else:
                logging.info(
                    "Export engine: Pandoc HTML → PDF (install basictex or wkhtmltopdf for direct PDF)."
                )
        else:
            logging.info(
                "Export engine: built-in HTML converter for DOCX and PDF (install Pandoc for best quality)."
            )

    if not output_dir.exists():
        logging.info(f"Creating output directory: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)

    success_count = 0
    failure_count = 0
    total = len(files_to_convert)

    for index, file_path in enumerate(files_to_convert, start=1):
        percent = round((index / total) * 100, 1)
        status = f"Converting {file_path.name} ({index}/{total})"
        broadcaster.publish("status", message=status)
        broadcaster.publish("progress", percent=percent)
        logging.debug(f"Processing: {file_path.name}")

        try:
            target_path = convert_file(
                file_path,
                input_root,
                output_dir,
                mode,
                md_engine=md_engine,
                preferences=preferences,
            )
            if mode == "to_docx_pdf":
                pdf_name = file_path.with_suffix(".pdf").name
                logging.info(
                    f"Converted: {file_path.name} -> {target_path.name}, {pdf_name}"
                )
            else:
                logging.info(f"Converted: {file_path.name} -> {target_path.name}")
            success_count += 1
        except Exception as error:
            logging.error(f"Failed to convert '{file_path.name}': {error}")
            logging.debug("Stack trace:", exc_info=True)
            failure_count += 1

    logging.info(f"Done. Success: {success_count}, Failed: {failure_count}")
    return success_count, failure_count


def create_app() -> Flask:
    app = Flask(__name__)
    broadcaster = EventBroadcaster()
    conversion_lock = threading.Lock()
    is_converting = {"value": False}

    log_handler = QueueLogHandler(broadcaster)
    setup_logging(False, handler=log_handler)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/engine-status")
    def api_engine_status():
        mode = request.args.get("mode")
        return jsonify(get_engine_status(mode))

    @app.post("/api/pick-folder")
    def api_pick_folder():
        payload = request.get_json(silent=True) or {}
        title = payload.get("title", "Select folder")
        selected = pick_folder_native(title)
        if not selected:
            return jsonify({"path": ""})
        return jsonify({"path": selected})

    @app.post("/api/pick-file")
    def api_pick_file():
        payload = request.get_json(silent=True) or {}
        title = payload.get("title", "Select file")
        selected = pick_file_native(title)
        if not selected:
            return jsonify({"path": ""})
        return jsonify({"path": selected})

    @app.post("/api/open-folder")
    def api_open_folder():
        payload = request.get_json(silent=True) or {}
        folder_value = (payload.get("folder_path") or "").strip()
        if not folder_value:
            return jsonify({"error": "No output folder provided."}), 400

        folder_path = Path(folder_value)
        if folder_path.exists() and not folder_path.is_dir():
            return jsonify({"error": "The output path is not a folder."}), 400

        try:
            open_folder_in_file_manager(folder_path)
        except Exception as error:
            return jsonify({"error": f"Could not open folder: {error}"}), 500

        return jsonify({"ok": True, "path": str(folder_path)})

    @app.post("/api/scan")
    def api_scan():
        payload = request.get_json(silent=True) or {}
        input_value = (payload.get("input_path") or payload.get("input_dir") or "").strip()
        mode = normalize_mode(payload.get("mode"))
        if not input_value:
            return jsonify({"error": "Input path is required"}), 400

        input_path = Path(input_value)
        if not input_path.exists():
            return jsonify({"error": f"Input not found: {input_path}"}), 400

        suggested_mode = suggest_mode_for_input(input_path, mode)
        effective_mode = suggested_mode or mode
        files = resolve_input_files(input_path, effective_mode)
        message = describe_input(input_path, effective_mode)
        if suggested_mode:
            mode_labels = {
                "to_markdown": "DOCX / PDF → Markdown",
                "to_docx": "Markdown → DOCX",
                "to_pdf": "Markdown → PDF",
                "to_docx_pdf": "Markdown → DOCX + PDF",
            }
            message = f"{message} · Switched to {mode_labels[suggested_mode]}"

        return jsonify(
            {
                "count": len(files),
                "message": message,
                "suggested_output": str(suggest_output_for_input(input_path, effective_mode)),
                "is_file": input_path.is_file(),
                "mode": effective_mode,
                "suggested_mode": suggested_mode,
                "mode_changed": suggested_mode is not None,
            }
        )

    @app.get("/api/events")
    def api_events():
        def stream():
            queue = broadcaster.subscribe()
            try:
                yield "data: {\"type\":\"connected\"}\n\n"
                while True:
                    try:
                        message = queue.get(timeout=15)
                    except Empty:
                        yield ": keepalive\n\n"
                        continue
                    yield f"data: {json.dumps(message)}\n\n"
            finally:
                broadcaster.unsubscribe(queue)

        return Response(stream(), mimetype="text/event-stream")

    @app.post("/api/convert")
    def api_convert():
        if is_converting["value"]:
            return jsonify({"error": "Conversion already in progress"}), 409

        payload = request.get_json(silent=True) or {}
        input_value = (payload.get("input_path") or payload.get("input_dir") or "").strip()
        output_value = (payload.get("output_dir") or "").strip()
        mode = normalize_mode(payload.get("mode"))
        debug_mode = bool(payload.get("debug"))
        preferences = parse_text_preferences(payload)

        setup_logging(debug_mode, handler=log_handler)

        if not input_value:
            return jsonify({"error": "Please select an input file or folder."}), 400

        input_path = Path(input_value)
        if not input_path.exists():
            return jsonify({"error": f"Input not found: {input_path}"}), 400

        suggested_mode = suggest_mode_for_input(input_path, mode)
        if suggested_mode:
            mode = suggested_mode

        files = resolve_input_files(input_path, mode)
        if not files:
            return jsonify({"error": str(get_mode_config(mode)["empty_message"])}), 400

        output_path = (
            Path(output_value) if output_value else suggest_output_for_input(input_path, mode)
        )

        def worker():
            with conversion_lock:
                is_converting["value"] = True

            broadcaster.publish("status", message="Starting conversion…")
            broadcaster.publish("progress", percent=0)
            logging.info(
                f"Starting {mode} conversion of {len(files)} file(s).\n"
                f"Input: {input_path}\n"
                f"Output: {output_path}"
            )

            try:
                success, failure = run_conversion(
                    input_path,
                    output_path,
                    broadcaster,
                    mode=mode,
                    preferences=preferences,
                )
                if success == 0 and failure == 0:
                    done_message = "No files were converted."
                    status = "empty"
                elif failure == 0:
                    done_message = (
                        f"Successfully converted {success} file{'s' if success != 1 else ''}!"
                    )
                    status = "success"
                else:
                    done_message = (
                        f"Finished with {success} success"
                        f"{'es' if success != 1 else ''} and {failure} failure"
                        f"{'s' if failure != 1 else ''}."
                    )
                    status = "partial"
                broadcaster.publish(
                    "done",
                    message=done_message,
                    success=success,
                    failure=failure,
                    status=status,
                    output_path=str(output_path),
                )
            except Exception as error:
                logging.critical(f"Conversion failed: {error}", exc_info=True)
                broadcaster.publish("error", message=str(error))
            finally:
                with conversion_lock:
                    is_converting["value"] = False

        threading.Thread(target=worker, daemon=True).start()
        return jsonify({"ok": True})

    return app


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Bulk convert between Markdown, DOCX, and PDF."
    )
    parser.add_argument(
        "-w", "--working_dir", type=str, help="Directory containing files to convert."
    )
    parser.add_argument(
        "-o", "--output_dir", type=str, help="Directory where converted files are saved."
    )
    parser.add_argument(
        "--mode",
        choices=list(CONVERSION_MODES.keys()),
        default=DEFAULT_MODE,
        help="Conversion direction (default: to_markdown).",
    )
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging.")
    parser.add_argument(
        "--cli", action="store_true", help="Force CLI mode even when no arguments are given."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Web UI host address.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Web UI port.")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the browser automatically.",
    )
    return parser.parse_args()


def run_cli(args):
    setup_logging(args.debug)

    if not args.working_dir or not args.output_dir:
        print("CLI mode requires both --working_dir and --output_dir.")
        print("Run without arguments to launch the web UI.")
        sys.exit(1)

    input_dir = Path(args.working_dir)
    output_dir = Path(args.output_dir)

    if not input_dir.exists():
        logging.error(f"Invalid input path: {input_dir}")
        sys.exit(1)

    broadcaster = EventBroadcaster()
    success, failure = run_conversion(
        input_dir,
        output_dir,
        broadcaster,
        mode=normalize_mode(args.mode),
    )
    if success == 0 and failure == 0:
        sys.exit(0)
    sys.exit(1 if failure > 0 else 0)


def run_web_ui(args):
    app = create_app()
    preferred_url = f"http://{args.host}:{args.port}"

    if app_is_running(preferred_url):
        print(f"MD Converter is already running at {preferred_url}")
        if not args.no_browser:
            open_browser_to(preferred_url)
        print("Leave that Terminal window open, or stop it with Ctrl+C before starting again.")
        return

    port = args.port
    if not port_is_available(args.host, port):
        port = find_available_port(args.host, port + 1)
        print(f"Port {args.port} is busy. Using port {port} instead.")

    url = f"http://{args.host}:{port}"

    if not args.no_browser:

        def open_browser():
            time.sleep(1)
            open_browser_to(url)

        threading.Thread(target=open_browser, daemon=True).start()

    print(f"MD Converter web UI running at {url}")
    print("Press Ctrl+C to stop.")
    app.run(host=args.host, port=port, debug=False, use_reloader=False, threaded=True)


def main():
    args = parse_arguments()

    if args.cli or (args.working_dir and args.output_dir):
        run_cli(args)
    else:
        run_web_ui(args)


if __name__ == "__main__":
    main()
