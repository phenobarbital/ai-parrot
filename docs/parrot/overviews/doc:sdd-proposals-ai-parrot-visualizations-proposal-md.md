---
type: Wiki Overview
title: FEAT-200 — Extract `parrot/outputs/formats` to `ai-parrot-visualizations`
id: doc:sdd-proposals-ai-parrot-visualizations-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: bokeh, holoviews, matplotlib, seaborn, d3, echarts, infographic_html, etc.).
relates_to:
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
- concept: mod:parrot.outputs.formats.assets
  rel: mentions
- concept: mod:parrot.outputs.formats.plotly
  rel: mentions
- concept: mod:parrot.outputs.formats.version
  rel: mentions
- concept: mod:parrot.rerankers
  rel: mentions
- concept: mod:parrot.stores
  rel: mentions
- concept: mod:parrot.stores.pgvector
  rel: mentions
---

---
id: FEAT-200
title: Extract parrot/outputs/formats to ai-parrot-visualizations with PEP 420 namespace merging
slug: ai-parrot-visualizations
type: feature
mode: enrichment
status: accepted
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-05-28
  summary_oneline: "Move outputs/formats to ai-parrot-visualizations with PEP 420 namespace merging"
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-200/
created: 2026-05-28
updated: 2026-05-28
---

# FEAT-200 — Extract `parrot/outputs/formats` to `ai-parrot-visualizations`

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` — move `outputs/formats` to a new package with PEP 420 support
> **Audit**: [`sdd/state/FEAT-200/`](../state/FEAT-200/)

---

## 0. Origin

`parrot/outputs/formats/` contains ~29 renderer modules (plotly, altair,
bokeh, holoviews, matplotlib, seaborn, d3, echarts, infographic_html, etc.).
Each drags heavy visualization dependencies into the ai-parrot core.
Objective: extract to a new satellite package `ai-parrot-visualizations`
using **PEP 420 implicit namespace packages** — the same pattern used by
`ai-parrot-embeddings` for `parrot.embeddings`, `parrot.stores`, and
`parrot.rerankers`. Import paths remain unchanged: `from parrot.outputs.formats.plotly import ...`.

**Initial signals**:
- Verbs: "extract", "modularize", "PEP 420", "same as ai-parrot-embeddings".
- Named entities: `parrot/outputs/formats/`, `ai-parrot-visualizations`,
  `ai-parrot-embeddings` (reference pattern).
- Acceptance criteria: core without heavy viz deps, consumers keep working,
  import paths unchanged.

---

## 1. Synthesis Summary

The architecture is **ready for extraction via PEP 420**: the same
`pkgutil.extend_path()` + `namespaces = true` pattern proven by
`ai-parrot-embeddings` applies directly. The existing `import_module()`
calls in `formats/__init__.py:33-91` work as-is once `extend_path()` is
added — Python searches both the core and satellite `parrot/outputs/formats/`
directories.

Only **3 production consumers** import renderers directly (all
`InfographicHTMLRenderer`); the rest uses `OutputFormatter` + registry.
`matplotlib==3.10.0` and `seaborn==0.13.2` are in **BASE dependencies**
(pyproject.toml:93-94) — removing them is the primary win. Heavy viz
deps (`plotly/altair/bokeh/holoviews/streamlit/folium`) are tangled in
the `[agents]` extra alongside scraping/finance.

**Key difference from original FEAT-200 proposal**: PEP 420 eliminates the
need for entry-points or plugin discovery. The namespace is
`parrot.outputs.formats` (not `parrot_visualizations`). The hardcoded
`import_module` switch continues working across package boundaries.

---

## 2. Codebase Findings

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/outputs/formats/` | 29 files + assets | — | Extraction target | F001 |
| 2 | `packages/ai-parrot/src/parrot/outputs/formats/__init__.py` | `get_renderer` hardcoded switch | 33-91 | Works as-is with `extend_path()` | F002 |
| 3 | `packages/ai-parrot/src/parrot/outputs/formatter.py` | `OutputFormatter`, `OutputRetryConfig` | — | Stays in core | F002 |
| 4 | `packages/ai-parrot/src/parrot/models/outputs.py` | `OutputMode` enum (23 values) | 39-72 | Stays in core; satellite depends on it | F006 |
| 5 | `packages/ai-parrot/src/parrot/bots/abstract.py` | `import InfographicHTMLRenderer` | 3877 | Direct consumer — migrate to `get_renderer()` | F004 |
| 6 | `packages/ai-parrot/src/parrot/handlers/artifacts.py` | same import | — | Direct consumer — migrate to `get_renderer()` | F004 |
| 7 | `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` | same import | — | Direct consumer — migrate to `get_renderer()` | F004 |
| 8 | `packages/ai-parrot/pyproject.toml` | `matplotlib==3.10.0`, `seaborn==0.13.2` in BASE deps | 93-94 | Leaking into core — extract | F005 |
| 9 | `packages/ai-parrot/pyproject.toml` | `[agents]` extra mixes viz with scraping/finance | 192-246 | Refactor: extract viz deps | F005 |
| 10 | `packages/ai-parrot-embeddings/pyproject.toml` | PEP 420 reference pattern | 95-98 | `namespaces = true` + `include = ["parrot*"]` | F008 |
| 11 | `packages/ai-parrot/src/parrot/embeddings/__init__.py` | `extend_path(__path__, __name__)` | 1-2 | Reference pattern for namespace merging | F008 |

