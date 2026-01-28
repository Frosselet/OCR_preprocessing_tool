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
# - Analysis: fast model for structure detection
# - Generation: reliable model for data extraction
# - Review: validates and completes any missing rows
DEFAULT_ANALYZE_CLIENT = "CustomGPT4oMini"
DEFAULT_GENERATE_CLIENT = "CustomGPT4o"
DEFAULT_REVIEW_CLIENT = "CustomGPT4o"

# Optimization settings
CHUNK_SIZE = 25  # Rows per chunk for parallel processing
DENSE_TABLE_THRESHOLD = 500  # rows × cols threshold for "dense" classification
SKIP_ANALYSIS_FOR_DENSE = True  # Skip analysis stage for dense uniform tables


# =============================================================================
# TIMING INSTRUMENTATION
# =============================================================================

import time

@dataclass
class TimingStats:
    """Timing statistics for a single page processing"""
    page_number: int
    analysis_time: float = 0.0
    generation_time: float = 0.0
    review_time: float = 0.0
    total_time: float = 0.0
    chunks_processed: int = 0
    skipped_analysis: bool = False

    def __str__(self):
        parts = [f"Page {self.page_number}:"]
        if self.skipped_analysis:
            parts.append("analysis=SKIPPED")
        else:
            parts.append(f"analysis={self.analysis_time:.1f}s")
        parts.append(f"generation={self.generation_time:.1f}s")
        parts.append(f"review={self.review_time:.1f}s")
        parts.append(f"total={self.total_time:.1f}s")
        if self.chunks_processed > 1:
            parts.append(f"({self.chunks_processed} chunks)")
        return " | ".join(parts)


# =============================================================================
# TOON FORMAT CONVERSION (Token-Optimized Object Notation)
# =============================================================================

def markdown_to_toon(markdown_table: str) -> tuple[str, List[str]]:
    """
    Convert markdown table to TOON format (pipe-delimited, more compact).

    Returns:
        tuple: (toon_string, headers_list)

    TOON format is ~30-50% fewer tokens than markdown for dense tables.
    """
    lines = markdown_table.strip().split('\n')
    toon_rows = []
    headers = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Skip markdown separator rows (|---|---|)
        if re.match(r'^\|[\s\-:]+\|$', line) or re.match(r'^\|(\s*-+\s*\|)+$', line):
            continue

        # Parse markdown row
        if line.startswith('|') and line.endswith('|'):
            cells = [cell.strip() for cell in line[1:-1].split('|')]

            # First data row becomes headers
            if not headers:
                headers = cells

            # Convert to TOON (pipe-delimited)
            toon_rows.append('|'.join(cells))

    return '\n'.join(toon_rows), headers


def estimate_table_size(markdown_content: str) -> tuple[int, int, int]:
    """
    Estimate table dimensions from markdown.

    Returns:
        tuple: (rows, cols, size=rows*cols)
    """
    lines = markdown_content.strip().split('\n')
    data_rows = 0
    max_cols = 0

    for line in lines:
        line = line.strip()
        if not line or not line.startswith('|'):
            continue

        # Skip separator rows
        if re.match(r'^\|[\s\-:]+\|$', line) or re.match(r'^\|(\s*-+\s*\|)+$', line):
            continue

        cols = line.count('|') - 1
        max_cols = max(max_cols, cols)
        data_rows += 1

    return data_rows, max_cols, data_rows * max_cols


def is_dense_uniform_table(markdown_content: str, metadata: Optional[TableMetadata] = None) -> bool:
    """
    Check if table is dense and uniform (good candidate for skipping analysis).

    Dense tables: >500 cells (rows × cols)
    Uniform: regular structure, no merged cells
    """
    rows, cols, size = estimate_table_size(markdown_content)

    if size < DENSE_TABLE_THRESHOLD:
        return False

    if metadata:
        # If we have metadata, check for irregularities
        if metadata.irregularStructure:
            return False
        if metadata.tableType in ["MIXED", "PIVOTED"]:
            return False

    return True


