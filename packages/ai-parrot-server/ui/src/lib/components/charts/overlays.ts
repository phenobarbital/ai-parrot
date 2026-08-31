/**
 * Shared overlay math helpers + overlay-layer descriptors for AppChart.
 *
 * These pure functions are used by:
 *   - AppChart.svelte  (LayerChart-based rendering)
 *   - DataChart.svelte (Chart.js-based rendering, until Phase-3 migration)
 *
 * No library dependencies — only plain TypeScript.
 */

// ── Pure math helpers ─────────────────────────────────────────────────────────

/** Compute the median of a numeric array. Returns 0 for empty input. */
export function computeMedian(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 !== 0
    ? sorted[mid]
    : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** Compute simple linear regression (least-squares) over index-based X. */
export function linearRegression(values: number[]): {
  slope: number;
  intercept: number;
} {
  const n = values.length;
  if (n < 2) return { slope: 0, intercept: values[0] ?? 0 };
  const sumX = (n * (n - 1)) / 2;
  const sumY = values.reduce((a, b) => a + b, 0);
  const sumXY = values.reduce((sum, y, x) => sum + x * y, 0);
  const sumX2 = values.reduce((sum, _, x) => sum + x * x, 0);
  const denom = n * sumX2 - sumX * sumX;
  if (denom === 0) return { slope: 0, intercept: sumY / n };
  const slope = (n * sumXY - sumX * sumY) / denom;
  const intercept = (sumY - slope * sumX) / n;
  return { slope, intercept };
}

/**
 * Return the trendline value for each position in `values`.
 * The result has the same length and can be plotted as a series.
 */
export function computeTrendlineValues(values: number[]): number[] {
  const { slope, intercept } = linearRegression(values);
  return values.map((_, i) => intercept + slope * i);
}

// ── Overlay-layer descriptor types ───────────────────────────────────────────

/** A horizontal median line to overlay on a cartesian chart. */
export interface MedianOverlay {
  kind: "median";
  /** The computed median value (Y axis). */
  value: number;
  /** Series key this overlay belongs to (used for color). */
  seriesKey: string;
  /** Resolved color string for the line. */
  color: string;
}

/** A trendline to overlay on a cartesian chart. */
export interface TrendlineOverlay {
  kind: "trendline";
  /**
   * Data array with the same x-values as the source series but with the
   * trend Y values stored under `_trend`.  The chart's existing x accessor
   * picks up the correct x value; the Spline is told `y="_trend"`.
   */
  trendData: Record<string, unknown>[];
  /** Series key this overlay belongs to. */
  seriesKey: string;
  /** Resolved color string for the line. */
  color: string;
}

export type Overlay = MedianOverlay | TrendlineOverlay;

// ── Factory helpers ───────────────────────────────────────────────────────────

/**
 * Build overlay descriptors for a set of series + chart data.
 *
 * @param rows   The chart data rows.
 * @param seriesDefs  Array of `{ key, color }` series definitions.
 * @param wantTrendline  Whether trendline overlays are requested.
 * @param wantMedian     Whether median overlays are requested.
 * @returns Array of Overlay descriptors, ready for AppChart to render.
 */
export function buildOverlays(
  rows: Record<string, unknown>[],
  seriesDefs: { key: string; color: string }[],
  wantTrendline: boolean,
  wantMedian: boolean,
): Overlay[] {
  const overlays: Overlay[] = [];
  if (!rows.length) return overlays;

  for (const s of seriesDefs) {
    const values = rows.map((d) => Number(d[s.key]) || 0);

    if (wantTrendline) {
      const trendValues = computeTrendlineValues(values);
      const trendData = rows.map((d, i) => ({
        ...d,
        _trend: trendValues[i],
      }));
      overlays.push({
        kind: "trendline",
        trendData,
        seriesKey: s.key,
        color: s.color,
      });
    }

    if (wantMedian) {
      overlays.push({
        kind: "median",
        value: computeMedian(values),
        seriesKey: s.key,
        color: s.color,
      });
    }
  }

  return overlays;
}
