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
  client CustomGPT5Mini
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
  client CustomGPT5
  prompt #"
    Convert this markdown table to 1NF (First Normal Form) with INTELLIGENT merged cell recovery.

    Table Metadata (TOON format for efficiency):
    {{ metadata|format(type="toon", delimiter="pipe") }}

    Target Schema:
    Class: {{ userSchema.className }}
    Fields:
    {{ userSchema.fields|format(type="toon", delimiter="pipe") }}

    SMART MERGED CELL RECOVERY STRATEGY:
    
    1. PATTERN ANALYSIS - Before processing any row, analyze the ENTIRE table:
       - Count columns in each row to identify inconsistencies
       - Look for rows with fewer cells than expected (likely merged cells)
       - Identify patterns: if row 5 has 3 cells but others have 5, cells are likely merged
       - Find "anchor rows" (complete rows with all expected columns) to use as templates
    
    2. CONTEXTUAL HEALING - Use surrounding rows to infer merged cell content:
       - If a row has missing cells, look at rows above/below for clues
       - Example: If row N has "John Doe 2023-01-15" in one cell, but row N-1 has "Jane Smith" and "2023-01-14" in separate cells, split accordingly
       - Use column alignment patterns from complete rows to guide splitting
    
    3. SEMANTIC SPLITTING - When a cell contains multiple values:
       - Analyze the DATA TYPES expected in each column (from schema)
       - Split based on type patterns: dates, numbers, text, codes, etc.
       - Example: "ABC123 John Doe 45.50 2023-01-15" → split into [code, name, amount, date] based on schema types
       - Use whitespace, punctuation, and format patterns as splitting hints
    
    4. HIERARCHICAL CONTEXT - For grouped/hierarchical tables:
       - Identify group headers vs detail rows
       - Carry forward group values to detail rows (fill empty cells with parent values)
       - Example: If "Department: Sales" appears in one row, carry "Sales" to subsequent detail rows
    
    5. VALIDATION CROSS-CHECK:
       - After splitting, verify each row has the expected number of fields
       - Check if data types match schema expectations
       - If a split doesn't work, try alternative splitting strategies
       - Use majority patterns from other rows to validate your approach

    STEP-BY-STEP PROCESS:
    
    Step 1: TABLE STRUCTURE ANALYSIS
    - Scan ALL rows and count cells per row
    - Identify the expected column count from complete rows
    - Mark rows that need healing (fewer cells than expected)
    - Note any hierarchical patterns or groupings

    Step 2: REFERENCE PATTERN EXTRACTION  
    - Find 2-3 "perfect" rows that have all expected columns filled correctly
    - Use these as templates for data type patterns and column alignment
    - Extract typical formats for each column (date formats, number formats, etc.)

    Step 3: INTELLIGENT ROW HEALING
    For each problematic row:
    - Compare cell count to expected count
    - Analyze cell content for multiple data types
    - Apply semantic splitting based on schema field types
    - Use reference patterns to guide splitting decisions
    - Cross-validate with adjacent rows for consistency

    Step 4: HIERARCHICAL VALUE PROPAGATION
    - Identify group/category rows vs detail rows  
    - Propagate group values down to detail rows
    - Fill empty cells with appropriate parent/group values

    EXAMPLES OF SMART HEALING:

    Example 1 - Merged Name and Date:
    Problematic row: | "John Doe 2023-01-15" | "Manager" | "50000" |
    Schema expects: | name | date | title | salary |
    Smart split: | "John Doe" | "2023-01-15" | "Manager" | "50000" |

    Example 2 - Hierarchical Grouping:
    Row 1: | "Sales Department" | "" | "" | "" |
    Row 2: | "John Doe" | "Manager" | "50000" |
    Row 3: | "Jane Smith" | "Associate" | "35000" |
    Healed:
    Row 2: | "John Doe" | "Manager" | "50000" | "Sales Department" |
    Row 3: | "Jane Smith" | "Associate" | "35000" | "Sales Department" |

    Example 3 - Multiple Values in One Cell:
    Problematic: | "EMP001 John Doe Manager 2023-01-15 50000" |
    Schema: | employee_id | name | title | start_date | salary |
    Smart split: | "EMP001" | "John Doe" | "Manager" | "2023-01-15" | "50000" |

    PROCESSING INSTRUCTIONS:
    1. CRITICAL: Extract EVERY meaningful data row - do NOT stop early or truncate
    2. Skip header rows (indices: {{ metadata.headerRowIndices|format(type="toon") }}) and total rows (indices: {{ metadata.totalRowIndices|format(type="toon") }})
    3. Apply smart healing to ALL rows that need it
    4. Map healed data to schema fields by semantic matching AND positional alignment
    5. Convert data types as needed (dates, numbers, booleans)
    6. Parse numeric values with commas (e.g., "30,000" -> 30000)
    7. Handle missing data with null or appropriate defaults
    8. Return ONLY a valid JSON array of objects matching the schema

    QUALITY CHECKS:
    - Every output record must have the same number of fields as the schema
    - Data types should match schema expectations
    - No information should be lost during healing
    - Hierarchical relationships should be preserved

    Output format: JSON array of objects with keys matching field names

    REMINDER: You MUST extract ALL rows. Use the entire table context to make intelligent healing decisions.

    {{ _.role("user") }}
    Markdown Table:
    {{ markdownTable }}
  "#
}

