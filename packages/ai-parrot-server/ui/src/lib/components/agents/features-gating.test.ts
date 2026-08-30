// ai-parrot (FEAT-476 TASK-2595): feature-flag gating for the canvas/
// charts/maps/infographic surfaces (spec §3 Module 5).
//
// What this suite verifies (and what it deliberately does NOT claim):
// with a flag off, the corresponding heavy component is never rendered
// and a "feature disabled in this build" placeholder appears instead —
// i.e. the runtime behavior the gating exists for. It does NOT assert
// that the flagged chunk is absent from `dist/assets`: verified during
// implementation (see this task's Completion Note) that Rollup always
// emits a chunk for every reachable `import()` call regardless of a
// surrounding `if (features.x)` runtime guard, because `features.x` is
// an object-property read (`$lib/features`'s `Object.freeze({...})`
// shape from TASK-2591), not a bare compile-time constant — esbuild/
// Rollup only cross-module-DCE a dead `if` branch (chunk included) for
// a directly-imported `const` binding, confirmed with an isolated repro.
// The chunk therefore always exists on disk but is never fetched at
// runtime unless the gated code path actually executes, which is what
// these tests exercise instead.
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

const { features } = vi.hoisted(() => ({
  features: {
    voice: true,
    avatar: true,
    maps: true,
    charts: true,
    canvas: true,
    infographic: true,
    datasets: true,
    richEditor: true,
  },
}));
vi.mock("$lib/features", () => ({ features }));

import ChartBlock from "./canvas/blocks/ChartBlock.svelte";
import MapBlock from "./canvas/blocks/MapBlock.svelte";
import InfographicChartBlock from "./canvas/infographic/blocks/InfographicChartBlock.svelte";

const chartBlockData = {
  data: [{ x: "a", y: 1 }],
  config: { type: "bar", x: "x", y: ["y"] },
};
const mapBlockData = {
  data: [{ lat: 1, lng: 2 }],
  config: { type: "map" },
};

describe("ChartBlock — features.charts gate", () => {
  it("renders a disabled placeholder (no AppChart/DataChart) when charts is off", () => {
    features.charts = false;
    render(ChartBlock, { data: chartBlockData });
    expect(screen.getByText("Chart feature disabled in this build.")).toBeInTheDocument();
    features.charts = true;
  });

  it("renders the real chart when charts is on", async () => {
    features.charts = true;
    const { container } = render(ChartBlock, { data: chartBlockData });
    expect(screen.queryByText("Chart feature disabled in this build.")).toBeNull();
    // DataChart resolves asynchronously (dynamic import) — the container
    // is non-empty and no placeholder is shown; DataChart's own rendering
    // is covered by TASK-2596's future test, not duplicated here.
    expect(container.querySelector("[data-chart-block-id]")).not.toBeNull();
  });
});

describe("MapBlock — features.maps gate", () => {
  it("renders a disabled placeholder (no leaflet/DataMap) when maps is off", () => {
    features.maps = false;
    render(MapBlock, { data: mapBlockData });
    expect(screen.getByText("Map feature disabled in this build.")).toBeInTheDocument();
    features.maps = true;
  });

  it("does not render the placeholder when maps is on", () => {
    features.maps = true;
    render(MapBlock, { data: mapBlockData });
    expect(screen.queryByText("Map feature disabled in this build.")).toBeNull();
  });
});

describe("InfographicChartBlock — features.charts gate", () => {
  const props = {
    chart_type: "bar" as const,
    title: "Revenue",
    labels: ["Jan"],
    series: [{ name: "Revenue", values: [10] }],
    stacked: false,
    show_legend: true,
  };

  it("renders a disabled placeholder when charts is off", () => {
    features.charts = false;
    render(InfographicChartBlock, props as any);
    expect(screen.getByText("Chart feature disabled in this build.")).toBeInTheDocument();
    features.charts = true;
  });

  it("does not render the placeholder when charts is on", () => {
    features.charts = true;
    render(InfographicChartBlock, props as any);
    expect(screen.queryByText("Chart feature disabled in this build.")).toBeNull();
  });
});
