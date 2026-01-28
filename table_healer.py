#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Table Healer - OCR markdown healing (step 2 in pipeline)

Pipeline architecture:
1. OCR → Raw Markdown (pdf_to_markdown.py)
2. Heal Markdown → Clean Markdown (THIS MODULE - table_healer.py)
3. Parse + Extract → JSON (table_normalizer_async.py with user schema)

This module handles step 2: fixing OCR artifacts in markdown.
- Infers table structure from OCR output
- Fixes merged cells
- Outputs clean markdown for downstream parsing

Separation of concerns:
- Healing uses INFERRED schema (from OCR)
- Parsing uses USER schema (human intent)
"""

import asyncio
import time
from typing import List, Optional, Tuple
from dataclasses import dataclass

from baml_client.async_client import b
from baml_client.types import InferredTableSchema, CleanTableData


@dataclass
class HealingResult:
    """Result of markdown healing"""
    page_number: int
    original_markdown: str
    healed_markdown: str
    inferred_schema: InferredTableSchema
    clean_data: Optional[CleanTableData]
    infer_time: float
    heal_time: float
    format_time: float
    total_time: float

    @property
    def had_merged_cells(self) -> bool:
        return self.inferred_schema.hasMergedCells

    @property
    def merge_patterns(self) -> List[str]:
        return self.inferred_schema.mergedCellPatterns or []

    @property
    def healing_notes(self) -> List[str]:
        if self.clean_data:
            return self.clean_data.healingNotes or []
        return []


async def heal_markdown(
    markdown_content: str,
    page_number: int = 1,
    infer_client: str = "CustomGPT4oMini",
    heal_client: str = "CustomGPT4o",
    format_client: str = "CustomGPT4oMini"
) -> HealingResult:
    """
    Heal OCR markdown by fixing merged cells using TOON format.

    Pipeline:
    1. InferTableSchema - Understand what the OCR produced
    2. HealToStructuredData - Fix merged cells, output CleanTableData (TOON)
    3. FormatAsCleanMarkdown - Convert back to clean markdown

    Args:
        markdown_content: Raw OCR markdown
        page_number: Page number for logging
        infer_client: Fast model for schema inference
        heal_client: Capable model for healing
        format_client: Fast model for markdown formatting

    Returns:
        HealingResult with original and healed markdown
    """
    total_start = time.time()
    clean_data = None
    heal_time = 0.0
    format_time = 0.0

    # =========================================================================
    # STEP 1: INFER TABLE SCHEMA FROM OCR
    # =========================================================================
    print(f"[Page {page_number}] Step 1: Inferring OCR structure...")
    infer_start = time.time()

    inferred_schema = await b.with_options(client=infer_client).InferTableSchema(
        markdown_content
    )

    infer_time = time.time() - infer_start

    print(f"[Page {page_number}]   Structure: {inferred_schema.expectedColumns} cols × {inferred_schema.expectedDataRows} rows")
    print(f"[Page {page_number}]   Merged cells: {inferred_schema.hasMergedCells}")

    # =========================================================================
    # STEP 2 & 3: HEAL AND FORMAT (if needed)
    # =========================================================================
    if inferred_schema.hasMergedCells:
        if inferred_schema.mergedCellPatterns:
            print(f"[Page {page_number}]   Patterns: {inferred_schema.mergedCellPatterns[:2]}")

        # Step 2: Convert to clean structured data (TOON format internally)
        print(f"[Page {page_number}] Step 2: Healing to structured data (TOON)...")
        heal_start = time.time()

        clean_data = await b.with_options(client=heal_client).HealToStructuredData(
            markdown_content,
            inferred_schema
        )

        heal_time = time.time() - heal_start
        print(f"[Page {page_number}]   Extracted: {clean_data.rowCount} rows × {clean_data.columnCount} cols")
        if clean_data.healingNotes:
            for note in clean_data.healingNotes[:2]:
                print(f"[Page {page_number}]   Fix: {note}")

        # Step 3: Format as clean markdown
        print(f"[Page {page_number}] Step 3: Formatting as markdown...")
        format_start = time.time()

        healed_markdown = await b.with_options(client=format_client).FormatAsCleanMarkdown(
            clean_data
        )

        format_time = time.time() - format_start
        print(f"[Page {page_number}] ✅ Healed in {heal_time + format_time:.1f}s")
    else:
        print(f"[Page {page_number}] ✅ No merged cells detected, skipping heal")
        healed_markdown = markdown_content

    total_time = time.time() - total_start

    return HealingResult(
        page_number=page_number,
        original_markdown=markdown_content,
        healed_markdown=healed_markdown,
        inferred_schema=inferred_schema,
        clean_data=clean_data,
        infer_time=infer_time,
        heal_time=heal_time,
        format_time=format_time,
        total_time=total_time
    )


async def heal_multiple_pages(
    pages: List[str],
    infer_client: str = "CustomGPT4oMini",
    heal_client: str = "CustomGPT4o",
    format_client: str = "CustomGPT4oMini"
) -> List[HealingResult]:
    """
    Heal multiple markdown pages with optimized parallel processing.

    Runs all inference steps in parallel first, then all healing steps
    in parallel, then all formatting steps in parallel.

    Args:
        pages: List of raw OCR markdown strings
        infer_client: Fast model for inference
        heal_client: Capable model for healing
        format_client: Fast model for formatting

    Returns:
        List of HealingResult, one per page
    """
    print(f"\n🔧 Markdown Healing Pipeline")
    print(f"   Pages: {len(pages)}")
    print(f"   Infer: {infer_client}")
    print(f"   Heal: {heal_client}")
    print(f"   Format: {format_client}")
    print()

    total_start = time.time()
    n_pages = len(pages)

    # =========================================================================
    # PHASE 1: INFER ALL SCHEMAS IN PARALLEL
    # =========================================================================
    print(f"[Phase 1] Inferring table structure for {n_pages} pages...")
    infer_start = time.time()

    async def infer_one(page_num: int, content: str):
        schema = await b.with_options(client=infer_client).InferTableSchema(content)
        return page_num, schema

    infer_tasks = [infer_one(i, page) for i, page in enumerate(pages, 1)]
    infer_results = await asyncio.gather(*infer_tasks, return_exceptions=True)

    # Collect successful inferences
    schemas = {}  # page_num -> schema
    for result in infer_results:
        if isinstance(result, Exception):
            print(f"  ❌ Inference failed: {result}")
        else:
            page_num, schema = result
            schemas[page_num] = schema
            status = "needs healing" if schema.hasMergedCells else "clean"
            print(f"  Page {page_num}: {schema.expectedColumns} cols × {schema.expectedDataRows} rows ({status})")

    infer_time = time.time() - infer_start
    print(f"  ⏱️  Inference: {infer_time:.1f}s")

    # =========================================================================
    # PHASE 2: HEAL PAGES WITH MERGED CELLS IN PARALLEL
    # =========================================================================
    pages_to_heal = [(i, pages[i-1], schemas[i]) for i in schemas if schemas[i].hasMergedCells]

    clean_data = {}  # page_num -> CleanTableData
    heal_time = 0.0

    if pages_to_heal:
        print(f"\n[Phase 2] Healing {len(pages_to_heal)} pages with merged cells...")
        heal_start = time.time()

        async def heal_one(page_num: int, content: str, schema):
            data = await b.with_options(client=heal_client).HealToStructuredData(content, schema)
            return page_num, data

        heal_tasks = [heal_one(pn, content, schema) for pn, content, schema in pages_to_heal]
        heal_results = await asyncio.gather(*heal_tasks, return_exceptions=True)

        for result in heal_results:
            if isinstance(result, Exception):
                print(f"  ❌ Healing failed: {result}")
            else:
                page_num, data = result
                clean_data[page_num] = data
                print(f"  Page {page_num}: {data.rowCount} rows × {data.columnCount} cols")
                if data.healingNotes:
                    for note in data.healingNotes[:2]:
                        print(f"    → {note}")

        heal_time = time.time() - heal_start
        print(f"  ⏱️  Healing: {heal_time:.1f}s")
    else:
        print(f"\n[Phase 2] No pages need healing - all clean!")

    # =========================================================================
    # PHASE 3: FORMAT HEALED PAGES AS MARKDOWN IN PARALLEL
    # =========================================================================
    healed_markdown = {}  # page_num -> markdown string
    format_time = 0.0

    if clean_data:
        print(f"\n[Phase 3] Formatting {len(clean_data)} healed pages...")
        format_start = time.time()

        async def format_one(page_num: int, data):
            md = await b.with_options(client=format_client).FormatAsCleanMarkdown(data)
            return page_num, md

        format_tasks = [format_one(pn, data) for pn, data in clean_data.items()]
        format_results = await asyncio.gather(*format_tasks, return_exceptions=True)

        for result in format_results:
            if isinstance(result, Exception):
                print(f"  ❌ Formatting failed: {result}")
            else:
                page_num, md = result
                healed_markdown[page_num] = md
                print(f"  Page {page_num}: {len(md):,} chars")

        format_time = time.time() - format_start
        print(f"  ⏱️  Formatting: {format_time:.1f}s")

    # =========================================================================
    # BUILD RESULTS
    # =========================================================================
    total_time = time.time() - total_start
    results = []

    for i, page in enumerate(pages, 1):
        if i not in schemas:
            continue  # Inference failed for this page

        schema = schemas[i]
        final_markdown = healed_markdown.get(i, page)  # Use healed or original
        data = clean_data.get(i, None)

        results.append(HealingResult(
            page_number=i,
            original_markdown=page,
            healed_markdown=final_markdown,
            inferred_schema=schema,
            clean_data=data,
            infer_time=infer_time / n_pages,  # Approximate per-page
            heal_time=heal_time / max(len(pages_to_heal), 1),
            format_time=format_time / max(len(clean_data), 1),
            total_time=total_time / n_pages
        ))

    # Summary
    healed_count = sum(1 for r in results if r.had_merged_cells)
    print(f"\n✅ Healed {healed_count}/{len(results)} pages | Total: {total_time:.1f}s")

    return results


def save_healed_markdown(result: HealingResult, output_path: str):
    """Save healed markdown to file."""
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(result.healed_markdown)
    print(f"💾 Saved healed markdown to {output_path}")


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Heal OCR markdown by fixing merged cells",
        epilog="""
