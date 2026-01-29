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

The key insight: **LLMs can reason about table structure** in ways heuristics cannot. By using AI to *analyze* table structure and *extract* to user-defined schemas with built-in merged cell recovery, we handle edge cases that break traditional parsers.

## Architecture

The pipeline has two distinct stages:

```
PDF → Images → OCR → Raw Markdown → ANALYZE + EXTRACT → JSON
       ↓        ↓                         ↓
   (Poppler) (Tesseract)           (User Schema)
                                   Human intent +
                                   Merged cell recovery
```

### Stage 1: OCR (pdf_to_markdown.py)
Renders PDF pages as images (via Poppler), then runs Tesseract OCR with spatial table extraction to produce markdown.

**Source quality matters:** Vector-based PDFs (Excel/Word exports, digital reports) render as crisp images and produce excellent OCR results. Scanned documents are already rasterized and may contain noise, skew, or compression artifacts - consider preprocessing for best results.

### Stage 2: Extract (table_normalizer_async.py)
Converts raw markdown to structured JSON using a **user schema** with built-in OCR healing:
1. **Analyze** (fast model) - Detect table structure (hierarchical, pivot, flat)
2. **Generate** (reliable model) - Extract records matching your schema, resolving merged cells inline

Merged cell recovery is integrated directly into the generation prompt using reasoning triggers. The LLM compares each row's values against expected columns, splits cells containing multiple types (e.g. a code next to a date), and assigns each value to the matching schema field.

## Core BAML Architecture

The `TableProcessor` class uses a multi-layered concurrency strategy with semaphore-based rate limiting, designed to run efficiently on AWS Lambda.

### Semaphore-Based Rate Limiting

```python
class TableProcessor:
    def __init__(self, analyze_client, generate_client, max_concurrent_tables=10):
        self.semaphore = asyncio.Semaphore(max_concurrent_tables)
```

- **Prevents API overload**: Without semaphores, processing 100 pages launches 100 concurrent API calls and hits rate limits
- **Optimal throughput**: Keeps exactly N operations running at once (no idle time, no overload)
- **Automatic release**: Semaphore released on completion or error

| Scenario | API Calls | Result |
|----------|-----------|--------|
| Without semaphores | 100 concurrent | Rate limit errors |
| With semaphore (10) | 10 concurrent, queued | Smooth processing |

### Async File Loading

```python
async def load_markdown_file(self, file_path: Path) -> str:
    if HAS_AIOFILES:
        async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
            return await f.read()
    else:
        return await asyncio.to_thread(lambda: file_path.read_text(encoding='utf-8'))
```

- **Non-blocking**: While one file loads, other operations continue
- **Graceful fallback**: Uses `aiofiles` if available, falls back to `asyncio.to_thread`
- **Memory efficient**: Files load on-demand, not all at once

### Sync Client + asyncio.to_thread Pattern

```python
async def process_single_table(self, markdown_table, page_number, page_context, user_schema):
    async with self.semaphore:
        # Step 1: Analyze structure (fast model)
        metadata = await asyncio.to_thread(
            lambda: b.with_options(client=self.analyze_client)
                     .AnalyzeTableStructure(markdown_table, page_context)
        )

        # Step 2: Generate normalized data (reliable model)
        normalized_json = await asyncio.to_thread(
            lambda: b.with_options(client=self.generate_client)
                     .GenerateNormalizedTable(markdown_table, metadata, user_schema)
        )
```

- **`asyncio.to_thread()`**: Runs BAML sync client in thread pool without blocking the event loop
- **`with_options(client=...)`**: Runtime model selection without redefining BAML functions
- **Semaphore protection**: Each table acquires the semaphore before making API calls
- **Error isolation**: One failed table doesn't crash the batch

### Streaming Results (FIRST_COMPLETED)

```python
async def process_markdown_files(self, file_paths, user_schema):
    tasks = {asyncio.create_task(process_single_file(fp, i)): i
             for i, fp in enumerate(file_paths, 1)}

    pending = set(tasks.keys())
    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            result = task.result()
            results.append(result)

    results.sort(key=lambda r: r.page_number)
```

- **Results stream as they complete**: No waiting for the slowest page before seeing results
- **Sorted output**: Final results ordered by page number regardless of completion order
- **Progress visibility**: Each completed page prints immediately

### TOON Format for Token Optimization

BAML's built-in `format` filter with TOON (Token-Oriented Object Notation) reduces token usage for structured data passed to LLMs:

```baml
// Metadata as compact TOON instead of verbose JSON
{{ metadata|format(type="toon", delimiter="pipe") }}

// Field definitions as tabular TOON instead of repeated objects
{{ userSchema.fields|format(type="toon", delimiter="pipe") }}
```

TOON represents arrays of objects in tabular format:
```
[3]{name,type,description,required}:
  item_code|string|Product SKU|true
  quantity|int|Units ordered|false
  total|float|Line total|false
```

This is significantly more compact than the equivalent JSON representation, reducing token usage for structured schema and metadata parameters.

### Processing Flow

```
Level 1: Files (all launched concurrently)
├── Page 1 (loads async) → process_single_table
├── Page 2 (loads async) → process_single_table
└── Page 3 (loads async) → process_single_table

Level 2: Per-table pipeline (semaphore-gated)
├── Analyze (fast model, ~2s)
└── Generate + Heal (reliable model, ~15s)

Level 3: Results (streamed as completed)
├── Page 2 completes first → printed immediately
├── Page 1 completes second → printed immediately
└── Page 3 completes last → printed, results sorted by page
```

### Performance Impact

| Approach | 3 pages | API calls | Wall time |
|----------|---------|-----------|-----------|
| Sequential sync | 3 × (analyze + generate) | 6 serial | ~100s |
| Parallel async + semaphore | 3 × (analyze + generate) | 6 concurrent | ~20s |
| + TOON format | Same | Same, fewer tokens | ~18s + lower cost |

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
4. **Schema Definition** - Define your target structure
5. **Extraction** - Analyze + Generate to normalized JSON (with merged cell recovery)
6. **Review** - Inspect and export results

## CLI Usage

### PDF to Markdown
```bash
uv run python pdf_to_markdown.py input.pdf output.md --dpi 300
```

### Extract to JSON
```bash
uv run python table_normalizer_async.py input.md output.json --schema my_schema.json
```

### List Available Models
```bash
uv run python table_normalizer_async.py --list-clients
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
├── pdf_to_markdown.py           # Stage 1: OCR
├── table_normalizer_async.py    # Stage 2: Extraction (with healing)
└── pipeline_demo.ipynb          # Interactive demo

BAML Definitions:
├── baml_src/
│   ├── table_analysis.baml      # Analysis + extraction prompts
│   └── clients.baml             # Model configuration

Configuration:
├── example_schema.json          # Sample user schema
├── pyproject.toml               # Dependencies (uv)
└── requirements.txt             # Dependencies (pip)
```

## Technical Details

### TOON Format
The extraction stage uses BAML's built-in TOON format filter to reduce token usage when passing structured metadata and schema definitions to the LLM.

### Async Parallel Processing
Multi-page documents are processed in parallel using `asyncio.to_thread` with semaphore-based rate limiting. Results stream via `asyncio.wait(FIRST_COMPLETED)` as each page completes.

### Model Selection
Default configuration uses GPT-4o-mini for analysis (fast, cheap) and GPT-4o for generation (accurate). Configure in BAML or via CLI flags.

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
- [BAML](https://github.com/BoundaryML/baml) - LLM function definitions with TOON optimization
- [pdf2image](https://github.com/Belval/pdf2image) - PDF rendering