### 2.2 Constraints Discovered

- **`OutputMode` is central and CANNOT move.**
  Imported by 30+ files. Satellite depends on core for the enum.
  *Evidence*: F006

- **`OutputFormatter` is the orchestrator (used in `bots/abstract.py:477`).**
  Queries registry via `get_renderer`. Stays in core.
  *Evidence*: F002, F004

- **The `import_module` switch works with PEP 420.**
  `import_module('.matplotlib', 'parrot.outputs.formats')` resolves modules
  in both core and satellite directories once `extend_path()` is added.
  This is the same mechanism that lets `ai-parrot-embeddings` provide
  `parrot.stores.pgvector` without entry-points.
  *Evidence*: F002, F008

- **Only 3 files import renderers directly (all `InfographicHTMLRenderer`).**
  Trivial migration: replace with `get_renderer(OutputMode.INFOGRAPHIC)`.
  *Evidence*: F004

- **`matplotlib` + `seaborn` are in BASE deps (pyproject.toml:93-94).**
  `plotly/altair/bokeh/holoviews/streamlit/folium` in `[agents]`.
  Extraction provides: (a) remove matplotlib/seaborn from core, (b) per-renderer
  granularity, (c) decouple viz from agents/scraping.
  *Evidence*: F005

- **`infographic_html` is under active development; rest is dormant.**
  Big-bang extraction is acceptable per user decision — single PR.
  *Evidence*: F007

- **`extend_path()` needed at two levels in core.**
  `parrot/outputs/__init__.py` and `parrot/outputs/formats/__init__.py`
  both need `extend_path()`. `parrot/__init__.py` likely already has it
  (from embeddings support).
  *Evidence*: F008

### 2.3 Recent History

| Commit | When | Message |
|--------|------|---------|
| `34cbef04` | recent | feat(multi-tab-infographic): TASK-661/662/663/664 |
| `a3d59542` | recent | feat(infographic-html-output): TASK-646 — ECharts Chart Rendering |
| `03b13eae` | recent | feat(infographic-html-output): TASK-645 — HTML Block Renderers |

Only `infographic_html` has recent activity. All other renderers are dormant.

---

## 3. Architecture — PEP 420 Namespace Merging

### 3.1 Pattern (from `ai-parrot-embeddings`)

