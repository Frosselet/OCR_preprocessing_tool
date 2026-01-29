#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Async Row Normalizer - Line-by-line table processing

Each markdown table line is parsed independently by a fast model in parallel,
then combined into the final JSON. More reliable for large tables (no row
skipping), faster, and cheaper than whole-page generation.

Pipeline:
  markdown -> Analyze (1 call) -> ParseLine x N (parallel) -> Combine (1 call) -> JSON
"""

import json
import asyncio
from pathlib import Path
from typing import Dict, List, Any, Optional

from baml_client import b
from baml_client.types import UserSchema, ParsedTableRow

from table_normalizer_async import (
    NormalizationResult,
    create_user_schema_from_json,
    get_default_schema,
    parse_baml_client_spec,
    get_available_clients,
    save_parallel_results,
    _parse_llm_json,
    DEFAULT_ANALYZE_CLIENT,
)

try:
    import aiofiles
    HAS_AIOFILES = True
except ImportError:
    HAS_AIOFILES = False


# Defaults for line-by-line processing
DEFAULT_LINE_CLIENT = "CustomGPT5Mini"
DEFAULT_LINE_CONCURRENCY = 100
DEFAULT_COMBINE_CLIENT = "CustomGPT5Mini"


# =============================================================================
# HELPERS
# =============================================================================

def _extract_table_lines(markdown: str) -> List[str]:
    """Extract individual lines from a markdown table, preserving pipe-delimited structure."""
    lines = []
    for line in markdown.split('\n'):
        stripped = line.strip()
        if stripped and '|' in stripped:
            lines.append(stripped)
        elif stripped:
            # Non-pipe lines (titles, notes) are still relevant
            lines.append(stripped)
    return lines


def _is_separator_line(line: str) -> bool:
    """Check if a line is a markdown table separator (e.g., |---|---|---|)."""
    cleaned = line.replace('|', '').replace('-', '').replace(':', '').replace(' ', '').replace('=', '')
    return len(cleaned) == 0 and '-' in line


def _extract_column_info_from_schema(user_schema: UserSchema) -> tuple:
    """Extract column names and field types from a UserSchema."""
    column_names = [f.name for f in user_schema.fields]
    field_types = [f.type for f in user_schema.fields]
    return column_names, field_types


# =============================================================================
# ROW PROCESSOR
# =============================================================================

class RowProcessor:
    """Processes markdown tables line-by-line with parallel LLM calls."""

    def __init__(
        self,
        analyze_client: str = DEFAULT_ANALYZE_CLIENT,
        line_client: str = DEFAULT_LINE_CLIENT,
        combine_client: str = DEFAULT_COMBINE_CLIENT,
        max_concurrent_lines: int = DEFAULT_LINE_CONCURRENCY,
    ):
        self.analyze_client = analyze_client
        self.line_client = line_client
        self.combine_client = combine_client
        self.line_semaphore = asyncio.Semaphore(max_concurrent_lines)

    async def _parse_single_line(
        self,
        line: str,
        row_index: int,
        expected_columns: int,
        column_names: List[str],
        field_types: List[str],
    ) -> Optional[ParsedTableRow]:
        """Parse one table line via LLM, with semaphore rate limiting."""
        async with self.line_semaphore:
            try:
                result = await asyncio.to_thread(
                    lambda: b.with_options(client=self.line_client).ParseSingleTableLine(
                        markdownLine=line,
                        rowIndex=row_index,
                        expectedColumns=expected_columns,
                        columnNames=column_names,
                        fieldTypes=field_types,
                    )
                )
                return result
            except Exception as e:
                print(f"  [Line {row_index}] Parse failed: {e}")
                return None

    async def process_table_line_by_line(
        self,
        markdown_table: str,
        page_number: int,
        page_context: Optional[str],
        user_schema: UserSchema,
    ) -> NormalizationResult:
        """
        Process a markdown table line-by-line:
        1. Analyze structure (1 call)
        2. Parse each line in parallel (N calls)
        3. Combine parsed rows into JSON (1 call)
        """
        # Step 1: Analyze table structure
        print(f"[Page {page_number}] Analyzing with {self.analyze_client}...")
        metadata = await asyncio.to_thread(
            lambda: b.with_options(client=self.analyze_client).AnalyzeTableStructure(
                markdown_table, page_context
            )
        )
        print(f"[Page {page_number}] Analysis complete: {metadata.tableType}")

        # Extract lines and column info
        lines = _extract_table_lines(markdown_table)
        column_names, field_types = _extract_column_info_from_schema(user_schema)
        expected_columns = len(column_names)

        # Filter out obvious separator lines locally (no LLM needed)
        lines_to_parse = []
        for idx, line in enumerate(lines):
            if _is_separator_line(line):
                continue
            lines_to_parse.append((idx, line))

        print(f"[Page {page_number}] Parsing {len(lines_to_parse)} lines (concurrency={self.line_semaphore._value})...")

        # Step 2: Parse all lines in parallel
        tasks = {
            asyncio.create_task(
                self._parse_single_line(line, idx, expected_columns, column_names, field_types)
            ): idx
            for idx, line in lines_to_parse
        }

        parsed_rows: List[ParsedTableRow] = []
        pending = set(tasks.keys())
        completed_count = 0

        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                completed_count += 1
                try:
                    result = task.result()
                    if result is not None:
                        parsed_rows.append(result)
                except Exception as e:
                    row_idx = tasks[task]
                    print(f"  [Page {page_number}, Line {row_idx}] Error: {e}")

            # Progress update every 25%
            if completed_count % max(1, len(lines_to_parse) // 4) == 0:
                print(f"  [Page {page_number}] {completed_count}/{len(lines_to_parse)} lines parsed")

        # Sort by row index for correct ordering
        parsed_rows.sort(key=lambda r: r.rowIndex)
        print(f"[Page {page_number}] Parsed {len(parsed_rows)} rows, combining...")

        # Step 3: Combine parsed rows into final JSON
        combined_json = await asyncio.to_thread(
            lambda: b.with_options(client=self.combine_client).CombineParsedRows(
                parsedRows=parsed_rows,
                columnNames=column_names,
                userSchema=user_schema,
            )
        )

        # Parse JSON response
        try:
            normalized_data = _parse_llm_json(combined_json)
            print(f"[Page {page_number}] Extracted {len(normalized_data)} records (line-by-line)")
        except json.JSONDecodeError as e:
            print(f"[Page {page_number}] Failed to parse combined JSON: {e}")
            print(f"[Page {page_number}] Raw (first 500): {combined_json[:500]}")
            normalized_data = []

        return NormalizationResult(
            page_number=page_number,
            metadata=metadata,
            schema=user_schema,
            normalized_data=normalized_data,
            raw_json=combined_json,
        )

    async def process_markdown_files(
        self,
        file_paths: List[Path],
        user_schema: UserSchema,
    ) -> List[NormalizationResult]:
        """Process multiple markdown files using line-by-line strategy."""

        async def process_single_file(file_path: Path, page_number: int):
            try:
                if HAS_AIOFILES:
                    async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                        content = await f.read()
                else:
                    content = await asyncio.to_thread(
                        lambda: file_path.read_text(encoding='utf-8')
                    )
                return await self.process_table_line_by_line(
                    markdown_table=content,
                    page_number=page_number,
                    page_context=f"File: {file_path.name}",
                    user_schema=user_schema,
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

        results = []
        pending = set(tasks.keys())

        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                page_num = tasks[task]
                try:
                    result = task.result()
                    if result is not None:
                        results.append(result)
                        print(f"Page {page_num} complete ({len(result.normalized_data)} records, line-by-line)")
                except Exception as e:
                    print(f"Page {page_num} failed: {e}")

        results.sort(key=lambda r: r.page_number)
        return results


# =============================================================================
# PUBLIC API
# =============================================================================

async def process_page_files_line_by_line_async(
    page_files: List[str],
    user_schema_json: Optional[Dict[str, Any]] = None,
    analyze_client: Optional[str] = None,
    line_client: Optional[str] = None,
    combine_client: Optional[str] = None,
    max_concurrent_lines: int = DEFAULT_LINE_CONCURRENCY,
) -> List[NormalizationResult]:
    """
    Process separate markdown files (one per page) using line-by-line strategy.

    Each table line is parsed independently by a fast model in parallel,
    then combined into the final JSON. More reliable for large tables
    (no row skipping), faster, and cheaper.

    Args:
        page_files: List of paths to markdown files (one per page)
        user_schema_json: Optional user schema
        analyze_client: BAML client for analysis (default: CustomGPT4oMini)
        line_client: BAML client for per-line parsing (default: CustomGPT5Mini)
        combine_client: BAML client for combining rows (default: CustomGPT5Mini)
        max_concurrent_lines: Max parallel line parses (default: 100)

    Returns:
        List of NormalizationResult, one per page
    """
    analyze_client = analyze_client or DEFAULT_ANALYZE_CLIENT
    line_client = line_client or DEFAULT_LINE_CLIENT
    combine_client = combine_client or DEFAULT_COMBINE_CLIENT

    if user_schema_json:
        schema = create_user_schema_from_json(user_schema_json)
        print(f"Using schema: {schema.className}")
    else:
        schema = get_default_schema()
        print(f"Using default schema: {schema.className}")

    print(f"\nProcessing {len(page_files)} pages LINE-BY-LINE...")
    print(f"   Analyze:  {analyze_client}")
    print(f"   Line:     {line_client}")
    print(f"   Combine:  {combine_client}")
    print(f"   Parallel: {max_concurrent_lines} lines\n")

    processor = RowProcessor(
        analyze_client=analyze_client,
        line_client=line_client,
        combine_client=combine_client,
        max_concurrent_lines=max_concurrent_lines,
    )

    results = await processor.process_markdown_files(
        [Path(f) for f in page_files],
        schema,
    )

    print(f"\nProcessed {len(results)}/{len(page_files)} pages successfully (line-by-line)")
    return results
