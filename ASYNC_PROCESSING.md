# Async Parallel Processing Guide

## Performance Improvements

The async version provides **significant speed improvements** for multi-page documents:

### Speed Comparison

**Synchronous (old):**
```
Page 1: 15s (analysis) + 20s (generation) = 35s
Page 2: 15s (analysis) + 20s (generation) = 35s
Page 3: 15s (analysis) + 20s (generation) = 35s
Total: 105 seconds
```

**Async Parallel (new):**
```
All 3 pages process concurrently:
Max(Page 1, Page 2, Page 3) = ~35-40s total
Speedup: ~3x faster for 3 pages!
```

### Models Used

- **Analysis (gpt-4o-mini):** Fast, cheap table classification
- **Normalization (gpt-4o):** Accurate 1NF conversion

This tiered approach optimizes cost and speed.

## Usage

### Command Line (Recommended)

```bash
# Process multi-page PDF in parallel
python example_pipeline_async.py
```

Output:
```
📄 Step 1: Converting PDF to Markdown...
   ✅ OCR complete in 12.3s

📋 Step 2: Loading schema...
   ✅ Loaded schema: ShippingRecord

🚀 Step 3: Processing pages in parallel...

[Page 1] Starting analysis...
[Page 2] Starting analysis...
[Page 3] Starting analysis...
[Page 1] Analysis complete: HIERARCHICAL
[Page 1] Starting 1NF generation...
[Page 2] Analysis complete: HIERARCHICAL
[Page 2] Starting 1NF generation...
[Page 3] Analysis complete: HIERARCHICAL
[Page 3] Starting 1NF generation...
[Page 1] Extracted 84 records
✅ Page 1 complete: 84 records
[Page 2] Extracted 76 records
✅ Page 2 complete: 76 records
[Page 3] Extracted 12 records
✅ Page 3 complete: 12 records

✅ Processed 3/3 pages successfully
✅ BAML processing complete in 28.4s

Performance:
  • OCR Time:         12.3s
  • BAML Time:        28.4s (parallel)
  • Total Time:       40.7s

Speedup vs sequential: ~2.6x faster!
```

### Programmatic Usage

```python
import asyncio
from table_normalizer_async import process_ocr_markdown_async, save_parallel_results

async def main():
    # Process all pages in parallel
    results = await process_ocr_markdown_async(
        "output/document.md",
        user_schema_json={
            "className": "Invoice",
            "fields": {
                "item": {"type": "string"},
                "amount": {"type": "float"}
            }
        }
    )

    # Save results
    save_parallel_results(results, "output/normalized.json")

    # Access individual page results
    for result in results:
        print(f"Page {result.page_number}: {len(result.normalized_data)} records")
        print(f"  Table type: {result.metadata.tableType}")

# Run
asyncio.run(main())
```

### Jupyter Notebook

In a notebook cell:

```python
import asyncio
from table_normalizer_async import process_ocr_markdown_async, save_parallel_results

# Load schema
import json
with open('example_schema.json') as f:
    schema = json.load(f)

# Process pages in parallel
results = await process_ocr_markdown_async(
    str(markdown_output),
    user_schema_json=schema
)

# Display results
for result in results:
    print(f"Page {result.page_number}: {result.metadata.tableType}")
    print(f"  Records: {len(result.normalized_data)}")

# Save
save_parallel_results(results, str(json_output))
```

**Note:** Jupyter notebooks support top-level `await` automatically!

