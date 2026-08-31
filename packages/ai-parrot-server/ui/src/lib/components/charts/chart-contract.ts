export type ChartType =
  | "bar"
  | "horizontalBar"
  | "line"
  | "area"
  | "scatter"
  | "pie"
  | "donut"
  | "radar"
  | "map";

export interface AppChartConfig {
  type: ChartType;
  x: string;
  y: string[];
  stacked?: boolean;
  trendline?: boolean;
  median?: boolean;
  splitSeries?: boolean;
  showLegend?: boolean;
  xAxisMode?: "category" | "time";
  palette?: string[];
  /** Bar charts only: color each bar by the sign of its value (positive vs negative). */
  colorBySign?: boolean;
  /** Color for negative bars when colorBySign is active (defaults to --color-error). */
  negativeColor?: string;
  /** Optional short chart title (used as the chat card header). */
  title?: string;
  /** Optional one-paragraph summary of the chart (shown as the message text). */
  description?: string;
}
