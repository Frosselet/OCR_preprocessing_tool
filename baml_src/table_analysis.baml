// Table Analysis and Normalization
// Business-agnostic table structure detection and 1NF conversion

enum TableType {
  REGULAR @description("Standard table with headers in first row and data in subsequent rows")
  PIVOTED @description("Table where categories are in rows and values are in columns")
  TRANSPOSED @description("Table rotated 90 degrees from normal orientation")
  HIERARCHICAL @description("Table with nested groupings or subtotals")
  MIXED @description("Table with irregular structure or multiple table types combined")
}

enum DataOrientation {
  HORIZONTAL @description("Data flows left to right")
  VERTICAL @description("Data flows top to bottom")
  MIXED @description("Data flows in multiple directions")
}

class TableMetadata {
  pageNumber int @description("Page number where this table appears")
  tableType TableType @description("Classification of table structure")
  dataOrientation DataOrientation @description("Primary direction of data flow")
  hasHeaders bool @description("Whether the table has clear column headers")
  hasSubtotals bool @description("Whether the table contains subtotal or summary rows")
  headerRowIndices int[] @description("Row indices that contain headers (0-based)")
  totalRowIndices int[] @description("Row indices that contain totals or subtotals")
  estimatedColumns int @description("Number of meaningful data columns")
  estimatedRows int @description("Number of meaningful data rows")
  irregularStructure bool @description("Whether the table has merged cells or irregular layout")
  notes string? @description("Any additional observations about the table structure")
}

class FieldDefinition {
  name string @description("Field name")
  type string @description("BAML type (string, int, float, bool, string[], etc.)")
  description string? @description("Optional field description")
  required bool @description("Whether this field is required")
}

class UserSchema {
  className string @description("Name for the generated class")
  fields FieldDefinition[] @description("List of field definitions")
}

function AnalyzeTableStructure(markdownTable: string, pageContext: string?) -> TableMetadata {
  client CustomGPT4oMini
  prompt #"
    Analyze the structure and characteristics of this markdown table extracted from OCR.

    Focus on:
    - Table type and orientation (REGULAR, PIVOTED, TRANSPOSED, HIERARCHICAL, or MIXED)
    - Location of headers and totals (provide row indices, 0-based)
    - Data flow patterns (HORIZONTAL, VERTICAL, or MIXED)
    - Structural irregularities (merged cells, uneven columns, etc.)

    Important:
    - Look for rows that contain totals or subtotals (keywords: "Total", "Subtotal", "Sum", etc.)
    - Identify header rows (typically at the top, containing column names)
    - Count meaningful data rows (exclude headers, totals, empty rows)
    - Detect hierarchical grouping (empty cells that indicate grouped data)

    {{ ctx.output_format }}

    {{ _.role("user") }}
    {% if pageContext %}Page Context: {{ pageContext }}{% endif %}

    Markdown Table:
    {{ markdownTable }}
  "#
}

// Generate normalized table from markdown - standard version
function GenerateNormalizedTable(
  markdownTable: string,
  metadata: TableMetadata,
  userSchema: UserSchema
) -> string {
  client CustomGPT4o
  prompt #"
    Convert this markdown table to 1NF (First Normal Form).

    Table Metadata:
    - Type: {{ metadata.tableType }}
    - Headers at rows: {{ metadata.headerRowIndices }}
    - Totals at rows: {{ metadata.totalRowIndices }}
    - Has subtotals: {{ metadata.hasSubtotals }}

    Target Schema ({{ userSchema.className }}):
    {% for field in userSchema.fields %}
    - {{ field.name }}: {{ field.type }} — {{ field.description }}
    {% endfor %}

    OCR MERGED CELL RECOVERY:
    Resolve merged cells by splitting content and assigning to correct fields:
    - Identify cells with multiple values by comparing column count to header
    - Split by type boundaries and match each part to field descriptions
    - Assign split values to adjacent empty fields that match the type

    VALIDATION:
    Use "note" only for truly unresolvable anomalies:
    - Resolve what can be resolved based on type matching
    - Field descriptions define the contract
    - Only null + note when data cannot be recovered

    EXTRACTION:
    1. Extract EVERY data row - no truncation
    2. Skip headers, totals, empty rows
    3. Carry forward group values for hierarchical tables
    4. Parse numbers: remove commas
    5. Return ONLY valid JSON array

    {{ _.role("user") }}
    {{ markdownTable }}
  "#
}