## How It Works

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    PDF to Markdown (sync)                   │
│                                                             │
│  pdf2image → Tesseract OCR → Spatial Extraction → MD       │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│              Split Markdown by Page (sync)                  │
│                                                             │
│  "# Page 1..." → ["Page 1", "Page 2", "Page 3"]           │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│          Parallel Page Processing (async)                   │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │   Page 1    │  │   Page 2    │  │   Page 3    │        │
│  │             │  │             │  │             │        │
│  │ Analysis    │  │ Analysis    │  │ Analysis    │        │
│  │ (4o-mini)   │  │ (4o-mini)   │  │ (4o-mini)   │        │
│  │     ↓       │  │     ↓       │  │     ↓       │        │
│  │ 1NF Gen     │  │ 1NF Gen     │  │ 1NF Gen     │        │
│  │ (gpt-4o)    │  │ (gpt-4o)    │  │ (gpt-4o)    │        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
│         ↓                ↓                ↓                │
│  [Result 1]       [Result 2]       [Result 3]              │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│              Combine & Save Results (sync)                  │
│                                                             │
│  {pages: [page1_data, page2_data, page3_data]}            │
└─────────────────────────────────────────────────────────────┘
```

### Key Optimizations

1. **Concurrent API Calls**
   - All pages analyzed simultaneously
   - Each page's generation starts immediately after its analysis
   - Maximum parallelism within API rate limits

2. **Tiered Model Usage**
   - gpt-4o-mini for quick classification (cheaper, faster)
   - gpt-4o for detailed normalization (better accuracy)

3. **Memory Efficient**
   - Pages processed independently
   - Results streamed, not buffered
   - Scales to large documents

## Output Format

The async version outputs JSON with this structure:

```json
{
  "total_pages": 3,
  "pages": [
    {
      "page_number": 1,
      "metadata": {
        "pageNumber": 1,
        "tableType": "HIERARCHICAL",
        "dataOrientation": "HORIZONTAL",
        "hasHeaders": true,
        "hasSubtotals": true,
        "headerRowIndices": [0],
        "totalRowIndices": [2, 4, 8],
        "estimatedColumns": 20,
        "estimatedRows": 84
      },
      "schema": { /* field definitions */ },
      "record_count": 84,
      "data": [
        { /* record 1 */ },
        { /* record 2 */ },
        /* ... */
      ]
    },
    {
      "page_number": 2,
      /* ... page 2 data ... */
    },
    {
      "page_number": 3,
      /* ... page 3 data ... */
    }
  ]
}
```

Each page's data is self-contained for easy processing.

## Migration from Sync Version

### Old Code (Synchronous)

```python
from table_normalizer import process_ocr_table, save_normalized_data

# Read markdown
with open('output.md') as f:
    markdown = f.read()

# Process first page only
first_page = markdown.split('# Page ')[1]
result = process_ocr_table(first_page, "Page 1", schema)

# Save
save_normalized_data(result, 'output.json')
```

### New Code (Async Parallel)

```python
from table_normalizer_async import process_ocr_markdown_async, save_parallel_results

# Process ALL pages in parallel
results = await process_ocr_markdown_async('output.md', schema)

# Save all pages
save_parallel_results(results, 'output.json')
```

**Benefits:**
- Processes all pages, not just first
- Runs in parallel, much faster
- Single function call
- Better error handling

## Performance Tips

### 1. Process Pages in Batches (Very Large PDFs)

For 100+ page documents, process in batches to avoid rate limits:

```python
async def process_in_batches(pages, schema, batch_size=10):
    results = []
    for i in range(0, len(pages), batch_size):
        batch = pages[i:i+batch_size]
        batch_results = await process_multiple_pages_parallel(batch, schema)
        results.extend(batch_results)
        await asyncio.sleep(1)  # Rate limit pause
    return results
```

### 2. Use Rate Limiting

OpenAI has rate limits. For production:

```python
from asyncio import Semaphore

# Limit concurrent requests
semaphore = Semaphore(5)  # Max 5 concurrent

async def process_with_limit(page, schema):
    async with semaphore:
        return await process_single_page(page, schema)
```

### 3. Monitor Costs

```python
# Rough cost estimation
pages = 10
cost_per_analysis = 0.0001  # gpt-4o-mini
cost_per_generation = 0.003  # gpt-4o

total_cost = pages * (cost_per_analysis + cost_per_generation)
print(f"Estimated cost: ${total_cost:.4f}")
```

## Troubleshooting

### "Event loop is already running" (Jupyter)

**Problem:** Jupyter has its own event loop

**Solution:** Use top-level await:
```python
# Don't use: asyncio.run(process_ocr_markdown_async(...))
# Do use:
results = await process_ocr_markdown_async(...)
```

### Rate Limit Errors

**Problem:** Too many concurrent requests

**Solution:** Reduce parallelism:
```python
# Process fewer pages at once
await process_in_batches(pages, schema, batch_size=3)
```

### Memory Issues

**Problem:** Processing too many large pages

**Solution:** Stream results:
```python
async for result in process_pages_streaming(pages, schema):
    # Process each result immediately
    save_page(result)
    # Don't accumulate in memory
```

## Comparison Table

| Feature | Sync Version | Async Version |
|---------|-------------|---------------|
| Speed (3 pages) | ~105s | ~40s |
| Parallelism | No | Yes |
| Memory | Low | Low |
| API Calls | Sequential | Concurrent |
| Error Handling | Per-page | Per-page + batch |
| Use Case | Single page | Multi-page |
| Complexity | Simple | Moderate |

## Summary

✅ **Use async version for:**
- Multi-page PDFs (2+ pages)
- Production pipelines
- Batch processing
- When speed matters

✅ **Use sync version for:**
- Single page documents
- Quick testing
- Simpler code
- Learning/debugging

The async version is **production-ready** and scales to hundreds of pages!
