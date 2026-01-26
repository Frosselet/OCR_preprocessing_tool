#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Table Structure Analyzer

Detects if extracted tables are hierarchical/pivot tables that need flattening,
or simple flat tables ready for CSV export.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import re


@dataclass
class TableStructureAnalysis:
    """Analysis of table structure"""
    is_flat_table: bool
    is_hierarchical: bool
    has_subtotals: bool
    has_merged_cells: bool
    has_sparse_rows: bool
    group_columns: List[int]  # Column indices that contain grouping info
    total_rows: List[int]  # Row indices that are subtotal/total rows
    confidence: float
    reasoning: str


def detect_total_rows(cells: List[List[str]]) -> List[int]:
    """
    Detect rows that are subtotals or grand totals.

    Common patterns:
    - Contains "Total", "Sub-total", "Grand Total"
    - Has numeric value in last column, rest mostly empty
    - Ends with aggregated data
    """
    total_rows = []
    total_keywords = ['total', 'subtotal', 'sub-total', 'grand total', 'sum']

    for i, row in enumerate(cells):
        row_text = ' '.join(row).lower()

        # Check for total keywords
        if any(keyword in row_text for keyword in total_keywords):
            total_rows.append(i)
            continue

        # Check for rows with mostly empty cells except last few
        # (common pattern for subtotal rows)
        non_empty = sum(1 for cell in row if cell.strip())
        if non_empty <= 3 and len(row) > 5:
            # Check if last cells contain numbers
            last_cells = [c.strip() for c in row[-3:] if c.strip()]
            if last_cells and any(is_numeric(c) for c in last_cells):
                total_rows.append(i)

    return total_rows


def is_numeric(value: str) -> bool:
    """Check if string represents a number (including formatted numbers like 30,000)"""
    # Remove common number formatting
    cleaned = value.replace(',', '').replace('$', '').strip()
    try:
        float(cleaned)
        return True
    except ValueError:
        return False


def detect_sparse_rows(cells: List[List[str]]) -> float:
    """
    Calculate proportion of rows that are sparse (many empty cells).
    High sparsity indicates hierarchical structure.

    Returns: proportion of sparse rows (0.0 to 1.0)
    """
    if not cells:
        return 0.0

    sparse_count = 0
    for row in cells:
        non_empty = sum(1 for cell in row if cell.strip())
        total_cells = len(row)

        # Row is sparse if less than 50% filled
        if total_cells > 0 and non_empty / total_cells < 0.5:
            sparse_count += 1

    return sparse_count / len(cells)


def detect_group_columns(cells: List[List[str]]) -> List[int]:
    """
    Detect columns that contain grouping information.

    Indicators:
    - Column has many empty cells (values carried forward implicitly)
    - Contains category labels (Year, Month, Region, etc.)
    - Low cardinality relative to row count
    """
    if not cells or len(cells) < 3:
        return []

    num_cols = len(cells[0]) if cells else 0
    group_cols = []

    for col_idx in range(num_cols):
        col_values = [row[col_idx].strip() if col_idx < len(row) else ''
                      for row in cells]

        non_empty = sum(1 for v in col_values if v)
        empty_ratio = 1 - (non_empty / len(col_values))

        # If column is 40%+ empty, likely a group column
        # (values only appear at start of group)
        if empty_ratio > 0.4:
            group_cols.append(col_idx)

    return group_cols


def detect_variable_column_count(cells: List[List[str]]) -> bool:
    """
    Check if rows have inconsistent numbers of non-empty columns.
    This indicates merged cells or hierarchical structure.
    """
    if not cells or len(cells) < 2:
        return False

    column_counts = []
    for row in cells:
        # Count columns with non-empty content
        non_empty_count = sum(1 for cell in row if cell.strip())
        column_counts.append(non_empty_count)

    # If variation is high, likely hierarchical
    unique_counts = len(set(column_counts))
    return unique_counts > 3  # More than 3 different patterns


def analyze_table_structure(cells: List[List[str]]) -> TableStructureAnalysis:
    """
    Analyze extracted table to determine its structure type.

    Args:
        cells: 2D array of cell contents (from table extraction)

    Returns:
        TableStructureAnalysis with detection results
    """
    if not cells or len(cells) < 2:
        return TableStructureAnalysis(
            is_flat_table=True,
            is_hierarchical=False,
            has_subtotals=False,
            has_merged_cells=False,
            has_sparse_rows=False,
            group_columns=[],
            total_rows=[],
            confidence=0.5,
            reasoning="Too few rows to analyze"
        )

    # Run detection heuristics
    total_rows = detect_total_rows(cells)
    group_columns = detect_group_columns(cells)
    sparse_ratio = detect_sparse_rows(cells)
    has_variable_cols = detect_variable_column_count(cells)

    # Determine structure type
    has_subtotals = len(total_rows) > 0
    has_sparse_rows = sparse_ratio > 0.3
    has_merged_cells = has_variable_cols
    is_hierarchical = has_subtotals or len(group_columns) > 2 or has_sparse_rows
    is_flat_table = not is_hierarchical

    # Calculate confidence based on evidence
    evidence_count = sum([
        has_subtotals,
        len(group_columns) > 2,
        has_sparse_rows,
        has_variable_cols
    ])
    confidence = min(0.9, 0.5 + (evidence_count * 0.15))

    # Generate reasoning
    reasons = []
    if has_subtotals:
        reasons.append(f"Found {len(total_rows)} total/subtotal rows")
    if group_columns:
        reasons.append(f"Detected {len(group_columns)} grouping columns")
    if has_sparse_rows:
        reasons.append(f"High row sparsity ({sparse_ratio:.1%})")
    if has_variable_cols:
        reasons.append("Variable column counts (merged cells)")

    if not reasons:
        reasons.append("Uniform structure with consistent columns")

    reasoning = "; ".join(reasons)

    return TableStructureAnalysis(
        is_flat_table=is_flat_table,
        is_hierarchical=is_hierarchical,
        has_subtotals=has_subtotals,
        has_merged_cells=has_merged_cells,
        has_sparse_rows=has_sparse_rows,
        group_columns=group_columns,
        total_rows=total_rows,
        confidence=confidence,
        reasoning=reasoning
    )


