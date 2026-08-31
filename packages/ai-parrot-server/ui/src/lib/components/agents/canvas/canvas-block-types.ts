/**
 * Canvas Block Types — unified content model for the BlockCanvas system.
 *
 * Replaces the old `string` (markdown) and `{ charts: [] }` (chart) data formats
 * with a heterogeneous `CanvasBlock[]` array that supports multiple content types.
 */
import { v4 as uuidv4 } from "uuid";

// ─── Block Type Union ─────────────────────────────────────────────────────────

export type CanvasBlockType =
  | "markdown"
  | "chart"
  | "image"
  | "table"
  | "html"
  | "map"
  | "interactive"
  | "title"
  | "hero_card"
  | "summary"
  | "quote"
  | "callout"
  | "divider"
  | "bullet_list";

// ─── Per-Type Data Interfaces ─────────────────────────────────────────────────

export interface MarkdownBlockData {
  content: string;
}

export interface ChartBlockData {
  data: Record<string, any>[];
  config: {
    type: string;
    x: string;
    y: string[];
    stacked?: boolean;
    trendline?: boolean;
    median?: boolean;
    splitSeries?: boolean;
    title?: string;
    showLegend?: boolean;
    xAxisMode?: "category" | "time";
    // Map-specific fields (for map blocks stored as chart type)
    mapLatColumn?: string;
    mapLngColumn?: string;
    mapLabelColumns?: string[];
    mapLabelColumn?: string;
    mapMarkerColor?: string;
  };
}

export interface ImageBlockData {
  url: string;
  alt?: string;
  caption?: string;
}

export interface TableBlockData {
  rows: Record<string, unknown>[];
  columns?: string[];
}

export interface HtmlBlockData {
  html: string;
}

export interface MapBlockData {
  data: Record<string, any>[];
  config: {
    type: string;
    mapLatColumn?: string;
    mapLngColumn?: string;
    mapLabelColumns?: string[];
    mapLabelColumn?: string;
    mapMarkerColor?: string;
    title?: string;
  };
}

export interface InteractiveBlockData {
  placeholder?: string; // Reserved for future use
}

export interface TitleBlockData {
  title: string; // <h1> content
  subtitle?: string; // <h2> content (optional)
}

export interface HeroCardBlockData {
  label: string;
  value: string;
  icon?: string;
  trend?: "up" | "down" | "flat";
  trend_value?: string;
  color?: string;
}

export interface SummaryBlockData {
  title?: string;
  content: string;
  highlight?: boolean;
}

export interface QuoteBlockData {
  text: string;
  author?: string;
  source?: string;
}

export type CalloutLevel = "info" | "success" | "warning" | "error" | "tip";

export interface CalloutBlockData {
  level: CalloutLevel;
  title?: string;
  content: string;
}

export interface DividerBlockData {
  style?: "solid" | "dashed" | "dotted";
  label?: string;
}

export interface BulletListBlockData {
  title?: string;
  items: string[];
  ordered?: boolean;
}

// ─── CanvasBlock Interface ────────────────────────────────────────────────────

export interface CanvasBlock {
  id: string; // UUID
  type: CanvasBlockType;
  data:
    | MarkdownBlockData
    | ChartBlockData
    | ImageBlockData
    | TableBlockData
    | HtmlBlockData
    | MapBlockData
    | InteractiveBlockData
    | TitleBlockData
    | HeroCardBlockData
    | SummaryBlockData
    | QuoteBlockData
    | CalloutBlockData
    | DividerBlockData
    | BulletListBlockData;
  meta?: {
    title?: string;
    collapsed?: boolean;
  };
}

// ─── Helper Functions ─────────────────────────────────────────────────────────

/**
 * Creates a new CanvasBlock with a generated UUID.
 */
export function createBlock(
  type: CanvasBlockType,
  data: CanvasBlock["data"],
): CanvasBlock {
  return {
    id: uuidv4(),
    type,
    data,
  };
}

/**
 * Type guard: returns true if data is a CanvasBlock[].
 * Checks that data is an array where every element has id, type, and data properties.
 */
export function isCanvasBlockArray(data: unknown): data is CanvasBlock[] {
  if (!Array.isArray(data)) return false;
  if (data.length === 0) return true; // empty array is valid CanvasBlock[]
  return data.every(
    (item) =>
      item !== null &&
      typeof item === "object" &&
      "id" in item &&
      "type" in item &&
      "data" in item,
  );
}

/**
 * Migrates a legacy string data format to CanvasBlock[].
 * Returns [] for empty/whitespace strings.
 * Note: '__loading__' sentinel should be handled by the caller before invoking this.
 */
export function migrateStringToBlocks(data: string): CanvasBlock[] {
  if (!data || !data.trim()) return [];
  return [createBlock("markdown", { content: data })];
}

/**
 * Migrates a legacy `{ charts: [] }` format to CanvasBlock[].
 * Each chart entry becomes a chart block.
 */
export function migrateChartArrayToBlocks(data: {
  charts?: Array<{ data: Record<string, any>[]; config: any }>;
}): CanvasBlock[] {
  if (!data?.charts || !Array.isArray(data.charts)) return [];
  return data.charts.map((chart) =>
    createBlock("chart", { data: chart.data, config: chart.config }),
  );
}
