# PDF Table Extraction Pipeline

LLM-augmented table extraction for documents where traditional parsers fall short.

## Why This Project?

Tools like [Docling](https://github.com/DS4SD/docling), [Marker](https://github.com/VikParuchuri/marker), and [Camelot](https://github.com/camelot-dev/camelot) work well for standard tables. But they rely on heuristics that assume conventional layouts.

**This project fills the gap when heuristics underestimate human creativity:**

- Tables with merged cells that span columns inconsistently
- Hierarchical data with subtotals embedded throughout
- Pivot-style layouts mixed with flat data
- OCR artifacts from unusual font/spacing combinations
- Multi-page tables with varying column widths

The key insight: **LLMs can reason about table structure** in ways heuristics cannot. By using AI to *heal* OCR artifacts and *extract* to user-defined schemas, we handle edge cases that break traditional parsers.

## Architecture

The pipeline has three distinct stages with clear separation of concerns:

```
PDF → Images → OCR → Raw Markdown → HEAL → Clean Markdown → EXTRACT → JSON
       ↓        ↓                    ↓                        ↓
   (Poppler) (Tesseract)      (Inferred Schema)        (User Schema)
                              Document-driven           Human intent
```

### Stage 1: OCR (pdf_to_markdown.py)
Renders PDF pages as images (via Poppler), then runs Tesseract OCR with spatial table extraction to produce markdown. Works best with digital documents (PDF exports, not scans).

### Stage 2: Heal (table_healer.py)
Fixes OCR artifacts using an **inferred schema** - what the document *actually shows*:
1. **InferTableSchema** - Detect column count, merged cells, data types
2. **HealToStructuredData** - Split merged cells using type boundaries
3. **FormatAsCleanMarkdown** - Output clean, normalized markdown

This stage is *document-driven*. It doesn't know what you want - it fixes what OCR broke.

### Stage 3: Extract (table_normalizer_async.py)
Converts clean markdown to structured JSON using a **user schema** - what you *actually want*:
1. **Analyze** - Detect table structure (hierarchical, pivot, flat)
2. **Generate** - Extract records matching your schema
3. **Review** - Validate completeness, fill gaps

This stage is *intent-driven*. Your schema defines the output structure.

### Why Separate Healing from Extraction?

**Healing** uses an inferred schema because OCR artifacts are document-specific. A merged cell like "57690 ARRC." needs to be split into `57690` | `ARRC.` regardless of what the user wants to extract.

**Extraction** uses a user schema because the output should match human intent, not OCR quirks. The schema is defined *before* seeing the document.

This separation keeps each stage focused and prevents OCR artifacts from polluting the user's schema definition.

## Quick Start

```bash
# Install dependencies
brew install tesseract poppler  # macOS
uv sync                          # Python packages

# Set API key
export OPENAI_API_KEY=your_key_here

# Run interactive demo
python setup_jupyter_kernel.py   # First time only
uv run jupyter notebook pipeline_demo.ipynb
```

## Pipeline Demo Notebook

The Jupyter notebook (`pipeline_demo.ipynb`) provides an interactive walkthrough:

1. **Setup Validation** - Check dependencies and API keys
2. **PDF Selection** - Browse and preview available PDFs
3. **OCR Conversion** - PDF → Markdown with spatial extraction
4. **Healing (Optional)** - Fix merged cells and OCR artifacts
5. **Schema Definition** - Define your target structure
6. **Extraction** - Convert to normalized JSON
7. **Review** - Inspect and export results

## CLI Usage

### PDF to Markdown
```bash
uv run python pdf_to_markdown.py input.pdf output.md --dpi 300
```

### Heal OCR Artifacts
```bash
uv run python table_healer.py input.md -o healed.md
```

### Extract to JSON
```bash
uv run python table_normalizer_async.py healed.md output.json --schema my_schema.json
```

### Full Pipeline (Example)
```bash
uv run python example_pipeline_async.py
```

## Defining Your Schema

Create a JSON file describing the records you want to extract:

```json
{
  "className": "InvoiceItem",
  "fields": {
    "item_code": {"type": "string", "description": "Product SKU", "required": true},
    "description": {"type": "string", "description": "Item description"},
    "quantity": {"type": "int", "description": "Units ordered"},
    "unit_price": {"type": "float", "description": "Price per unit"},
    "total": {"type": "float", "description": "Line total"}
  }
}
```

The schema is purely about *your intent* - what data you need. Keep descriptions focused on the business meaning, not OCR edge cases.

## When to Use This Tool

**Good fit:**
- Complex tables that break Camelot/Docling
- Documents with merged cells or irregular layouts
- Multi-page tables with subtotals and grouping
- When you need custom output schemas

**Better alternatives exist for:**
- Simple, well-formatted tables (use Camelot)
- Scanned documents needing heavy preprocessing
- Tables embedded in dense text (use Docling)
- High-volume batch processing where speed matters more than accuracy

## Project Structure

```
Core Pipeline:
├── pdf_to_markdown.py       # Stage 1: OCR
├── table_healer.py          # Stage 2: Healing
├── table_normalizer_async.py # Stage 3: Extraction
└── example_pipeline_async.py # End-to-end example

BAML Definitions:
├── baml_src/
│   ├── table_healing.baml   # Healing prompts
│   ├── table_analysis.baml  # Extraction prompts
│   └── clients.baml         # Model configuration

Configuration:
├── example_schema.json      # Sample user schema
├── pyproject.toml           # Dependencies (uv)
└── requirements.txt         # Dependencies (pip)

Documentation:
├── README.md                # This file
├── BAML_README.md           # BAML details
├── ASYNC_PROCESSING.md      # Async guide
└── NOTEBOOK_GUIDE.md        # Jupyter usage
```

## Technical Details

### TOON Format
The healing stage uses Token-Optimized Object Notation internally, reducing LLM token usage by 30-50% for structured data.

### Async Parallel Processing
Multi-page documents are processed in parallel - analysis starts immediately for all pages, and generation follows as soon as each page's analysis completes.

### Model Selection
Default configuration uses GPT-4o-mini for fast stages (analysis, formatting) and GPT-4o for accuracy-critical stages (healing, generation). Configure in BAML or via CLI flags.

## Installation

### Prerequisites
- Python 3.11+
- Tesseract OCR
- Poppler (for PDF rendering)
- OpenAI API key (or Anthropic for Claude)

### macOS
```bash
brew install tesseract poppler
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
```

### Ubuntu/Debian
```bash
sudo apt-get install tesseract-ocr poppler-utils
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
```

## License

See LICENSE file.

## Credits

- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) - Text extraction
- [BAML](https://github.com/BoundaryML/baml) - LLM function definitions
- [pdf2image](https://github.com/Belval/pdf2image) - PDF rendering