def flatten_hierarchical_table(cells: List[List[str]],
                               analysis: TableStructureAnalysis) -> List[List[str]]:
    """
    Convert hierarchical/pivot table to flat table suitable for CSV.

    Transformations:
    1. Carry forward group values to detail rows
    2. Remove total rows
    3. Fill in empty cells with context from above

    Args:
        cells: Original table cells
        analysis: Structure analysis results

    Returns:
        Flattened table ready for CSV export
    """
    if analysis.is_flat_table:
        # Already flat, just return as-is
        return cells

    flattened = []
    group_values = {}  # Track current values for each group column

    for row_idx, row in enumerate(cells):
        # Skip header row (first row)
        if row_idx == 0:
            flattened.append(row)
            continue

        # Skip total rows
        if row_idx in analysis.total_rows:
            continue

        # Process row
        new_row = row.copy()

        # Carry forward group column values
        for col_idx in analysis.group_columns:
            if col_idx < len(row):
                value = row[col_idx].strip()
                if value:
                    # Update current group value
                    group_values[col_idx] = value
                else:
                    # Carry forward previous group value
                    if col_idx in group_values:
                        new_row[col_idx] = group_values[col_idx]

        # Only add rows that have actual data (not just group labels)
        non_empty_count = sum(1 for cell in new_row if cell.strip())
        if non_empty_count > len(analysis.group_columns):
            flattened.append(new_row)

    return flattened


def table_to_csv_string(cells: List[List[str]], delimiter: str = ',') -> str:
    """
    Convert table cells to CSV string.

    Args:
        cells: 2D array of cell contents
        delimiter: CSV delimiter (default: comma)

    Returns:
        CSV-formatted string
    """
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output, delimiter=delimiter)

    for row in cells:
        writer.writerow(row)

    return output.getvalue()


if __name__ == '__main__':
    # Test with sample data
    print("Table Structure Analyzer - Test Mode\n")

    # Example 1: Flat table
    flat_table = [
        ['ID', 'Name', 'Age', 'City'],
        ['1', 'John', '30', 'NYC'],
        ['2', 'Jane', '25', 'LA'],
        ['3', 'Bob', '35', 'Chicago']
    ]

    print("Example 1: Flat Table")
    print("-" * 50)
    analysis = analyze_table_structure(flat_table)
    print(f"Is Flat: {analysis.is_flat_table}")
    print(f"Is Hierarchical: {analysis.is_hierarchical}")
    print(f"Confidence: {analysis.confidence:.2f}")
    print(f"Reasoning: {analysis.reasoning}")
    print()

    # Example 2: Hierarchical table (like graincorp)
    hierarchical_table = [
        ['Year', 'Month', 'Port', 'Reference', 'Exporter', 'Ship', 'Commodity', 'Total'],
        ['2025/26', 'Nov 25', 'Mackay', '56285', 'GCOP', 'DODO', 'Chickpeas', '30,000'],
        ['', '', 'Mackay Total', '', '', '', '', '30,000'],
        ['', '', 'Gladstone', '56307', 'GCOP', 'DELTA', 'Chickpeas', '30,000'],
        ['', '', 'Gladstone Total', '', '', '', '', '30,000'],
        ['', 'Nov 25 Total', '', '', '', '', '', '520,000'],
        ['', 'Dec 25', 'Mackay', '56799', 'BUNGE', 'TBA', 'Chickpeas', '10,000'],
        ['', '', 'Mackay Total', '', '', '', '', '50,000'],
    ]

    print("Example 2: Hierarchical Table")
    print("-" * 50)
    analysis = analyze_table_structure(hierarchical_table)
    print(f"Is Flat: {analysis.is_flat_table}")
    print(f"Is Hierarchical: {analysis.is_hierarchical}")
    print(f"Has Subtotals: {analysis.has_subtotals}")
    print(f"Group Columns: {analysis.group_columns}")
    print(f"Total Rows: {analysis.total_rows}")
    print(f"Confidence: {analysis.confidence:.2f}")
    print(f"Reasoning: {analysis.reasoning}")
    print()

    # Test flattening
    print("Flattened version:")
    print("-" * 50)
    flattened = flatten_hierarchical_table(hierarchical_table, analysis)
    for row in flattened:
        print('|'.join(row))
