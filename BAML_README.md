# BAML Table Normalization

Convert OCR'd markdown tables to 1NF (First Normal Form) using BAML AI.

## Overview

This pipeline uses BAML (Boundary ML) to intelligently analyze and normalize tables extracted from PDFs. It works with any table type: hierarchical, pivoted, transposed, or regular.

### Two-Step Process

1. **Analyze Table Structure** - Detect table type, headers, totals, and data flow
2. **Generate 1NF Table** - Convert to normalized records matching user schema

## Quick Start

### Prerequisites

Set up your OpenAI API key:

```bash
export OPENAI_API_KEY=your_key_here
```

**Note:** This pipeline is configured to use OpenAI GPT-5 by default. You can modify `baml_src/table_analysis.baml` to use other providers (Anthropic, Google, AWS Bedrock, etc.) if needed.

### Basic Usage

```bash
# 1. Convert PDF to markdown (OCR)
uv run python pdf_to_markdown.py test_images/graincorp.pdf output/result.md

# 2. Normalize table to 1NF
uv run python table_normalizer.py output/result.md output/normalized.json --schema example_schema.json
```

### Complete Pipeline Example

```bash
uv run python example_pipeline.py
```

This demonstrates the full workflow: PDF → Markdown → 1NF

## Custom Schemas

Define your own schema in JSON format:

```json
{
  "className": "InvoiceLineItem",
  "fields": {
    "item_code": {
      "type": "string",
      "description": "Product code",
      "required": true
    },
    "description": {
      "type": "string",
      "description": "Item description"
    },
    "quantity": {
      "type": "int",
      "description": "Quantity ordered"
    },
    "unit_price": {
      "type": "float",
      "description": "Price per unit"
    },
    "total": {
      "type": "float",
      "description": "Line total"
    }
  }
}
```

### Supported BAML Types

- `string` - Text data
- `int` - Integers
- `float` - Decimal numbers
- `bool` - True/false values
- `string[]` - Array of strings
- `int[]` - Array of integers

## Architecture

### BAML Schema (`baml_src/table_analysis.baml`)

Defines the table analysis functions and types:

- **TableType** enum: REGULAR, PIVOTED, TRANSPOSED, HIERARCHICAL, MIXED
- **DataOrientation** enum: HORIZONTAL, VERTICAL, MIXED
- **TableMetadata** class: Structure analysis results
- **AnalyzeTableStructure** function: Detects table characteristics
- **GenerateNormalizedTable** function: Converts to 1NF

### Python Wrapper (`table_normalizer.py`)

Business-agnostic Python interface:

```python
from table_normalizer import process_ocr_table

result = process_ocr_table(
    markdown_content=markdown_table,
    page_context="Page 1 of invoice",
    user_schema_json=schema
)

print(f"Table type: {result.metadata.tableType}")
print(f"Extracted {len(result.normalized_data)} records")
```

## What Gets Detected

The analyzer identifies:

- **Table Type**: Whether it's a pivot table, hierarchical, transposed, etc.
- **Header Rows**: Where column names are located (0-based indices)
- **Total Rows**: Rows containing subtotals or grand totals
- **Data Orientation**: How data flows (horizontal, vertical, mixed)
- **Structural Issues**: Merged cells, irregular layouts
- **Group Columns**: Columns with hierarchical grouping

## How Normalization Works

1. **Skip non-data rows**: Headers, totals, empty rows
2. **Carry forward values**: Fill empty cells with group values from above
3. **Type conversion**: Parse dates, numbers with commas (30,000 → 30000)
4. **Schema mapping**: Match columns to schema fields semantically
5. **1NF output**: Each row is atomic, no repeating groups

## BAML Client Configuration

The BAML client supports multiple AI providers. Edit `baml_src/clients.baml` to configure:

- **CustomSonnet4** - Anthropic Claude Sonnet 4 (default)
- **CustomGPT5** - OpenAI GPT-5
- **CustomHaiku** - Anthropic Claude Haiku (faster, cheaper)

To change the model used for table analysis:

```baml
function AnalyzeTableStructure(markdownTable: string, pageContext: string?) -> TableMetadata {
  client CustomGPT5  // Change this to use different model
  ...
}
```

## Regenerating BAML Client

After modifying BAML schema files:

```bash
baml-cli generate
```

This regenerates the Python client in `baml_client/`.

## Dependencies

BAML-specific dependencies (already in `requirements.txt`):

- `baml-py==0.218.0` - BAML Python runtime
- `pydantic>=2.12.0` - Data validation
- `typing-extensions>=4.15.0` - Type annotations

## Troubleshooting

### "No API key found"

Set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in your environment.

### "Version mismatch"

Ensure BAML components are synced:

```bash
uv add baml-py==0.218.0
baml-cli generate
```

Check versions:
- BAML CLI: `baml-cli --version`
- BAML Python: `uv pip list | grep baml-py`
- Generator config: See `baml_src/generators.baml`

### "Failed to parse JSON"

The LLM might have returned invalid JSON. Check:
- API key is valid
- Model is available
- Input markdown is well-formed

## Example Output

```json
{
  "metadata": {
    "pageNumber": 1,
    "tableType": "HIERARCHICAL",
    "dataOrientation": "HORIZONTAL",
    "hasHeaders": true,
    "hasSubtotals": true,
    "headerRowIndices": [0],
    "totalRowIndices": [2, 4, 8, 11],
    "estimatedColumns": 20,
    "estimatedRows": 84
  },
  "data": [
    {
      "port": "Mackay",
      "reference_number": "56285",
      "exporter": "GCOP",
      "vessel_name": "DODO",
      "commodity": "Chickpeas",
      "quantity_tonnes": 30000.0,
      "status": "Accepted"
    }
  ]
}
```

## Business Agnostic

This system works with **any table type**, not just shipping manifests:

- Financial statements
- Inventory reports
- Sales data
- Medical records
- Scientific data
- Invoices
- Any structured tabular data

Just provide a schema matching your domain!
