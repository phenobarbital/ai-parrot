/**
 * Infographic Block Types — FEAT-039
 * TypeScript type definitions for the infographic block system.
 * Mirrors the backend API contract (docs/infographic_handler_api.md, section 8).
 */

// ─── Discriminated Union Types ────────────────────────────────────────────────

export type InfographicBlockType =
  | "title"
  | "hero_card"
  | "summary"
  | "chart"
  | "bullet_list"
  | "table"
  | "image"
  | "quote"
  | "callout"
  | "divider"
  | "timeline"
  | "progress";

export type ChartType =
  | "bar"
  | "line"
  | "pie"
  | "donut"
  | "area"
  | "scatter"
  | "radar"
  | "heatmap"
  | "treemap"
  | "funnel"
  | "gauge"
  | "waterfall";

export type TrendDirection = "up" | "down" | "flat";

export type CalloutLevel = "info" | "success" | "warning" | "error" | "tip";

// ─── Per-Block Data Interfaces ────────────────────────────────────────────────

export interface TitleBlockData {
  title: string;
  subtitle?: string;
  author?: string;
  date?: string;
  logo_url?: string;
}

export interface HeroCardBlockData {
  label: string;
  value: string | number;
  icon?: string;
  trend?: TrendDirection;
  trend_value?: string | number;
  comparison_period?: string;
  color?: string;
}

export interface SummaryBlockData {
  title?: string;
  content: string;
  highlight?: boolean;
}

export interface ChartSeriesItem {
  name: string;
  values: (number | null)[];
  /** Optional per-series color (CSS value). Used when not coloring by sign. */
  color?: string;
}

export interface ChartBlockData {
  chart_type: ChartType;
  title?: string;
  description?: string;
  labels: string[];
  series: ChartSeriesItem[];
  x_axis_label?: string;
  y_axis_label?: string;
  stacked?: boolean;
  show_legend?: boolean;
  /** Layout hint: 'half' renders side-by-side in a 2-column grid; 'full' (default) full-width. */
  layout?: "full" | "half";
  /**
   * When true, each data point is colored by the sign of its value
   * (positive vs negative) instead of by series. Intended for
   * variance/delta charts (bar/waterfall).
   */
  color_by_sign?: boolean;
  /** Override color for positive values when `color_by_sign` is on. Falls back to theme. */
  positive_color?: string;
  /** Override color for negative values when `color_by_sign` is on. Falls back to theme. */
  negative_color?: string;
}

export interface BulletListBlockData {
  title?: string;
  items: string[];
  ordered?: boolean;
}

export interface TableBlockData {
  title?: string;
  columns: string[];
  rows: unknown[][];
  highlight_first_column?: boolean;
  sortable?: boolean;
}

export interface ImageBlockData {
  url: string;
  alt?: string;
  caption?: string;
  width?: string | number;
  height?: string | number;
}

export interface QuoteBlockData {
  text: string;
  author?: string;
  source?: string;
}

export interface CalloutBlockData {
  level: CalloutLevel;
  title?: string;
  content: string;
}

export interface DividerBlockData {
  style?: "solid" | "dashed" | "dotted";
  label?: string;
}

export interface TimelineItem {
  date?: string;
  title: string;
  description?: string;
  icon?: string;
  color?: string;
}

export interface TimelineBlockData {
  title?: string;
  items: TimelineItem[];
}

export interface ProgressItem {
  label: string;
  value: number;
  max?: number;
  color?: string;
}

export interface ProgressBlockData {
  title?: string;
  items: ProgressItem[];
}

// ─── Discriminated Union ──────────────────────────────────────────────────────

export type InfographicBlock =
  | ({ type: "title" } & TitleBlockData)
  | ({ type: "hero_card" } & HeroCardBlockData)
  | ({ type: "summary" } & SummaryBlockData)
  | ({ type: "chart" } & ChartBlockData)
  | ({ type: "bullet_list" } & BulletListBlockData)
  | ({ type: "table" } & TableBlockData)
  | ({ type: "image" } & ImageBlockData)
  | ({ type: "quote" } & QuoteBlockData)
  | ({ type: "callout" } & CalloutBlockData)
  | ({ type: "divider" } & DividerBlockData)
  | ({ type: "timeline" } & TimelineBlockData)
  | ({ type: "progress" } & ProgressBlockData);

// ─── Envelope ─────────────────────────────────────────────────────────────────

export interface InfographicData {
  template?: string;
  theme?: string;
  blocks: InfographicBlock[];
  metadata?: Record<string, unknown>;
}

// ─── API Request / Response Types ─────────────────────────────────────────────

export interface InfographicGenerateParams {
  query: string;
  template?: string;
  theme?: string;
  session_id?: string;
  user_id?: string;
}

export interface InfographicJsonResponse {
  infographic: InfographicData;
}

export interface TemplateItem {
  name: string;
  description?: string;
}

export interface TemplateListResponse {
  templates: string[] | TemplateItem[];
}

export interface TemplateDetailResponse {
  template: {
    name: string;
    description?: string;
    block_specs?: unknown[];
    default_theme?: string;
  };
}

export interface ThemeItem {
  name: string;
  primary?: string;
  neutral_bg?: string;
  body_bg?: string;
}

export interface ThemeListResponse {
  themes: string[] | ThemeItem[];
}

export interface ThemeDetailResponse {
  theme: {
    name: string;
    primary?: string;
    neutral_bg?: string;
    body_bg?: string;
    font_family?: string;
    [key: string]: unknown;
  };
}

// ─── Tab Data ─────────────────────────────────────────────────────────────────

export interface InfographicTabData {
  mode: "json" | "html";
  html?: string;
  /**
   * URL of a backend-rendered infographic artifact. When present (with
   * mode 'html'), the canvas loads it directly into an iframe via `src`
   * instead of rendering inline `html` via `srcdoc`.
   */
  url?: string;
  infographic?: InfographicData;
  query?: string;
  template?: string;
  theme?: string;
}