// =============================================================================
// LINE-BY-LINE TABLE PROCESSING
// =============================================================================

enum RowType {
  HEADER @description("Column header row")
  DATA @description("Regular data row")
  TOTAL @description("Total or subtotal row")
  GROUP_HEADER @description("Group/category label row spanning columns")
  SEPARATOR @description("Separator row (dashes, equals, etc.)")
  TITLE @description("Table title or caption row")
  EMPTY @description("Empty or whitespace-only row")
}

class ParsedTableRow {
  rowIndex int @description("0-based row index from the original table")
  rowType RowType @description("Classification of this row")
  cells string[] @description("Parsed cell values, one per expected column. Split merged cells to match expectedColumns count.")
  confidence float @description("Confidence score 0.0-1.0 for this parse")
  groupLabel string? @description("If rowType is GROUP_HEADER, the group/category label")
  totalLabel string? @description("If rowType is TOTAL, the total label (e.g. 'Subtotal', 'Grand Total')")
  notes string? @description("Any observations about merged cells, splitting decisions, or data quality")
}

function ParseSingleTableLine(
  markdownLine: string,
  rowIndex: int,
  expectedColumns: int,
  columnNames: string[],
  fieldTypes: string[]
) -> ParsedTableRow {
  client CustomGPT5Mini
  prompt #"
    Parse this single markdown table line into structured cells.

    Row index: {{ rowIndex }}
    Expected columns: {{ expectedColumns }}
    Column names: {{ columnNames }}
    Field types: {{ fieldTypes }}

    INSTRUCTIONS:
    1. CLASSIFY the row type (HEADER, DATA, TOTAL, GROUP_HEADER, SEPARATOR, TITLE, EMPTY)
    2. SPLIT the line into exactly {{ expectedColumns }} cells
    3. If the line has FEWER pipe-separated values than expected, cells are likely merged:
       - Use field types and column names to determine where to split
       - Example: "John Doe 2023-01-15 Manager" with types [string, string, string] and names [name, date, title]
         → split into ["John Doe", "2023-01-15", "Manager"]
    4. If the line has MORE pipe-separated values than expected, merge adjacent cells
    5. Clean cell values: trim whitespace, remove stray pipes
    6. For TOTAL rows: identify the total label (e.g., "Total", "Subtotal")
    7. For GROUP_HEADER rows: extract the group label
    8. Set confidence based on how certain you are about the parse (1.0 = perfect pipe-delimited row, 0.5 = had to split/merge)

    {{ ctx.output_format }}

    {{ _.role("user") }}
    Markdown line:
    {{ markdownLine }}
  "#
}

function CombineParsedRows(
  parsedRows: ParsedTableRow[],
  columnNames: string[],
  userSchema: UserSchema
) -> string {
  client CustomGPT5Mini
  prompt #"
    Combine these individually-parsed table rows into a final JSON array.

    Column names: {{ columnNames }}

    Target Schema:
    Class: {{ userSchema.className }}
    Fields:
    {{ userSchema.fields|format(type="toon", delimiter="pipe") }}

    Parsed rows (TOON format):
    {{ parsedRows|format(type="toon", delimiter="pipe") }}

    INSTRUCTIONS:
    1. FILTER: Keep only rows where rowType is DATA. Skip HEADER, SEPARATOR, TITLE, EMPTY rows.
    2. TOTAL ROWS: Skip TOTAL rows (they are summary rows, not data).
    3. HIERARCHICAL CARRY-FORWARD: For GROUP_HEADER rows, carry the groupLabel forward
       to all subsequent DATA rows until the next GROUP_HEADER. Map the group label to the
       appropriate schema field.
    4. MAP cells to schema fields by position (cells[0] → first field, cells[1] → second field, etc.)
    5. TYPE CONVERSION:
       - "int" fields: parse integers, remove commas (e.g., "1,234" → 1234)
       - "float" fields: parse floats, remove commas (e.g., "1,234.56" → 1234.56)
       - "bool" fields: parse booleans
       - "string" fields: keep as-is, trim whitespace
       - Empty/blank cells → null
    6. Return ONLY a valid JSON array of objects matching the schema field names.

    QUALITY CHECKS:
    - Every record must have all schema fields (use null for missing)
    - No duplicate records
    - Verify type conversions are correct

    {{ _.role("user") }}
    Combine the parsed rows into the final JSON array.
  "#
}
