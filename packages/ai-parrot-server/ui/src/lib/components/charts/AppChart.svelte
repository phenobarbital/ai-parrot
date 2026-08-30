<script lang="ts">
  import {
    Area,
    Axis,
    Bars,
    Canvas,
    Chart,
    Group,
    Highlight,
    Pie,
    Points,
    Rule,
    Spline,
    Svg,
    Tooltip,
  } from "layerchart";
  import {
    scaleBand,
    scaleLinear,
    scaleOrdinal,
    scalePoint,
  } from "d3-scale";
  import { browser } from "$app/environment";
  import { themeStore } from "$lib/stores/theme.svelte";
  import type { AppChartConfig } from "./chart-contract.js";
  import { buildOverlays } from "./overlays.js";
  import { onMount } from "svelte";
  // ai-parrot (FEAT-476 TASK-2595): AppChartGeo's own deps (d3-geo,
  // topojson-client, world-atlas) belong to features.maps, not
  // features.charts (spec §3 Module 5) — gate its lazy load accordingly,
  // even though AppChart itself is a features.charts surface.
  import { features } from "$lib/features";

  // Lazy-load the geo renderer only when type === 'map'
  let AppChartGeo = $state<any>(null);
  onMount(async () => {
    if (config.type === "map" && features.maps) {
      const mod = await import("./AppChartGeo.svelte");
      AppChartGeo = mod.default;
    }
  });

  interface Props {
    config: AppChartConfig;
    data: Record<string, any>[];
    loading?: boolean;
    /** Shrinks axis tick labels for tight previews (e.g. Configure Chart modal). */
    compact?: boolean;
  }

  let { config, data = [], loading = false, compact = false }: Props = $props();

  /**
   * Smaller tick labels on the category axis when rendered in a tight preview,
   * to avoid the labels crowding into each other.
   */
  let categoryTickLabelProps = $derived(
    compact ? { class: "text-[8px]" } : undefined,
  );

  const DEFAULT_PALETTE = [
    "var(--chart-1)",
    "var(--chart-2)",
    "var(--chart-3)",
    "var(--chart-4)",
    "var(--chart-5)",
  ];

  let containerWidth = $state(0);
  let containerHeight = $state(0);

  let palette = $derived(config.palette ?? DEFAULT_PALETTE);

  /**
   * Resolve a color string to a concrete rgb value via a probe element.
   * The SVG layer accepts `var(--chart-N)` directly, but the Canvas layer
   * paints to a 2D context whose fillStyle does NOT resolve CSS variables —
   * so canvas series would render colorless. Resolving to computed rgb (which
   * also normalizes oklch from the warm/midnight themes) makes both layers work.
   */
  function resolveColor(color: string): string {
    if (!browser || !color.includes("var(")) return color;
    const probe = document.createElement("span");
    probe.style.color = color;
    probe.style.display = "none";
    document.body.appendChild(probe);
    const resolved = getComputedStyle(probe).color;
    probe.remove();
    return resolved || color;
  }

  // Re-resolves when the active theme changes, keeping SVG and Canvas in sync.
  let resolvedPalette = $derived.by(() => {
    themeStore.currentTheme; // reactive dependency: re-resolve on theme switch
    if (!browser) return palette;
    return palette.map(resolveColor);
  });

  let isPie = $derived(config.type === "pie" || config.type === "donut");
  let isLine = $derived(
    config.type === "line" || (config.type as string) === "lineSigned",
  );
  let isArea = $derived(config.type === "area");
  let isScatter = $derived(config.type === "scatter");
  let isRadar = $derived(config.type === "radar");
  let isMap = $derived(config.type === "map");
  let isHorizontalBar = $derived(config.type === "horizontalBar");
  let isBar = $derived(
    !isPie &&
      !isLine &&
      !isArea &&
      !isScatter &&
      !isRadar &&
      !isMap &&
      !isHorizontalBar,
  );

  // Guard: the configured x/y columns must actually exist in the data rows.
  // A mismatch (e.g. config.x names a column that isn't present in the rows)
  // makes LayerChart build a scale over `undefined`, which crashes inside
  // <Axis> ("Cannot read properties of undefined (reading 'valueOf')") and
  // takes down the entire chat render. When the columns don't line up we show
  // a graceful fallback instead of mounting <Chart>.
  let hasValidColumns = $derived.by(() => {
    if (isMap) return true; // geo renderer doesn't use x/y columns
    if (!data.length) return false;
    const row = data[0] ?? {};
    const xOk = config.x == null || config.x in row;
    const yOk = config.y.some((k) => k in row);
    return xOk && yOk;
  });

  let seriesDefs = $derived(
    config.y.map((key, i) => ({
      key,
      label: key,
      value: (d: Record<string, any>) => Number(d[key]) || 0,
      color: resolvedPalette[i % resolvedPalette.length],
    })),
  );

  // Per-bar sign coloring: single-series bar / horizontalBar charts that opt in.
  // LayerChart resolves a bar's fill as `fill ?? series.color ?? cGet(d)`, so we render
  // two filtered <Bars> (positives green, negatives red) with explicit fills instead.
  let useSignColor = $derived(
    (isBar || isHorizontalBar) &&
      (config.colorBySign ?? false) &&
      config.y.length === 1,
  );
  let signPosColor = $derived(resolvedPalette[0]);
  let signNegColor = $derived(
    resolveColor(config.negativeColor ?? "var(--color-error)"),
  );

  let showLegend = $derived((config.showLegend ?? true) && config.y.length > 1);

  // Pie/donut slices are categories (config.x), not y-series, so the multi-series
  // legend above never applies. Pin the color scale's domain to category order
  // (d3.pie reorders arcs by value) so swatch colors stay deterministic and the
  // legend below matches each slice exactly.
  let pieCategories = $derived(data.map((d) => String(d[config.x] ?? "")));
  let pieLegend = $derived.by(() =>
    isPie && (config.showLegend ?? true)
      ? pieCategories.map((label, i) => ({
          label,
          color: resolvedPalette[i % resolvedPalette.length],
        }))
      : [],
  );

  let totalPoints = $derived(data.length * config.y.length);
  let useCanvas = $derived(totalPoints > 2000);

  // For cartesian: cover all Y columns in the domain
  let yMax = $derived(
    Math.max(0, ...data.flatMap((d) => config.y.map((k) => Number(d[k]) || 0))),
  );

  // Include negative values in the domain (e.g. EBITDA losses). Stacked positives
  // keep a 0 floor; otherwise the floor is the real minimum (≤ 0) so negative bars
  // render below the zero baseline instead of overflowing the container.
  let yMin = $derived(
    config.stacked
      ? 0
      : Math.min(
          0,
          ...data.flatMap((d) => config.y.map((k) => Number(d[k]) || 0)),
        ),
  );

  // Stacked charts: sum of all Y values per row
  let yMaxStacked = $derived(
    config.stacked
      ? Math.max(
          0,
          ...data.map((d) =>
            config.y.reduce((s, k) => s + (Number(d[k]) || 0), 0),
          ),
        )
      : yMax,
  );

  let chartSeries = $derived(
    seriesDefs.map((s) => ({
      key: s.key,
      label: s.label,
      value: s.value,
      // Omit the series color when coloring per-bar by sign so LayerChart falls
      // through to the chart's `c`/`cScale` (cGet) for each bar.
      ...(useSignColor ? {} : { color: s.color }),
    })),
  );

  // Overlays: trendlines + median lines (cartesian only)
  let overlays = $derived.by(() => {
    if (isPie || isRadar || isMap || (!config.trendline && !config.median))
      return [];
    return buildOverlays(
      data,
      seriesDefs.map((s) => ({ key: s.key, color: s.color })),
      config.trendline ?? false,
      config.median ?? false,
    );
  });

  // ── Radar helpers ─────────────────────────────────────────────────────────
  /** Compute SVG polygon points for a radar series. */
  function radarPoints(
    values: number[],
    maxVal: number,
    cx: number,
    cy: number,
    radius: number,
  ): string {
    const n = values.length;
    if (n === 0 || maxVal === 0) return "";
    return values
      .map((v, i) => {
        const angle = (Math.PI * 2 * i) / n - Math.PI / 2;
        const r = (v / maxVal) * radius;
        return `${cx + r * Math.cos(angle)},${cy + r * Math.sin(angle)}`;
      })
      .join(" ");
  }

  let radarCategories = $derived(data.map((d) => String(d[config.x] ?? "")));

  let radarMaxVal = $derived.by(() => {
    let m = 0;
    for (const d of data) {
      for (const k of config.y) {
        const v = Number(d[k]) || 0;
        if (v > m) m = v;
      }
    }
    return m || 1;
  });

  /** Axis spoke endpoint for a given category index. */
  function radarSpokeEnd(
    i: number,
    n: number,
    cx: number,
    cy: number,
    radius: number,
  ) {
    const angle = (Math.PI * 2 * i) / n - Math.PI / 2;
    return { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) };
  }