Example:
  # Heal single file
  python table_healer.py input.md -o output_healed.md

  # Heal multiple pages
  python table_healer.py page1.md page2.md page3.md -o healed/
"""
    )
    parser.add_argument("input_files", nargs="+", help="Input markdown files")
    parser.add_argument("-o", "--output", required=True, help="Output file or directory")
    parser.add_argument("--infer-client", default="CustomGPT4oMini")
    parser.add_argument("--heal-client", default="CustomGPT4o")

    args = parser.parse_args()

    import os

    # Load pages
    pages = []
    for f in sorted(args.input_files):
        with open(f, 'r', encoding='utf-8') as fp:
            pages.append(fp.read())

    # Heal
    results = asyncio.run(
        heal_multiple_pages(pages, args.infer_client, args.heal_client)
    )

    # Save
    if len(results) == 1:
        save_healed_markdown(results[0], args.output)
    else:
        os.makedirs(args.output, exist_ok=True)
        for i, result in enumerate(results, 1):
            save_healed_markdown(result, f"{args.output}/page_{i}_healed.md")

    # Print stats
    print("\n" + "=" * 50)
    for r in results:
        status = "HEALED" if r.had_merged_cells else "clean"
        print(f"Page {r.page_number}: {status} | infer={r.infer_time:.1f}s heal={r.heal_time:.1f}s format={r.format_time:.1f}s")
