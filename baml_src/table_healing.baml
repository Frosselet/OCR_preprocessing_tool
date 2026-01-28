// Table Healing - OCR artifact recovery
// Separate from user schema - this is about understanding and fixing OCR output

// =============================================================================
// STEP 1: INFER TABLE SCHEMA FROM OCR OUTPUT
// =============================================================================

enum InferredDataType {
  TEXT @description("Free text content")
  INTEGER @description("Whole numbers")
  DECIMAL @description("Numbers with decimals")
  DATE @description("Date values in any format")
  TIME @description("Time values")
  DATETIME @description("Combined date and time")
  CODE @description("Short uppercase codes or identifiers")
  BOOLEAN @description("Yes/No, True/False values")
  MIXED @description("Column contains multiple data types")
}

class InferredColumn {
  index int @description("Column position (0-based)")
  name string @description("Column header name as it appears")
  dataType InferredDataType @description("Inferred data type from cell contents")
  nullable bool @description("Whether empty values appear in this column")
  examples string[] @description("2-3 example values from this column")
}

class InferredTableSchema {
  expectedColumns int @description("Expected number of columns based on header")
  expectedDataRows int @description("Expected number of data rows")
  headerRowCount int @description("Number of header rows")
  columns InferredColumn[] @description("Information about each column")
  hasMergedCells bool @description("Whether merged cells were detected")
  mergedCellPatterns string[] @description("Patterns of merged cells observed")
  notes string? @description("Observations about table structure")
}

function InferTableSchema(markdownTable: string) -> InferredTableSchema {
  client CustomGPT4oMini
  prompt #"
    Analyze this OCR-extracted markdown table and infer its logical structure.

    The table may have imperfections from OCR:
    - Some cells might be accidentally merged
    - Column alignment might be off
    - Data might appear in wrong columns

    Your task: Look past imperfections and determine what the table SHOULD look like.

    To detect merged cells:
    - Count columns in header row = expected column count
    - Rows with fewer columns likely have merged cells
    - Cells containing multiple data types are likely merged

    {{ ctx.output_format }}

    {{ _.role("user") }}
    {{ markdownTable }}
  "#
}

// =============================================================================
// STEP 2: CONVERT TO CLEAN STRUCTURED DATA
// Uses TOON format for efficient token usage
// =============================================================================

class CleanTableData {
  headers string[] @description("Column headers")
  dataRows string[][] @description("Each inner array is one row of cell values")
  rowCount int @description("Number of data rows")
  columnCount int @description("Number of columns")
  healingNotes string[] @description("Notes about fixes applied")
}

function HealToStructuredData(
  markdownTable: string,
  inferredSchema: InferredTableSchema
) -> CleanTableData {
  client CustomGPT4o
  prompt #"
    Convert this messy OCR markdown table into clean structured data.

    Fix structural issues and output clean tabular data matching the schema.

    Target structure (TOON format):
    {{ inferredSchema|format(type="toon", delimiter="pipe") }}

    HEALING RULES:
    Split merged cells by type boundaries:
    - INTEGER + CODE in one cell → split into two cells
    - TEXT + DATE in one cell → split into two cells
    - TEXT + TIME in one cell → split into two cells
    - Place split values in correct column positions

    For each row:
    - Ensure column count matches expected ({{ inferredSchema.expectedColumns }})
    - Split merged cells and redistribute values
    - Skip header rows, total/subtotal rows

    {{ ctx.output_format }}

    {{ _.role("user") }}
    {{ markdownTable }}
  "#
}

// =============================================================================
// STEP 3: FORMAT AS CLEAN MARKDOWN
// =============================================================================

function FormatAsCleanMarkdown(cleanData: CleanTableData) -> string {
  client CustomGPT4oMini
  prompt #"
    Convert this clean structured data back to properly formatted markdown table.

    Input data (TOON format):
    {{ cleanData|format(type="toon", delimiter="pipe") }}

    Output a clean markdown table with proper alignment and separators.
    Do not include any other text, just the markdown table.

    {{ _.role("user") }}
    Generate the markdown table.
  "#
}