</script>

<div
  class="flex h-full w-full flex-col"
  bind:clientWidth={containerWidth}
  bind:clientHeight={containerHeight}
>
  {#if loading}
    <div
      class="flex h-full items-center justify-center text-sm text-muted-foreground"
    >
      Loading…
    </div>
  {:else if data.length === 0}
    <div
      class="flex h-full items-center justify-center text-sm text-muted-foreground"
    >
      No data
    </div>
  {:else if isMap}
    <!-- Map type: lazily-loaded geo renderer (AppChartGeo) -->
    <div class="min-h-0 flex-1">
      {#if AppChartGeo}
        <svelte:component this={AppChartGeo} {data} />
      {:else}
        <div
          class="flex h-full items-center justify-center text-sm text-muted-foreground"
        >
          Loading map…
        </div>
      {/if}
    </div>
  {:else if !hasValidColumns}
    <!-- Config/data mismatch: x or y columns absent from the rows. Render a
         fallback instead of mounting <Chart> (which would crash <Axis>). -->
    <div
      class="flex h-full items-center justify-center px-4 text-center text-sm text-muted-foreground"
    >
      Unable to render chart: the configured x/y columns don't match the data.
    </div>
  {:else if containerWidth > 0}
    <!-- Error boundary: charts come from untrusted LLM output. If anything
         inside LayerChart throws at runtime, degrade to a fallback instead of
         crashing the surrounding ChatBubble / AgentChat render. -->
    <svelte:boundary>
      <div class="min-h-0 flex-1">
      {#if isRadar}
        <!-- ── Radar emulation (pure SVG) ────────────────────────────── -->
        {@const size = Math.min(
          containerWidth,
          containerHeight || containerWidth,
        )}
        {@const cx = size / 2}
        {@const cy = size / 2}
        {@const radius = size * 0.32}
        {@const labelOffset = Math.max(10, size * 0.08)}
        {@const n = radarCategories.length}
        <svg
          viewBox="0 0 {size} {size}"
          width={size}
          height={size}
          class="mx-auto block"
          role="img"
          aria-label="Radar chart"
        >
          <!-- Background rings (25%, 50%, 75%, 100%) -->
          {#each [0.25, 0.5, 0.75, 1] as frac}
            <polygon
              points={radarCategories
                .map((_, i) => {
                  const angle = (Math.PI * 2 * i) / n - Math.PI / 2;
                  return `${cx + radius * frac * Math.cos(angle)},${cy + radius * frac * Math.sin(angle)}`;
                })
                .join(" ")}
              fill="none"
              stroke="currentColor"
              stroke-opacity="0.15"
              stroke-width="1"
            />
          {/each}

          <!-- Axis spokes -->
          {#each radarCategories as _cat, i}
            {@const spoke = radarSpokeEnd(i, n, cx, cy, radius)}
            <line
              x1={cx}
              y1={cy}
              x2={spoke.x}
              y2={spoke.y}
              stroke="currentColor"
              stroke-opacity="0.2"
              stroke-width="1"
            />
            <!-- Category label -->
            <text
              x={cx +
                (radius + labelOffset) *
                  Math.cos((Math.PI * 2 * i) / n - Math.PI / 2)}
              y={cy +
                (radius + labelOffset) *
                  Math.sin((Math.PI * 2 * i) / n - Math.PI / 2)}
              text-anchor="middle"
              dominant-baseline="middle"
              class="fill-muted-foreground {compact ? 'text-[8px]' : 'text-[10px]'}"
            >{_cat}</text>
          {/each}

          <!-- Series polygons -->
          {#each seriesDefs as s, si}
            {@const vals = data.map((d) => Number(d[s.key]) || 0)}
            {@const pts = radarPoints(vals, radarMaxVal, cx, cy, radius)}
            <polygon
              points={pts}
              fill={s.color}
              fill-opacity="0.15"
              stroke={s.color}
              stroke-width="2"
            />
            <!-- Dots at each vertex -->
            {#each vals as v, i}
              {@const angle = (Math.PI * 2 * i) / n - Math.PI / 2}
              {@const r = (v / radarMaxVal) * radius}
              <circle
                cx={cx + r * Math.cos(angle)}
                cy={cy + r * Math.sin(angle)}
                r={3}
                fill={s.color}
              />
            {/each}
          {/each}
        </svg>
      {:else if isPie}
        <!-- ── Pie / Donut ───────────────────────────────────────────── -->
        <!-- LayerChart v2 builds pie slices from `d3.pie().value(ctx.x)`, so the
             chart's `x` accessor must be the numeric value; `c` carries the
             category for slice coloring (matches the high-level PieChart idiom). -->
        <Chart
          {data}
          x={config.y[0]}
          c={config.x}
          cScale={scaleOrdinal<string>().domain(pieCategories).range(resolvedPalette)}
          padding={{ top: 8, bottom: 8, left: 8, right: 8 }}
          tooltipContext={{ mode: "manual" }}
        >
          <Svg>
            <Group center>
              <Pie
                innerRadius={config.type === "donut" ? 0.6 : 0}
                padAngle={0.02}
                cornerRadius={4}
                tooltip
              />
            </Group>
          </Svg>

          <Tooltip.Root>
            {#snippet children({ data: d })}
              <div
                class="rounded-lg bg-popover/95 px-2.5 py-1.5 text-popover-foreground shadow-md backdrop-blur-sm"
              >
                <p class="text-xs font-medium">{d[config.x]}</p>
                <p class="text-xs text-muted-foreground">{d[config.y[0]]}</p>
              </div>
            {/snippet}
          </Tooltip.Root>
        </Chart>
      {:else if isHorizontalBar}
        <!-- ── Horizontal Bar (swapped axes: value→x, category→y) ─────── -->
        <Chart
          {data}
          x={config.y[0]}
          y={config.x}
          valueAxis="x"
          xBaseline={0}
          xScale={scaleLinear()}
          xDomain={[yMin * 1.05, yMaxStacked * 1.05]}
          xNice
          yScale={scaleBand().padding(0.3)}
          padding={{ top: 8, right: 16, bottom: 28, left: 96 }}
          tooltipContext={{ mode: "band" }}
        >
          <Svg>
            <Axis placement="bottom" grid rule />
            <Axis placement="left" rule tickLabelProps={categoryTickLabelProps} />

            {#if useSignColor}
              <Bars
                data={data.filter((d) => Number(d[config.y[0]]) >= 0)}
                fill={signPosColor}
                radius={4}
              />
              <Bars
                data={data.filter((d) => Number(d[config.y[0]]) < 0)}
                fill={signNegColor}
                radius={4}
              />
            {:else}
              <Bars fill={resolvedPalette[0]} radius={4} />
            {/if}
          </Svg>

          <Tooltip.Root>
            {#snippet children({ data: d })}
              <div
                class="rounded-lg bg-popover/95 px-2.5 py-1.5 text-popover-foreground shadow-md backdrop-blur-sm"
              >
                <p class="mb-1 text-xs font-medium">{d[config.x]}</p>
                <p class="text-xs text-muted-foreground">
                  {d[config.y[0]]}
                </p>
              </div>
            {/snippet}
          </Tooltip.Root>
        </Chart>
      {:else}
        <!-- ── Cartesian: bar / line / area / scatter ────────────────── -->
        <Chart
          {data}
          x={config.x}
          y={config.y[0]}
          xScale={isBar
            ? scaleBand().padding(0.3)
            : (scalePoint().padding(0.5) as any)}
          yScale={scaleLinear()}
          yDomain={[yMin * 1.05, yMaxStacked * 1.05]}
          yNice
          series={useSignColor ? undefined : chartSeries}
          seriesLayout={config.stacked ? "stack" : "group"}
          padding={{ top: 16, right: 16, bottom: 36, left: 52 }}
          tooltipContext={{ mode: "band" }}
        >
          {#if useCanvas}
            <Canvas>
              {#each seriesDefs as s}
                {#if isBar}
                  {#if useSignColor}
                    <Bars
                      data={data.filter(
                        (d) => Number(d[config.y[0]]) >= 0,
                      )}
                      fill={signPosColor}
                      radius={4}
                    />
                    <Bars
                      data={data.filter((d) => Number(d[config.y[0]]) < 0)}
                      fill={signNegColor}
                      radius={4}
                    />
                  {:else}
                    <Bars seriesKey={s.key} fill={s.color} radius={4} />
                  {/if}
                {:else if isLine}
                  <Spline seriesKey={s.key} stroke={s.color} strokeWidth={2} />
                {:else if isArea}
                  <Area
                    seriesKey={s.key}
                    fill={s.color}
                    fillOpacity={0.2}
                    line={{ stroke: s.color, strokeWidth: 2 }}
                  />
                {:else if isScatter}
                  <Points seriesKey={s.key} fill={s.color} />
                {/if}
              {/each}
            </Canvas>
          {:else}
            <Svg>
              <Axis placement="left" grid rule />
              <Axis
                placement="bottom"
                rule
                tickLabelProps={categoryTickLabelProps}
              />

              {#each seriesDefs as s}
                {#if isBar}
                  {#if useSignColor}
                    <Bars
                      data={data.filter(
                        (d) => Number(d[config.y[0]]) >= 0,
                      )}
                      fill={signPosColor}
                      radius={4}
                    />
                    <Bars
                      data={data.filter((d) => Number(d[config.y[0]]) < 0)}
                      fill={signNegColor}
                      radius={4}
                    />
                  {:else}
                    <Bars seriesKey={s.key} fill={s.color} radius={4} />
                  {/if}
                {:else if isLine}
                  <Spline seriesKey={s.key} stroke={s.color} strokeWidth={2} />
                {:else if isArea}
                  <Area
                    seriesKey={s.key}
                    fill={s.color}
                    fillOpacity={0.2}
                    line={{ stroke: s.color, strokeWidth: 2 }}
                  />
                {:else if isScatter}
                  <Points seriesKey={s.key} fill={s.color} />
                {/if}
              {/each}

              <!-- Overlay: trendline (dashed Spline) + median (Rule) -->
              {#each overlays as ov}
                {#if ov.kind === "trendline"}
                  <Spline
                    data={ov.trendData}
                    y="_trend"
                    stroke={ov.color}
                    strokeWidth={1.5}
                    stroke-dasharray="6 4"
                    fillOpacity={0}
                  />
                {:else if ov.kind === "median"}
                  <Rule
                    y={ov.value}
                    stroke={ov.color}
                    strokeWidth={1.5}
                    dashArray="2 3"
                  />
                {/if}
              {/each}

              <Highlight area />
            </Svg>
          {/if}

          <Tooltip.Root>
            {#snippet children({ data: d })}
              <div
                class="rounded-lg bg-popover/95 px-2.5 py-1.5 text-popover-foreground shadow-md backdrop-blur-sm"
              >
                <p class="mb-1 text-xs font-medium">{d[config.x]}</p>
                {#each seriesDefs as s}
                  <div class="flex items-center gap-1.5 text-xs">
                    <span
                      class="inline-block h-2 w-2 shrink-0 rounded-full"
                      style:background-color={useSignColor
                        ? Number(d[s.key]) < 0
                          ? signNegColor
                          : signPosColor
                        : s.color}
                    ></span>
                    <span class="text-muted-foreground">{s.label}:</span>
                    <span>{d[s.key]}</span>
                  </div>
                {/each}
              </div>
            {/snippet}
          </Tooltip.Root>
        </Chart>
      {/if}
    </div>

    <!-- ── Legend (multi-series only) ───────────────────────────────── -->
    {#if showLegend}
      <div
        class="flex max-h-12 flex-wrap gap-x-4 gap-y-1 overflow-y-auto px-2 pb-1 pt-0.5"
      >
        {#each seriesDefs as s}
          <div class="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span
              class="inline-block h-2.5 w-2.5 shrink-0 rounded-sm"
              style:background-color={s.color}
            ></span>
            {s.label}
          </div>
        {/each}
      </div>
    {/if}

    <!-- ── Legend (pie / donut: one entry per category slice) ──────────── -->
    {#if pieLegend.length}
      <div
        class="flex max-h-16 flex-wrap justify-center gap-x-4 gap-y-1 overflow-y-auto px-2 pb-1 pt-1"
      >
        {#each pieLegend as item}
          <div class="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span
              class="inline-block h-2.5 w-2.5 shrink-0 rounded-sm"
              style:background-color={item.color}
            ></span>
            {item.label}
          </div>
        {/each}
      </div>
    {/if}

      {#snippet failed(error, reset)}
        <div
          class="flex h-full items-center justify-center px-4 text-center text-sm text-muted-foreground"
        >
          Unable to render chart.
        </div>
      {/snippet}
    </svelte:boundary>
  {/if}
</div>
