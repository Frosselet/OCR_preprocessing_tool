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
    heal_client: str = "CustomGPT4o"
) -> List[HealingResult]:
    """
    Heal multiple markdown pages in parallel.

    Args:
        pages: List of raw OCR markdown strings
        infer_client: Fast model for inference
        heal_client: Capable model for healing

    Returns:
        List of HealingResult, one per page
    """
    print(f"\n🔧 Markdown Healing Pipeline")
    print(f"   Pages: {len(pages)}")
    print(f"   Infer: {infer_client}")
    print(f"   Heal: {heal_client}")
    print()

    tasks = [
        heal_markdown(page, i, infer_client, heal_client)
        for i, page in enumerate(pages, 1)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Handle errors
    final_results = []
    for i, result in enumerate(results, 1):
        if isinstance(result, Exception):
            print(f"❌ Page {i} failed: {result}")
        else:
            final_results.append(result)

    # Summary
    healed_count = sum(1 for r in final_results if r.had_merged_cells)
    print(f"\n✅ Healed {healed_count}/{len(final_results)} pages with merged cells")

    return final_results


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
