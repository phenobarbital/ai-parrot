/**
 * Utilities for parsing numeric values from formatted strings (currency, thousands separators, etc.).
 *
 * Chart.js requires raw numbers. Agent responses may contain formatted values like "$764,539.74"
 * which `Number()` cannot parse. These helpers strip formatting before conversion.
 */

/** Strip currency symbols, thousands separators, and whitespace, then parse to number. */
export function parseNumericValue(raw: unknown): number {
  if (typeof raw === "number") return isNaN(raw) ? 0 : raw;
  if (raw == null) return 0;
  const s = String(raw).trim();
  if (s === "") return 0;
  // Detect negative in parentheses: (1,234.56) → -1234.56
  const isParenNeg = s.startsWith("(") && s.endsWith(")");
  const stripped = isParenNeg ? s.slice(1, -1) : s;
  // Remove everything except digits, dot, minus, plus, e/E (for scientific notation)
  const cleaned = stripped.replace(/[^0-9.\-+eE]/g, "");
  if (cleaned === "") return 0;
  const n = Number(cleaned);
  if (isNaN(n)) return 0;
  return isParenNeg ? -n : n;
}

/**
 * Check if a value looks numeric (actual number or currency/formatted string).
 * Used to detect Y-axis candidates in the chart config UI.
 */
export function isNumericLike(val: unknown): boolean {
  if (typeof val === "number") return true;
  if (typeof val !== "string") return false;
  const s = val.trim();
  if (s === "") return false;
  // Matches patterns like: $1,234.56  €99  -$12.34  (1,234)  1234  +5.0  1.2e3
  return /^[(\-+$€£¥₹₽₩₫₦₪₱¢₴₸₺₼₿R$kr]*[\d][\d,]*\.?\d*[)*%]?$/.test(s);
}
