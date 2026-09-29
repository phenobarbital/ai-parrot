/**
 * A2UI display-format hints (FEAT-611).
 *
 * Pure, unit-tested helper applied by `A2UINode.svelte` to `KPICard.value`
 * (`format` + `unit`, `catalog/parrot/kpicard.py`) and to `DataTable`
 * cells (`columns[].format`, `parrot.models.outputs.TableColumn`).
 * `percent` means the value is a RATIO (0.683 → "68.3%") — renderers never
 * guess a number's meaning from its label. Values that are not numeric
 * (or formats this helper does not model, e.g. `email`/`uri`/`id`) pass
 * through unchanged.
 */

/** Display formats this helper renders; any other hint passes the value through. */
export type A2UINumberFormat = 'percent' | 'currency' | 'number';

const ONE_DECIMAL_FMT = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });
const CURRENCY_FMT = new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD' });

/** Return `value` as a finite number (numbers and fully-numeric strings), else `null`. */
function toFiniteNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value === 'string' && value.trim() !== '') {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/**
 * Format one value per an A2UI `format` hint (+ optional `unit`).
 *
 * @param value - The resolved value (number, numeric string, or anything else).
 * @param format - `percent` (ratio → ×100, max 1 decimal, "%"), `number`
 *   (max 1 fraction digit), `currency` (USD); anything else leaves the number unformatted.
 * @param unit - Appended after a space when present and `format` is not `percent`.
 * @returns The display string for a numeric value; a non-numeric value unchanged.
 */
export function formatA2UIValue(value: unknown, format?: unknown, unit?: unknown): unknown {
  const n = toFiniteNumber(value);
  if (n === null) return value;
  if (format === 'percent') return `${ONE_DECIMAL_FMT.format(n * 100)}%`;
  const hasUnit = typeof unit === 'string' && unit !== '';
  let text: string;
  if (format === 'number') text = ONE_DECIMAL_FMT.format(n);
  else if (format === 'currency') text = CURRENCY_FMT.format(n);
  else if (hasUnit) text = String(value);
  else return value;
  return hasUnit ? `${text} ${unit}` : text;
}
