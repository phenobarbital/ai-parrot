/**
 * Demo fixture: Financial Projection Variance infographic
 * Mirrors the layout requested by Carlos:
 *   - Title (date range)
 *   - 4 hero KPI cards (Revenue, Revenue change, EBITDA, Today's DoD)
 *   - 2 bar charts side-by-side (Daily revenue DoD, Daily EBITDA DoD)
 *   - 1 line chart full-width (Cumulative revenue by day)
 *   - Executive summary
 *
 * Used as a hardcoded preview while the parrot `financial_variance` template
 * is being defined. Renders entirely client-side through InfographicBlockCanvas.
 */
import type { InfographicData } from "./infographic-types";

const DAYS = [
  "May 15",
  "May 16",
  "May 17",
  "May 18",
  "May 19",
  "May 20",
  "May 21",
  "May 22",
  "May 23",
  "May 24",
  "May 25",
  "May 26",
  "May 27",
];

const DAILY_REVENUE_DOD = [
  1_200_000, -150_000, 80_000, 60_000, 110_000, 40_000, 30_000, -20_000, 50_000,
  10_000, 70_000, 120_000, 200_000,
];

const DAILY_EBITDA_DOD = [
  340_000, -10_000, -60_000, 80_000, 90_000, 20_000, -15_000, 5_000, -25_000,
  10_000, -10_000, 30_000, 60_000,
];

const CUMULATIVE_REVENUE = [
  2_340_000, 3_540_000, 3_390_000, 3_470_000, 3_530_000, 3_640_000, 3_680_000,
  3_710_000, 3_690_000, 3_740_000, 3_750_000, 3_620_000, 3_710_000,
];

export const FINANCIAL_VARIANCE_DEMO: InfographicData = {
  template: "executive",
  theme: "light",
  blocks: [
    {
      type: "title",
      title: "Financial Projection Variance",
      subtitle: "May 14 – 27, 2026",
      date: "2026-05-27",
    },
    {
      type: "hero_card",
      label: "Revenue (May 27)",
      value: "$3.71M",
      comparison_period: "Total across all projects",
    },
    {
      type: "hero_card",
      label: "Revenue change (14 → 27)",
      value: "$1.37M",
      trend: "up",
      trend_value: "+58.6%",
      comparison_period: "period variance",
    },
    {
      type: "hero_card",
      label: "EBITDA (May 27)",
      value: "$31.2K",
      trend: "down",
      trend_value: "-$401.4K",
      comparison_period: "vs May 14",
    },
    {
      type: "hero_card",
      label: "Today's DoD (May 27)",
      value: "$107.4K rev",
      trend: "up",
      trend_value: "$60.0K EBITDA DoD",
    },
    {
      type: "chart",
      chart_type: "bar",
      title: "Daily total revenue — day-over-day change ($)",
      labels: DAYS,
      series: [{ name: "Revenue DoD", values: DAILY_REVENUE_DOD }],
      show_legend: false,
      layout: "half",
    },
    {
      type: "chart",
      chart_type: "bar",
      title: "Daily EBITDA — day-over-day change ($)",
      labels: DAYS,
      series: [{ name: "EBITDA DoD", values: DAILY_EBITDA_DOD }],
      show_legend: false,
      layout: "half",
    },
    {
      type: "chart",
      chart_type: "line",
      title: "Cumulative total revenue by day ($)",
      labels: DAYS,
      series: [{ name: "Cumulative revenue", values: CUMULATIVE_REVENUE }],
      show_legend: false,
    },
    {
      type: "summary",
      title: "Executive Summary",
      content:
        "Revenue grew 58.6% over the May 14–27 window, closing at $3.71M with a $107.4K day-over-day lift on May 27. " +
        "EBITDA recovered $60.0K DoD but remains $401.4K below the May 14 baseline, driven by a sharp drop on May 17–18 " +
        "that the cumulative revenue trend has only partially offset. Watch the EBITDA gap into early June.",
    },
  ],
  metadata: {
    demo: true,
    source: "demo-financial-variance.ts",
  },
};
