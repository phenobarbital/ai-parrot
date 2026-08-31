<script lang="ts">
  /**
   * StructuredMap — renders the framework-agnostic `structured_map` output
   * (ai-parrot FEAT-221/224) on a Leaflet map.
   *
   * `config` is the StructuredMapConfig (serialized `output`): `layers[]`
   * (presentation schema incl. per-layer `markerColor`), `datasets[]`
   * (per-layer GeoJSON/rows payloads — the geometry we paint), `viewport`,
   * `title`. Geometry lives in `config.datasets`; `response.data` (NOT passed
   * here) now carries flat tabular rows for grid/export only.
   *
   * Color model per layer (see structured-map-colors.ts):
   *   effective = userOverride ?? config.markerColor ?? defaultPalette[index]
   * User overrides win, persist per `<chatbotId>:<layerId>` in localStorage,
   * and are editable live via the overlay toolbar (repaint without reload).
   */
  import { onMount, onDestroy } from "svelte";
  import { browser } from "$app/environment";
  import Icon from "@iconify/svelte";
  import "leaflet/dist/leaflet.css";
  import {
    SWATCH_COLORS,
    isValidColor,
    resolveEffectiveColor,
    loadOverride,
    saveOverride,
    clearOverride,
    DEFAULT_RADIUS,
    MIN_RADIUS,
    MAX_RADIUS,
    loadSize,
    saveSize,
    clearSize,
  } from "./structured-map-colors";

  interface Props {
    config: Record<string, any>;
    /**
     * Flat tabular rows from `response.data`. This is the live geometry source:
     * the backend strips `datasets` (per-layer GeoJSON) from the artifact
     * envelope the frontend receives, so rows are what actually reach us.
     * Each row carries `latitude`/`longitude` (Point) or `_geometry`, plus a
     * `layer` discriminator when the map has more than one layer.
     */
    data?: any[];
    /** Agent/chatbot id — namespaces persisted color overrides. */
    chatbotId?: string;
  }
  let { config, data = [], chatbotId }: Props = $props();

  interface LayerMeta {
    id: string;
    index: number;
    configColor: string | null;
    tpl?: string;
    labelField?: string;
    capped: boolean;
    count: number;
    features: any[];
  }

  let mapContainer = $state<HTMLDivElement | null>(null);
  let errored = $state(false);
  /** User color overrides, keyed by layer id; seeded from localStorage. */
  let overrides = $state<Record<string, string>>({});
  /** User marker-size overrides (radius), keyed by layer id. */
  let sizes = $state<Record<string, number>>({});
  let panelOpen = $state(false);

  let mapInstance: any = null;
  let L: any = null;
  /** Layer id → Leaflet GeoJSON layer (non-reactive; used for hot repaint). */
  const gjByLayer = new Map<string, any>();

  const DEFAULT_TILE = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
  const ATTRIBUTION =
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

  /** Per-layer metadata, from config.datasets when present, else response.data rows. */
  let layerMeta = $derived(buildLayerMeta(config, data));

  function makeMeta(
    layerKey: unknown,
    index: number,
    lc: Record<string, any>,
    features: any[],
    truncated: boolean,
  ): LayerMeta {
    return {
      id: String(layerKey ?? `layer-${index}`),
      index,
      configColor: lc?.markerColor ?? lc?.marker_color ?? null,
      tpl: lc?.tooltipTemplate ?? lc?.tooltip_template,
      labelField: lc?.labelField ?? lc?.label_field,
      capped: truncated || Boolean(lc?.capped),
      count: features.length,
      features,
    };
  }

  /** True when entries look like per-layer payload wrappers `{layer, payload}`. */
  function isPayloadWrappers(arr: any[]): boolean {
    return arr.some(
      (e: any) => e && typeof e === "object" && ("payload" in e || "data_shape" in e),
    );
  }

  function buildLayerMeta(cfg: Record<string, any>, rows: any[]): LayerMeta[] {
    const layerCfgs = Array.isArray(cfg?.layers) ? cfg.layers : [];
    const allRows = Array.isArray(rows) ? rows : [];
    const findCfg = (id: unknown): Record<string, any> =>
      layerCfgs.find((l: any) => l?.layer === id) || {};

    // Per-layer payloads: from config.datasets (full contract), else from
    // response.data when it carries `{dataset, layer, data_shape, payload}`
    // wrappers (the live shape — backend routes payloads to response.data and
    // strips `datasets` from the artifact envelope).
    const datasets = Array.isArray(cfg?.datasets) && cfg.datasets.length
      ? cfg.datasets
      : isPayloadWrappers(allRows)
        ? allRows
        : null;

    if (datasets) {
      return datasets.map((entry: any, index: number) => {
        const layerKey = entry?.layer ?? entry?.dataset;
        const lc = findCfg(layerKey);
        const shape = entry?.data_shape ?? entry?.dataShape ?? lc.dataShape ?? "geojson";
        const features = extractFeatures(entry?.payload, shape);
        return makeMeta(layerKey, index, lc, features, Boolean(entry?.payload?.truncated));
      });
    }

    // Fallback: response.data is flat tabular rows (each row has lat/lng or _geometry).
    const multi = layerCfgs.length > 1;
    const sourceLayers = layerCfgs.length ? layerCfgs : [{ layer: "data" }];
    return sourceLayers.map((lc: any, index: number) => {
      const layerKey = lc?.layer ?? `layer-${index}`;
      const layerRows = multi
        ? allRows.filter((r: any) => String(r?.layer) === String(layerKey))
        : allRows;
      const features = layerRows.map(rowToFeature).filter(Boolean);
      return makeMeta(layerKey, index, lc, features, false);
    });
  }

  /** Extract a GeoJSON Feature[] from a per-layer payload, branching on data_shape. */
  function extractFeatures(payload: any, shape: string): any[] {
    if (!payload) return [];
    if (shape === "rows") {
      const rows = Array.isArray(payload.rows) ? payload.rows : [];
      return rows.map(rowToFeature).filter(Boolean);
    }
    // geojson: payload is a FeatureCollection
    return Array.isArray(payload.features) ? payload.features : [];
  }

  const LAT_KEYS = ["latitude", "lat", "kiosk_latitude", "wh_latitude", "y"];
  const LNG_KEYS = ["longitude", "lng", "lon", "long", "kiosk_longitude", "wh_longitude", "x"];

  function num(v: unknown): number | null {
    if (v == null || v === "") return null;
    const n = Number(v);
    return Number.isNaN(n) ? null : n;
  }

  /** Resolve a coordinate from explicit keys, then any key matching the regex. */
  function pickCoord(
    row: Record<string, any>,
    keys: string[],
    fuzzy: RegExp,
  ): number | null {
    for (const k of keys) {
      const n = num(row[k]);
      if (n != null) return n;
    }
    for (const k of Object.keys(row)) {
      if (fuzzy.test(k)) {
        const n = num(row[k]);
        if (n != null) return n;
      }
    }
    return null;
  }

  /** Build a GeoJSON Feature from a flat row (_geometry, or lat/lng columns). */
  function rowToFeature(row: any): any | null {
    if (!row || typeof row !== "object") return null;
    const props = { ...row };
    delete props._geometry;
    let geometry = row._geometry ?? null;
    if (!geometry) {
      const lat = pickCoord(row, LAT_KEYS, /lat/i);
      const lng = pickCoord(row, LNG_KEYS, /(lon|lng)/i);
      if (lat != null && lng != null) {
        geometry = { type: "Point", coordinates: [lng, lat] };
      }
    }
    if (!geometry) return null;
    return { type: "Feature", geometry, properties: props };
  }

  function esc(v: unknown): string {
    return String(v ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  /** Render a layer tooltip: `{field}` template → properties, else labelField, else first props. */
  function renderTooltip(
    props: Record<string, any> | undefined,
    tpl?: string,
    labelField?: string,
  ): string {
    const p = props || {};
    if (tpl) {
      return esc(tpl.replace(/\{(\w+)\}/g, (_m, k) => String(p[k] ?? "")));
    }
    if (labelField && p[labelField] != null) return `<b>${esc(p[labelField])}</b>`;
    return Object.entries(p)
      .filter(([k]) => k !== "_geometry")
      .slice(0, 5)
      .map(([k, v]) => `<span style="color:#64748b">${esc(k)}:</span> ${esc(v)}`)
      .join("<br/>");
  }

  /** Effective color for a layer, honoring override → config → default palette. */
  function effColor(meta: LayerMeta): string {
    return resolveEffectiveColor({
      override: overrides[meta.id],
      configColor: meta.configColor,
      index: meta.index,
    });
  }

  /** Effective marker radius for a layer (user size override → default). */
  function effSize(id: string): number {
    const s = sizes[id];
    return typeof s === "number" ? s : DEFAULT_RADIUS;
  }

  /** Repaint a single layer in place (color + radius, no map reload). */
  function repaint(id: string) {
    const gj = gjByLayer.get(id);
    const meta = layerMeta.find((m) => m.id === id);
    if (!gj || !meta) return;
    const c = effColor(meta);
    const r = effSize(id);
    try {
      gj.setStyle({ color: c, fillColor: c });
      gj.eachLayer((l: any) => {
        if (typeof l.setRadius === "function") l.setRadius(r);
      });
    } catch {
      /* layer without styleable features — ignore */
    }
  }

  function chooseColor(id: string, color: string) {
    if (!isValidColor(color)) return;
    overrides[id] = color.trim();
    saveOverride(chatbotId, id, color);
    repaint(id);
  }

  function chooseSize(id: string, size: number) {
    const r = Math.max(MIN_RADIUS, Math.min(MAX_RADIUS, Math.round(size)));
    sizes[id] = r;
    saveSize(chatbotId, id, r);
    repaint(id);
  }

  /** Reset a layer to its defaults (clears color + size override + persisted). */
  function resetColor(id: string) {
    delete overrides[id];
    delete sizes[id];
    clearOverride(chatbotId, id);
    clearSize(chatbotId, id);
    repaint(id);
  }

  // Normalize any CSS color name/hex to a 6-digit hex for the native picker value.
  let _hexCtx: CanvasRenderingContext2D | null = null;
  function toHexColor(color: string): string {
    if (!browser) return "#000000";
    if (/^#[0-9a-fA-F]{6}$/.test(color)) return color;
    if (/^#[0-9a-fA-F]{3}$/.test(color)) {
      return (
        "#" +
        color
          .slice(1)
          .split("")
          .map((ch) => ch + ch)
          .join("")
      );
    }
    try {
      if (!_hexCtx) _hexCtx = document.createElement("canvas").getContext("2d");
      if (!_hexCtx) return "#000000";
      _hexCtx.fillStyle = "#000000";
      _hexCtx.fillStyle = color;
      const v = _hexCtx.fillStyle;
      return typeof v === "string" && v.startsWith("#") ? v : "#000000";
    } catch {
      return "#000000";
    }
  }

  async function initMap() {
    if (!browser || !mapContainer) return;
    try {
      // Seed color + size overrides from localStorage before first paint.
      for (const meta of layerMeta) {
        const ov = loadOverride(chatbotId, meta.id);
        if (ov) overrides[meta.id] = ov;
        const sz = loadSize(chatbotId, meta.id);
        if (sz != null) sizes[meta.id] = sz;
      }

      if (!L) {
        const mod = await import("leaflet");
        L = mod.default;
      }

      const base = config?.baseLayer ?? config?.base_layer;
      const tile =
        typeof base === "string" && base.includes("{z}") ? base : DEFAULT_TILE;

      mapInstance = L.map(mapContainer);
      L.tileLayer(tile, { attribution: ATTRIBUTION }).addTo(mapInstance);

      const bounds: any[] = [];

      layerMeta.forEach((meta) => {
        if (!meta.features.length) return;
        const color = effColor(meta);
        const gj = L.geoJSON(
          { type: "FeatureCollection", features: meta.features },
          {
            pointToLayer: (_f: any, latlng: any) =>
              L.circleMarker(latlng, {
                radius: effSize(meta.id),
                color,
                weight: 2,
                fillColor: color,
                fillOpacity: 0.85,
              }),
            style: () => ({
              color,
              weight: 2,
              fillColor: color,
              fillOpacity: 0.25,
            }),
            onEachFeature: (f: any, layer: any) => {
              const html = renderTooltip(f?.properties, meta.tpl, meta.labelField);
              if (html) layer.bindTooltip(html, { sticky: true });
            },
          },
        ).addTo(mapInstance);
        gjByLayer.set(meta.id, gj);

        try {
          const b = gj.getBounds();
          if (b.isValid()) bounds.push(b);
        } catch {
          /* layer without geometry bounds — ignore */
        }
      });

      // Fit priority: viewport.bbox → computed layer bounds → center/zoom → world.
      const vp = config?.viewport;
      const bbox = vp?.bbox; // [minLng, minLat, maxLng, maxLat]
      if (Array.isArray(bbox) && bbox.length === 4) {
        mapInstance.fitBounds(
          [
            [bbox[1], bbox[0]],
            [bbox[3], bbox[2]],
          ],
          { padding: [24, 24] },
        );
      } else if (bounds.length) {
        let b = bounds[0];
        for (let i = 1; i < bounds.length; i++) b = b.extend(bounds[i]);
        mapInstance.fitBounds(b, { padding: [24, 24] });
      } else if (Array.isArray(vp?.center)) {
        mapInstance.setView([vp.center[0], vp.center[1]], vp?.zoom ?? 10);
      } else {
        mapInstance.setView([0, 0], 2);
      }

      // Leaflet needs a size recompute when mounted inside a freshly-shown box.
      setTimeout(() => mapInstance && mapInstance.invalidateSize(), 0);
    } catch (e) {
      console.error("StructuredMap render failed", e);
      errored = true;
    }
  }

  onMount(() => {
    initMap();
  });

  onDestroy(() => {
    if (mapInstance) {
      mapInstance.remove();
      mapInstance = null;
    }
    gjByLayer.clear();
  });
</script>

{#if errored}
  <div
    class="flex h-full items-center justify-center text-center text-sm text-muted-foreground"
  >
    Unable to render map.
  </div>
{:else}
  <div class="relative h-full w-full">
    <div bind:this={mapContainer} class="h-full w-full"></div>

    {#if layerMeta.length}
      <div class="absolute right-2 top-2 z-[1100] flex flex-col items-end gap-2">
        {#if !panelOpen}
          <!-- Collapsed: compact legend that also opens the color editor -->
          <button
            type="button"
            class="flex max-w-[220px] items-center gap-2 rounded-box border border-base-300 bg-base-100/90 px-2 py-1.5 text-xs shadow-md backdrop-blur transition-colors hover:bg-base-200"
            onclick={() => (panelOpen = true)}
            aria-expanded="false"
            aria-label="Open layer color controls"
            title="Layer colors"
          >
            <span class="flex flex-wrap items-center gap-x-2 gap-y-1">
              {#each layerMeta as meta (meta.id)}
                <span class="flex items-center gap-1">
                  <span
                    class="inline-block size-2.5 shrink-0 rounded-full ring-1 ring-black/10"
                    style="background-color: {effColor(meta)};"
                  ></span>
                  <span class="truncate">{meta.id}</span>
                </span>
              {/each}
            </span>
            <Icon icon="mdi:palette" class="size-4 shrink-0 text-base-content/60" />
          </button>
        {:else}
          <!-- Expanded: per-layer color editor + legend -->
          <div
            class="w-64 max-w-[80vw] rounded-box border border-base-300 bg-base-100/95 shadow-lg backdrop-blur"
            role="group"
            aria-label="Layer color controls"
          >
            <div
              class="flex items-center justify-between border-b border-base-300 px-3 py-2"
            >
              <span class="flex items-center gap-2 text-sm font-medium">
                <Icon icon="mdi:palette" class="size-4" />
                Layer colors
              </span>
              <button
                type="button"
                class="btn btn-ghost btn-xs btn-circle"
                onclick={() => (panelOpen = false)}
                aria-label="Collapse color controls"
                title="Collapse"
              >
                <Icon icon="mdi:close" class="size-4" />
              </button>
            </div>

            <div class="max-h-[320px] space-y-3 overflow-y-auto p-3">
              {#each layerMeta as meta (meta.id)}
                {@const current = effColor(meta)}
                <div class="space-y-1.5">
                  <div class="flex items-center justify-between gap-2">
                    <span class="flex min-w-0 items-center gap-1.5 text-xs font-medium">
                      <span
                        class="inline-block size-3 shrink-0 rounded-full ring-1 ring-black/10"
                        style="background-color: {current};"
                      ></span>
                      <span class="truncate" title={meta.id}>{meta.id}</span>
                      {#if meta.capped}
                        <Icon
                          icon="mdi:alert-outline"
                          class="size-3.5 shrink-0 text-warning"
                          aria-label="Results were truncated"
                        />
                      {/if}
                    </span>
                    <button
                      type="button"
                      class="btn btn-ghost btn-xs gap-1 px-1.5"
                      onclick={() => resetColor(meta.id)}
                      aria-label={`Reset ${meta.id} to default color`}
                      title="Reset to default"
                    >
                      <Icon icon="mdi:restore" class="size-3.5" />
                    </button>
                  </div>

                  <div class="flex flex-wrap items-center gap-1">
                    {#each SWATCH_COLORS as c (c)}
                      <button
                        type="button"
                        class="size-5 rounded ring-1 ring-black/10 transition-transform hover:scale-110 {current.toLowerCase() ===
                        c
                          ? 'outline outline-2 outline-offset-1 outline-primary'
                          : ''}"
                        style="background-color: {c};"
                        onclick={() => chooseColor(meta.id, c)}
                        aria-label={`Set ${meta.id} to ${c}`}
                        aria-pressed={current.toLowerCase() === c}
                        title={c}
                      ></button>
                    {/each}
                    <label
                      class="flex size-5 cursor-pointer items-center justify-center rounded ring-1 ring-black/10"
                      title="Custom color"
                    >
                      <Icon icon="mdi:eyedropper-variant" class="size-3.5" />
                      <input
                        type="color"
                        class="sr-only"
                        value={toHexColor(current)}
                        oninput={(e) => chooseColor(meta.id, e.currentTarget.value)}
                        aria-label={`Custom color for ${meta.id}`}
                      />
                    </label>
                  </div>
                  <div class="flex items-center gap-2">
                    <Icon
                      icon="mdi:circle-medium"
                      class="size-3.5 shrink-0 text-base-content/60"
                    />
                    <input
                      type="range"
                      class="range range-xs flex-1"
                      min={MIN_RADIUS}
                      max={MAX_RADIUS}
                      value={effSize(meta.id)}
                      oninput={(e) =>
                        chooseSize(meta.id, Number(e.currentTarget.value))}
                      aria-label={`Marker size for ${meta.id}`}
                      title="Marker size"
                    />
                    <span class="w-5 text-right text-[10px] tabular-nums text-base-content/60">
                      {effSize(meta.id)}
                    </span>
                  </div>

                  {#if meta.capped}
                    <p class="text-[10px] text-base-content/60">
                      Showing first {meta.count} (truncated).
                    </p>
                  {/if}
                </div>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    {/if}
  </div>
{/if}
