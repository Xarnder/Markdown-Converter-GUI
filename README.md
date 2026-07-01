# MD Converter

MD Converter is a local web application for converting documents between Markdown, Microsoft Word (DOCX), and PDF. It runs on your machine; files are not uploaded to a remote service.

Supported conversions:

| Direction | Input | Output |
|-----------|-------|--------|
| Import | `.docx`, `.pdf` | `.md` |
| Export | `.md`, `.markdown` | `.docx` |
| Export | `.md`, `.markdown` | `.pdf` |
| Export | `.md`, `.markdown` | `.docx` and `.pdf` (both at once) |

Batch conversion is supported for folders and subfolders. Single-file conversion is the default in the web UI.

---

## Requirements

- **Python 3.10 or later** — [python.org/downloads](https://www.python.org/downloads/)
- **pip** — included with most Python installations

**Recommended (for best export quality):**

- **Pandoc** — improves DOCX and PDF output, especially tables with visible grid lines
- **A PDF engine** — required for direct PDF export via Pandoc (for example BasicTeX, wkhtmltopdf, or another engine Pandoc supports)

The application includes built-in converters when Pandoc is not installed. Export quality is lower without Pandoc, particularly for complex tables.

---

## Download

Clone the repository from GitHub:

```bash
git clone https://github.com/Xarnder/Markdown-Converter-GUI.git
cd Markdown-Converter-GUI
```

Alternatively, download the project as a ZIP archive from the repository page on GitHub, then extract it to a folder on your computer.

---

## Installation

### macOS (recommended)

1. Open the project folder in **Finder** (not inside an IDE terminal panel).
2. Double-click **`Start MD Converter.command`**.

The launcher will:

- Verify that `python3` is available
- Install Python dependencies from `requirements.txt`
- Start the web server
- Open the UI in your default browser

If dependency installation fails, run the command manually in Terminal:

```bash
cd /path/to/Markdown-Converter-GUI
python3 -m pip install -r requirements.txt
```

### Windows and Linux

Install dependencies from the project root:

```bash
cd /path/to/Markdown-Converter-GUI
python3 -m pip install -r requirements.txt
```

### Optional: Install Pandoc and a PDF engine

On macOS with [Homebrew](https://brew.sh/):

```bash
brew install pandoc
brew install --cask basictex
```

After installing BasicTeX, open a new terminal so `xelatex` and related tools are on your `PATH`. Alternatively:

```bash
brew install wkhtmltopdf
```

On other platforms, install Pandoc from [pandoc.org/installing.html](https://pandoc.org/installing.html) and a supported PDF engine for your system.

Restart MD Converter after installing Pandoc so the app detects it.

---

## Running the application

### Web UI (default)

From the project directory:

```bash
python3 MD-Converter.py
```

The UI is served at [http://127.0.0.1:8765](http://127.0.0.1:8765) by default. Your browser should open automatically. Keep the terminal window open while the app is running. Press `Ctrl+C` in that window to stop the server.

Useful options:

```bash
python3 MD-Converter.py --port 9000          # Use a different port
python3 MD-Converter.py --no-browser       # Do not open the browser automatically
python3 MD-Converter.py --host 127.0.0.1     # Bind address (default: 127.0.0.1)
```

If the default port is already in use, the app selects the next available port and prints the URL.

### Command-line mode

Convert a folder without the web UI:

```bash
python3 MD-Converter.py -w ./input -o ./output
```

By default this converts DOCX and PDF files in the input folder (including subfolders) to Markdown.

Specify a conversion mode with `--mode`:

```bash
python3 MD-Converter.py -w ./markdown-files -o ./output --mode to_docx
python3 MD-Converter.py -w ./markdown-files -o ./output --mode to_pdf
python3 MD-Converter.py -w ./markdown-files -o ./output --mode to_docx_pdf
python3 MD-Converter.py -w ./documents -o ./output --mode to_markdown
```

Enable detailed logging:

```bash
python3 MD-Converter.py -w ./input -o ./output --debug
```

---

## Using the web UI

1. **Start the app** using `Start MD Converter.command` (macOS) or `python3 MD-Converter.py`.
2. **Choose a conversion direction** — DOCX/PDF to Markdown, Markdown to DOCX, Markdown to PDF, or Markdown to DOCX and PDF together.
3. **Select input** — Single file (default) or folder. Use **Browse** to pick a path, or type a full path.
4. **Set the output folder** — A suggested path is filled in automatically; you can change it.
5. Click **Convert** — Progress appears on the page. When conversion finishes, use **Open output folder** to view results.

### Additional options

- **Enable debug logging** — Shows a detailed log panel on the page and in the terminal.
- **Reset** — Clears paths and returns settings to defaults.
- **Light / dark mode** — Toggle in the header; preference is saved in the browser.
- **Conversion engine** — The panel at the bottom shows whether Pandoc and a PDF engine are detected.

The app may suggest a different conversion direction when the input file type does not match the selected mode (for example, selecting a `.md` file while in import mode).

---

## Output and file handling

- Converted files are written to the output folder you specify.
- For folder input, the directory structure under the input folder is preserved in the output folder.
- For single-file input, the output file is placed in the output folder with the appropriate extension.
- Broken or placeholder inline images in Markdown (for example `data:image/png;base64...`) are replaced with placeholder text during export so conversion can complete.

---

## Troubleshooting

| Issue | What to try |
|-------|-------------|
| `python3` not found | Install Python from [python.org](https://www.python.org/downloads/) and ensure it is on your `PATH`. |
| pip install fails | Run `python3 -m pip install --upgrade pip`, then retry `pip install -r requirements.txt`. |
| Browser does not open | Open [http://127.0.0.1:8765](http://127.0.0.1:8765) manually. |
| Port already in use | Stop the other instance (`Ctrl+C` in its terminal), or start with `--port 9000`. |
| Poor table formatting in DOCX/PDF | Install Pandoc and a PDF engine, then restart the app. |
| PDF export fails on images | Replace invalid embedded images in the source Markdown, or use file paths to real image files. |
| macOS launcher closes immediately | Run `Start MD Converter.command` from Finder, not from an IDE. Check `launcher.log` in the project folder. |

---

## Project structure

```
Markdown-Converter-GUI/
  MD-Converter.py              Main application (Flask server and conversion logic)
  Start MD Converter.command   macOS launcher (installs deps and starts the UI)
  requirements.txt             Python dependencies
  filters/tables-rules.lua     Pandoc filter for table grid lines in PDF output
  templates/                   Web UI HTML
  static/                      CSS, JavaScript, icons, and assets
```

---

## Dependencies

Python packages (see `requirements.txt`):

- `markitdown[all]` — DOCX/PDF to Markdown import
- `flask` — Local web UI
- `markdown` — Markdown to HTML (fallback export path)
- `html2docx` — HTML to DOCX (fallback export path)
- `xhtml2pdf` — HTML to PDF (fallback export path)

---

## License

See the repository for license information.
