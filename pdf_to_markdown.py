#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PDF to Markdown Converter

Simple, focused tool for converting digital PDFs (or XLS/HTML exports) to markdown.
Uses spatial table extraction - no preprocessing needed for digital documents.

Usage:
    python pdf_to_markdown.py input.pdf output.md
    python pdf_to_markdown.py --pdf document.pdf --output result.md --lang eng
"""

import os
import sys
import argparse
import logging
from typing import List
import numpy as np
import cv2

from improved_table_extractor import extract_table_spatially, format_table_as_markdown

try:
    from pdf2image import convert_from_path
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    print("Error: pdf2image not installed")
    print("Install with: pip install pdf2image")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def pdf_to_markdown_pages(pdf_path: str, output_dir: str, dpi: int = 300, lang: str = 'eng') -> List[str]:
    """
    Convert PDF to separate markdown files per page.

    This is the preferred method - each page gets its own clean markdown file
    with no risk of splitting issues.

    Args:
        pdf_path: Path to input PDF
        output_dir: Directory to save markdown files
        dpi: DPI for PDF rendering (default: 300)
        lang: Language code for OCR (default: 'eng')

    Returns:
        List of paths to generated markdown files (one per page)
    """
    logger.info(f"Converting: {pdf_path}")

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Convert PDF to images
    try:
        logger.info(f"Rendering PDF at {dpi} DPI...")
        pil_images = convert_from_path(pdf_path, dpi=dpi)
        logger.info(f"Converted {len(pil_images)} pages")
    except Exception as e:
        logger.error(f"Failed to convert PDF: {e}")
        return []

    # Document base name for file naming
    doc_name = os.path.splitext(os.path.basename(pdf_path))[0]

    page_files = []

    for i, pil_img in enumerate(pil_images, 1):
        logger.info(f"Processing page {i}/{len(pil_images)}...")

        # Convert PIL image to OpenCV format
        img_array = np.array(pil_img)
        img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

        # Extract table using spatial analysis (no preprocessing)
        table = extract_table_spatially(img_bgr, lang)

        logger.info(f"  Extracted {len(table.cells)} rows, {len(table.cells[0]) if table.cells else 0} columns")

        # Format as markdown - clean, just the table
        markdown = format_table_as_markdown(table)

        # Save each page to its own file
        page_file = os.path.join(output_dir, f"{doc_name}_page_{i}.md")
        with open(page_file, 'w', encoding='utf-8') as f:
            f.write(markdown)

        page_files.append(page_file)
        logger.info(f"  Saved: {page_file}")

    logger.info(f"✓ Processed {len(pil_images)} pages successfully")
    return page_files


def pdf_to_markdown(pdf_path: str, output_path: str, dpi: int = 300, lang: str = 'eng'):
    """
    Convert PDF to a single merged markdown file (legacy method).

    For better results with the async pipeline, use pdf_to_markdown_pages() instead.

    Args:
        pdf_path: Path to input PDF
        output_path: Path to output markdown file
        dpi: DPI for PDF rendering (default: 300)
        lang: Language code for OCR (default: 'eng')
    """
    logger.info(f"Converting: {pdf_path}")

    # Convert PDF to images
    try:
        logger.info(f"Rendering PDF at {dpi} DPI...")
        pil_images = convert_from_path(pdf_path, dpi=dpi)
        logger.info(f"Converted {len(pil_images)} pages")
    except Exception as e:
        logger.error(f"Failed to convert PDF: {e}")
        return

    # Process each page
    markdown_parts = []

    # Document title
    doc_title = os.path.splitext(os.path.basename(pdf_path))[0]
    markdown_parts.append(f"# {doc_title}\n\n")

    for i, pil_img in enumerate(pil_images, 1):
        logger.info(f"Processing page {i}/{len(pil_images)}...")

        # Convert PIL image to OpenCV format
        img_array = np.array(pil_img)
        img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

        # Extract table using spatial analysis (no preprocessing)
        table = extract_table_spatially(img_bgr, lang)

        logger.info(f"  Extracted {len(table.cells)} rows, {len(table.cells[0]) if table.cells else 0} columns")

        # Format as markdown
        markdown = format_table_as_markdown(table)

        # Add to output
        markdown_parts.append(f"# Page {i}\n\n{markdown}\n")

        if i < len(pil_images):
            markdown_parts.append("\n---\n\n")

    # Add footer
    markdown_parts.append("\n---\n*Generated with PDF-to-Markdown converter*\n")

    # Save output
    full_markdown = "".join(markdown_parts)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(full_markdown)

    logger.info(f"✓ Saved: {output_path}")
    logger.info(f"✓ Processed {len(pil_images)} pages successfully")


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description='Convert PDF to Markdown with table extraction',
        epilog="""
Examples:
  python pdf_to_markdown.py document.pdf output.md
  python pdf_to_markdown.py --pdf report.pdf --output report.md --dpi 600
  python pdf_to_markdown.py --pdf invoice.pdf --output invoice.md --lang jpn
        """
    )

    parser.add_argument('pdf', nargs='?', help='Input PDF file')
    parser.add_argument('output', nargs='?', help='Output markdown file')
    parser.add_argument('--pdf', dest='pdf_flag', help='Input PDF file (alternative syntax)')
    parser.add_argument('--output', '-o', dest='output_flag', help='Output markdown file (alternative syntax)')
    parser.add_argument('--dpi', type=int, default=300, help='PDF rendering DPI (default: 300)')
    parser.add_argument('--lang', '-l', default='eng', help='OCR language code (default: eng)')
    parser.add_argument('--quiet', '-q', action='store_true', help='Reduce output')

    args = parser.parse_args()

    # Handle both positional and flag-based arguments
    pdf_path = args.pdf or args.pdf_flag
    output_path = args.output or args.output_flag

    if not pdf_path or not output_path:
        parser.print_help()
        sys.exit(1)

    # Validate input
    if not os.path.exists(pdf_path):
        logger.error(f"File not found: {pdf_path}")
        sys.exit(1)

    # Set logging level
    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    try:
        pdf_to_markdown(pdf_path, output_path, dpi=args.dpi, lang=args.lang)
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
