/**
 * Lightweight formula evaluation engine for the SpreadsheetCanvas.
 * Supports: SUM, AVERAGE, COUNT, MIN, MAX, and basic arithmetic with cell references.
 * No external dependencies — pure TypeScript.
 */

export interface FormulaEntry {
  formula: string;
  result: unknown;
}

/** Map of "row:col" → FormulaEntry */
export type FormulaMap = Map<string, FormulaEntry>;

/** Convert a 0-based column index to a spreadsheet letter (0→A, 1→B, ..., 25→Z, 26→AA) */
export function colIndexToLetter(index: number): string {
  let result = "";
  let n = index;
  while (n >= 0) {
    result = String.fromCharCode((n % 26) + 65) + result;
    n = Math.floor(n / 26) - 1;
  }
  return result;
}

/** Convert a spreadsheet letter to a 0-based column index (A→0, B→1, Z→25, AA→26) */
export function letterToColIndex(letter: string): number {
  let result = 0;
  for (let i = 0; i < letter.length; i++) {
    result = result * 26 + (letter.charCodeAt(i) - 64);
  }
  return result - 1;
}

/** Parse a cell reference like "A1" into { col: 0, row: 0 } (0-based) */
export function parseCellRef(ref: string): { col: number; row: number } | null {
  const match = ref.match(/^([A-Z]+)(\d+)$/i);
  if (!match) return null;
  return {
    col: letterToColIndex(match[1].toUpperCase()),
    row: parseInt(match[2], 10) - 1, // 1-based → 0-based
  };
}

/** Expand a range like "A1:A5" into an array of cell references */
function expandRange(range: string): { col: number; row: number }[] {
  const parts = range.split(":");
  if (parts.length !== 2) return [];
  const start = parseCellRef(parts[0].trim());
  const end = parseCellRef(parts[1].trim());
  if (!start || !end) return [];

  const cells: { col: number; row: number }[] = [];
  for (
    let r = Math.min(start.row, end.row);
    r <= Math.max(start.row, end.row);
    r++
  ) {
    for (
      let c = Math.min(start.col, end.col);
      c <= Math.max(start.col, end.col);
      c++
    ) {
      cells.push({ col: c, row: r });
    }
  }
  return cells;
}

/** Get a numeric value from a cell in the data grid */
function getCellValue(
  row: number,
  col: number,
  data: Record<string, unknown>[],
  columnProps: string[],
  formulaMap: FormulaMap,
): number {
  // Check formula map first
  const key = `${row}:${col}`;
  const formulaEntry = formulaMap.get(key);
  if (formulaEntry && typeof formulaEntry.result === "number") {
    return formulaEntry.result;
  }

  // Get from data
  if (row < 0 || row >= data.length) return 0;
  if (col < 0 || col >= columnProps.length) return 0;
  const val = data[row][columnProps[col]];
  const num = Number(val);
  return isNaN(num) ? 0 : num;
}

/** Resolve a range argument to an array of numeric values */
function resolveRangeValues(
  rangeStr: string,
  data: Record<string, unknown>[],
  columnProps: string[],
  formulaMap: FormulaMap,
): number[] {
  const cells = expandRange(rangeStr);
  return cells.map((c) =>
    getCellValue(c.row, c.col, data, columnProps, formulaMap),
  );
}

// ---------------------------------------------------------------------------
// Computed Column & Roll-Up Types
// ---------------------------------------------------------------------------

export type AggregationType =
  | "sum"
  | "average"
  | "min"
  | "max"
  | "count"
  | "distinct_count";

export interface ComputedColumn {
  id: string;
  type: AggregationType;
  sourceColumns: string[];
  label: string;
  prop: string; // e.g. "_computed_sum_1"
}

export interface RollUpRow {
  id: string;
  type: AggregationType;
  sourceColumn: string;
  label: string;
}

// ---------------------------------------------------------------------------
// Row-level aggregation (across multiple columns for a single row)
// ---------------------------------------------------------------------------

/** Aggregate values across multiple columns for a single row. */
export function computeRowAggregation(
  row: Record<string, unknown>,
  sourceColumns: string[],
  type: AggregationType,
): number {
  const rawValues = sourceColumns.map((col) => row[col]);

  // For count/distinct_count, work with raw values
  if (type === "count") {
    return rawValues.filter((v) => v != null && v !== "").length;
  }
  if (type === "distinct_count") {
    const unique = new Set(
      rawValues.filter((v) => v != null && v !== "").map(String),
    );
    return unique.size;
  }

  // Numeric aggregations — parse to numbers, skip NaN
  const nums = rawValues.map((v) => Number(v)).filter((n) => !isNaN(n));

  if (nums.length === 0) return 0;

  switch (type) {
    case "sum":
      return nums.reduce((a, b) => a + b, 0);
    case "average":
      return nums.reduce((a, b) => a + b, 0) / nums.length;
    case "min":
      return Math.min(...nums);
    case "max":
      return Math.max(...nums);
    default:
      return 0;
  }
}