```
Host (ai-parrot)                        Satellite (ai-parrot-visualizations)
─────────────────                       ─────────────────────────────────────
src/parrot/                             src/parrot/              ← .gitkeep only
  outputs/                                outputs/              ← .gitkeep only
    __init__.py  ← extend_path()            formats/            ← .gitkeep only
    formatter.py ← stays in core              matplotlib.py     ← moved here
    formats/                                  seaborn.py
      __init__.py ← extend_path() +          plotly.py
                    registry + switch         altair.py
      base.py     ← stays in core            bokeh.py
      json.py     ← stays in core            holoviews.py
      yaml.py     ← stays in core            d3.py
      html.py     ← stays in core            echarts.py
      table.py    ← stays in core            map.py
                                              infographic.py
                                              infographic_html.py
                                              application.py
                                              chart.py
                                              card.py
                                              slack.py
                                              whatsapp.py
                                              jinja2.py
                                              template_report.py
                                              markdown.py
                                              generators/
                                                __init__.py
                                                abstract.py
                                                panel.py
                                                streamlit.py
                                                terminal.py
                                              mixins/
                                                __init__.py
                                                emaps.py
                                              assets/
                                                echarts.min.js
```

### 3.2 How `import_module` Works Across Packages

```python
# In core's formats/__init__.py (UNCHANGED logic):
import_module('.matplotlib', 'parrot.outputs.formats')

# Python resolution with extend_path():
# 1. parrot.outputs.formats.__path__ = [
#      '.../ai-parrot/src/parrot/outputs/formats',      ← core
#      '.../ai-parrot-visualizations/src/parrot/outputs/formats'  ← satellite
#    ]
# 2. Finds matplotlib.py in satellite → imports it
# 3. @register_renderer decorator fires → RENDERERS[OutputMode.MATPLOTLIB] = cls
# 4. get_renderer(OutputMode.MATPLOTLIB) returns the class
```

### 3.3 Core `__init__.py` Changes

**`parrot/outputs/__init__.py`** — add at top:
```python
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)
```

**`parrot/outputs/formats/__init__.py`** — add at top:
```python
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)
```

### 3.4 Satellite `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=67.6.1", "wheel>=0.44.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-parrot-visualizations"
dynamic = ["version"]
description = "Visualization renderers for AI-Parrot outputs"
requires-python = ">=3.11"
license = "MIT"
dependencies = [
    "ai-parrot",
]

[project.optional-dependencies]
matplotlib = ["matplotlib>=3.7"]
seaborn = ["seaborn>=0.13", "matplotlib>=3.7"]
plotly = ["plotly>=5.0"]
altair = ["altair>=5.0"]
bokeh = ["bokeh>=3.0", "pandas-bokeh>=0.5"]
holoviews = ["holoviews>=1.18"]
echarts = []  # JS-based, no Python deps
d3 = []       # JS-based, no Python deps
map = ["folium>=0.14"]
infographic = ["cairosvg", "svglib", "reportlab"]
jinja2 = ["jinja2>=3.0"]
streamlit = ["streamlit>=1.30"]
panel = ["panel>=1.0"]
messaging = []  # card/slack/whatsapp — no heavy deps
charts = [
    "ai-parrot-visualizations[matplotlib,seaborn,plotly,altair,bokeh,holoviews,echarts,d3]",
]
all = [
    "ai-parrot-visualizations[charts,map,infographic,jinja2,streamlit,panel,messaging]",
]

[tool.setuptools.dynamic]
version = {attr = "parrot.outputs.formats.version.__version__"}

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true

[tool.setuptools.package-data]
"parrot.outputs.formats.assets" = ["*.js"]