def get_default_metadata_for_dense_table(page_number: int, markdown_content: str) -> TableMetadata:
    """
    Create reasonable default metadata for dense uniform tables.
    Skips the analysis LLM call for faster processing.
    """
    rows, cols, _ = estimate_table_size(markdown_content)

    return TableMetadata(
        pageNumber=page_number,
        tableType="HIERARCHICAL",  # Most business tables are hierarchical
        dataOrientation="HORIZONTAL",
        hasHeaders=True,
        hasSubtotals=True,  # Assume subtotals for safety
        headerRowIndices=[0, 1],  # First two rows typically headers
        totalRowIndices=[],  # Will be detected by keywords
        estimatedColumns=cols,
        estimatedRows=rows - 2,  # Minus headers
        irregularStructure=False,
        notes="Auto-generated metadata for dense table (analysis skipped)"
    )


# =============================================================================
# TABLE CHUNKING FOR PARALLEL PROCESSING
# =============================================================================

def chunk_table_rows(markdown_content: str, chunk_size: int = CHUNK_SIZE) -> List[str]:
    """
    Split large table into smaller chunks by rows for parallel processing.

    Each chunk includes the header rows for context.

    Args:
        markdown_content: Full markdown table
        chunk_size: Number of data rows per chunk

    Returns:
        List of markdown chunks, each with headers
    """
    lines = markdown_content.strip().split('\n')

    header_lines = []
    separator_line = None
    data_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Detect separator row
        if re.match(r'^\|[\s\-:]+\|$', stripped) or re.match(r'^\|(\s*-+\s*\|)+$', stripped):
            separator_line = line
            continue

        if not stripped.startswith('|'):
            continue

        # First few rows are headers (before we have enough data rows)
        if len(data_lines) == 0 and len(header_lines) < 2:
            header_lines.append(line)
        else:
            data_lines.append(line)

    # If table is small, return as-is
    if len(data_lines) <= chunk_size:
        return [markdown_content]

    # Build header block
    header_block = '\n'.join(header_lines)
    if separator_line:
        header_block += '\n' + separator_line

    # Create chunks
    chunks = []
    for i in range(0, len(data_lines), chunk_size):
        chunk_data = data_lines[i:i + chunk_size]
        chunk = header_block + '\n' + '\n'.join(chunk_data)
        chunks.append(chunk)

    return chunks


def chunk_toon_rows(toon_content: str, chunk_size: int = CHUNK_SIZE) -> List[str]:
    """
    Split TOON-format table into chunks.
    First row (headers) is included in each chunk.
    """
    lines = toon_content.strip().split('\n')

    if len(lines) <= 1:
        return [toon_content]

    header = lines[0]
    data_lines = lines[1:]

    # If small, return as-is
    if len(data_lines) <= chunk_size:
        return [toon_content]

    # Create chunks with header
    chunks = []
    for i in range(0, len(data_lines), chunk_size):
        chunk_data = data_lines[i:i + chunk_size]
        chunk = header + '\n' + '\n'.join(chunk_data)
        chunks.append(chunk)

    return chunks


