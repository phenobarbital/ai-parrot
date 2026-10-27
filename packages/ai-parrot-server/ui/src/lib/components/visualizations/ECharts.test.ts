import { render } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import ECharts from "./ECharts.svelte";

type Chart = {
  dispose: ReturnType<typeof vi.fn>;
  resize: ReturnType<typeof vi.fn>;
  setOption: ReturnType<typeof vi.fn>;
};

const mocks = vi.hoisted(() => ({
  coreInit: vi.fn(),
  fullInit: vi.fn(),
}));

vi.mock("echarts/core", () => ({
  init: mocks.coreInit,
  use: vi.fn(),
}));

vi.mock("echarts", () => ({ init: mocks.fullInit }));

vi.mock("echarts/charts", () => ({
  BarChart: {},
  CustomChart: {},
  FunnelChart: {},
  GaugeChart: {},
  HeatmapChart: {},
  LineChart: {},
  MapChart: {},
  PieChart: {},
  RadarChart: {},
  ScatterChart: {},
}));

vi.mock("echarts/components", () => ({
  AxisPointerComponent: {},
  DataZoomComponent: {},
  DataZoomInsideComponent: {},
  DataZoomSliderComponent: {},
  DatasetComponent: {},
  GeoComponent: {},
  GraphicComponent: {},
  GridComponent: {},
  LegendComponent: {},
  MarkAreaComponent: {},
  MarkLineComponent: {},
  MarkPointComponent: {},
  PolarComponent: {},
  RadarComponent: {},
  TitleComponent: {},
  ToolboxComponent: {},
  TooltipComponent: {},
  TransformComponent: {},
  VisualMapComponent: {},
}));

vi.mock("echarts/features", () => ({ LabelLayout: {}, UniversalTransition: {} }));
vi.mock("echarts/renderers", () => ({ CanvasRenderer: {} }));

function createChart(): Chart {
  return {
    dispose: vi.fn(),
    resize: vi.fn(),
    setOption: vi.fn(),
  };
}

async function settle(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

describe("ECharts onChartReady", () => {
  it("calls the callback once after the first setOption", async () => {
    const chart = createChart();
    const onChartReady = vi.fn();
    mocks.coreInit.mockReturnValue(chart);

    render(ECharts, { options: { series: [{ type: "bar" }] }, onChartReady });
    await settle();

    expect(onChartReady).toHaveBeenCalledTimes(1);
    expect(onChartReady).toHaveBeenCalledWith(chart);
    expect(chart.setOption).toHaveBeenCalledBefore(onChartReady);
  });

  it("cleans up and re-attaches when the callback changes", async () => {
    const chart = createChart();
    const firstCleanup = vi.fn();
    const firstCallback = vi.fn(() => firstCleanup);
    const secondCallback = vi.fn();
    mocks.coreInit.mockReturnValue(chart);

    const { rerender } = render(ECharts, {
      options: { series: [{ type: "bar" }] },
      onChartReady: firstCallback,
    });
    await settle();
    await rerender({ options: { series: [{ type: "bar" }] }, onChartReady: secondCallback });
    await settle();

    expect(firstCleanup).toHaveBeenCalledOnce();
    expect(secondCallback).toHaveBeenCalledOnce();
    expect(secondCallback).toHaveBeenCalledWith(chart);
  });

  it("re-attaches after instance recreation for the full build", async () => {
    const coreChart = createChart();
    const fullChart = createChart();
    const cleanup = vi.fn();
    const onChartReady = vi.fn(() => cleanup);
    mocks.coreInit.mockReturnValue(coreChart);
    mocks.fullInit.mockReturnValue(fullChart);

    const { rerender } = render(ECharts, {
      options: { series: [{ type: "bar" }] },
      onChartReady,
    });
    await settle();
    await rerender({ options: { series: [{ type: "graph" }] }, onChartReady });
    await settle();

    expect(coreChart.dispose).toHaveBeenCalledOnce();
    expect(cleanup).toHaveBeenCalledOnce();
    expect(onChartReady).toHaveBeenNthCalledWith(1, coreChart);
    expect(onChartReady).toHaveBeenNthCalledWith(2, fullChart);
  });

  it("runs the cleanup on unmount", async () => {
    const chart = createChart();
    const cleanup = vi.fn();
    mocks.coreInit.mockReturnValue(chart);

    const { unmount } = render(ECharts, {
      options: { series: [{ type: "bar" }] },
      onChartReady: vi.fn(() => cleanup),
    });
    await settle();
    unmount();

    expect(cleanup).toHaveBeenCalledOnce();
    expect(chart.dispose).toHaveBeenCalledOnce();
  });
});
