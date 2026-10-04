/**
 * Pure dual-axis helpers for AppChart (FEAT-623 TASK-3999).
 * Kept out of the Svelte component so the split/domain rules are unit-testable.
 */

export interface AxisSplit {
  left: string[];
  right: string[];
}

/** Split `y` keys by `seriesAxes` (parallel array; anything but 'right' is left). */
export function splitByAxis(y: string[], seriesAxes?: ("left" | "right" | null)[]): AxisSplit {
  const left: string[] = [];
  const right: string[] = [];
  y.forEach((key, i) => (seriesAxes?.[i] === "right" ? right : left).push(key));
  return { left, right };
}

/**
 * Value domain for `keys`, matching AppChart's floor rule (`yMin` / `yMaxStacked`):
 * stacked → [0, max row sum]; otherwise → [min(0, min value), max(0, max value)].
 */
export function axisDomain(
  data: Record<string, unknown>[],
  keys: string[],
  stacked: boolean,
): [number, number] {
  const num = (v: unknown): number => Number(v) || 0;
  if (stacked) {
    return [0, Math.max(0, ...data.map((d) => keys.reduce((s, k) => s + num(d[k]), 0)))];
  }
  const values = data.flatMap((d) => keys.map((k) => num(d[k])));
  return [Math.min(0, ...values), Math.max(0, ...values)];
}
