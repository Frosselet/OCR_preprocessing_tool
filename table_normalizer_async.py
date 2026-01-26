#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Async Table Normalizer - Convert OCR'd markdown tables to 1NF in parallel

Uses BAML async client for parallel processing of multiple pages.
Much faster than synchronous version.

Supports parameterized model selection and dynamic client spec capture.
"""

import json
import asyncio
import re
from datetime import datetime
from typing import Dict, List, Any, Optional, AsyncGenerator, Callable
from dataclasses import dataclass, asdict

from baml_client.async_client import b
from baml_client.types import TableMetadata, UserSchema, FieldDefinition
from baml_client.inlinedbaml import get_baml_files


# Default clients (can be overridden at runtime)
DEFAULT_ANALYZE_CLIENT = "CustomGPT4oMini"
DEFAULT_GENERATE_CLIENT = "CustomGPT4oMini"


def _extract_brace_block(text: str, start_pos: int) -> str:
    """Extract content between matching braces starting at start_pos (which should be '{')."""
    if start_pos >= len(text) or text[start_pos] != '{':
        return ""

    depth = 0
    end_pos = start_pos
    for i in range(start_pos, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                end_pos = i
                break

    return text[start_pos + 1:end_pos]


def parse_baml_client_spec(client_name: str) -> Dict[str, Any]:
    """
    Parse BAML client definition dynamically from the inlined BAML source.

    Returns a dict with client configuration including provider, options, retry_policy, etc.
    This adapts to whatever attributes are defined in the BAML client.
    """
    baml_files = get_baml_files()
    clients_baml = baml_files.get("clients.baml", "")

    # Find the start of the client definition
    pattern = rf'client<llm>\s+{re.escape(client_name)}\s*\{{'
    match = re.search(pattern, clients_baml)

    if not match:
        return {"name": client_name, "error": "Client not found in BAML definitions"}

    # Extract the block content using brace matching
    brace_start = match.end() - 1  # Position of '{'
    block_content = _extract_brace_block(clients_baml, brace_start)

    result = {"name": client_name}

    # Extract provider
    provider_match = re.search(r'provider\s+(\S+)', block_content)
    if provider_match:
        result["provider"] = provider_match.group(1)

    # Extract retry_policy if present
    retry_match = re.search(r'retry_policy\s+(\S+)', block_content)
    if retry_match:
        result["retry_policy"] = retry_match.group(1)

    # Extract options block using brace matching
    options_start = re.search(r'options\s*\{', block_content)
    if options_start:
        options_brace_pos = block_content.find('{', options_start.start())
        options_content = _extract_brace_block(block_content, options_brace_pos)
        options = {}

        # Parse each option line dynamically
        for line in options_content.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('//'):
                continue

            # Match: key "string_value"
            str_match = re.match(r'(\w+)\s+"([^"]*)"', line)
            if str_match:
                options[str_match.group(1)] = str_match.group(2)
                continue

            # Match: key env.VAR_NAME (redact actual value for security)
            env_match = re.match(r'(\w+)\s+env\.(\w+)', line)
            if env_match:
                options[env_match.group(1)] = f"env.{env_match.group(2)}"
                continue

            # Match: key numeric_value
            num_match = re.match(r'(\w+)\s+(\d+)', line)
            if num_match:
                options[num_match.group(1)] = int(num_match.group(2))
                continue

            # Match: key [array]
            arr_match = re.match(r'(\w+)\s+\[([^\]]*)\]', line)
            if arr_match:
                arr_items = [item.strip() for item in arr_match.group(2).split(',')]
                options[arr_match.group(1)] = arr_items
                continue

        result["options"] = options

    return result


def get_available_clients() -> List[str]:
    """
    Get list of all available BAML client names.
    """
    baml_files = get_baml_files()
    clients_baml = baml_files.get("clients.baml", "")

    # Find all client<llm> definitions (excluding commented ones)
    clients = []
    for line in clients_baml.split('\n'):
        line = line.strip()
        if line.startswith('//'):
            continue
        match = re.match(r'client<llm>\s+(\w+)', line)
        if match:
            clients.append(match.group(1))

    return clients


@dataclass
class NormalizationResult:
    """Result of table normalization process"""
    page_number: int
    metadata: TableMetadata
    schema: UserSchema
    normalized_data: List[Dict[str, Any]]
    raw_json: str


def create_user_schema_from_json(schema_json: Dict[str, Any]) -> UserSchema:
    """
    Convert user-provided JSON schema to BAML UserSchema.

    Synchronous - no I/O needed, just data transformation.
    """
    fields = []
    for field_name, field_config in schema_json.get("fields", {}).items():
        fields.append(FieldDefinition(
            name=field_name,
            type=field_config.get("type", "string"),
            description=field_config.get("description"),
            required=field_config.get("required", False)
        ))

    return UserSchema(
        className=schema_json.get("className", "ExtractedRecord"),
        fields=fields
    )


def get_default_schema() -> UserSchema:
    """Default schema for when user doesn't provide one."""
    return UserSchema(
        className="GenericRecord",
        fields=[
            FieldDefinition(
                name="data",
                type="string",
                description="Generic data field",
                required=False
            )
        ]
    )


