#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Async Table Normalizer - Convert OCR'd markdown tables to 1NF in parallel

Uses BAML sync client with asyncio.to_thread for parallel processing.
Semaphore-based rate limiting prevents API throttling.
"""

import json
import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from baml_client import b
from baml_client.types import TableMetadata, UserSchema, FieldDefinition
from baml_client.inlinedbaml import get_baml_files

try:
    import aiofiles
    HAS_AIOFILES = True
except ImportError:
    HAS_AIOFILES = False


# Default clients (can be overridden at runtime)
DEFAULT_ANALYZE_CLIENT = "CustomGPT4oMini"
DEFAULT_GENERATE_CLIENT = "CustomGPT4o"


# =============================================================================
# BAML CLIENT SPEC UTILITIES
# =============================================================================

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
    """
    baml_files = get_baml_files()
    clients_baml = baml_files.get("clients.baml", "")

    pattern = rf'client<llm>\s+{re.escape(client_name)}\s*\{{'
    match = re.search(pattern, clients_baml)

    if not match:
        return {"name": client_name, "error": "Client not found in BAML definitions"}

    brace_start = match.end() - 1
    block_content = _extract_brace_block(clients_baml, brace_start)

    result = {"name": client_name}

    provider_match = re.search(r'provider\s+(\S+)', block_content)
    if provider_match:
        result["provider"] = provider_match.group(1)

    retry_match = re.search(r'retry_policy\s+(\S+)', block_content)
    if retry_match:
        result["retry_policy"] = retry_match.group(1)

    options_start = re.search(r'options\s*\{', block_content)
    if options_start:
        options_brace_pos = block_content.find('{', options_start.start())
        options_content = _extract_brace_block(block_content, options_brace_pos)
        options = {}

        for line in options_content.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('//'):
                continue

            str_match = re.match(r'(\w+)\s+"([^"]*)"', line)
            if str_match:
                options[str_match.group(1)] = str_match.group(2)
                continue

            env_match = re.match(r'(\w+)\s+env\.(\w+)', line)
            if env_match:
                options[env_match.group(1)] = f"env.{env_match.group(2)}"
                continue

            num_match = re.match(r'(\w+)\s+(\d+)', line)
            if num_match:
                options[num_match.group(1)] = int(num_match.group(2))
                continue

            arr_match = re.match(r'(\w+)\s+\[([^\]]*)\]', line)
            if arr_match:
                arr_items = [item.strip() for item in arr_match.group(2).split(',')]
                options[arr_match.group(1)] = arr_items
                continue

        result["options"] = options

    return result


def get_available_clients() -> List[str]:
    """Get list of all available BAML client names."""
    baml_files = get_baml_files()
    clients_baml = baml_files.get("clients.baml", "")

    clients = []
    for line in clients_baml.split('\n'):
        line = line.strip()
        if line.startswith('//'):
            continue
        match = re.match(r'client<llm>\s+(\w+)', line)
        if match:
            clients.append(match.group(1))

    return clients


# =============================================================================
# DATA TYPES
# =============================================================================

@dataclass
class NormalizationResult:
    """Result of table normalization process"""
    page_number: int
    metadata: Optional[TableMetadata]
    schema: UserSchema
    normalized_data: List[Dict[str, Any]]
    raw_json: str


@dataclass
class ProcessingJob:
    """A single table processing job"""
    file_path: Path
    markdown_content: str
    page_number: int
    page_context: Optional[str]
    user_schema: UserSchema


def create_user_schema_from_json(schema_json: Dict[str, Any]) -> UserSchema:
    """Convert user-provided JSON schema to BAML UserSchema."""
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


def _parse_llm_json(raw_json: str) -> List[Dict[str, Any]]:
    """Parse JSON from LLM response, stripping markdown code blocks if present."""
    json_str = raw_json.strip()
    if json_str.startswith('```'):
        lines = json_str.split('\n')
        json_str = '\n'.join(lines[1:-1]) if len(lines) > 2 else json_str
        json_str = json_str.replace('```json', '').replace('```', '').strip()

    data = json.loads(json_str)
    if not isinstance(data, list):
        data = [data]
    return data


# =============================================================================
# TABLE PROCESSOR (BAML bot pattern: sync client + asyncio.to_thread)
# =============================================================================

