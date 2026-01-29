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

// Optimized with TOON format for field definitions
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

// Use TOON format for better token efficiency with field arrays
function GenerateNormalizedTable(
  markdownTable: string,
  metadata: TableMetadata,
  userSchema: UserSchema
) -> string {
  client CustomGPT4o
  prompt #"
    Convert this markdown table to 1NF (First Normal Form) based on the provided metadata and user schema.

    Table Metadata (TOON format for efficiency):
    {{ metadata|format(type="toon", delimiter="pipe") }}

    Target Schema:
    Class: {{ userSchema.className }}
    Fields:
    {{ userSchema.fields|format(type="toon", delimiter="pipe") }}

    OCR MERGED CELL RECOVERY:
    Some cells may contain values that belong in adjacent columns. For each row:
    - Count the values vs expected columns
    - If a cell contains multiple types (e.g. a code next to a date), split them
    - Assign each split value to the field matching its type
    - ...
    - ...
    - ...

    Instructions:
    1. CRITICAL: Extract EVERY meaningful data row as a separate record - do NOT stop early or truncate
    2. Skip header rows (indices: {{ metadata.headerRowIndices|format(type="toon") }}), total rows (indices: {{ metadata.totalRowIndices|format(type="toon") }}), and empty rows
    3. Map data to the specified schema fields by position and semantic matching
    4. For hierarchical tables, carry forward group values to detail rows (fill empty cells with values from above)
    5. Convert data types as needed (dates, numbers, booleans)
    6. Parse numeric values with commas (e.g., "30,000" -> 30000)
    7. Handle missing data with null or appropriate defaults
    8. Return ONLY a valid JSON array of objects matching the schema
    9. IMPORTANT: Process the ENTIRE table from start to finish - do not stop until you have extracted ALL data rows

    Output format: JSON array of objects with keys matching field names

    REMINDER: You MUST extract ALL rows. If there are 50 data rows, output 50 records. If there are 100 data rows, output 100 records.

    {{ _.role("user") }}
    Markdown Table:
    {{ markdownTable }}
  "#
}
