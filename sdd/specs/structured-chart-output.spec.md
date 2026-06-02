---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Structured Chart Output Mode

**Feature ID**: FEAT-215
**Date**: 2026-06-02
**Author**: Juan2coder
**Status**: draft
**Target version**: additive — release at maintainers' discretion
**Brainstorm**: `sdd/proposals/structured-chart-output.brainstorm.md` (Recommended Option A, scope-cut)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

The `navigator-frontend-next` app migrated every chart to **LayerChart** behind a single
`<AppChart>` component that consumes a structured, **library-agnostic** contract
(`AppChartConfig`: a chart `type`, `x`/`y` column references, flags like
`stacked`/`trendline`/`splitSeries`, palette controls, plus flat data rows).

The one place the frontend **could not migrate** is the `ChatBubble` component. When the
agent/LLM answers with a chart, it emits a **raw library-specific spec**:

- `message.output_mode === "echarts"` → `message.output` is a full Apache ECharts `option`
  object, painted verbatim.
- `message.output_mode === "altair"` → `message.output` is a Vega-Lite / Altair spec,
  painted verbatim.

Because those are raw specs, the chat had to keep **both `echarts` and `vega`** runtime
dependencies alive purely for that surface, blocking the goal of rendering **every** chart
through one library (LayerChart / `<AppChart>`). The fix belongs in the **backend**
(ai-parrot): teach the agent to emit the same agnostic contract the frontend already speaks.

### Goals

- Add a new `OutputMode.STRUCTURED_CHART` (`"structured_chart"`) that makes the agent emit a
  **library-agnostic** chart configuration mirroring the frontend `AppChartConfig`.
- Introduce a `StructuredChartConfig` pydantic model (camelCase-serialized via aliases) that
  maps **1:1** to `AppChartConfig`, with the flat data rows embedded.
- The agent fetches real domain data via tools (DB query etc.) — same flow as the Altair
  renderer — then maps columns into the config and embeds the rows.
- Populate the rows into the existing `AIMessage.data` / envelope `data` field as well.
- Be **strictly additive and opt-in**: ECHARTS/ALTAIR and their renderers/prompts untouched;
  the mode is selected only when a client requests `output_mode=structured_chart`.

### Non-Goals (explicitly out of scope)

- **No native ECharts/Vega fallback.** `response.code` is left **null**. The deterministic
  `structured→ECharts` transform and its `EChartsMapsMixin` geo dependency are out of scope.
  (Runtime fallback-on-failure was rejected — see `proposals/structured-chart-output.brainstorm.md`
  Option A scope-cut, backed by the Impact Investigation, verdict B.)
- **No LLM-repair retry in v1.** Validation failures degrade gracefully; LLM-driven repair is
  a deferred follow-up (would require injecting an `AbstractClient` into the renderer).
- **No server-side chart rendering** (no HTML/image). The frontend renders from `output`.
- **No changes to ECHARTS / ALTAIR / MAP modes.**
- **No backend enumeration of `mapName` values** — that vocabulary is owned by the frontend.

---

## 2. Architectural Design

### Overview

A new `OutputMode.STRUCTURED_CHART` is added to the core enum. When a client requests it,
`BaseBot` injects a new system prompt (registered alongside a new renderer) instructing the
LLM to fetch data via tools and emit **only** a JSON object matching `StructuredChartConfig`.
On finalize, the existing generic formatter path dispatches to a new
`StructuredChartRenderer` (shipped from the `ai-parrot-visualizations` satellite). The
renderer:

1. extracts the JSON (from `response.code` or message text),
2. validates it into `StructuredChartConfig`,
3. sets `response.output` to the validated config (`model_dump(mode="json", by_alias=True)` →
   camelCase, mirroring `AppChartConfig`),
4. populates `response.data` with the embedded rows (if not already present),
5. **leaves `response.code` null** (no native spec), returning `(config, None)`.

The HTTP handler serializes the existing generic JSON envelope unchanged — `code=null` is
already handled. The frontend `<AppChart>` renders from `output`.

This follows the exact pattern of `AltairRenderer` / `EChartsRenderer` (module-level system
prompt constant + `@register_renderer(mode, system_prompt=...)` + `async def render(...)`),
but is simpler: no `execute_code` spec validation, no `EChartsMapsMixin`, no HTML.

