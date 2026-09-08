/**
 * A2UI `Chart` descriptor → `ChartBlockData` adapter (FEAT-527).
 *
 * Pure, unit-tested separately from any Svelte component. Maps the backend
 * adapter's camelCase `Chart` wire props (`parrot.outputs.a2ui.adapters.
 * infographic._chart()`) plus its resolved data-model rows (bound via
 * `{"path": "/charts/<key>"}`, one dict per row: `{label: <x-value>,
 * <seriesName>: value, ...}` — the x column is ALWAYS named `"label"`,
 * see `_X_COLUMN` in `adapters/infographic.py`) into the shape
 * `InfographicChartBlock.svelte` already renders (`ChartBlockData`).
 */
import { resolveBinding } from './a2ui-binding';
import type { ChartBlockData, ChartSeriesItem, ChartType } from '../infographic/infographic-types';

/** A2UI `Chart` type vocabulary is a superset of the legacy `ChartType`
 * (FEAT-527 parity: same 12 members, camelCase `horizontalBar` aside,
 * which `InfographicChartBlock` does not model — falls back to `bar`). */
const KNOWN_CHART_TYPES: ReadonlySet<string> = new Set<ChartType>([
  'bar',
  'line',
  'pie',
  'donut',
  'area',
  'scatter',
  'radar',
  'heatmap',
  'treemap',
  'funnel',
  'gauge',
  'waterfall',
]);

function toChartType(raw: unknown): ChartType {
  return typeof raw === 'string' && KNOWN_CHART_TYPES.has(raw) ? (raw as ChartType) : 'bar';
}

/**
 * Build `ChartBlockData` from a resolved (post-`resolveProps`) `Chart`
 * descriptor's properties and the envelope's data model.
 *
 * @param properties - The `Chart` descriptor's `properties` (unresolved —
 *   `data` may still be a `{"path": ...}` binding).
 * @param dataModel - The envelope's flat data model, for resolving `data`.
 * @returns `ChartBlockData` ready for `InfographicChartBlock`.
 */
export function toChartBlockData(
  properties: Record<string, unknown>,
  dataModel: Record<string, unknown>,
): ChartBlockData {
  const x = typeof properties.x === 'string' ? properties.x : 'label';
  const yCols = Array.isArray(properties.y) ? (properties.y as string[]) : [];
  const rawRows = resolveBinding(properties.data, dataModel);
  const rows: Record<string, unknown>[] = Array.isArray(rawRows)
    ? (rawRows as Record<string, unknown>[])
    : [];

  const labels = rows.map((row) => String(row?.[x] ?? ''));
  const palette = Array.isArray(properties.palette) ? (properties.palette as string[]) : undefined;
  const series: ChartSeriesItem[] = yCols.map((col, i) => {
    const item: ChartSeriesItem = {
      name: col,
      values: rows.map((row) => {
        const v = row?.[col];
        return typeof v === 'number' ? v : v === null || v === undefined ? null : Number(v);
      }),
    };
    if (palette?.[i] !== undefined) item.color = palette[i];
    return item;
  });

  const data: ChartBlockData = {
    chart_type: toChartType(properties.type),
    labels,
    series,
  };
  if (typeof properties.title === 'string') data.title = properties.title;
  if (typeof properties.description === 'string') data.description = properties.description;
  if (typeof properties.xAxisLabel === 'string') data.x_axis_label = properties.xAxisLabel;
  if (typeof properties.yAxisLabel === 'string') data.y_axis_label = properties.yAxisLabel;
  if (typeof properties.stacked === 'boolean') data.stacked = properties.stacked;
  if (typeof properties.showLegend === 'boolean') data.show_legend = properties.showLegend;
  if (properties.layout === 'full' || properties.layout === 'half') data.layout = properties.layout;
  if (typeof properties.colorBySign === 'boolean') data.color_by_sign = properties.colorBySign;
  if (typeof properties.positiveColor === 'string') data.positive_color = properties.positiveColor;
  if (typeof properties.negativeColor === 'string') data.negative_color = properties.negativeColor;
  return data;
}
