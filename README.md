# PDF to Markdown Converter

Simple, focused tool for converting digital PDFs (and XLS/HTML exports) to markdown with intelligent table extraction.

**Optimized for digital documents** - no preprocessing needed. Works perfectly with colored table backgrounds, formatted cells, and multi-column layouts.

## 🚀 Interactive Demo

**New users: Start here!** Launch the interactive Jupyter notebook:

```bash
# First-time setup
python setup_jupyter_kernel.py  # Installs Jupyter kernel for our environment

# Set OpenAI API key (required for BAML normalization)
export OPENAI_API_KEY=your_key_here

# Launch notebook
uv run jupyter notebook pipeline_demo.ipynb
```

The notebook will validate your setup, show available PDFs, and guide you through the complete pipeline with live previews.

**Why the kernel setup?** Jupyter needs a kernel that uses our uv virtual environment. The setup script (run once) registers this kernel so the notebook can access all installed packages.

## Features

- ✅ **Spatial table extraction** - Accurately detects columns and rows using text position analysis
- ✅ **No preprocessing** - Direct OCR on clean digital documents for best quality
- ✅ **GitHub Flavored Markdown** - Tables output in standard markdown format
- ✅ **Multi-language support** - Works with any language Tesseract supports
- ✅ **Multi-page PDFs** - Processes all pages automatically
- ✅ **AI-powered normalization** - Convert hierarchical/pivot tables to 1NF with BAML (see [BAML_README.md](BAML_README.md))

## Installation

### Quick Start with uv (Recommended)