### Component Diagram
```
Client (chat) ──output_mode=structured_chart──► BaseBot.ask()/conversation()
                                                      │
                  get_system_prompt(STRUCTURED_CHART) ┤ (inject prompt → LLM fetches data via tools,
                                                      │  emits StructuredChartConfig JSON)
                                                      ▼
                              formatter.format(STRUCTURED_CHART, response)   [base.py:404 / :1166]
                                                      │
                                                      ▼
                          StructuredChartRenderer.render(response)   [satellite, NEW]
                             ├─ extract JSON (response.code or text)
                             ├─ validate → StructuredChartConfig (pydantic)
                             ├─ response.output = config.model_dump(by_alias=True)   (camelCase)
                             ├─ response.data  = rows (if empty)
                             └─ response.code  = null  ◄── no fallback
                                                      │
                                                      ▼
                       HTTP envelope [handlers/agent.py:2591-2614]  → output / data / code(null) / output_mode
                                                      │
                                                      ▼
                              Frontend <AppChart> renders from `output`
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `OutputMode` (`models/outputs.py:39`) | extends (add member) | `STRUCTURED_CHART = "structured_chart"` |
| `register_renderer` / `_MODULE_MAP` (`outputs/formats/__init__.py:47,20`) | uses + extends | Add `OutputMode.STRUCTURED_CHART: ('.structured_chart',)` to `_MODULE_MAP` |
| `BaseBot.ask()/conversation()` (`bots/base.py:290-292, 977-979, 398-409, 1160-1171`) | uses (no change) | Generic `output_mode != DEFAULT` path injects the prompt and calls `formatter.format()` |
| `OutputFormatter.format()` (`outputs/formatter.py:267`) | uses (no change) | Dispatches to the new renderer via `get_renderer()` |
| `AIMessage` (`models/responses.py:72`) | uses (no change) | Reuse `output`/`data`/`code`/`output_mode` fields |
| `ChatMessage` (`storage/models.py:73`) | uses (no change) | Persists the same fields verbatim |
| HTTP envelope (`handlers/agent.py:2591-2614`) | uses (no change) | `code=null` already handled at `:2597`; dict `output` safe at `:2585` |
| `BaseChart` / `BaseRenderer` (`visualizations .../formats/chart.py:20`) | extends | `StructuredChartRenderer` base class (reuse `_get_content`, env wrapping) |

### Data Models
```python
# packages/ai-parrot/src/parrot/models/outputs.py  (alongside ObjectDetectionResult et al.)
# Fields are snake_case in Python with camelCase aliases so model_dump(by_alias=True)
# emits the frontend AppChartConfig shape 1:1. populate_by_name=True lets the LLM emit
# either casing.

ChartType = Literal[
    "bar", "horizontalBar", "line", "area", "scatter",
    "pie", "donut", "radar", "map",
]
XAxisMode = Literal["category", "time"]

class StructuredChartConfig(BaseModel):
    """Library-agnostic chart configuration mirroring the frontend AppChartConfig."""
    model_config = ConfigDict(populate_by_name=True)  # accept snake_case OR alias on input

    type: ChartType = Field(..., description="Chart type")
    x: str = Field(..., description="Categorical/label column name")
    y: list[str] = Field(..., description="One or more value column names (multi-series)")
    stacked: Optional[bool] = Field(default=None)
    trendline: Optional[bool] = Field(default=None)
    split_series: Optional[bool] = Field(default=None, alias="splitSeries")
    show_legend: Optional[bool] = Field(default=None, alias="showLegend")
    x_axis_mode: Optional[XAxisMode] = Field(default=None, alias="xAxisMode")
    palette: Optional[list[str]] = Field(default=None)
    color_by_sign: Optional[bool] = Field(default=None, alias="colorBySign")
    negative_color: Optional[str] = Field(default=None, alias="negativeColor")
    map_name: Optional[str] = Field(default=None, alias="mapName",
                                    description="GeoJSON map name (frontend-validated, free-form)")
    data: list[dict] = Field(default_factory=list,
                             description="Flat data rows (each row keyed by column name)")
    # Validators (model-level):
    #  - type=="map" requires map_name present.
    #  - every entry in `y` (and `x`) must be a key present in the data rows (when rows non-empty).
    #  - x_axis_mode=="time": x-column values SHOULD be ISO 8601 strings (prompt-enforced).
```

### New Public Interfaces
```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py  (NEW)
STRUCTURED_CHART_SYSTEM_PROMPT = """..."""   # instructs: fetch data via tools, emit ONLY the
                                             # StructuredChartConfig JSON; ISO 8601 for time x.