def extract_group_context(markdown_content: str) -> Optional[str]:
    """
    Extract hierarchical group context from table (fiscal year, month, etc.).
    This context is applied to all rows in chunks.
    """
    # Look for patterns like "2025/26", "Jan 26", etc. in early rows
    lines = markdown_content.strip().split('\n')[:10]

    context_parts = []

    for line in lines:
        # Look for fiscal year pattern
        fy_match = re.search(r'(\d{4}/\d{2})', line)
        if fy_match:
            context_parts.append(f"Fiscal Year: {fy_match.group(1)}")
            break

    if context_parts:
        return "; ".join(context_parts)

    return None


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
    generate_client: Optional[str] = None,
    review_client: Optional[str] = None,
    use_chunking: bool = True,
    use_toon: bool = True
) -> NormalizationResult:
    """
    Process a single page asynchronously with optimizations.

    Optimizations:
    - Skip analysis for dense uniform tables
    - TOON format for ~30-50% token reduction
    - Chunking for parallel processing of large tables
    - Timing instrumentation

    Args:
        page_number: Page number for tracking
        markdown_content: Markdown table content
        page_context: Optional context string
        user_schema: Schema to use for normalization
        on_analysis_complete: Optional callback when analysis finishes
        analyze_client: BAML client name for analysis
        generate_client: BAML client name for generation
        review_client: BAML client name for review/completion
        use_chunking: Enable parallel chunk processing for large tables
        use_toon: Enable TOON format for token efficiency
    """
    total_start = time.time()
    timing = TimingStats(page_number=page_number)

    # Use defaults if not specified
    analyze_client = analyze_client or DEFAULT_ANALYZE_CLIENT
    generate_client = generate_client or DEFAULT_GENERATE_CLIENT
    review_client = review_client or DEFAULT_REVIEW_CLIENT

    # Prepare schema
    if user_schema is None:
        user_schema = get_default_schema()

    # Estimate table size
    rows, cols, size = estimate_table_size(markdown_content)
    is_dense = size >= DENSE_TABLE_THRESHOLD

    print(f"[Page {page_number}] Table size: {rows}×{cols} = {size} cells {'(DENSE)' if is_dense else ''}")

    # ==========================================================================
    # STAGE 1: ANALYSIS (skip for dense uniform tables)
    # ==========================================================================
    analysis_start = time.time()

    if SKIP_ANALYSIS_FOR_DENSE and is_dense:
        # Skip analysis for dense tables - use defaults
        metadata = get_default_metadata_for_dense_table(page_number, markdown_content)
        timing.skipped_analysis = True
        print(f"[Page {page_number}] ⚡ Skipped analysis (dense table)")
    else:
        print(f"[Page {page_number}] Starting analysis with {analyze_client}...")
        metadata = await b.with_options(client=analyze_client).AnalyzeTableStructure(
            markdown_content, page_context
        )
        print(f"[Page {page_number}] Analysis complete: {metadata.tableType}")

    timing.analysis_time = time.time() - analysis_start

    # Notify callback if provided
    if on_analysis_complete:
        on_analysis_complete(page_number, metadata)

    # ==========================================================================
    # STAGE 2: GENERATION (with TOON format and chunking optimizations)
    # ==========================================================================
    generation_start = time.time()

    # Convert to TOON format for efficiency
    if use_toon:
        toon_content, headers = markdown_to_toon(markdown_content)
        group_context = extract_group_context(markdown_content)
    else:
        toon_content = markdown_content
        group_context = None

    # Check if we should chunk
    chunks = []
    if use_chunking and rows > CHUNK_SIZE:
        if use_toon:
            chunks = chunk_toon_rows(toon_content, CHUNK_SIZE)
        else:
            chunks = chunk_table_rows(markdown_content, CHUNK_SIZE)
        timing.chunks_processed = len(chunks)

    if len(chunks) > 1:
        # PARALLEL CHUNK PROCESSING
        print(f"[Page {page_number}] Processing {len(chunks)} chunks in parallel...")

        chunk_tasks = []
        for i, chunk in enumerate(chunks):
            task = b.with_options(client=generate_client).GenerateNormalizedTableChunk(
                chunk,
                user_schema,
                i,
                group_context
            )
            chunk_tasks.append(task)

        # Process all chunks in parallel
        chunk_results = await asyncio.gather(*chunk_tasks, return_exceptions=True)

        # Merge chunk results
        all_data = []
        for i, result in enumerate(chunk_results):
            if isinstance(result, Exception):
                print(f"[Page {page_number}] ⚠️ Chunk {i} failed: {result}")
                continue

            try:
                json_str = result.strip()
                if json_str.startswith('```'):
                    lines = json_str.split('\n')
                    json_str = '\n'.join(lines[1:-1]) if len(lines) > 2 else json_str
                    json_str = json_str.replace('```json', '').replace('```', '').strip()

                chunk_data = json.loads(json_str)
                if isinstance(chunk_data, list):
                    all_data.extend(chunk_data)
                else:
                    all_data.append(chunk_data)
            except json.JSONDecodeError as e:
                print(f"[Page {page_number}] ⚠️ Chunk {i} JSON error: {e}")

        normalized_json = json.dumps(all_data)
        initial_count = len(all_data)
        print(f"[Page {page_number}] Chunked generation complete: {initial_count} records from {len(chunks)} chunks")

    else:
        # SINGLE-PASS GENERATION (small tables or chunking disabled)
        if use_toon and is_dense:
            # Use fast TOON-optimized function
            print(f"[Page {page_number}] Starting fast TOON generation with {generate_client}...")
            normalized_json = await b.with_options(client=generate_client).GenerateNormalizedTableFast(
                toon_content,
                user_schema,
                group_context
            )
        else:
            # Standard generation
            print(f"[Page {page_number}] Starting generation with {generate_client}...")
            normalized_json = await b.with_options(client=generate_client).GenerateNormalizedTable(
                markdown_content,
                metadata,
                user_schema
            )

        # Parse to count
        initial_count = 0
        try:
            json_str = normalized_json.strip()
            if json_str.startswith('```'):
                lines = json_str.split('\n')
                json_str = '\n'.join(lines[1:-1]) if len(lines) > 2 else json_str
                json_str = json_str.replace('```json', '').replace('```', '').strip()
            initial_data = json.loads(json_str)
            if isinstance(initial_data, list):
                initial_count = len(initial_data)
        except:
            pass

        print(f"[Page {page_number}] Generation complete: {initial_count} records")

    timing.generation_time = time.time() - generation_start

    # ==========================================================================
    # STAGE 3: REVIEW (validate and complete missing rows)
    # ==========================================================================
    review_start = time.time()

    print(f"[Page {page_number}] Starting review with {review_client}...")

    reviewed_json = await b.with_options(client=review_client).ReviewAndCompleteExtraction(
        markdown_content,  # Use original markdown for review
        normalized_json,
        metadata,
        user_schema
    )

    timing.review_time = time.time() - review_start

    # ==========================================================================
    # PARSE FINAL RESULT
    # ==========================================================================
    try:
        json_str = reviewed_json.strip()
        if json_str.startswith('```'):
            lines = json_str.split('\n')
            json_str = '\n'.join(lines[1:-1]) if len(lines) > 2 else json_str
            json_str = json_str.replace('```json', '').replace('```', '').strip()

        normalized_data = json.loads(json_str)
        if not isinstance(normalized_data, list):
            normalized_data = [normalized_data]

        final_count = len(normalized_data)
        if final_count > initial_count:
            print(f"[Page {page_number}] ✅ Review added {final_count - initial_count} missing records: {final_count} total")
        else:
            print(f"[Page {page_number}] ✅ Review complete: {final_count} records")

        if len(normalized_data) == 0:
            print(f"[Page {page_number}] ⚠️ Empty array returned")

    except json.JSONDecodeError as e:
        print(f"[Page {page_number}] ❌ Failed to parse reviewed JSON: {e}")
        print(f"[Page {page_number}] Raw response (first 500 chars):")
        print(reviewed_json[:500])
        normalized_data = []

    timing.total_time = time.time() - total_start
    print(f"[Page {page_number}] ⏱️ {timing}")

    return NormalizationResult(
        page_number=page_number,
        metadata=metadata,
        schema=user_schema,
        normalized_data=normalized_data,
        raw_json=reviewed_json
    )


