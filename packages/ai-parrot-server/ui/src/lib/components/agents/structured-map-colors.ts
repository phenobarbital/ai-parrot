/**
 * structured-map-colors — pure color-resolution + persistence helpers for the
 * STRUCTURED_MAP renderer (StructuredMap.svelte).
 *
 * Color model (per layer, on every render):
 *
 *     effectiveColor(layer) = userOverride[layerId]
 *                             ?? config.markerColor   (when valid)
 *                             ?? defaultPalette[index]
 *
 * The backend `markerColor` is only the INITIAL value. A manual user override
 * wins and persists per layer (localStorage), even if a later backend response
 * ships a different color. "Reset" clears the override (and its stored value),
 * falling back to the backend color, then the default palette.
 *
 * Overrides are namespaced by `<chatbotId>:<layerId>` so the same layer id
 * (e.g. "schools") across different agents/maps does not collide, while still
 * persisting across sessions for the same agent.
 */
import { browser } from "$app/environment";

/**
 * Closed set of canonical CSS color names accepted from the backend
 * (mirrors `_NAMED_COLORS` in ai-parrot `structured_map.py`).
 */
export const CANONICAL_COLORS = [
  "red",
  "blue",
  "green",
  "orange",
  "purple",
  "yellow",
  "pink",
  "brown",
  "black",
  "white",
  "gray",
  "grey",
  "cyan",
  "magenta",
  "teal",
  "navy",
  "lime",
  "olive",
  "maroon",
  "gold",
  "violet",
  "indigo",
  "turquoise",
  "darkred",
  "darkblue",
  "darkgreen",
  "lightblue",
  "lightgreen",
] as const;

/** Curated, visually-distinct subset rendered as clickable swatches in the toolbar. */
export const SWATCH_COLORS = [
  "red",
  "blue",
  "green",
  "orange",
  "purple",
  "yellow",
  "pink",
  "brown",
  "teal",
  "navy",
  "gray",
  "black",
  "cyan",
  "magenta",
  "lime",
  "gold",
] as const;

/** Default per-layer palette, keyed by layer index (matches the legacy LAYER_COLORS). */
export const DEFAULT_PALETTE = [
  "#3b82f6",
  "#ef4444",
  "#22c55e",
  "#f97316",
  "#a855f7",
  "#06b6d4",
] as const;

const NAMED = new Set<string>(CANONICAL_COLORS);
const HEX_RE = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

/** True for a canonical CSS color name or a 3-/6-digit hex string. */
export function isValidColor(v: unknown): v is string {
  if (typeof v !== "string") return false;
  const s = v.trim();
  return HEX_RE.test(s) || NAMED.has(s.toLowerCase());
}

/** Default color for a layer at the given index (cycles through the palette). */
export function defaultColorForIndex(index: number): string {
  const i =
    ((index % DEFAULT_PALETTE.length) + DEFAULT_PALETTE.length) %
    DEFAULT_PALETTE.length;
  return DEFAULT_PALETTE[i];
}

/** Resolve the effective color: override → config.markerColor → default palette. */
export function resolveEffectiveColor(opts: {
  override?: string | null;
  configColor?: string | null;
  index: number;
}): string {
  const { override, configColor, index } = opts;
  if (isValidColor(override)) return override.trim();
  if (isValidColor(configColor)) return configColor.trim();
  return defaultColorForIndex(index);
}

// ── Persistence (localStorage, namespaced by chatbot + layer) ────────────────

const STORAGE_PREFIX = "navmap:color";

/** Build the localStorage key for a given chatbot + layer pair. */
export function overrideStorageKey(
  chatbotId: string | undefined | null,
  layerId: string,
): string {
  return `${STORAGE_PREFIX}:${chatbotId ?? "_"}:${layerId}`;
}

/** Read a persisted override; returns null when absent, invalid, or unavailable. */
export function loadOverride(
  chatbotId: string | undefined | null,
  layerId: string,
): string | null {
  if (!browser) return null;
  try {
    const v = localStorage.getItem(overrideStorageKey(chatbotId, layerId));
    return isValidColor(v) ? (v as string) : null;
  } catch {
    return null;
  }
}

/** Persist a user override for a layer (only when the color is valid). */
export function saveOverride(
  chatbotId: string | undefined | null,
  layerId: string,
  color: string,
): void {
  if (!browser || !isValidColor(color)) return;
  try {
    localStorage.setItem(overrideStorageKey(chatbotId, layerId), color.trim());
  } catch {
    /* quota exceeded / storage disabled — ignore */
  }
}

/** Remove a persisted override ("reset to default" for that layer). */
export function clearOverride(
  chatbotId: string | undefined | null,
  layerId: string,
): void {
  if (!browser) return;
  try {
    localStorage.removeItem(overrideStorageKey(chatbotId, layerId));
  } catch {
    /* ignore */
  }
}

// ── Marker size (radius) per layer ───────────────────────────────────────────

export const DEFAULT_RADIUS = 9;
export const MIN_RADIUS = 3;
export const MAX_RADIUS = 24;

const SIZE_PREFIX = "navmap:size";

export function isValidSize(n: unknown): n is number {
  return (
    typeof n === "number" &&
    Number.isFinite(n) &&
    n >= MIN_RADIUS &&
    n <= MAX_RADIUS
  );
}

export function sizeStorageKey(
  chatbotId: string | undefined | null,
  layerId: string,
): string {
  return `${SIZE_PREFIX}:${chatbotId ?? "_"}:${layerId}`;
}

/** Read a persisted marker size; null when absent/invalid/unavailable. */
export function loadSize(
  chatbotId: string | undefined | null,
  layerId: string,
): number | null {
  if (!browser) return null;
  try {
    const raw = localStorage.getItem(sizeStorageKey(chatbotId, layerId));
    if (raw == null) return null;
    const n = Number(raw);
    return isValidSize(n) ? n : null;
  } catch {
    return null;
  }
}

/** Persist a marker size override for a layer (only when in range). */
export function saveSize(
  chatbotId: string | undefined | null,
  layerId: string,
  size: number,
): void {
  if (!browser || !isValidSize(size)) return;
  try {
    localStorage.setItem(sizeStorageKey(chatbotId, layerId), String(size));
  } catch {
    /* quota exceeded / storage disabled — ignore */
  }
}

/** Remove a persisted marker size override. */
export function clearSize(
  chatbotId: string | undefined | null,
  layerId: string,
): void {
  if (!browser) return;
  try {
    localStorage.removeItem(sizeStorageKey(chatbotId, layerId));
  } catch {
    /* ignore */
  }
}