@register_renderer(OutputMode.STRUCTURED_CHART, system_prompt=STRUCTURED_CHART_SYSTEM_PROMPT)
class StructuredChartRenderer(BaseChart):
    async def render(self, response, *, environment: str = "html", **kwargs
                     ) -> Tuple[Any, Optional[Any]]:
        """Validate the agnostic chart config; populate data; leave code null.

        Returns (config_dict, None). On validation failure: graceful degradation —
        return a best-effort dict carrying an error flag, never raise.
        """
```

---

## 3. Module Breakdown

> These map directly to Task Artifacts in `/sdd-task`.

### Module 1: OutputMode enum member
- **Path**: `packages/ai-parrot/src/parrot/models/outputs.py`
- **Responsibility**: Add `STRUCTURED_CHART = "structured_chart"` to `OutputMode` (after
  `INFOGRAPHIC`, line ~70).
- **Depends on**: nothing.

### Module 2: `StructuredChartConfig` pydantic model
- **Path**: `packages/ai-parrot/src/parrot/models/outputs.py`
- **Responsibility**: The agnostic chart contract (camelCase aliases, `populate_by_name`,
  model-level validators for map/columns). Hosted alongside the other output models.
- **Depends on**: Module 1 (for `type="map"` correlation; otherwise independent).

### Module 3: Dispatch registration
- **Path**: `packages/ai-parrot/src/parrot/outputs/formats/__init__.py`
- **Responsibility**: Add `OutputMode.STRUCTURED_CHART: ('.structured_chart',)` to `_MODULE_MAP`
  so `get_renderer` lazy-imports the satellite renderer.
- **Depends on**: Module 1.

### Module 4: `StructuredChartRenderer` + system prompt
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py` (NEW)
- **Responsibility**: System prompt constant + `@register_renderer`-decorated renderer that
  extracts JSON, validates into `StructuredChartConfig`, sets `output` (camelCase dump),
  populates `response.data`, leaves `code` null, and degrades gracefully on failure.
- **Depends on**: Modules 1, 2, 3.

### Module 5: Tests
- **Path**: `packages/ai-parrot/tests/outputs/formats/test_structured_chart.py` (NEW)
- **Responsibility**: Unit-test the model (alias round-trip, validators) and the renderer
  (valid config → output/data set, code null; malformed → graceful degradation; mode is
  registered and discoverable via `get_renderer`).
- **Depends on**: Modules 1–4.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_structured_chart_config_alias_roundtrip` | M2 | `model_dump(by_alias=True)` emits camelCase (`splitSeries`, `xAxisMode`, `colorBySign`, `negativeColor`, `mapName`); accepts snake_case AND camelCase on input |
| `test_structured_chart_config_map_requires_mapname` | M2 | `type="map"` without `map_name` → `ValidationError` |
| `test_structured_chart_config_y_columns_present` | M2 | `y` referencing a column absent from non-empty `data` → `ValidationError` |
| `test_outputmode_has_structured_chart` | M1 | `OutputMode("structured_chart") is OutputMode.STRUCTURED_CHART` |
| `test_get_renderer_resolves_structured_chart` | M3/M4 | `get_renderer(OutputMode.STRUCTURED_CHART)` returns `StructuredChartRenderer` (lazy import works) |
| `test_renderer_valid_config_sets_output_and_data` | M4 | Valid JSON → `output` is camelCase dict, `data` populated, returned `wrapped` is `None`, `response.code` stays `None` |
| `test_renderer_extracts_from_code_and_text` | M4 | Reads `response.code` first, falls back to `_extract_json_code` on message text |
| `test_renderer_malformed_graceful_degradation` | M4 | Invalid JSON / failed validation → returns best-effort dict with error flag, does NOT raise, `code` still `None` |
| `test_system_prompt_registered` | M4 | `get_output_prompt(OutputMode.STRUCTURED_CHART)` returns the new prompt |

### Integration Tests
| Test | Description |
|---|---|
| `test_envelope_serializes_structured_chart` | Given an `AIMessage` with `output_mode=STRUCTURED_CHART`, `output`=config dict, `code=None`, the handler JSON envelope (`agent.py:2591-2614`) serializes cleanly (`code: null`, `output` is the camelCase config) |
| `test_echarts_altair_unchanged` | ECHARTS and ALTAIR renderers/prompts still resolve and behave exactly as before (regression guard) |

### Test Data / Fixtures
```python
@pytest.fixture
def bar_config_json():
    return (
        '{"type":"bar","x":"month","y":["revenue","cost"],"stacked":true,'
        '"showLegend":true,"xAxisMode":"category",'
        '"data":[{"month":"Jan","revenue":100,"cost":60},'
        '{"month":"Feb","revenue":120,"cost":70}]}'
    )

