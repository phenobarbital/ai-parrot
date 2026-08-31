<script lang="ts">
  /**
   * AppChartGeo — lazily-loaded world choropleth rendered via layerchart/geo.
   *
   * Loaded by AppChart only when type === 'map', keeping geo code out of the
   * base chart bundle (dynamic import via AppChart.svelte).
   *
   * Props:
   *   data   — array of records with at least one string column (country name/code)
   *            and one numeric value column; used for choropleth fill intensity.
   *   nameKey — key in each row for the country identifier (default: first string col).
   *   valueKey — key in each row for the numeric value (default: first numeric col).
   */

  import { onMount } from "svelte";
  import { browser } from "$app/environment";
  import { GeoProjection, GeoPath, Graticule } from "layerchart/geo";
  import { geoNaturalEarth1 } from "d3-geo";
  import type { GeoJSON } from "geojson";

  interface Props {
    data: Record<string, unknown>[];
    nameKey?: string;
    valueKey?: string;
  }

  let { data, nameKey, valueKey }: Props = $props();

  let worldGeo = $state<GeoJSON | null>(null);
  let loadError = $state<string | null>(null);
  let containerRef = $state<HTMLDivElement | null>(null);
  let width = $state(0);
  let height = $state(0);

  // Resolve name and value keys from data
  let resolvedNameKey = $derived.by(() => {
    if (nameKey) return nameKey;
    if (!data.length) return "";
    return (
      Object.keys(data[0]).find((k) => typeof data[0][k] === "string") ?? ""
    );
  });

  let resolvedValueKey = $derived.by(() => {
    if (valueKey) return valueKey;
    if (!data.length) return "";
    return (
      Object.keys(data[0]).find((k) => typeof data[0][k] === "number") ?? ""
    );
  });

  // Build a lookup: country name → value
  let valueByName = $derived.by(() => {
    const map = new Map<string, number>();
    for (const row of data) {
      const name = String(row[resolvedNameKey] ?? "");
      const val = Number(row[resolvedValueKey] ?? 0);
      if (name) map.set(name.toLowerCase(), val);
    }
    return map;
  });

  // Compute max value for choropleth scale
  let maxVal = $derived(
    data.length
      ? Math.max(
          1,
          ...data.map((d) => Number(d[resolvedValueKey] ?? 0)),
        )
      : 1,
  );

  function intensityClass(featureName: string): string {
    const key = featureName.toLowerCase();
    const val = valueByName.get(key) ?? 0;
    const ratio = val / maxVal;
    if (ratio === 0) return "fill-muted/30";
    if (ratio < 0.2) return "fill-chart-1/30";
    if (ratio < 0.4) return "fill-chart-1/50";
    if (ratio < 0.6) return "fill-chart-1/70";
    if (ratio < 0.8) return "fill-chart-1/80";
    return "fill-chart-1";
  }

  onMount(async () => {
    if (!browser) return;
    try {
      // Dynamic imports — keep geo code out of the base bundle.
      const [topoModule, atlasModule] = await Promise.all([
        import("topojson-client"),
        import("world-atlas/countries-110m.json"),
      ]);
      const { feature } = topoModule;
      const topology = atlasModule.default as any;
      worldGeo = feature(topology, topology.objects.countries) as unknown as GeoJSON;
    } catch (err) {
      loadError = err instanceof Error ? err.message : String(err);
    }
  });

  $effect(() => {
    if (containerRef) {
      const observer = new ResizeObserver((entries) => {
        for (const entry of entries) {
          width = entry.contentRect.width;
          height = entry.contentRect.height;
        }
      });
      observer.observe(containerRef);
      return () => observer.disconnect();
    }
  });
</script>

<div class="flex h-full w-full items-center justify-center" bind:this={containerRef}>
  {#if loadError}
    <p class="text-sm text-destructive">Map error: {loadError}</p>
  {:else if !worldGeo}
    <p class="text-sm text-muted-foreground">Loading map…</p>
  {:else if width > 0 && height > 0}
    <svg {width} {height} viewBox="0 0 {width} {height}" class="block">
      <GeoProjection
        projection={geoNaturalEarth1}
        fitGeojson={worldGeo}
      >
        <Graticule class="stroke-border/30 fill-none" strokeWidth={0.5} />
        {#if worldGeo && 'features' in worldGeo}
          {#each (worldGeo as any).features as feature (feature.id ?? feature.properties?.name)}
            <GeoPath
              geojson={feature}
              class="stroke-background/50 transition-colors {intensityClass(feature.properties?.name ?? '')}"
              stroke-width={0.5}
            />
          {/each}
        {/if}
      </GeoProjection>
    </svg>
  {/if}
</div>
