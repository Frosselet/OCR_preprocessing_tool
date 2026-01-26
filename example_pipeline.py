#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Example: Complete PDF-to-1NF Pipeline

Demonstrates the full workflow:
1. Convert PDF to markdown (OCR)
2. Analyze table structure
3. Normalize to 1NF with schema

Usage:
    python example_pipeline.py
"""

import json
import os
from pathlib import Path

# Import our modules
from pdf_to_markdown import pdf_to_markdown
from table_normalizer import process_ocr_table, save_normalized_data


def main():
    # Configuration
    pdf_path = "test_images/graincorp.pdf"
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    markdown_path = output_dir / "graincorp.md"
    json_output_path = output_dir / "graincorp_normalized.json"
    schema_path = "example_schema.json"

    # Check if API key is set
    if not os.getenv("ANTHROPIC_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        print("⚠️  Warning: No API key found in environment")
        print("   Set ANTHROPIC_API_KEY or OPENAI_API_KEY to use BAML")
        return

    print("=" * 60)
    print("PDF-to-1NF Pipeline Example")
    print("=" * 60)

    # Step 1: Convert PDF to Markdown (OCR)
    print(f"\n📄 Step 1: Converting PDF to Markdown...")
    print(f"   Input: {pdf_path}")
    print(f"   Output: {markdown_path}")

    # Generate markdown
    pdf_to_markdown(pdf_path, str(markdown_path), dpi=300, lang='eng')

    # Read the generated markdown
    with open(markdown_path, 'r', encoding='utf-8') as f:
        markdown_content = f.read()

    # Extract just the first page's table for this example
    # (In production, you'd process each page separately)
    pages = markdown_content.split("# Page ")
    if len(pages) > 1:
        first_page_md = "# Page " + pages[1].split("# Page")[0]
    else:
        first_page_md = markdown_content

    print(f"   ✓ Markdown generated ({len(markdown_content)} characters)")

    # Step 2: Load user schema
    print(f"\n📋 Step 2: Loading schema...")
    print(f"   Schema: {schema_path}")

    with open(schema_path, 'r', encoding='utf-8') as f:
        user_schema = json.load(f)

    print(f"   ✓ Loaded schema: {user_schema['className']}")
    print(f"   Fields: {', '.join(user_schema['fields'].keys())}")

    # Step 3: Analyze and normalize table
    print(f"\n🔬 Step 3: Analyzing table structure and normalizing to 1NF...")

    result = process_ocr_table(
        markdown_content=first_page_md,
        page_context="Page 1 of GrainCorp Shipping Stem",
        user_schema_json=user_schema
    )

    # Step 4: Save results
    print(f"\n💾 Step 4: Saving normalized data...")
    save_normalized_data(result, str(json_output_path))

    # Summary
    print("\n" + "=" * 60)
    print("✅ Pipeline Complete!")
    print("=" * 60)
    print(f"\nResults:")
    print(f"  • Markdown:         {markdown_path}")
    print(f"  • Normalized JSON:  {json_output_path}")
    print(f"\nTable Analysis:")
    print(f"  • Type:             {result.metadata.tableType}")
    print(f"  • Orientation:      {result.metadata.dataOrientation}")
    print(f"  • Has headers:      {result.metadata.hasHeaders}")
    print(f"  • Has subtotals:    {result.metadata.hasSubtotals}")
    print(f"  • Header rows:      {result.metadata.headerRowIndices}")
    print(f"  • Total rows:       {result.metadata.totalRowIndices}")
    print(f"  • Columns:          {result.metadata.estimatedColumns}")
    print(f"  • Data rows:        {result.metadata.estimatedRows}")
    print(f"\n  Extracted {len(result.normalized_data)} records")

    if result.metadata.notes:
        print(f"  Notes: {result.metadata.notes}")

    print(f"\nSample records (first 3):")
    for i, record in enumerate(result.normalized_data[:3], 1):
        print(f"\n  Record {i}:")
        for key, value in record.items():
            if value:  # Only show non-empty fields
                print(f"    {key}: {value}")


if __name__ == '__main__':
    main()