@pytest.fixture
def map_config_json():
    return ('{"type":"map","x":"country","y":["sales"],"mapName":"world",'
            '"data":[{"country":"AR","sales":42}]}')
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `OutputMode.STRUCTURED_CHART == "structured_chart"` exists and is importable.
- [ ] `StructuredChartConfig` exists in `models/outputs.py`, maps 1:1 to `AppChartConfig`,
      and serializes camelCase via `model_dump(by_alias=True)`.
- [ ] `get_renderer(OutputMode.STRUCTURED_CHART)` resolves the new `StructuredChartRenderer`
      (lazy-imported via `_MODULE_MAP`).
- [ ] `get_output_prompt(OutputMode.STRUCTURED_CHART)` returns the new system prompt.
- [ ] A valid config response yields: `output`=camelCase config dict, `data`=rows,
      **`code` is null**.
- [ ] Malformed config → **graceful degradation** (best-effort result + error flag, no raise).
- [ ] `type="map"` requires `mapName`; `y`/`x` must reference present columns (validators).
- [ ] **Strictly additive**: ECHARTS / ALTAIR / MAP modes, renderers, and prompts are byte-for-byte
      unchanged; no change to `bots/base.py`, `outputs/formatter.py`, or `handlers/agent.py`.
- [ ] All new unit tests pass: `pytest packages/ai-parrot/tests/outputs/formats/test_structured_chart.py -v`.
- [ ] Full suite green: `pytest` (no regressions).
- [ ] No new third-party dependency added.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Re-verified on `dev` (2026-06-02).

