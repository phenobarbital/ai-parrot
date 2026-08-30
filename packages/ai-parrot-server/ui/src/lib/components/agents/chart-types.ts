/**
 * Chart type definitions registry — engine-agnostic.
 *
 * This registry describes chart capabilities independently of any rendering
 * library. Individual surfaces (DataChart/Chart.js, AppChart/LayerChart, etc.)
 * maintain their own id→engine-type maps locally.
 *
 * Add new chart types by appending to the `chartTypes` array.
 */

export interface ChartTypeDefinition {
  /** Unique identifier, used as the value in config. */
  id: string;
  /** Human-readable label shown in the toolbar. */
  label: string;
  /** SVG path data for the icon (24×24 viewBox). */
  iconPath: string;
  /** Whether the chart can render multiple Y columns as separate datasets. */
  multiSeries: boolean;
  /** Whether a linear-regression trendline overlay is meaningful. */
  supportsTrendline: boolean;
  /** Whether stacking datasets is meaningful. */
  supportsStacked: boolean;
  /** Axis layout hint for the config UI. */
  axisMode: "cartesian" | "radial" | "none" | "map";
  /** Whether a horizontal median line overlay is meaningful. */
  supportsMedian: boolean;
}

// ─── SVG icon paths (Heroicons 24×24 style) ───────────────────────────

const ICON_BAR = "M3 3v18h18M7 16v-4M11 16V8M15 16v-6M19 16v-8";

const ICON_HORIZONTAL_BAR = "M3 3v18h18M4 7h8M4 11h12M4 15h6M4 19h14";

const ICON_LINE = "M3 3v18h18M4 17l4-6 4 3 4-7 4 4";

const ICON_AREA = "M3 3v18h18M4 17l4-6 4 3 4-7 4 4V20H4z";

const ICON_LINE_SIGNED =
  "M3 12h18M4 12l3-5 3 4 3-6 3 3 3-4M4 12l3 5 3-4 3 6 3-3 3 4";

const ICON_SCATTER =
  "M3 3v18h18M7 14a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM10 9a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM13 12a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM16 7a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM18 10a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM11 16a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM15 14a1 1 0 1 0 0-2 1 1 0 0 0 0 2z";

const ICON_RADAR =
  "M12 2l8.09 5.87-3.09 9.52H7l-3.09-9.52L12 2zM12 2v17.39M3.91 7.87h16.18M7 17.39l5-9.52 5 9.52";

const ICON_PIE = "M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20zM12 2v10h10";

const ICON_DOUGHNUT =
  "M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20zM12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8zM12 2v6M22 12h-6";

const ICON_MAP =
  "M9 6.882l-7-3.5v13.236l7 3.5 6-3 7 3.5V7.382l-7-3.5-6 3zM9 6.882v13.236M15 3.882v13.236";

// ─── Chart Type Definitions ────────────────────────────────────────────

export const chartTypes: ChartTypeDefinition[] = [
  {
    id: "bar",
    label: "Bar",
    iconPath: ICON_BAR,
    multiSeries: true,
    supportsTrendline: false,
    supportsStacked: true,
    supportsMedian: true,
    axisMode: "cartesian",
  },
  {
    id: "horizontalBar",
    label: "Horizontal Bar",
    iconPath: ICON_HORIZONTAL_BAR,
    multiSeries: true,
    supportsTrendline: false,
    supportsStacked: true,
    supportsMedian: true,
    axisMode: "cartesian",
  },
  {
    id: "line",
    label: "Line",
    iconPath: ICON_LINE,
    multiSeries: true,
    supportsTrendline: true,
    supportsStacked: false,
    supportsMedian: true,
    axisMode: "cartesian",
  },
  {
    id: "area",
    label: "Area",
    iconPath: ICON_AREA,
    multiSeries: true,
    supportsTrendline: true,
    supportsStacked: true,
    supportsMedian: true,
    axisMode: "cartesian",
  },
  {
    id: "lineSigned",
    label: "Signed Line",
    iconPath: ICON_LINE_SIGNED,
    multiSeries: true,
    supportsTrendline: true,
    supportsStacked: false,
    supportsMedian: true,
    axisMode: "cartesian",
  },
  {
    id: "scatter",
    label: "Scatter",
    iconPath: ICON_SCATTER,
    multiSeries: true,
    supportsTrendline: true,
    supportsStacked: false,
    supportsMedian: true,
    axisMode: "cartesian",
  },
  {
    id: "radar",
    label: "Radar",
    iconPath: ICON_RADAR,
    multiSeries: true,
    supportsTrendline: false,
    supportsStacked: false,
    supportsMedian: false,
    axisMode: "radial",
  },
  {
    id: "pie",
    label: "Pie",
    iconPath: ICON_PIE,
    multiSeries: false,
    supportsTrendline: false,
    supportsStacked: false,
    supportsMedian: false,
    axisMode: "none",
  },
  {
    id: "doughnut",
    label: "Doughnut",
    iconPath: ICON_DOUGHNUT,
    multiSeries: false,
    supportsTrendline: false,
    supportsStacked: false,
    supportsMedian: false,
    axisMode: "none",
  },
  {
    id: "map",
    label: "Map",
    iconPath: ICON_MAP,
    multiSeries: false,
    supportsTrendline: false,
    supportsStacked: false,
    supportsMedian: false,
    axisMode: "map",
  },
];

/** Look up a chart type definition by its id. */
export function getChartType(id: string): ChartTypeDefinition | undefined {
  return chartTypes.find((ct) => ct.id === id);
}