async def process_multiple_pages_parallel(
    pages: List[str],
    user_schema_json: Optional[Dict[str, Any]] = None,
    base_context: str = "PDF document",
    analyze_client: Optional[str] = None,
    generate_client: Optional[str] = None,
    review_client: Optional[str] = None
) -> List[NormalizationResult]:
    """
    Process multiple pages in parallel using async BAML.

    This is the main entry point for parallel processing.
    Pipeline per page: Analysis -> Generation -> Review (validate & complete)

    Args:
        pages: List of markdown content strings (one per page)
        user_schema_json: Optional user-provided schema
        base_context: Base description for page context
        analyze_client: BAML client name for analysis (default: CustomGPT4oMini)
        generate_client: BAML client name for generation (default: CustomGPT4o)
        review_client: BAML client name for review/completion (default: CustomGPT4o)

    Returns:
        List of NormalizationResult, one per page
    """
    # Use defaults if not specified
    analyze_client = analyze_client or DEFAULT_ANALYZE_CLIENT
    generate_client = generate_client or DEFAULT_GENERATE_CLIENT
    review_client = review_client or DEFAULT_REVIEW_CLIENT

    # Prepare schema once (shared across all pages)
    if user_schema_json:
        schema = create_user_schema_from_json(user_schema_json)
        print(f"Using user-provided schema: {schema.className}")
    else:
        schema = get_default_schema()
        print(f"Using default schema: {schema.className}")

    print(f"\n🚀 Processing {len(pages)} pages in parallel...")
    print(f"   Analyze client: {analyze_client}")
    print(f"   Generate client: {generate_client}")
    print(f"   Review client: {review_client}\n")

    # Create tasks for all pages
    tasks = []
    for i, page_content in enumerate(pages, 1):
        page_context = f"{base_context} - Page {i}"
        task = asyncio.create_task(
            process_single_page(
                i, page_content, page_context, schema,
                analyze_client=analyze_client,
                generate_client=generate_client,
                review_client=review_client
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
    generate_client: Optional[str] = None,
    review_client: Optional[str] = None
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
        generate_client: BAML client name for generation (default: CustomGPT4o)
        review_client: BAML client name for review/completion (default: CustomGPT4o)

    Yields:
        Dict with:
        - type: "schema_ready", "page_complete", or "all_complete"
        - For page_complete: page_number, result
        - For all_complete: total_pages, successful_count
    """
    # Use defaults if not specified
    analyze_client = analyze_client or DEFAULT_ANALYZE_CLIENT
    generate_client = generate_client or DEFAULT_GENERATE_CLIENT
    review_client = review_client or DEFAULT_REVIEW_CLIENT

    # Prepare schema once
    if user_schema_json:
        schema = create_user_schema_from_json(user_schema_json)
    else:
        schema = get_default_schema()

    yield {"type": "schema_ready", "schema": schema}

    print(f"\n🚀 Processing {len(pages)} pages (streaming results)...")
    print(f"   Analyze client: {analyze_client}")
    print(f"   Generate client: {generate_client}")
    print(f"   Review client: {review_client}\n")

    # Create tasks for all pages - they run in parallel
    tasks = {}
    for i, page_content in enumerate(pages, 1):
        page_context = f"{base_context} - Page {i}"
        task = asyncio.create_task(
            process_single_page(
                i, page_content, page_context, schema,
                analyze_client=analyze_client,
                generate_client=generate_client,
                review_client=review_client
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
    generate_client: Optional[str] = None,
    review_client: Optional[str] = None
) -> List[NormalizationResult]:
    """
    Load markdown file and process all pages in parallel.

    DEPRECATED: Use process_page_files_async() with separate page files instead.

    Args:
        markdown_path: Path to markdown file
        user_schema_json: Optional user schema
        analyze_client: BAML client name for analysis (default: CustomGPT4oMini)
        generate_client: BAML client name for generation (default: CustomGPT4o)
        review_client: BAML client name for review/completion (default: CustomGPT4o)

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
        generate_client=generate_client,
        review_client=review_client
    )

    return results


async def process_page_files_async(
    page_files: List[str],
    user_schema_json: Optional[Dict[str, Any]] = None,
    analyze_client: Optional[str] = None,
    generate_client: Optional[str] = None,
    review_client: Optional[str] = None
) -> List[NormalizationResult]:
    """
    Process separate markdown files (one per page) in parallel.

    This is the preferred method - each page file is independent,
    no splitting logic required, no risk of contamination between pages.

    Args:
        page_files: List of paths to markdown files (one per page)
        user_schema_json: Optional user schema
        analyze_client: BAML client name for analysis (default: CustomGPT4oMini)
        generate_client: BAML client name for generation (default: CustomGPT4o)
        review_client: BAML client name for review/completion (default: CustomGPT4o)

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
        generate_client=generate_client,
        review_client=review_client
    )

    return results


def save_parallel_results(
    results: List[NormalizationResult],
    output_path: str,
    analyze_client: Optional[str] = None,
    generate_client: Optional[str] = None,
    review_client: Optional[str] = None
):
    """
    Save results from parallel processing to JSON file.

    Includes pipeline_config with dynamically parsed BAML client specs.

    Args:
        results: List of NormalizationResult from parallel processing
        output_path: Path to save JSON file
        analyze_client: BAML client used for analysis
        generate_client: BAML client used for generation
        review_client: BAML client used for review/completion
    """
    # Use defaults if not specified
    analyze_client = analyze_client or DEFAULT_ANALYZE_CLIENT
    generate_client = generate_client or DEFAULT_GENERATE_CLIENT
    review_client = review_client or DEFAULT_REVIEW_CLIENT

    # Dynamically parse client specs from BAML definitions
    analyze_spec = parse_baml_client_spec(analyze_client)
    generate_spec = parse_baml_client_spec(generate_client)
    review_spec = parse_baml_client_spec(review_client)

    output = {
        "pipeline_config": {
            "processed_at": datetime.now().isoformat(),
            "analyze_client": analyze_spec,
            "generate_client": generate_spec,
            "review_client": review_spec,
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

Pipeline: Analyze -> Generate -> Review (validate & complete)

Examples:
  # Use default clients
  python table_normalizer_async.py input.md output.json

  # Custom client selection
  python table_normalizer_async.py input.md output.json \\
    --analyze-client CustomGPT4oMini \\
    --generate-client CustomGPT4o \\
    --review-client CustomGPT4o

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
    parser.add_argument('--review-client', default=DEFAULT_REVIEW_CLIENT,
                        help=f'BAML client for review/completion (default: {DEFAULT_REVIEW_CLIENT})')
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
    if args.review_client not in available:
        parser.error(f"Unknown review client: {args.review_client}. Available: {', '.join(available)}")

    # Read schema if provided
    user_schema = None
    if args.schema:
        with open(args.schema, 'r', encoding='utf-8') as f:
            user_schema = json.load(f)

    print(f"🔧 Configuration:")
    print(f"   Analyze client: {args.analyze_client}")
    print(f"   Generate client: {args.generate_client}")
    print(f"   Review client: {args.review_client}")

    # Run async processing
    results = asyncio.run(
        process_ocr_markdown_async(
            args.markdown_file,
            user_schema,
            analyze_client=args.analyze_client,
            generate_client=args.generate_client,
            review_client=args.review_client
        )
    )

    # Save results with client info
    save_parallel_results(
        results, args.output_file,
        analyze_client=args.analyze_client,
        generate_client=args.generate_client,
        review_client=args.review_client
    )

    # Summary
    total_records = sum(len(r.normalized_data) for r in results)
    print(f"\n📊 Summary:")
    print(f"   Pages processed: {len(results)}")
    print(f"   Total records: {total_records}")
    print(f"   Average per page: {total_records / len(results):.1f}")