class TableProcessor:
    def __init__(
        self,
        analyze_client: str = DEFAULT_ANALYZE_CLIENT,
        generate_client: str = DEFAULT_GENERATE_CLIENT,
        max_concurrent_tables: int = 10
    ):
        self.analyze_client = analyze_client
        self.generate_client = generate_client
        self.semaphore = asyncio.Semaphore(max_concurrent_tables)

    async def load_markdown_file(self, file_path: Path) -> str:
        """Async file loading with fallback to sync."""
        if HAS_AIOFILES:
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                return await f.read()
        else:
            return await asyncio.to_thread(
                lambda: file_path.read_text(encoding='utf-8')
            )

    async def process_single_table(
        self,
        markdown_table: str,
        page_number: int,
        page_context: Optional[str],
        user_schema: UserSchema
    ) -> NormalizationResult:
        """Process a single table with semaphore rate limiting."""
        async with self.semaphore:
            # Step 1: Analyze table structure
            print(f"[Page {page_number}] Analyzing with {self.analyze_client}...")
            metadata = await asyncio.to_thread(
                lambda: b.with_options(client=self.analyze_client).AnalyzeTableStructure(
                    markdown_table, page_context
                )
            )
            print(f"[Page {page_number}] Analysis complete: {metadata.tableType}")

            # Step 2: Generate normalized table
            print(f"[Page {page_number}] Generating with {self.generate_client}...")
            normalized_json = await asyncio.to_thread(
                lambda: b.with_options(client=self.generate_client).GenerateNormalizedTable(
                    markdown_table, metadata, user_schema
                )
            )

            # Parse JSON response
            try:
                normalized_data = _parse_llm_json(normalized_json)
                print(f"[Page {page_number}] Extracted {len(normalized_data)} records")
            except json.JSONDecodeError as e:
                print(f"[Page {page_number}] Failed to parse JSON: {e}")
                print(f"[Page {page_number}] Raw (first 500): {normalized_json[:500]}")
                normalized_data = []

            return NormalizationResult(
                page_number=page_number,
                metadata=metadata,
                schema=user_schema,
                normalized_data=normalized_data,
                raw_json=normalized_json
            )

    async def process_markdown_files(
        self,
        file_paths: List[Path],
        user_schema: UserSchema
    ) -> List[NormalizationResult]:
        """Process multiple markdown files concurrently."""

        async def process_single_file(file_path: Path, page_number: int):
            try:
                content = await self.load_markdown_file(file_path)
                return await self.process_single_table(
                    markdown_table=content,
                    page_number=page_number,
                    page_context=f"File: {file_path.name}",
                    user_schema=user_schema
                )
            except Exception as e:
                print(f"[Page {page_number}] Failed: {e}")
                return None

        # Launch all files concurrently
        tasks = {
            asyncio.create_task(
                process_single_file(Path(fp), i)
            ): i
            for i, fp in enumerate(file_paths, 1)
        }

        # Stream results as they complete (FIRST_COMPLETED)
        results = []
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
                    if result is not None:
                        results.append(result)
                        print(f"Page {page_num} complete ({len(result.normalized_data)} records)")
                except Exception as e:
                    print(f"Page {page_num} failed: {e}")

        # Sort by page number
        results.sort(key=lambda r: r.page_number)
        return results


# =============================================================================
# PUBLIC API (notebook-facing interfaces)
# =============================================================================

async def process_page_files_async(
    page_files: List[str],
    user_schema_json: Optional[Dict[str, Any]] = None,
    analyze_client: Optional[str] = None,
    generate_client: Optional[str] = None
) -> List[NormalizationResult]:
    """
    Process separate markdown files (one per page) in parallel.

    Args:
        page_files: List of paths to markdown files (one per page)
        user_schema_json: Optional user schema
        analyze_client: BAML client for analysis (default: CustomGPT4oMini)
        generate_client: BAML client for generation (default: CustomGPT4o)

    Returns:
        List of NormalizationResult, one per page
    """
    analyze_client = analyze_client or DEFAULT_ANALYZE_CLIENT
    generate_client = generate_client or DEFAULT_GENERATE_CLIENT

    if user_schema_json:
        schema = create_user_schema_from_json(user_schema_json)
        print(f"Using schema: {schema.className}")
    else:
        schema = get_default_schema()
        print(f"Using default schema: {schema.className}")

    print(f"\nProcessing {len(page_files)} pages in parallel...")
    print(f"   Analyze: {analyze_client}")
    print(f"   Generate: {generate_client}\n")

    processor = TableProcessor(
        analyze_client=analyze_client,
        generate_client=generate_client
    )

    results = await processor.process_markdown_files(
        [Path(f) for f in page_files],
        schema
    )

    print(f"\nProcessed {len(results)}/{len(page_files)} pages successfully")
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
    """
    analyze_client = analyze_client or DEFAULT_ANALYZE_CLIENT
    generate_client = generate_client or DEFAULT_GENERATE_CLIENT

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
        if result.metadata is not None:
            metadata_dict = {
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
            }
        else:
            metadata_dict = None

        output["pages"].append({
            "page_number": result.page_number,
            "metadata": metadata_dict,
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

    print(f"\nSaved to {output_path}")


# =============================================================================
# CLI
# =============================================================================

if __name__ == '__main__':
    import sys
    import argparse

    available = get_available_clients()

    parser = argparse.ArgumentParser(
        description='Async parallel table normalization for multi-page PDFs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Available BAML clients:
  {', '.join(available)}

Examples:
  python table_normalizer_async.py input.md output.json
  python table_normalizer_async.py input.md output.json --analyze-client CustomGPT4oMini --generate-client CustomGPT4o
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

    if not args.markdown_file or not args.output_file:
        parser.error("markdown_file and output_file are required")

    if args.analyze_client not in available:
        parser.error(f"Unknown analyze client: {args.analyze_client}. Available: {', '.join(available)}")
    if args.generate_client not in available:
        parser.error(f"Unknown generate client: {args.generate_client}. Available: {', '.join(available)}")

    user_schema = None
    if args.schema:
        with open(args.schema, 'r', encoding='utf-8') as f:
            user_schema = json.load(f)

    print(f"Configuration:")
    print(f"   Analyze: {args.analyze_client}")
    print(f"   Generate: {args.generate_client}")

    # Find page files or split single file
    md_path = Path(args.markdown_file)
    if md_path.is_dir():
        page_files = sorted(str(f) for f in md_path.glob("*.md"))
    else:
        page_files = [str(md_path)]

    results = asyncio.run(
        process_page_files_async(
            page_files,
            user_schema,
            analyze_client=args.analyze_client,
            generate_client=args.generate_client
        )
    )

    save_parallel_results(
        results, args.output_file,
        analyze_client=args.analyze_client,
        generate_client=args.generate_client
    )

    total_records = sum(len(r.normalized_data) for r in results)
    print(f"\nSummary:")
    print(f"   Pages: {len(results)}")
    print(f"   Records: {total_records}")
    print(f"   Avg/page: {total_records / max(len(results), 1):.1f}")
