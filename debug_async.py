#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Debug script to diagnose async processing issues
"""

import asyncio
import json
import os
from pathlib import Path
from table_normalizer_async import split_markdown_by_page, process_ocr_markdown_async

async def main():
    # Check API key
    if not os.getenv('OPENAI_API_KEY'):
        print("❌ OPENAI_API_KEY not set!")
        return

    print("✅ OPENAI_API_KEY is set")
    print()

    # Test file
    markdown_file = "output/graincorp_output.md"
    if not Path(markdown_file).exists():
        markdown_file = "output/graincorp.md"

    if not Path(markdown_file).exists():
        print(f"❌ Markdown file not found: {markdown_file}")
        return

    print(f"📄 Reading: {markdown_file}")

    # Read markdown
    with open(markdown_file, 'r', encoding='utf-8') as f:
        markdown_content = f.read()

    print(f"   Total characters: {len(markdown_content):,}")
    print(f"   Total lines: {len(markdown_content.splitlines()):,}")
    print()

    # Test splitting
    print("🔪 Testing page splitting...")
    pages = split_markdown_by_page(markdown_content)
    print(f"   Found {len(pages)} pages")

    if len(pages) == 0:
        print("   ❌ No pages found! Markdown might not have '# Page N' headers")
        print()
        print("First 500 characters of markdown:")
        print(markdown_content[:500])
        return

    for i, page in enumerate(pages, 1):
        lines = page.splitlines()
        chars = len(page)
        print(f"   Page {i}: {len(lines)} lines, {chars:,} characters")
        print(f"      First line: {lines[0][:80] if lines else '(empty)'}")

    print()
    print("📋 Testing schema...")

    schema_file = "example_schema.json"
    if Path(schema_file).exists():
        with open(schema_file, 'r') as f:
            schema = json.load(f)
        print(f"   ✅ Loaded: {schema['className']}")
        print(f"   Fields: {len(schema['fields'])}")
    else:
        schema = None
        print(f"   ⚠️  No schema file found, using default")

    print()
    print("🚀 Testing BAML processing on Page 1 only...")
    print()

    # Test the first REAL page (skip title if it's tiny)
    from table_normalizer_async import process_single_page, create_user_schema_from_json, get_default_schema

    if schema:
        user_schema = create_user_schema_from_json(schema)
    else:
        user_schema = get_default_schema()

    # Find first real page (more than 100 characters)
    test_page_idx = 0
    for i, page in enumerate(pages):
        if len(page) > 100:
            test_page_idx = i
            break

    print(f"   Testing page index {test_page_idx} (length: {len(pages[test_page_idx])} chars)")
    print()

    try:
        result = await process_single_page(
            page_number=test_page_idx + 1,
            markdown_content=pages[test_page_idx],
            page_context=f"Test - Page {test_page_idx + 1}",
            user_schema=user_schema
        )

        print()
        print(f"✅ Processing successful!")
        print(f"   Metadata:")
        print(f"      Table Type: {result.metadata.tableType}")
        print(f"      Has Headers: {result.metadata.hasHeaders}")
        print(f"      Has Subtotals: {result.metadata.hasSubtotals}")
        print(f"      Estimated Rows: {result.metadata.estimatedRows}")
        print(f"      Estimated Columns: {result.metadata.estimatedColumns}")
        print()
        print(f"   Normalized Data:")
        print(f"      Records extracted: {len(result.normalized_data)}")

        if len(result.normalized_data) == 0:
            print()
            print("⚠️  No records extracted!")
            print()
            print("Raw JSON response:")
            print(result.raw_json[:1000])
            print()
        else:
            print()
            print("First record:")
            print(json.dumps(result.normalized_data[0], indent=2))

    except Exception as e:
        print(f"❌ Error during processing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(main())
