# Quick Start Guide

## Interactive Demo (Recommended)

Launch the interactive Jupyter notebook to validate your setup and see the complete pipeline in action:

```bash
# 1. First-time setup: Install Jupyter kernel
python setup_jupyter_kernel.py
# or: ./setup_jupyter_kernel.sh

# 2. Set OpenAI API key (required for BAML table normalization)
export OPENAI_API_KEY=your_key_here

# 3. Launch notebook
uv run jupyter notebook pipeline_demo.ipynb
```

This notebook will:
- ✅ Check all dependencies are installed
- 📁 Show available PDFs in test_images/
- 🚀 Run the complete PDF → Markdown → 1NF pipeline
- 📊 Display results with previews

**Note:** The kernel setup is only needed once. After that, just use `uv run jupyter notebook`.

## Prerequisites

Install Tesseract and Poppler:

```bash
# macOS
brew install tesseract poppler

# Ubuntu/Debian
sudo apt-get install tesseract-ocr poppler-utils
```

## Setup with uv (Fast & Modern)

```bash
# 1. Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone and setup
git clone <repo-url>
cd OCR_preprocessing_tool
uv sync

# 3. Run!
uv run python pdf_to_markdown.py test_images/graincorp.pdf output/result.md
```

## Common Commands

```bash
# Basic conversion
uv run python pdf_to_markdown.py input.pdf output.md

# High quality (600 DPI)
uv run python pdf_to_markdown.py input.pdf output.md --dpi 600

# Japanese document
uv run python pdf_to_markdown.py input.pdf output.md --lang jpn

# Quiet mode
uv run python pdf_to_markdown.py input.pdf output.md --quiet
```

## What gets created?

- `.venv/` - Virtual environment (auto-created by uv, don't commit)
- `uv.lock` - Lockfile with exact dependency versions (commit this)
- `output/*.md` - Generated markdown files (don't commit)

## Updating dependencies

```bash
# Update all dependencies
uv sync --upgrade

# Add a new dependency
uv add <package-name>

# Remove a dependency
uv remove <package-name>
```

## Without uv (Traditional)

If you prefer pip:

```bash
pip install -r requirements.txt
python pdf_to_markdown.py input.pdf output.md
```

## Troubleshooting

**uv command not found**
- Make sure uv is installed: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Restart your terminal

**Tesseract not found**
- Install Tesseract: `brew install tesseract` (macOS) or `apt-get install tesseract-ocr` (Linux)

**pdf2image error**
- Install Poppler: `brew install poppler` (macOS) or `apt-get install poppler-utils` (Linux)