// Fast generation for dense uniform tables - uses TOON format for efficiency
// TOON = pipe-delimited compact format, ~30-50% fewer tokens
function GenerateNormalizedTableFast(
  toonTable: string,
  userSchema: UserSchema,
  groupContext: string?
) -> string {
  client CustomGPT4o
  prompt #"
    Convert this TOON-format table data to JSON array.
    TOON format: pipe-delimited rows, first row is headers.

    Schema ({{ userSchema.className }}):
    {% for field in userSchema.fields %}
    {{ field.name }}: {{ field.type }} — {{ field.description }}
    {% endfor %}

    {% if groupContext %}
    Context (apply to all rows): {{ groupContext }}
    {% endif %}

    MERGED CELL RECOVERY:
    Resolve merged cells by splitting content and assigning to correct fields:
    - Identify cells with multiple values by comparing column count to header
    - Split by type boundaries and match each part to field descriptions
    - Assign split values to adjacent empty fields that match the type

    VALIDATION:
    Use "note" only for truly unresolvable anomalies:
    - Resolve what can be resolved based on type matching
    - Field descriptions define the contract
    - Only null + note when data cannot be recovered

    EXTRACTION:
    - Extract ALL rows, no truncation
    - Skip totals/subtotals
    - Parse numbers: remove commas
    - Output: JSON array only

    {{ _.role("user") }}
    {{ toonTable }}
  "#
}

// Process a chunk of table rows (for parallel chunking)
function GenerateNormalizedTableChunk(
  toonChunk: string,
  userSchema: UserSchema,
  chunkIndex: int,
  groupContext: string?
) -> string {
  client CustomGPT4o
  prompt #"
    Convert this table chunk (chunk {{ chunkIndex }}) to JSON array.
    Format: pipe-delimited, first row is headers.

    Schema ({{ userSchema.className }}):
    {% for field in userSchema.fields %}
    {{ field.name }}: {{ field.type }} — {{ field.description }}
    {% endfor %}

    {% if groupContext %}
    Apply to all rows: {{ groupContext }}
    {% endif %}

    MERGED CELL RECOVERY:
    Resolve merged cells by splitting content and assigning to correct fields:
    - Identify cells with multiple values by comparing column count to header
    - Split by type boundaries and match each part to field descriptions
    - Assign split values to adjacent empty fields that match the type

    VALIDATION:
    Use "note" only for truly unresolvable anomalies:
    - Resolve what can be resolved based on type matching
    - Field descriptions define the contract
    - Only null + note when data cannot be recovered

    EXTRACTION:
    - Extract ALL rows in this chunk
    - Skip totals
    - Parse numbers: remove commas
    - Output: JSON array only

    {{ _.role("user") }}
    {{ toonChunk }}
  "#
}

// Review and complete extraction - ensures no rows are missing
function ReviewAndCompleteExtraction(
  markdownTable: string,
  extractedJson: string,
  metadata: TableMetadata,
  userSchema: UserSchema
) -> string {
  client CustomGPT4o
  prompt #"
    Review extracted JSON against source markdown. Output COMPLETE, CORRECTED JSON array.

    Table Metadata:
    - Type: {{ metadata.tableType }}
    - Estimated data rows: {{ metadata.estimatedRows }}
    - Header rows (skip): {{ metadata.headerRowIndices }}
    - Total/subtotal rows (skip): {{ metadata.totalRowIndices }}

    Target Schema ({{ userSchema.className }}):
    {% for field in userSchema.fields %}
    - {{ field.name }}: {{ field.type }} — {{ field.description }}
    {% endfor %}

    REVIEW TASK:
    1. Compare source markdown ROW BY ROW against extracted JSON
    2. For each data row: if MISSING, extract and add; if PRESENT, verify correctness
    3. Output COMPLETE JSON array with ALL data rows

    MERGED CELL RECOVERY:
    Resolve merged cells by splitting content and assigning to correct fields:
    - Identify cells with multiple values by comparing column count to header
    - Split by type boundaries and match each part to field descriptions
    - Assign split values to adjacent empty fields that match the type

    VALIDATION:
    Use "note" only for truly unresolvable anomalies:
    - Resolve what can be resolved based on type matching
    - Field descriptions define the contract
    - Only null + note when data cannot be recovered

    RULES:
    - Output valid JSON array only
    - Every data row must appear
    - Carry forward group values for hierarchical tables
    - Parse numbers: remove commas
    - Add missing rows - do not just report them

    Output: JSON array only, no explanations, no markdown.

    {{ _.role("user") }}
    === SOURCE MARKDOWN ===
    {{ markdownTable }}

    === EXTRACTED JSON ===
    {{ extractedJson }}

    === CORRECTED OUTPUT ===
  "#
}