### Verified Imports
```python
# Core (ai-parrot):
from parrot.models.outputs import OutputMode                  # outputs.py:39
from parrot.outputs.formats import register_renderer, get_renderer, get_output_prompt  # formats/__init__.py:47,62,76
# Inside the satellite renderer module (packages/ai-parrot-visualizations/.../formats/structured_chart.py):
from . import register_renderer            # resolves to core formats/__init__ via PEP 420 namespace (echarts.py:7)
from ...models.outputs import OutputMode   # echarts.py:8 uses this exact path
from .chart import BaseChart               # echarts.py:6
# pydantic:
from pydantic import BaseModel, Field, ConfigDict   # ConfigDict for populate_by_name
from typing import Literal, Optional
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/models/outputs.py:39
class OutputMode(str, Enum):
    ALTAIR = "altair"            # line 53
    MAP = "map"                  # line 59
    ECHARTS = "echarts"          # line 62
    INFOGRAPHIC = "infographic"  # line 70
    # ADD HERE: STRUCTURED_CHART = "structured_chart"

# packages/ai-parrot/src/parrot/outputs/formats/__init__.py
_MODULE_MAP: dict = {            # line 20
    ...
    OutputMode.ALTAIR:   ('.altair',),    # line 28
    OutputMode.ECHARTS:  ('.echarts',),   # line 35
    ...                                   # ADD: OutputMode.STRUCTURED_CHART: ('.structured_chart',)
}
def register_renderer(mode: OutputMode, system_prompt: Optional[str] = None):  # line 47
def get_renderer(mode: OutputMode) -> Type[Renderer]:                          # line 62 (lazy-imports via _MODULE_MAP)
def get_output_prompt(mode: OutputMode) -> Optional[str]:                      # line 76

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/altair.py  (closest reference)
ALTAIR_SYSTEM_PROMPT = """..."""                                # line 10 (module constant)
@register_renderer(OutputMode.ALTAIR, system_prompt=ALTAIR_SYSTEM_PROMPT)   # line 50
class AltairRenderer(BaseChart):                                # line 51

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/echarts.py  (render/extract pattern)
@register_renderer(OutputMode.ECHARTS, system_prompt=ECHARTS_SYSTEM_PROMPT) # line 105
class EChartsRenderer(EChartsMapsMixin, BaseChart):             # line 106 (DO NOT mix in EChartsMapsMixin)
    async def render(self, response, ..., **kwargs) -> Tuple[Any, Optional[Any]]:  # line 253
        # code = getattr(response, 'code', None) (line 265); else _extract_json_code(content)
    @staticmethod
    def _extract_json_code(content: str) -> Optional[str]:      # line 336 (copy this extraction pattern)

# packages/ai-parrot/src/parrot/bots/base.py  (NO CHANGE — generic path already routes new modes)
if output_mode != OutputMode.DEFAULT:                           # line 290 / 398 / 977 / 1160
    system_prompt_addon := self.formatter.get_system_prompt(output_mode)  # line 292 / 979
    content, wrapped = await self.formatter.format(output_mode, response, **format_kwargs)  # line 404 / 1166
    # response.output = content; response.response = wrapped; response.output_mode = output_mode (407-409 / 1169-1171)

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):          # line 72
    output: Any                      # line 79
    response: Optional[str]          # line 82
    data: Optional[Any]              # line 86
    code: Optional[str]              # line 90
    output_mode: OutputMode          # line 210

# packages/ai-parrot/src/parrot/storage/models.py
@dataclass
class ChatMessage:                   # line 73
    output_mode: Optional[str] = None  # line 88
    data: Optional[Any] = None         # line 89
    code: Optional[str] = None         # line 90

# packages/ai-parrot-server/src/parrot/handlers/agent.py  (NO CHANGE)
"output": output,                                       # line 2593
"code": str(response.code) if response.code else None,  # line 2597  ← already None-safe
output_mode in ('chart', 'dataframe', 'export')          # line 2675  ← artifact tuple (optional additive)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `OutputMode.STRUCTURED_CHART` | `_MODULE_MAP` dispatch | dict entry | `outputs/formats/__init__.py:20-44` |
| `StructuredChartRenderer` | `register_renderer` | decorator | `outputs/formats/__init__.py:47` |
| `StructuredChartRenderer.render()` | `BaseBot` finalize | `formatter.format(mode, response)` | `bots/base.py:404, 1166` |
| system prompt | `BaseBot` prompt injection | `get_system_prompt(mode)` | `bots/base.py:292, 979` |
| `output` (config) / `code` (null) | HTTP envelope | dict serialization | `handlers/agent.py:2593, 2597` |

### Does NOT Exist (Anti-Hallucination)
- ~~`StructuredChartConfig`~~ — to be created in `models/outputs.py` (Module 2).
- ~~`OutputMode.STRUCTURED_CHART`~~ — to be added (Module 1).
- ~~`ChartConfig` / `SeriesConfig` / `AppChartConfig`~~ — no intermediate structured chart model
  exists in ai-parrot today.
- ~~`parrot.outputs.formats.structured_chart`~~ — module to be created in the satellite.
- ~~deterministic `structured→ECharts` transform~~ — **cut from scope**; `response.code` stays null.
- ~~`DEFAULT_RETRY_PROMPTS[OutputMode.STRUCTURED_CHART]`~~ — **not** added in v1 (LLM-repair deferred).
- `EChartsMapsMixin` / `get_echarts_system_prompt_with_geo` (`mixins/emaps.py:609,835`) — exist
  but are **OUT OF SCOPE**; do NOT mix in or call (no server-side geo render).
- `OutputFormatter.format_with_retry` (`formatter.py:608`) — exists but is **DORMANT** (called
  nowhere in `bots/`/`handlers/`, only docstring + `tests/outputs/test_formatter_retry.py`).
  Do NOT rely on it for retry. The bot uses plain `format()` (`base.py:404, 1166`).
- The satellite `parrot/outputs/formats/` directory has **NO `__init__.py`** — do NOT create one
  (it would shadow the core namespace package; merges via `extend_path`, core `__init__.py:1-2`).
- `GenerateChartInput` (`packages/ai-parrot-tools/src/parrot_tools/chart.py`) — exists but is the
  matplotlib/plotly image `ChartTool`; **NOT applicable** to this feature.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mirror `AltairRenderer` (`altair.py:10,50-51`) for the system-prompt-constant +
  `@register_renderer(mode, system_prompt=...)` shape, and the "fetch data via tools then
  emit" prompt style.
- Mirror `EChartsRenderer.render` (`echarts.py:253`) for reading `response.code` first then
  `_extract_json_code(content)` (copy the static `_extract_json_code` extraction, `echarts.py:336`).
- The renderer returns `(content, wrapped)`; for this mode `content`=config dict, `wrapped=None`.
  `BaseBot` assigns them to `response.output`/`response.response` (`base.py:407-409`). Populate
  `response.data` by mutating the `response` passed into `render()` (it is by-reference).
- pydantic: `populate_by_name=True` + camelCase `alias` per field; dump with
  `model_dump(mode="json", by_alias=True)`.
- async-first; Google-style docstrings; strict type hints; `self.logger` for logging.

### Known Risks / Gotchas
- **Graceful degradation contract**: a malformed config must NOT raise out of `render()` — it
  must return a best-effort dict (e.g. `{"error": "...", "raw": <text>}`) so the envelope still
  serializes. Mirror how `EChartsRenderer` returns an error payload instead of raising.
- **camelCase round-trip**: the LLM may emit either snake_case or camelCase; `populate_by_name`
  must accept both, but the dumped `output` must always be camelCase (`by_alias=True`).
- **`data` already present**: only populate `response.data` if empty (the bot may have already
  extracted tool data — `base.py:399-402, 1162-1164`); do not clobber.
- **`code` must stay null**: do not set `response.code`; verify no base path repopulates it.
- **Namespace import**: confirm `get_renderer(OutputMode.STRUCTURED_CHART)` triggers the lazy
  import (`_MODULE_MAP` entry) — same mechanism as `.echarts`.
- **Frontend bridge (coordination)**: the current `AppChartConfig` has neither `mapName` nor an
  embedded `data` field (data is a separate prop). The frontend must adapt the envelope (read
  `mapName` and embedded `data` from `output`, or split them). Documented here; not a backend
  blocker (see §8).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | (already a core dep) | `StructuredChartConfig` model + validation |
| `ai-parrot-visualizations` | (in-repo satellite) | Hosts the new renderer (PEP 420 namespace) |

**No new third-party dependency.**

---

## 8. Open Questions

> Resolved items carry the brainstorm decision trail. Unresolved items must be handled before
> merge where noted.

- [x] Flow type & base branch — *Resolved in brainstorm*: `type: feature`, `base_branch: dev`.
- [x] Emit structured only vs. structured + native spec — *Resolved in brainstorm*: structured
  ONLY; **no native fallback**; `response.code` null (Impact Investigation verdict B).
- [x] Data placement — *Resolved in brainstorm*: rows embedded in config AND populated into
  `AIMessage.data`.
- [x] How the LLM produces the config — *Resolved in brainstorm*: fetch via tools (Altair-style),
  then map columns and embed rows.
- [x] Map coverage — *Resolved in brainstorm*: `type="map"` supported; `x`=region, `y`=value,
  plus `mapName` field (frontend-consumed only).
- [x] Validation failure behavior / retry wiring — *Resolved in brainstorm*: v1 = strict pydantic
  validation + graceful degradation; LLM-repair deferred (no `AbstractClient` in renderer, no
  `base.py` change).
- [x] Backwards compatibility — *Resolved in brainstorm*: strictly additive + opt-in; ECHARTS/ALTAIR
  untouched.
- [x] Field casing — *Resolved in brainstorm*: camelCase via pydantic alias + `populate_by_name`;
  `model_dump(by_alias=True)`.
- [x] `mapName` vocabulary — *Resolved in brainstorm*: free-form `str`; frontend `AppChartGeo`
  owns/validates the set.
- [x] `xAxisMode="time"` row format — *Resolved in brainstorm*: ISO 8601 strings (prompt-enforced).
- [ ] **Frontend coordination / bridge** — *Owner: Juan2coder*: the frontend `AppChartConfig` has
  no `mapName` nor embedded `data` today. Coordinate with the frontend on how `<AppChart>` /
  `ChatBubble` adapts the `structured_chart` envelope (read `mapName` + embedded `data` from
  `output`, or split into config + data-prop). Documentation/coordination item — **not a backend
  blocker** for this spec.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`.
- All tasks (Modules 1–5) run **sequentially in one worktree**
  (`.claude/worktrees/feat-215-structured-chart-output`, already created). They form a tight,
  interdependent vertical slice (enum → model → dispatch → renderer → tests); splitting across
  worktrees adds coordination overhead with no parallelism gain.
- **Cross-feature dependencies**: touches `models/outputs.py` and `outputs/formats/__init__.py`
  (shared with infographic/echarts work). All edits are **additive** (new enum member, new dict
  entry, new model, new file), minimizing conflict surface. Rebase onto `dev` before merge given
  recent infographic/echarts activity.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-02 | Juan2coder | Initial draft from brainstorm (Option A, scope-cut: no native fallback, LLM-repair deferred) |
