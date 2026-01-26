#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Example: Complete Async PDF-to-1NF Pipeline

Demonstrates parallel page processing for maximum speed.

Usage:
    python example_pipeline_async.py
"""

import json
import os
import asyncio
import time
from pathlib import Path

# Import our modules
from pdf_to_markdown import pdf_to_markdown
from table_normalizer_async import process_ocr_markdown_async, save_parallel_results


async def main():
    # Configuration
    pdf_path = "test_images/graincorp.pdf"
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    markdown_path = output_dir / "graincorp_async.md"
    json_output_path = output_dir / "graincorp_async_normalized.json"
    schema_path = "example_schema.json"

    # Check if API key is set
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️  Warning: No OPENAI_API_KEY found in environment")
        print("   Set OPENAI_API_KEY to use BAML")
        return

    print("=" * 60)
    print("Async PDF-to-1NF Pipeline Example")
    print("=" * 60)
    print()
    print("⚡ Using parallel processing for maximum speed!")
    print()

    # Step 1: Convert PDF to Markdown (synchronous)
    print(f"📄 Step 1: Converting PDF to Markdown...")
    print(f"   Input: {pdf_path}")
    print(f"   Output: {markdown_path}")

    start_ocr = time.time()
    pdf_to_markdown(pdf_path, str(markdown_path), dpi=300, lang='eng')
    ocr_time = time.time() - start_ocr

    print(f"   ✅ OCR complete in {ocr_time:.1f}s")
    print()

    # Step 2: Load user schema
    print(f"📋 Step 2: Loading schema...")
    print(f"   Schema: {schema_path}")

    with open(schema_path, 'r', encoding='utf-8') as f:
        user_schema = json.load(f)

    print(f"   ✅ Loaded schema: {user_schema['className']}")
    print(f"   Fields: {len(user_schema['fields'])}")
    print()

    # Step 3: Process all pages in parallel with BAML
    print(f"🚀 Step 3: Processing pages in parallel...")
    print()

    start_baml = time.time()

    # This processes all pages concurrently!
    results = await process_ocr_markdown_async(
        str(markdown_path),
        user_schema_json=user_schema
    )

    baml_time = time.time() - start_baml

    print()
    print(f"   ✅ BAML processing complete in {baml_time:.1f}s")
    print()

    # Step 4: Save results
    print(f"💾 Step 4: Saving results...")
    save_parallel_results(results, str(json_output_path))
    print()

    # Summary
    total_time = ocr_time + baml_time
    total_records = sum(len(r.normalized_data) for r in results)

    print("=" * 60)
    print("✅ Pipeline Complete!")
    print("=" * 60)
    print()
    print(f"Results:")
    print(f"  • Markdown:         {markdown_path}")
    print(f"  • Normalized JSON:  {json_output_path}")
    print()
    print(f"Performance:")
    print(f"  • OCR Time:         {ocr_time:.1f}s")
    print(f"  • BAML Time:        {baml_time:.1f}s (parallel)")
    print(f"  • Total Time:       {total_time:.1f}s")
    print()
    print(f"Data:")
    print(f"  • Pages Processed:  {len(results)}")
    print(f"  • Total Records:    {total_records}")
    print(f"  • Avg per Page:     {total_records / len(results):.1f}")
    print()
    print(f"Models Used:")
    print(f"  • Analysis:         gpt-4o-mini (fast classification)")
    print(f"  • Normalization:    gpt-4o (accurate 1NF conversion)")
    print()
    print("=" * 60)


if __name__ == '__main__':
    asyncio.run(main())