// ---------------------------------------------------------------------------
// Column-level aggregation (down a single column across all rows)
// ---------------------------------------------------------------------------

/** Aggregate values vertically down a single column across all rows. */
export function computeColumnAggregation(
  rows: Record<string, unknown>[],
  sourceColumn: string,
  type: AggregationType,
): number {
  const rawValues = rows.map((row) => row[sourceColumn]);

  if (type === "count") {
    return rawValues.filter((v) => v != null && v !== "").length;
  }
  if (type === "distinct_count") {
    const unique = new Set(
      rawValues.filter((v) => v != null && v !== "").map(String),
    );
    return unique.size;
  }

  const nums = rawValues.map((v) => Number(v)).filter((n) => !isNaN(n));

  if (nums.length === 0) return 0;

  switch (type) {
    case "sum":
      return nums.reduce((a, b) => a + b, 0);
    case "average":
      return nums.reduce((a, b) => a + b, 0) / nums.length;
    case "min":
      return Math.min(...nums);
    case "max":
      return Math.max(...nums);
    default:
      return 0;
  }
}

// ---------------------------------------------------------------------------
// Apply computed columns to rows
// ---------------------------------------------------------------------------

/**
 * Returns a new array where each row has additional properties for each
 * computed column. Does NOT mutate the original rows.
 */
export function applyComputedColumns(
  rows: Record<string, unknown>[],
  computedCols: ComputedColumn[],
): Record<string, unknown>[] {
  if (computedCols.length === 0) return rows;
  return rows.map((row) => {
    const extra: Record<string, unknown> = {};
    for (const cc of computedCols) {
      extra[cc.prop] = computeRowAggregation(row, cc.sourceColumns, cc.type);
    }
    return { ...row, ...extra };
  });
}

// ---------------------------------------------------------------------------
// Build roll-up row
// ---------------------------------------------------------------------------

/**
 * Returns a single summary row object with aggregated values for each
 * roll-up definition. Non-aggregated cells show "—". The row has
 * `__rollup: true` to drive conditional styling.
 */
export function buildRollUpRow(
  rows: Record<string, unknown>[],
  rollUps: RollUpRow[],
  columnKeys: string[],
): Record<string, unknown> {
  // Start with all non-computed column keys set to "—"
  const summaryRow: Record<string, unknown> = { __rollup: true };
  for (const key of columnKeys) {
    summaryRow[key] = "—";
  }

  // Overwrite with aggregated values for each roll-up
  for (const ru of rollUps) {
    summaryRow[ru.sourceColumn] = computeColumnAggregation(
      rows,
      ru.sourceColumn,
      ru.type,
    );
  }

  return summaryRow;
}

// ---------------------------------------------------------------------------
// Formula engine
// ---------------------------------------------------------------------------

/** Evaluate a formula string (starting with =) against the data grid */
export function evaluateFormula(
  formula: string,
  data: Record<string, unknown>[],
  columnProps: string[],
  formulaMap: FormulaMap,
): unknown {
  if (!formula.startsWith("=")) return formula;
  const expr = formula.substring(1).trim();

  try {
    // Try to match function calls: SUM(A1:A5), AVERAGE(B2:B10), DISTINCT_COUNT(A1:A5), etc.
    const funcMatch = expr.match(
      /^(SUM|AVERAGE|AVG|COUNT|DISTINCT_COUNT|MIN|MAX)\((.+)\)$/i,
    );
    if (funcMatch) {
      const func = funcMatch[1].toUpperCase();
      const arg = funcMatch[2].trim();
      const values = resolveRangeValues(arg, data, columnProps, formulaMap);

      switch (func) {
        case "SUM":
          return values.reduce((a, b) => a + b, 0);
        case "AVERAGE":
        case "AVG":
          return values.length > 0
            ? values.reduce((a, b) => a + b, 0) / values.length
            : 0;
        case "COUNT":
          return values.filter((v) => v !== 0).length;
        case "DISTINCT_COUNT":
          return new Set(values.filter((v) => v !== 0)).size;
        case "MIN":
          return values.length > 0 ? Math.min(...values) : 0;
        case "MAX":
          return values.length > 0 ? Math.max(...values) : 0;
        default:
          return "#FUNC?";
      }
    }

    // Replace cell references (A1, B3, etc.) with their numeric values for arithmetic
    const resolved = expr.replace(/([A-Z]+)(\d+)/gi, (_, letters, digits) => {
      const ref = parseCellRef(letters + digits);
      if (!ref) return "0";
      return String(
        getCellValue(ref.row, ref.col, data, columnProps, formulaMap),
      );
    });

    // Evaluate basic arithmetic (only digits, operators, parens, dots, spaces)
    if (/^[\d\s+\-*/().]+$/.test(resolved)) {
      // Use Function constructor instead of eval for slightly better isolation
      const result = new Function(`return (${resolved})`)();
      return typeof result === "number" && isFinite(result) ? result : "#ERR!";
    }

    return "#ERR!";
  } catch {
    return "#ERR!";
  }
}