async def process_single_page(
    page_number: int,
    markdown_content: str,
    page_context: Optional[str] = None,
    user_schema: Optional[UserSchema] = None,
    on_analysis_complete: Optional[callable] = None,
    analyze_client: Optional[str] = None,
    generate_client: Optional[str] = None
) -> NormalizationResult:
    """
    Process a single page asynchronously.

    Uses async BAML client for parallel processing.
    Analysis starts immediately, generation follows as soon as metadata is ready.

    Args:
        page_number: Page number for tracking
        markdown_content: Markdown table content
        page_context: Optional context string
        user_schema: Schema to use for normalization
        on_analysis_complete: Optional callback when analysis finishes
        analyze_client: BAML client name for analysis (default: CustomGPT4oMini)
        generate_client: BAML client name for generation (default: CustomGPT4oMini)
    """
    # Use defaults if not specified
    analyze_client = analyze_client or DEFAULT_ANALYZE_CLIENT
    generate_client = generate_client or DEFAULT_GENERATE_CLIENT

    print(f"[Page {page_number}] Starting analysis with {analyze_client}...")

    # Prepare schema (synchronous, but yield control)
    if user_schema is None:
        user_schema = get_default_schema()

    # Start analysis immediately (async) - this is the first LLM call
    # Use with_options to specify the client at runtime
    metadata = await b.with_options(client=analyze_client).AnalyzeTableStructure(
        markdown_content, page_context
    )

    print(f"[Page {page_number}] Analysis complete: {metadata.tableType}")

    # Notify callback if provided (useful for streaming updates)
    if on_analysis_complete:
        on_analysis_complete(page_number, metadata)

    print(f"[Page {page_number}] Starting 1NF generation with {generate_client}...")

    # Start generation IMMEDIATELY after analysis - no waiting
    # This is the key optimization: generation starts as soon as metadata is available
    normalized_json = await b.with_options(client=generate_client).GenerateNormalizedTable(
        markdown_content,
        metadata,
        user_schema
    )

    # Parse JSON result (strip markdown code blocks if present)
    try:
        # Remove markdown code blocks (```json ... ```)
        json_str = normalized_json.strip()
        if json_str.startswith('```'):
            # Find the actual JSON content between code blocks
            lines = json_str.split('\n')
            # Skip first line (```json) and last line (```)
            json_str = '\n'.join(lines[1:-1]) if len(lines) > 2 else json_str
            # Also handle case where ``` is on same line
            json_str = json_str.replace('```json', '').replace('```', '').strip()

        normalized_data = json.loads(json_str)
        if not isinstance(normalized_data, list):
            normalized_data = [normalized_data]
        print(f"[Page {page_number}] Extracted {len(normalized_data)} records")

        if len(normalized_data) == 0:
            print(f"[Page {page_number}] ⚠️  Empty array returned by LLM")

    except json.JSONDecodeError as e:
        print(f"[Page {page_number}] ❌ Failed to parse JSON: {e}")
        print(f"[Page {page_number}] Raw response (first 500 chars):")
        print(normalized_json[:500])
        normalized_data = []

    return NormalizationResult(
        page_number=page_number,
        metadata=metadata,
        schema=user_schema,
        normalized_data=normalized_data,
        raw_json=normalized_json
    )


