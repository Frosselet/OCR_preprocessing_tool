#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Table Normalizer - Convert OCR'd markdown tables to 1NF

Uses BAML to intelligently parse table structure and convert to normalized records.
Business-agnostic: works with any table type, not just specific domains.
"""

import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict

from baml_client import b
from baml_client.types import TableMetadata, UserSchema, FieldDefinition


@dataclass
class NormalizationResult:
    """Result of table normalization process"""
    metadata: TableMetadata
    schema: UserSchema
    normalized_data: List[Dict[str, Any]]
    raw_json: str


def create_user_schema_from_json(schema_json: Dict[str, Any]) -> UserSchema:
    """
    Convert user-provided JSON schema to BAML UserSchema.

    Expected JSON format:
    {
        "className": "RecordName",
        "fields": {
            "field1": {"type": "string", "description": "...", "required": true},
            "field2": {"type": "int", "description": "...", "required": false}
        }
    }

    Args:
        schema_json: User schema in JSON format

    Returns:
        UserSchema object for BAML
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
    """
    Default schema for when user doesn't provide one.
    Creates a generic flexible schema.
    """
    return UserSchema(
        className="GenericRecord",
        fields=[
            FieldDefinition(
                name="data",
                type="string",
                description="Generic data field - will contain all extracted data as JSON string",
                required=False
            )
        ]
    )


def process_ocr_table(
    markdown_content: str,
    page_context: Optional[str] = None,
    user_schema_json: Optional[Dict[str, Any]] = None
) -> NormalizationResult:
    """
    Process OCR'd markdown table and convert to 1NF.

    Two-step process:
    1. Analyze table structure (metadata extraction)
    2. Convert to normalized records based on schema

    Args:
        markdown_content: Markdown table from OCR
        page_context: Optional context about page (e.g., "Page 1 of shipping manifest")
        user_schema_json: Optional user-provided schema in JSON format

    Returns:
        NormalizationResult with metadata, schema, and normalized data

    Example:
        >>> schema = {
        ...     "className": "ShippingRecord",
        ...     "fields": {
        ...         "port": {"type": "string", "required": True},
        ...         "vessel": {"type": "string"},
        ...         "cargo_tons": {"type": "float"}
        ...     }
        ... }
        >>> result = process_ocr_table(markdown_table, "Page 1", schema)
        >>> print(f"Found {len(result.normalized_data)} records")
        >>> print(f"Table type: {result.metadata.tableType}")
    """
    # Step 1: Analyze table structure
    print(f"Analyzing table structure...")
    metadata = b.AnalyzeTableStructure(markdown_content, page_context)

    print(f"  Detected table type: {metadata.tableType}")
    print(f"  Page: {metadata.pageNumber}")
    print(f"  Headers at rows: {metadata.headerRowIndices}")
    print(f"  Total rows at: {metadata.totalRowIndices}")
    print(f"  Has subtotals: {metadata.hasSubtotals}")
    if metadata.notes:
        print(f"  Notes: {metadata.notes}")

    # Step 2: Create schema
    if user_schema_json:
        schema = create_user_schema_from_json(user_schema_json)
        print(f"\nUsing user-provided schema: {schema.className}")
    else:
        schema = get_default_schema()
        print(f"\nUsing default schema: {schema.className}")

    print(f"  Fields: {', '.join([f'{f.name}:{f.type}' for f in schema.fields])}")

    # Step 3: Generate normalized table
    print(f"\nConverting to 1NF...")
    raw_json = b.GenerateNormalizedTable(markdown_content, metadata, schema)

    # Parse JSON result (strip markdown code blocks if present)
    try:
        # Remove markdown code blocks (```json ... ```)
        json_str = raw_json.strip()
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
        print(f"  Extracted {len(normalized_data)} records")
    except json.JSONDecodeError as e:
        print(f"  Warning: Failed to parse JSON: {e}")
        print(f"  Raw output: {raw_json[:200]}...")
        normalized_data = []

    return NormalizationResult(
        metadata=metadata,
        schema=schema,
        normalized_data=normalized_data,
        raw_json=raw_json
    )


def save_normalized_data(result: NormalizationResult, output_path: str):
    """
    Save normalized data to JSON file.

    Args:
        result: NormalizationResult from process_ocr_table
        output_path: Path to save JSON file
    """
    output = {
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
        "data": result.normalized_data
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to {output_path}")


if __name__ == '__main__':
    import sys
    import argparse

    parser = argparse.ArgumentParser(
        description='Normalize OCR markdown table to 1NF',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example schemas:

Shipping manifest:
{
  "className": "ShippingRecord",
  "fields": {
    "port": {"type": "string", "required": true},
    "reference": {"type": "string"},
    "exporter": {"type": "string"},
    "vessel": {"type": "string"},
    "commodity": {"type": "string"},
    "quantity": {"type": "float"},
    "eta_date": {"type": "string"},
    "status": {"type": "string"}
  }
}

Invoice:
{
  "className": "InvoiceLineItem",
  "fields": {
    "item_code": {"type": "string"},
    "description": {"type": "string"},
    "quantity": {"type": "int"},
    "unit_price": {"type": "float"},
    "total": {"type": "float"}
  }
}
        """
    )

    parser.add_argument('markdown_file', help='Input markdown file')
    parser.add_argument('output_file', help='Output JSON file')
    parser.add_argument('--schema', help='Schema JSON file (optional)')
    parser.add_argument('--page', help='Page context (e.g., "Page 1")')

    args = parser.parse_args()

    # Read markdown
    with open(args.markdown_file, 'r', encoding='utf-8') as f:
        markdown_content = f.read()

    # Read schema if provided
    user_schema = None
    if args.schema:
        with open(args.schema, 'r', encoding='utf-8') as f:
            user_schema = json.load(f)

    # Process
    result = process_ocr_table(markdown_content, args.page, user_schema)

    # Save
    save_normalized_data(result, args.output_file)
