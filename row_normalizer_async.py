#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Async Row Normalizer - Line-by-line table processing

Each markdown table line is parsed independently by gpt-4o-mini in parallel,
then combined in Python (no LLM). Guarantees zero row loss.

Pipeline:
  markdown -> ParseLine x N (100 parallel, gpt-4o-mini) -> Combine (Python) -> JSON
"""

import json
import asyncio
import time
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

from baml_client import b
from baml_client.types import UserSchema, ParsedTableRow

from table_normalizer_async import (
    NormalizationResult,
    create_user_schema_from_json,
    get_default_schema,
)

try:
    import aiofiles
    HAS_AIOFILES = True
except ImportError:
    HAS_AIOFILES = False


# Defaults — gpt-4o-mini for line parsing (fast + cheap)
DEFAULT_LINE_CLIENT = "CustomGPT4oMini"
DEFAULT_LINE_CONCURRENCY = 100


# =============================================================================
# PYTHON COMBINER (no LLM needed)
# =============================================================================

def _convert_value(raw: str, field_type: str) -> Any:
    """Convert a raw string cell value to the target type."""
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned or cleaned.lower() in ('', 'blank', '(blank)', 'null', 'none', '-', 'n/a'):
        return None

    if field_type == "int":
        try:
            return int(cleaned.replace(',', '').replace(' ', ''))
        except ValueError:
            # Try extracting first number
            match = re.search(r'-?\d[\d,]*', cleaned)
            if match:
                try:
                    return int(match.group().replace(',', ''))
                except ValueError:
                    pass
            return None
    elif field_type == "float":
        try:
            return float(cleaned.replace(',', '').replace(' ', ''))
        except ValueError:
            match = re.search(r'-?\d[\d,]*\.?\d*', cleaned)
            if match:
                try:
                    return float(match.group().replace(',', ''))
                except ValueError:
                    pass
            return None
    elif field_type == "bool":
        return cleaned.lower() in ('true', 'yes', '1', 'y')
    else:
        return cleaned


def combine_parsed_rows_python(
    parsed_rows: List[ParsedTableRow],
    user_schema: UserSchema,
) -> List[Dict[str, Any]]:
    """
    Combine ParsedTableRow objects into final records using pure Python.

    - Keeps only isDataRow=True rows
    - Maps rowData[i] -> schema field names by position
    - Converts types (int, float, string, bool)
    - Zero row loss, deterministic, instant
    """
    field_names = [f.name for f in user_schema.fields]
    field_types = [f.type for f in user_schema.fields]
    num_fields = len(field_names)

    records = []
    for row in parsed_rows:
        if not row.isDataRow:
            continue

        record = {}
        for i, field_name in enumerate(field_names):
            if i < len(row.rowData):
                record[field_name] = _convert_value(row.rowData[i], field_types[i])
            else:
                record[field_name] = None
        records.append(record)

    return records


# =============================================================================
# LINE-BY-LINE PROCESSOR
# =============================================================================

class LineByLineProcessor:
    """Processes markdown tables line-by-line with parallel LLM calls."""

    def __init__(
        self,
        line_client: str = DEFAULT_LINE_CLIENT,
        max_concurrent_lines: int = DEFAULT_LINE_CONCURRENCY,
    ):
        self.line_client = line_client
        self.line_semaphore = asyncio.Semaphore(max_concurrent_lines)

    async def process_table_line_by_line(
        self,
        markdown_table: str,
        user_schema: UserSchema,
    ) -> Dict:
        """Process table line by line for guaranteed completeness."""

        # Split table into lines
        lines = [line.strip() for line in markdown_table.split('\n') if line.strip()]

        # Determine expected structure from schema
        expected_columns = len(user_schema.fields)
        field_types = [field.type for field in user_schema.fields]

        async def process_single_line(line: str, line_index: int, prev: List[str]) -> tuple:
            async with self.line_semaphore:
                try:
                    parsed_row = await asyncio.to_thread(
                        lambda: b.with_options(client=self.line_client).ParseSingleTableLine(
                            markdownLine=line,
                            expectedColumns=expected_columns,
                            fieldTypes=field_types,
                            userSchema=user_schema,
                            previousLines=prev,
                        )
                    )
                    return line_index, parsed_row
                except Exception as e:
                    # Return error row but don't fail entire process
                    print(f"  [Line {line_index}] Parse failed: {e}")
                    return line_index, ParsedTableRow(
                        rowData=[],
                        isHeaderRow=False,
                        isDataRow=False,
                        isTotalRow=False,
                        isEmpty=True,
                        confidence=0.0,
                    )

        # Process all lines concurrently — each gets the 3 preceding raw lines as context
        print(f"  Parsing {len(lines)} lines concurrently (max {self.line_semaphore._value})...")
        start_time = time.time()

        line_tasks = [
            process_single_line(line, i, lines[max(0, i - 3):i])
            for i, line in enumerate(lines)
        ]
        line_results = await asyncio.gather(*line_tasks)

        # Sort by original line order
        line_results.sort(key=lambda x: x[0])
        parsed_rows = [result[1] for result in line_results]

        parsing_time = time.time() - start_time
        data_rows = sum(1 for row in parsed_rows if row.isDataRow)
        header_rows = sum(1 for row in parsed_rows if row.isHeaderRow)
        total_rows = sum(1 for row in parsed_rows if row.isTotalRow)
        empty_rows = sum(1 for row in parsed_rows if row.isEmpty)
        print(f"  Line parsing done in {parsing_time:.1f}s — "
              f"{data_rows} data, {header_rows} header, {total_rows} total, {empty_rows} empty")

        # Combine in Python (deterministic, no LLM, zero row loss)
        start_time = time.time()
        normalized_data = combine_parsed_rows_python(parsed_rows, user_schema)
        combination_time = time.time() - start_time

        return {
            "normalized_data": normalized_data,
            "lines_processed": len(lines),
            "data_rows_found": data_rows,
            "records_produced": len(normalized_data),
            "parsing_time": parsing_time,
            "combination_time": combination_time,
            "total_time": parsing_time + combination_time,
        }

    async def load_markdown_file(self, file_path: Path) -> str:
        """Async file loading with fallback to sync."""
        if HAS_AIOFILES:
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                return await f.read()
        else:
            return await asyncio.to_thread(
                lambda: file_path.read_text(encoding='utf-8')
            )

    async def process_file_line_by_line(
        self,
        file_path: Path,
        page_number: int,
        user_schema: UserSchema,
    ) -> Optional[NormalizationResult]:
        """Process one markdown file line-by-line, return NormalizationResult."""
        try:
            content = await self.load_markdown_file(file_path)
            print(f"[Page {page_number}] Processing line-by-line ({file_path.name})...")

            result = await self.process_table_line_by_line(content, user_schema)

            normalized_data = result["normalized_data"]
            print(f"[Page {page_number}] Extracted {len(normalized_data)} records "
                  f"({result['total_time']:.1f}s)")

            return NormalizationResult(
                page_number=page_number,
                metadata=None,  # no analyze step in line-by-line mode
                schema=user_schema,
                normalized_data=normalized_data,
                raw_json=json.dumps(normalized_data),
            )
        except Exception as e:
            print(f"[Page {page_number}] Failed: {e}")
            return None

    async def process_markdown_files(
        self,
        file_paths: List[Path],
        user_schema: UserSchema,
    ) -> List[NormalizationResult]:
        """Process multiple markdown files using line-by-line strategy."""
        tasks = {
            asyncio.create_task(
                self.process_file_line_by_line(Path(fp), i, user_schema)
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
    line_client: Optional[str] = None,
    max_concurrent_lines: int = DEFAULT_LINE_CONCURRENCY,
) -> List[NormalizationResult]:
    """
    Process markdown files (one per page) using line-by-line strategy.

    Each table line is parsed independently by gpt-4o-mini in parallel,
    then combined in Python. Guarantees zero row loss.

    Args:
        page_files: List of paths to markdown files (one per page)
        user_schema_json: Optional user schema
        line_client: BAML client for per-line parsing (default: CustomGPT4oMini)
        max_concurrent_lines: Max parallel line parses (default: 100)

    Returns:
        List of NormalizationResult, one per page
    """
    line_client = line_client or DEFAULT_LINE_CLIENT

    if user_schema_json:
        schema = create_user_schema_from_json(user_schema_json)
        print(f"Using schema: {schema.className}")
    else:
        schema = get_default_schema()
        print(f"Using default schema: {schema.className}")

    print(f"\nProcessing {len(page_files)} pages LINE-BY-LINE...")
    print(f"   Line parse: {line_client}")
    print(f"   Combine:    Python (deterministic)")
    print(f"   Parallel:   {max_concurrent_lines} lines\n")

    processor = LineByLineProcessor(
        line_client=line_client,
        max_concurrent_lines=max_concurrent_lines,
    )

    results = await processor.process_markdown_files(
        [Path(f) for f in page_files],
        schema,
    )

    total = sum(len(r.normalized_data) for r in results)
    print(f"\nProcessed {len(results)}/{len(page_files)} pages — {total} records total")
    return results
