#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Improved Table Extraction Module

Uses Tesseract's layout analysis and spatial clustering for better table extraction.
This approach works better for dense, multi-column tables.
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Dict
import numpy as np
import cv2
from collections import defaultdict

try:
    import pytesseract
except ImportError:
    pytesseract = None


@dataclass
class TextBox:
    """Represents a detected text element with position"""
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float

    @property
    def center_x(self):
        return self.x + self.width // 2

    @property
    def center_y(self):
        return self.y + self.height // 2

    @property
    def right(self):
        return self.x + self.width

    @property
    def bottom(self):
        return self.y + self.height


@dataclass
class ImprovedTableData:
    """Represents a table extracted using spatial analysis"""
    x: int
    y: int
    width: int
    height: int
    cells: List[List[str]] = field(default_factory=list)  # 2D array of cell contents


def extract_text_boxes(image: np.ndarray, lang: str = 'eng') -> List[TextBox]:
    """
    Extract all text boxes from image using Tesseract's layout analysis.

    Args:
        image: Input image (BGR or grayscale)
        lang: Language code

    Returns:
        List of TextBox objects
    """
    if pytesseract is None:
        return []

    # Convert to grayscale if needed
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image

    # Use PSM 6 (uniform block of text) for better layout detection
    custom_config = r'--oem 3 --psm 6'

    try:
        # Get detailed data with bounding boxes
        data = pytesseract.image_to_data(
            gray,
            lang=lang,
            config=custom_config,
            output_type=pytesseract.Output.DICT
        )

        text_boxes = []
        n_boxes = len(data['text'])

        for i in range(n_boxes):
            # Skip empty text
            if not data['text'][i].strip():
                continue

            # Skip low confidence detections
            conf = int(data['conf'][i])
            if conf < 0:
                continue

            text_box = TextBox(
                text=data['text'][i].strip(),
                x=data['left'][i],
                y=data['top'][i],
                width=data['width'][i],
                height=data['height'][i],
                confidence=float(conf)
            )
            text_boxes.append(text_box)

        return text_boxes

    except Exception as e:
        print(f"Error extracting text boxes: {e}")
        return []


def cluster_into_rows(text_boxes: List[TextBox], tolerance: int = 10) -> List[List[TextBox]]:
    """
    Group text boxes into rows based on y-coordinate proximity.

    Args:
        text_boxes: List of text boxes
        tolerance: Maximum vertical distance to be considered same row

    Returns:
        List of rows, where each row is a list of text boxes
    """
    if not text_boxes:
        return []

    # Sort by y coordinate
    sorted_boxes = sorted(text_boxes, key=lambda b: b.y)

    rows = []
    current_row = [sorted_boxes[0]]
    current_y = sorted_boxes[0].center_y

    for box in sorted_boxes[1:]:
        # If this box is close enough to current row, add it
        if abs(box.center_y - current_y) <= tolerance:
            current_row.append(box)
        else:
            # Start new row
            rows.append(current_row)
            current_row = [box]
            current_y = box.center_y

    # Add last row
    if current_row:
        rows.append(current_row)

    # Sort boxes within each row by x coordinate
    for row in rows:
        row.sort(key=lambda b: b.x)

    return rows


def merge_words_in_row(row: List[TextBox], horizontal_gap: int = 15) -> List[TextBox]:
    """
    Merge words that are horizontally close into single cells.

    Args:
        row: List of text boxes in a row
        horizontal_gap: Maximum horizontal gap to merge words

    Returns:
        List of merged text boxes representing cells
    """
    if not row:
        return []

    # Sort by x position
    sorted_row = sorted(row, key=lambda b: b.x)

    merged = []
    current_group = [sorted_row[0]]

    for box in sorted_row[1:]:
        # If this box is close enough to the last box in current group, merge
        last_box = current_group[-1]
        if box.x - last_box.right <= horizontal_gap:
            current_group.append(box)
        else:
            # Finalize current group
            merged.append(_merge_text_boxes(current_group))
            current_group = [box]

    # Finalize last group
    if current_group:
        merged.append(_merge_text_boxes(current_group))

    return merged


def _merge_text_boxes(boxes: List[TextBox]) -> TextBox:
    """Merge multiple text boxes into one."""
    if len(boxes) == 1:
        return boxes[0]

    # Combine text with spaces
    text = ' '.join(box.text for box in boxes)

    # Calculate bounding box
    x = min(box.x for box in boxes)
    y = min(box.y for box in boxes)
    right = max(box.right for box in boxes)
    bottom = max(box.bottom for box in boxes)

    # Average confidence
    avg_conf = sum(box.confidence for box in boxes) / len(boxes)

    return TextBox(
        text=text,
        x=x,
        y=y,
        width=right - x,
        height=bottom - y,
        confidence=avg_conf
    )


def detect_column_boundaries(rows: List[List[TextBox]], min_column_width: int = 30) -> List[int]:
    """
    Detect column boundaries by analyzing text box positions across all rows.
    Now works with merged cells instead of individual words.

    Args:
        rows: List of rows (each row is a list of text boxes - already merged within rows)
        min_column_width: Minimum width for a column

    Returns:
        List of x-coordinates representing column boundaries
    """
    if not rows:
        return []

    # Collect all x-positions (left edges) across all rows
    x_positions = []
    for row in rows:
        for box in row:
            x_positions.append(box.x)

    if not x_positions:
        return []

    # Sort positions
    x_positions.sort()

    # Cluster nearby positions (columns should align vertically)
    column_boundaries = []
    tolerance = 30  # Positions within 30 pixels are considered same column

    i = 0
    while i < len(x_positions):
        # Start a new column boundary cluster
        cluster = [x_positions[i]]
        j = i + 1

        # Add nearby positions to this cluster
        while j < len(x_positions) and x_positions[j] - x_positions[i] <= tolerance:
            cluster.append(x_positions[j])
            j += 1

        # Use median of cluster as column boundary
        boundary = int(np.median(cluster))
        column_boundaries.append(boundary)

        i = j

    # Filter out columns that are too close together
    filtered_boundaries = [column_boundaries[0]]
    for boundary in column_boundaries[1:]:
        if boundary - filtered_boundaries[-1] >= min_column_width:
            filtered_boundaries.append(boundary)

    return filtered_boundaries