async def process_multiple_pages_parallel(
    pages: List[str],
    user_schema_json: Optional[Dict[str, Any]] = None,
    base_context: str = "PDF document",
    analyze_client: Optional[str] = None,
    generate_client: Optional[str] = None
) -> List[NormalizationResult]:
    """
    Process multiple pages in parallel using async BAML.

    This is the main entry point for parallel processing.

    Args:
        pages: List of markdown content strings (one per page)
        user_schema_json: Optional user-provided schema
        base_context: Base description for page context
        analyze_client: BAML client name for analysis (default: CustomGPT4oMini)
        generate_client: BAML client name for generation (default: CustomGPT4oMini)

    Returns:
        List of NormalizationResult, one per page
    """
    # Use defaults if not specified
    analyze_client = analyze_client or DEFAULT_ANALYZE_CLIENT
    generate_client = generate_client or DEFAULT_GENERATE_CLIENT

    # Prepare schema once (shared across all pages)
    if user_schema_json:
        schema = create_user_schema_from_json(user_schema_json)
        print(f"Using user-provided schema: {schema.className}")
    else:
        schema = get_default_schema()
        print(f"Using default schema: {schema.className}")

    print(f"\n🚀 Processing {len(pages)} pages in parallel...")
    print(f"   Analyze client: {analyze_client}")
    print(f"   Generate client: {generate_client}\n")

    # Create tasks for all pages
    tasks = []
    for i, page_content in enumerate(pages, 1):
        page_context = f"{base_context} - Page {i}"
        task = asyncio.create_task(
            process_single_page(
                i, page_content, page_context, schema,
                analyze_client=analyze_client,
                generate_client=generate_client
            )
        )
        tasks.append(task)

    # Wait for all pages to complete
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Handle any exceptions
    successful_results = []
    for i, result in enumerate(results, 1):
        if isinstance(result, Exception):
            print(f"❌ Page {i} failed: {result}")
        else:
            successful_results.append(result)
            print(f"✅ Page {i} complete: {len(result.normalized_data)} records")

    print(f"\n✅ Processed {len(successful_results)}/{len(pages)} pages successfully")

    return successful_results