[uv](https://github.com/astral-sh/uv) is a fast Python package manager. It's much faster than pip and handles dependencies better.

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repo
git clone <repo-url>
cd OCR_preprocessing_tool

# Install system dependencies (Tesseract + Poppler)
# macOS:
brew install tesseract poppler

# Ubuntu/Debian:
# sudo apt-get install tesseract-ocr poppler-utils

# Install Python dependencies with uv
uv sync

# Run the script
uv run python pdf_to_markdown.py test_images/graincorp.pdf output/result.md
```

### Alternative: Traditional pip Installation

<details>
<summary>Click to expand pip installation instructions</summary>

#### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

#### 2. Install system dependencies

**macOS:**
```bash
brew install tesseract poppler
```

**Ubuntu/Debian:**
```bash
sudo apt-get install tesseract-ocr poppler-utils
```

**Windows:**
- Tesseract: https://github.com/UB-Mannheim/tesseract/wiki
- Poppler: http://blog.alivate.com.au/poppler-windows/

</details>

### (Optional) Install language packs

For non-English OCR:

**macOS:**
```bash
brew install tesseract-lang
```

**Ubuntu:**
```bash
sudo apt-get install tesseract-ocr-jpn tesseract-ocr-chi-sim
```

## Usage

### With uv (Recommended)

```bash
# Basic usage
uv run python pdf_to_markdown.py input.pdf output.md

# Or use the installed script directly
uv run pdf-to-md input.pdf output.md

# Specify DPI (higher = better quality, slower)
uv run python pdf_to_markdown.py --pdf document.pdf --output result.md --dpi 600

# Non-English documents
uv run python pdf_to_markdown.py --pdf japanese.pdf --output result.md --lang jpn

# Quiet mode
uv run python pdf_to_markdown.py document.pdf output.md --quiet
```

### Without uv (traditional)

```bash
# Basic usage
python pdf_to_markdown.py input.pdf output.md

# With options
python pdf_to_markdown.py --pdf document.pdf --output result.md --dpi 600
python pdf_to_markdown.py --pdf japanese.pdf --output result.md --lang jpn
python pdf_to_markdown.py document.pdf output.md --quiet
```

## Example

**Input:** `graincorp.pdf` (3-page shipping manifest with complex tables)

**Command:**
```bash
python pdf_to_markdown.py test_images/graincorp.pdf output/graincorp.md
```

**Output:** Clean markdown with properly formatted tables:

```markdown
# Page 1

| GC Fin Year | Month | Port | Reference Number | Exporter | Name Of Ship | Date ETA of Ship | ... |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2025/26 | Nov 25 | Mackay | 56285 | GCOP | DODO | 18/11/2025 | ... |
| 2025/26 | Nov 25 | Gladstone | 56307 | GCOP | DELTA | 22/11/2025 | ... |
```

## How It Works

1. **PDF Rendering** - Converts PDF pages to high-resolution images (300 DPI default)
2. **Text Detection** - Uses Tesseract to detect all text with bounding boxes
3. **Spatial Clustering** - Groups text into rows and detects column boundaries
4. **Word Merging** - Combines nearby words into single cells
5. **Markdown Generation** - Outputs clean GitHub Flavored Markdown tables

**No preprocessing is applied** because digital documents (PDF, XLS exports, HTML) are already high quality. Preprocessing (denoising, enhancement) actually degrades quality on clean documents.

## Supported Document Types

This tool is optimized for **digitally-generated documents**:

- ✅ PDF reports with tables
- ✅ Excel exports saved as PDF
- ✅ HTML tables printed to PDF
- ✅ Invoices, shipping manifests, data tables
- ✅ Documents with colored table backgrounds

**Not recommended for:**
- ❌ Scanned documents (use adaptive preprocessing instead)
- ❌ Photos of documents (use perspective correction first)
- ❌ Handwritten notes

## Table Normalization (BAML)

For advanced use cases, you can convert OCR'd tables to 1NF (First Normal Form) using BAML:

```bash
# Async parallel processing (recommended for multi-page PDFs)
uv run python example_pipeline_async.py

# Or synchronous version
uv run python example_pipeline.py
```

**⚡ Async version is ~3x faster for multi-page documents!**

This intelligently handles:
- **Hierarchical tables** (with subtotals and grouping)
- **Pivot tables** (transposed data)
- **Irregular structures** (merged cells, variable columns)

**Features:**
- Page-by-page processing (better accuracy)
- Parallel execution (much faster)
- Tiered models: gpt-4o-mini for classification, gpt-4o for 1NF conversion

Define your own schema and extract structured data! See [BAML_README.md](BAML_README.md) and [ASYNC_PROCESSING.md](ASYNC_PROCESSING.md) for details.

## Files

**Core Pipeline:**
- `pdf_to_markdown.py` - Main PDF to markdown conversion
- `improved_table_extractor.py` - Spatial table extraction engine
- `table_normalizer.py` - BAML normalization (synchronous)
- `table_normalizer_async.py` - BAML normalization (async parallel) ⚡
- `example_pipeline.py` - Complete PDF-to-1NF example (sync)
- `example_pipeline_async.py` - Complete PDF-to-1NF example (async) ⚡

**Documentation:**
- `README.md` - This file
- `QUICKSTART.md` - Quick setup guide
- `BAML_README.md` - BAML normalization details
- `ASYNC_PROCESSING.md` - Async parallel processing guide ⚡
- `NOTEBOOK_GUIDE.md` - Jupyter notebook usage

**Configuration:**
- `requirements.txt` - Python dependencies
- `pyproject.toml` - uv configuration
- `baml_src/` - BAML schema and client configuration

**Examples:**
- `test_images/graincorp.pdf` - Example PDF
- `example_schema.json` - Sample schema for shipping manifest

## Performance

- **Speed:** ~5-10 seconds per page at 300 DPI
- **Accuracy:** 95%+ for printed text in digital documents
- **Table detection:** Works with 15+ column tables

## Troubleshooting

**"pytesseract not installed"**
- Run: `pip install pytesseract`
- Install Tesseract binary (see installation section)

**"pdf2image error"**
- Install Poppler (see installation section)

**Tables not detected correctly**
- Try higher DPI: `--dpi 600`
- For very complex tables, results may vary

**Wrong language detected**
- Specify language: `--lang jpn` (or `fra`, `deu`, `chi_sim`, etc.)
- Install language pack if needed

## License

See LICENSE file.

## Credits

- Built on [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)
- Uses [pdf2image](https://github.com/Belval/pdf2image) for PDF rendering