def assign_boxes_to_cells(rows: List[List[TextBox]],
                         column_boundaries: List[int]) -> List[List[str]]:
    """
    Assign text boxes to cells based on row and column positions.

    Args:
        rows: List of rows (each row is a list of text boxes)
        column_boundaries: List of column x-positions

    Returns:
        2D array of cell contents (strings)
    """
    num_cols = len(column_boundaries)
    table_cells = []

    for row in rows:
        # Initialize row cells
        row_cells = [''] * num_cols

        # Assign each box to appropriate column
        for box in row:
            # Find which column this box belongs to
            col_idx = 0
            for i, boundary in enumerate(column_boundaries):
                if box.x >= boundary:
                    col_idx = i

            # Add text to cell (handle multiple boxes in same cell)
            if row_cells[col_idx]:
                row_cells[col_idx] += ' ' + box.text
            else:
                row_cells[col_idx] = box.text

        table_cells.append(row_cells)

    return table_cells


def extract_table_spatially(image: np.ndarray, lang: str = 'eng') -> ImprovedTableData:
    """
    Extract table using spatial analysis of text positions.

    This method works better for dense tables than morphological line detection.

    Args:
        image: Input image (BGR or grayscale)
        lang: Language code

    Returns:
        ImprovedTableData with extracted table structure
    """
    # Step 1: Extract all text boxes with positions
    text_boxes = extract_text_boxes(image, lang)

    if not text_boxes:
        return ImprovedTableData(x=0, y=0, width=0, height=0, cells=[])

    # Step 2: Cluster boxes into rows
    rows = cluster_into_rows(text_boxes, tolerance=15)

    # Step 3: Merge words within each row that are horizontally close
    merged_rows = []
    for row in rows:
        merged_row = merge_words_in_row(row, horizontal_gap=15)
        merged_rows.append(merged_row)

    # Step 4: Detect column boundaries from merged cells
    column_boundaries = detect_column_boundaries(merged_rows, min_column_width=50)

    # Step 5: Assign merged cells to table columns
    table_cells = assign_boxes_to_cells(merged_rows, column_boundaries)

    # Calculate table bounding box
    all_x = [box.x for box in text_boxes]
    all_y = [box.y for box in text_boxes]
    all_right = [box.right for box in text_boxes]
    all_bottom = [box.bottom for box in text_boxes]

    table_data = ImprovedTableData(
        x=min(all_x) if all_x else 0,
        y=min(all_y) if all_y else 0,
        width=max(all_right) - min(all_x) if all_x else 0,
        height=max(all_bottom) - min(all_y) if all_y else 0,
        cells=table_cells
    )

    return table_data


def format_table_as_markdown(table: ImprovedTableData) -> str:
    """
    Format extracted table as markdown.

    Args:
        table: ImprovedTableData object

    Returns:
        Markdown formatted table
    """
    if not table.cells:
        return ""

    markdown_lines = []

    # Determine column count
    num_cols = max(len(row) for row in table.cells) if table.cells else 0

    if num_cols == 0:
        return ""

    # Normalize all rows to have same number of columns
    normalized_cells = []
    for row in table.cells:
        normalized_row = row + [''] * (num_cols - len(row))
        normalized_cells.append(normalized_row)

    # First row as header
    if normalized_cells:
        header = "| " + " | ".join(cell.replace('|', '\\|') for cell in normalized_cells[0]) + " |"
        markdown_lines.append(header)

        # Separator
        separator = "| " + " | ".join(["---"] * num_cols) + " |"
        markdown_lines.append(separator)

        # Data rows
        for row in normalized_cells[1:]:
            row_text = "| " + " | ".join(cell.replace('|', '\\|') for cell in row) + " |"
            markdown_lines.append(row_text)

    return "\n".join(markdown_lines)


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python improved_table_extractor.py <image_path> [lang]")
        sys.exit(1)

    if pytesseract is None:
        print("Error: pytesseract not installed")
        sys.exit(1)

    image_path = sys.argv[1]
    lang = sys.argv[2] if len(sys.argv) > 2 else 'eng'

    # Load image
    image = cv2.imread(image_path)
    if image is None:
        print(f"Error: Could not load image {image_path}")
        sys.exit(1)

    print(f"Extracting table from {image_path}...")
    print(f"Language: {lang}\n")

    # Extract table
    table = extract_table_spatially(image, lang)

    print(f"Table extracted:")
    print(f"  Position: ({table.x}, {table.y})")
    print(f"  Size: {table.width}x{table.height}")
    print(f"  Rows: {len(table.cells)}")
    print(f"  Columns: {len(table.cells[0]) if table.cells else 0}")

    # Format as markdown
    print("\nMarkdown output:")
    print("-" * 80)
    markdown = format_table_as_markdown(table)
    print(markdown)
    print("-" * 80)