async def process_pages_streaming(
    pages: List[str],
    user_schema_json: Optional[Dict[str, Any]] = None,
    base_context: str = "PDF document",
    analyze_client: Optional[str] = None,
    generate_client: Optional[str] = None
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Process pages in parallel with streaming results.

    Yields results as each page completes, so you can start using
    results before all pages are done.

    Args:
        pages: List of markdown content strings (one per page)
        user_schema_json: Optional user-provided schema
        base_context: Base description for page context
        analyze_client: BAML client name for analysis (default: CustomGPT4oMini)
        generate_client: BAML client name for generation (default: CustomGPT4oMini)

    Yields:
        Dict with:
        - type: "schema_ready", "page_complete", or "all_complete"
        - For page_complete: page_number, result
        - For all_complete: total_pages, successful_count
    """
    # Use defaults if not specified
    analyze_client = analyze_client or DEFAULT_ANALYZE_CLIENT
    generate_client = generate_client or DEFAULT_GENERATE_CLIENT

    # Prepare schema once
    if user_schema_json:
        schema = create_user_schema_from_json(user_schema_json)
    else:
        schema = get_default_schema()

    yield {"type": "schema_ready", "schema": schema}

    print(f"\n🚀 Processing {len(pages)} pages (streaming results)...")
    print(f"   Analyze client: {analyze_client}")
    print(f"   Generate client: {generate_client}\n")

    # Create tasks for all pages - they run in parallel
    tasks = {}
    for i, page_content in enumerate(pages, 1):
        page_context = f"{base_context} - Page {i}"
        task = asyncio.create_task(
            process_single_page(
                i, page_content, page_context, schema,
                analyze_client=analyze_client,
                generate_client=generate_client
            )
        )
        tasks[task] = i

    # Yield results as they complete (first-finished order)
    successful_count = 0
    pending = set(tasks.keys())

    while pending:
        done, pending = await asyncio.wait(
            pending,
            return_when=asyncio.FIRST_COMPLETED
        )

        for task in done:
            page_num = tasks[task]
            try:
                result = task.result()
                successful_count += 1
                yield {
                    "type": "page_complete",
                    "page_number": page_num,
                    "result": result,
                    "records_count": len(result.normalized_data)
                }
                print(f"✅ Page {page_num} complete: {len(result.normalized_data)} records")
            except Exception as e:
                yield {
                    "type": "page_error",
                    "page_number": page_num,
                    "error": str(e)
                }
                print(f"❌ Page {page_num} failed: {e}")

    yield {
        "type": "all_complete",
        "total_pages": len(pages),
        "successful_count": successful_count
    }


def split_markdown_by_page(markdown_content: str) -> List[str]:
    """
    Split multi-page markdown into individual pages.

    Args:
        markdown_content: Full markdown with multiple pages

    Returns:
        List of markdown strings, one per page
    """
    import re

    # Split by "# Page N" headers (where N is a number)
    pages = []
    current_page = []

    for line in markdown_content.split('\n'):
        # Check if line is "# Page N" (not just any header starting with #)
        if re.match(r'^#\s+Page\s+\d+', line.strip(), re.IGNORECASE):
            # Start of new page
            if current_page:
                page_content = '\n'.join(current_page)
                # Only add non-empty pages
                if page_content.strip():
                    pages.append(page_content)
            current_page = [line]
        else:
            current_page.append(line)

    # Add last page
    if current_page:
        page_content = '\n'.join(current_page)
        if page_content.strip():
            pages.append(page_content)

    # If no pages found (no "# Page N" headers), treat entire content as one page
    if not pages and markdown_content.strip():
        pages = [markdown_content]

    # Filter out tiny pages (likely just titles, less than 50 chars)
    pages = [p for p in pages if len(p.strip()) > 50]

    return pages


async def process_ocr_markdown_async(
    markdown_path: str,
    user_schema_json: Optional[Dict[str, Any]] = None,
    analyze_client: Optional[str] = None,
    generate_client: Optional[str] = None
) -> List[NormalizationResult]:
    """
    Load markdown file and process all pages in parallel.

    DEPRECATED: Use process_page_files_async() with separate page files instead.

    Args:
        markdown_path: Path to markdown file
        user_schema_json: Optional user schema
        analyze_client: BAML client name for analysis (default: CustomGPT4oMini)
        generate_client: BAML client name for generation (default: CustomGPT4oMini)

    Returns:
        List of NormalizationResult, one per page
    """
    # Read markdown file
    with open(markdown_path, 'r', encoding='utf-8') as f:
        markdown_content = f.read()

    # Split into pages
    pages = split_markdown_by_page(markdown_content)
    print(f"📄 Found {len(pages)} pages in markdown file")

    # Process all pages in parallel
    results = await process_multiple_pages_parallel(
        pages,
        user_schema_json,
        base_context=markdown_path,
        analyze_client=analyze_client,
        generate_client=generate_client
    )

    return results


async def process_page_files_async(
    page_files: List[str],
    user_schema_json: Optional[Dict[str, Any]] = None,
    analyze_client: Optional[str] = None,
    generate_client: Optional[str] = None
) -> List[NormalizationResult]:
    """
    Process separate markdown files (one per page) in parallel.

    This is the preferred method - each page file is independent,
    no splitting logic required, no risk of contamination between pages.

    Args:
        page_files: List of paths to markdown files (one per page)
        user_schema_json: Optional user schema
        analyze_client: BAML client name for analysis (default: CustomGPT4oMini)
        generate_client: BAML client name for generation (default: CustomGPT4oMini)

    Returns:
        List of NormalizationResult, one per page
    """
    # Read all page contents
    pages = []
    for page_file in page_files:
        with open(page_file, 'r', encoding='utf-8') as f:
            pages.append(f.read())

    print(f"📄 Processing {len(pages)} separate page files")

    # Process all pages in parallel
    results = await process_multiple_pages_parallel(
        pages,
        user_schema_json,
        base_context="PDF pages",
        analyze_client=analyze_client,
        generate_client=generate_client
    )

    return results


def save_parallel_results(
    results: List[NormalizationResult],
    output_path: str,
    analyze_client: Optional[str] = None,
    generate_client: Optional[str] = None
):
    """
    Save results from parallel processing to JSON file.

    Includes pipeline_config with dynamically parsed BAML client specs.

    Args:
        results: List of NormalizationResult from parallel processing
        output_path: Path to save JSON file
        analyze_client: BAML client used for analysis
        generate_client: BAML client used for generation
    """
    # Use defaults if not specified
    analyze_client = analyze_client or DEFAULT_ANALYZE_CLIENT
    generate_client = generate_client or DEFAULT_GENERATE_CLIENT

    # Dynamically parse client specs from BAML definitions
    analyze_spec = parse_baml_client_spec(analyze_client)
    generate_spec = parse_baml_client_spec(generate_client)

    output = {
        "pipeline_config": {
            "processed_at": datetime.now().isoformat(),
            "analyze_client": analyze_spec,
            "generate_client": generate_spec,
            "available_clients": get_available_clients()
        },
        "total_pages": len(results),
        "total_records": sum(len(r.normalized_data) for r in results),
        "pages": []
    }

    for result in results:
        output["pages"].append({
            "page_number": result.page_number,
            "metadata": {
                "pageNumber": result.metadata.pageNumber,
                "tableType": result.metadata.tableType,
                "dataOrientation": result.metadata.dataOrientation,
                "hasHeaders": result.metadata.hasHeaders,
                "hasSubtotals": result.metadata.hasSubtotals,
                "headerRowIndices": result.metadata.headerRowIndices,
                "totalRowIndices": result.metadata.totalRowIndices,
                "estimatedColumns": result.metadata.estimatedColumns,
                "estimatedRows": result.metadata.estimatedRows,
                "irregularStructure": result.metadata.irregularStructure,
                "notes": result.metadata.notes
            },
            "schema": {
                "className": result.schema.className,
                "fields": [
                    {
                        "name": f.name,
                        "type": f.type,
                        "description": f.description,
                        "required": f.required
                    }
                    for f in result.schema.fields
                ]
            },
            "record_count": len(result.normalized_data),
            "data": result.normalized_data
        })

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n💾 Saved to {output_path}")


if __name__ == '__main__':
    import sys
    import argparse

    # Get available clients for help text
    available = get_available_clients()

    parser = argparse.ArgumentParser(
        description='Async parallel table normalization for multi-page PDFs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Available BAML clients:
  {', '.join(available)}

Examples:
  # Use default clients (CustomGPT4oMini for both)
  python table_normalizer_async.py input.md output.json

  # Use gpt-4o-mini for analysis, gpt-4o for generation
  python table_normalizer_async.py input.md output.json --analyze-client CustomGPT4oMini --generate-client CustomGPT4o

  # Use o4-mini reasoning model for generation
  python table_normalizer_async.py input.md output.json --generate-client CustomO4Mini

  # List available clients
  python table_normalizer_async.py --list-clients
"""
    )

    parser.add_argument('markdown_file', nargs='?', help='Input markdown file')
    parser.add_argument('output_file', nargs='?', help='Output JSON file')
    parser.add_argument('--schema', help='Schema JSON file (optional)')
    parser.add_argument('--analyze-client', default=DEFAULT_ANALYZE_CLIENT,
                        help=f'BAML client for analysis (default: {DEFAULT_ANALYZE_CLIENT})')
    parser.add_argument('--generate-client', default=DEFAULT_GENERATE_CLIENT,
                        help=f'BAML client for generation (default: {DEFAULT_GENERATE_CLIENT})')
    parser.add_argument('--list-clients', action='store_true',
                        help='List available BAML clients and exit')

    args = parser.parse_args()

    # Handle --list-clients
    if args.list_clients:
        print("Available BAML clients:\n")
        for client_name in available:
            spec = parse_baml_client_spec(client_name)
            provider = spec.get('provider', 'unknown')
            model = spec.get('options', {}).get('model', 'unknown')
            print(f"  {client_name}")
            print(f"    provider: {provider}")
            print(f"    model: {model}")
            print()
        sys.exit(0)

    # Validate required args if not listing clients
    if not args.markdown_file or not args.output_file:
        parser.error("markdown_file and output_file are required")

    # Validate client names
    if args.analyze_client not in available:
        parser.error(f"Unknown analyze client: {args.analyze_client}. Available: {', '.join(available)}")
    if args.generate_client not in available:
        parser.error(f"Unknown generate client: {args.generate_client}. Available: {', '.join(available)}")

    # Read schema if provided
    user_schema = None
    if args.schema:
        with open(args.schema, 'r', encoding='utf-8') as f:
            user_schema = json.load(f)

    print(f"🔧 Configuration:")
    print(f"   Analyze client: {args.analyze_client}")
    print(f"   Generate client: {args.generate_client}")

    # Run async processing
    results = asyncio.run(
        process_ocr_markdown_async(
            args.markdown_file,
            user_schema,
            analyze_client=args.analyze_client,
            generate_client=args.generate_client
        )
    )

    # Save results with client info
    save_parallel_results(
        results, args.output_file,
        analyze_client=args.analyze_client,
        generate_client=args.generate_client
    )

    # Summary
    total_records = sum(len(r.normalized_data) for r in results)
    print(f"\n📊 Summary:")
    print(f"   Pages processed: {len(results)}")
    print(f"   Total records: {total_records}")
    print(f"   Average per page: {total_records / len(results):.1f}")