[tool.uv.sources]
ai-parrot = { workspace = true }
```

---

## 4. Scope (All Unknowns Resolved)

### What's New

- **Package `packages/ai-parrot-visualizations/`** (workspace member)
  with its own `pyproject.toml` declaring granular extras.
- **`extend_path()` calls** in `parrot/outputs/__init__.py` and
  `parrot/outputs/formats/__init__.py` to enable PEP 420 merging.
- **`parrot/outputs/formats/version.py`** in the satellite for dynamic
  version discovery.

### What Changes

- **`parrot/outputs/__init__.py`** — add `extend_path()` (2 lines).
- **`parrot/outputs/formats/__init__.py`** — add `extend_path()` (2 lines).
  The `import_module` switch is unchanged.
- **`parrot/bots/abstract.py:3877`**, **`handlers/artifacts.py`**,
  **`tools/infographic_toolkit.py`** — replace direct
  `import InfographicHTMLRenderer` with `get_renderer(OutputMode.INFOGRAPHIC)`.
- **`packages/ai-parrot/pyproject.toml`**:
  - Remove `matplotlib==3.10.0` and `seaborn==0.13.2` from BASE deps (l.93-94).
  - Remove viz deps from `[agents]` extra.
  - Add new extra: `visualizations = ["ai-parrot-visualizations[charts]"]`.
  - Update `[all]` meta-extra to include `visualizations`.

### What's Moved (to satellite `parrot/outputs/formats/`)

| Module(s) | Extra | Heavy deps |
|-----------|-------|------------|
| `matplotlib.py` | `[matplotlib]` | matplotlib |
| `seaborn.py` | `[seaborn]` | seaborn, matplotlib |
| `plotly.py` | `[plotly]` | plotly |
| `altair.py` | `[altair]` | altair |
| `bokeh.py` | `[bokeh]` | bokeh, pandas-bokeh |
| `holoviews.py` | `[holoviews]` | holoviews |
| `d3.py` | `[d3]` | none (JS-based) |
| `echarts.py` + `assets/echarts.min.js` | `[echarts]` | none (JS-based) |
| `map.py` | `[map]` | folium |
| `infographic.py`, `infographic_html.py` | `[infographic]` | cairosvg, svglib, reportlab |
| `application.py` | — | TBD |
| `chart.py` | — | (base chart class) |
| `card.py`, `slack.py`, `whatsapp.py` | `[messaging]` | none |
| `jinja2.py`, `template_report.py` | `[jinja2]` | jinja2 |
| `markdown.py` | — | none |
| `generators/` (panel, streamlit, terminal, abstract) | `[panel]`/`[streamlit]` | panel, streamlit |
| `mixins/emaps.py` | — | — |

### What Stays in Core

- **`OutputMode` + `OutputType` enums** (`parrot/models/outputs.py`).
- **`OutputFormatter`**, **`OutputRetryConfig`**, **`DEFAULT_RETRY_PROMPTS`**
  (`parrot/outputs/formatter.py`).
- **Registry**: `Renderer` Protocol, `RENDERERS` dict, `register_renderer`,
  `get_renderer`, `get_output_prompt`, `has_system_prompt`
  (`parrot/outputs/formats/__init__.py` — with `extend_path()` added).
- **`RenderResult`, `RenderError`, `BaseRenderer`**
  (`parrot/outputs/formats/base.py`).
- **Zero-dep renderers**: `json.py`, `yaml.py`, `html.py`, `table.py`.

### Non-Goals

- No rewrite of `OutputFormatter` API or renderer signatures.
- No changes to `OutputMode` enum (stable and central).
- No entry-points or plugin discovery mechanism — PEP 420 is sufficient.

### Patterns to Follow

- **Identical build config** to `ai-parrot-embeddings`:
  `namespaces = true`, `include = ["parrot*"]`, `where = ["src"]`.
- **`.gitkeep` files** at namespace boundaries in the satellite
  (no `__init__.py` at `parrot/`, `parrot/outputs/`, `parrot/outputs/formats/`).
- **`extend_path()`** in the core's `__init__.py` files at each namespace level.
- **`ai-parrot` as a dependency** of the satellite (for enums, base classes, registry).

### Phasing

**Big-bang single PR** (user decision):
1. Scaffold `packages/ai-parrot-visualizations/` with pyproject.toml.
2. Add `extend_path()` to core `__init__.py` files.
3. Move all non-zero-dep renderer files to satellite.
4. Update core pyproject.toml (remove matplotlib/seaborn from BASE, refactor extras).
5. Migrate 3 direct `InfographicHTMLRenderer` imports to `get_renderer()`.
6. Add `version.py` to satellite.
7. Update workspace `pyproject.toml` (add member).
8. Run full test suite.

### Integration Risks

- **Users depending on `matplotlib`/`seaborn` transitively** will break.
  *Mitigate*: CHANGELOG entry with `pip install ai-parrot-visualizations[charts]`.
- **`infographic_html` under active development** — coordinate timing.
  Since it's big-bang, merge should happen at a quiet moment.
- **`DEFAULT_RETRY_PROMPTS` references `OutputMode.ECHARTS`** — verify
  `get_output_prompt` works after extraction (test explicitly).
- **`generators/terminal.py`** may be lightweight enough for core — but per
  U2 decision, it moves with the rest. If issues arise, can be moved back.

---

## 5. Confidence Map

| ID | Claim | Evidence | Confidence |
|----|-------|----------|-----------|
| C1 | `formats/` has 29 extractable files + 1MB asset | F001 | **high** |
| C2 | Registry is designed for extraction (lazy import + decorator) | F002 | **high** |
| C3 | `import_module` switch works with PEP 420 + `extend_path()` | F002, F008 | **high** |
| C4 | Only 3 production consumers import renderers directly | F004 | **high** |
| C5 | matplotlib and seaborn are in BASE deps (leak) | F005 | **high** |
| C6 | plotly/altair/bokeh/holoviews only in `[agents]` (no granularity) | F005 | **high** |
| C7 | `OutputMode` is stable and central — stays in core | F006 | **high** |
| C8 | `OutputFormatter` stays in core | F002, F004 | **high** |
| C9 | `infographic_html` active, rest dormant | F007 | **high** |
| C10 | `ai-parrot-embeddings` PEP 420 pattern is proven and replicable | F008 | **high** |
| C11 | `base.py` importable from satellite via shared namespace | F008 | **high** |
| C12 | Zero-dep renderers (json/yaml/html/table) can stay in core | F003 | **high** |

Distribution: **12** high, **0** medium, **0** low.

---

## 6. Open Questions

### Resolved

- [x] **U1: Discovery mechanism?**
  **Answer**: PEP 420 implicit namespace packages + `extend_path()`.
  The existing `import_module('.matplotlib', 'parrot.outputs.formats')`
  switch works as-is. No entry-points needed. Same pattern as
  `ai-parrot-embeddings`.

- [x] **U2: Which renderers stay in core?**
  **Answer**: Only zero-dep renderers: `json.py`, `yaml.py`, `html.py`,
  `table.py`. Everything else moves to the satellite with appropriate extras.

- [x] **U3: Phasing strategy?**
  **Answer**: Big-bang single PR. All renderers moved in one shot.
  Coordinate timing to avoid conflicts with active `infographic_html` work.

- [x] **U4: Package name and Python namespace?**
  **Answer**: PyPI name `ai-parrot-visualizations`. Python namespace
  `parrot.outputs.formats` via PEP 420 (import paths unchanged).

### Unresolved

*(none)*

---

## 7. Recommended Next Step

**`/sdd-spec FEAT-200`** — All unknowns are resolved with high confidence.
The architecture mirrors the proven `ai-parrot-embeddings` pattern. A spec
can proceed directly to task decomposition.

### Alternatives

- **`/sdd-task FEAT-200`** — if scope is clear enough to skip the spec
  formality (the proposal covers architecture in detail).
- **`/sdd-brainstorm FEAT-200`** — not needed: no architectural unknowns remain.

---

## 8. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-200/state.json` |
| Source (raw) | `sdd/state/FEAT-200/source.md` |
| Research plan | `sdd/state/FEAT-200/research_plan.json` |
| Findings | `sdd/state/FEAT-200/findings/F001..F008-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-200/synthesis.json` |

**Budget consumed** (profile `default`):
- Files read: 12 / 40
- Grep calls: 8 / 25
- Git calls: 2 / 10
- Wall time: ~180s / 300s
- Truncated: **no**

**Mode determination**: `auto` -> `enrichment` (existing code extraction with
a proven reference pattern).

---

## 9. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v2.0` (enrichment of original FEAT-200) |
| Operator | Claude Opus 4.6 |
| Key delta from v1.0 | PEP 420 namespace merging replaces entry-points; all 4 unknowns resolved |
