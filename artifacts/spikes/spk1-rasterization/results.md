# SPK-1 — Rasterization backend spike (weasyprint vs playwright)

**Feature**: FEAT-273 (Module 0a) · **Date**: 2026-07-11 · **Author**: sdd-worker (Claude)

## Setup

- Fixture: `fixture_infographic_envelope.json` — a realistic `CreateSurface`
  (Infographic + 2 KPICards + a bar Chart), validated through the TASK-1720
  serialization layer (`check_fixture_parses_with_a2ui_models`).
- Both backends consume the **same** materialized HTML (`build_html`) — inline CSS,
  a **static SVG** bar chart, no `<script>`, no external fetches (email-safe).
- Backends: `weasyprint==69.0` (installed; pinned in host pyproject to 68.0),
  `playwright==1.52.0` with Chromium Headless Shell 136.0.7103.25 (installed via
  `playwright install chromium`).
- 3 runs per backend; PDFs compared by `sha256`.

## Measurements

| Backend | Format | Size (bytes) | Latency (ms, 3 runs) | Byte-identical across 3 runs |
|---|---|---|---|---|
| weasyprint | PDF | 8,447 | 140.6 / 101.1 / 100.7 | **Yes** (`2eb622b9…`) |
| weasyprint | email HTML | (self-contained doc) | n/a | Yes (`dcaab372…`) |
| playwright (chromium) | PDF | 30,299 | 7.3 / 8.3 / 6.8 * | **Yes** (`ac53daa7…`) |

\* playwright per-`page.pdf()` latency excludes the one-time `browser.launch()` cost
(~hundreds of ms, amortized across a batch). weasyprint has no launch cost, so for
**cold, single-artifact** rendering weasyprint is competitive-to-faster end-to-end.

Checksums: see `outputs/checksums.sha256`.

## Determinism

- **weasyprint**: byte-identical across all 3 runs. No creation-date drift observed
  (weasyprint pins a fixed PDF metadata date unless overridden).
- **playwright**: byte-identical across all 3 runs **in this environment** (headless
  shell, `set_content` + `page.pdf`). Spec §7 flags playwright PDF nondeterminism in
  some container setups (font substitution, embedded timestamps); it was **not**
  reproduced here, but the risk remains environment-dependent, whereas weasyprint's
  determinism is intrinsic (no browser, no JS, no font-server variance).

## ECharts → static-SVG constraint (weasyprint)

weasyprint executes **no JavaScript**. The fixture's chart is therefore a
hand-authored **static SVG**, and it rasterizes cleanly. Implication for the Module 5
echarts renderer (TASK-1731): for the PDF/weasyprint path, chart content MUST be
pre-rendered to static SVG (ECharts `renderer: 'svg'` server-side, or an SVG builder) —
the live `echarts.init()` HTML wrap is fine for browser/email-preview surfaces but is
invisible to weasyprint. The A2UI echarts renderer's **option-JSON primary output**
plus a static-SVG pre-render companion satisfies this.

## Decision

**weasyprint is confirmed as the default PDF backend for ALL static A2UI artifact
classes (infographic, report, baked HTML).** Rationale:

1. **Intrinsic determinism** — no JS/browser/font-server variance (byte-identical here
   and by construction).
2. **~3.6× smaller output** (8.4 KB vs 30 KB) for the same document.
3. **No browser dependency** — no `playwright install`, no ~100 MB headless shell in
   the deploy image; ships behind the existing `pdf`/`a2ui-pdf` extra only.
4. **No cold-start browser launch** for single-artifact delivery (the common path).

**playwright is NOT adopted as a per-artifact-class split in v1** — no v1 artifact class
requires JS-driven layout. It remains a documented fallback candidate should a future
artifact class need browser-only capabilities (e.g. complex CSS grid/JS charts that
can't pre-render to SVG); revisit in FEAT-B if such a class appears.

Companion requirement carried into TASK-1732 (PDF renderer): rasterize the **SSR-HTML**
output (TASK-1729) via weasyprint, with chart content as static SVG.
