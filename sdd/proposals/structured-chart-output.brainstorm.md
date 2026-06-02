---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Structured Chart Output Mode

**Date**: 2026-06-02
**Author**: Juan2coder
**Status**: exploration
**Recommended Option**: A
**Feature ID**: FEAT-215

---

## Problem Statement

The `navigator-frontend-next` app migrated every chart to **LayerChart** behind a
single `<AppChart>` component that consumes a structured, **library-agnostic**
contract (`AppChartConfig`: a chart `type`, `x`/`y` column references, flags like
`stacked`/`trendline`/`splitSeries`, palette controls, plus flat data rows).

The one place the frontend **could not migrate** is the `ChatBubble` component.
When the agent/LLM answers with a chart, it emits a **raw library-specific spec**:

- `message.output_mode === "echarts"` → `message.output` is a full Apache ECharts
  `option` object, painted verbatim.
- `message.output_mode === "altair"` → `message.output` is a Vega-Lite / Altair spec,
  painted verbatim.

Because those are raw specs, the chat had to keep **both `echarts` and `vega`**
runtime dependencies alive purely for that surface, blocking the goal of rendering
**every** chart through one library (LayerChart / `<AppChart>`).

**Who is affected:** frontend (carries two extra chart runtimes + duplicated render
paths), and indirectly every consumer of the agent chat surface.

**Why now:** the frontend migration is otherwise complete; the chat is the last
blocker to removing `echarts` + `vega` from the bundle. The fix belongs in the
**backend** (ai-parrot): teach the agent to emit the same agnostic contract the
frontend already speaks.

## Constraints & Requirements

- **Mirror the frontend contract.** The new pydantic model must map 1:1 to
  `AppChartConfig` (`type`, `x`, `y[]`, `stacked?`, `trendline?`, `splitSeries?`,
  `showLegend?`, `xAxisMode?`, `palette?`, `colorBySign?`, `negativeColor?`) plus flat
  data rows (`list[dict]`).
- **Strictly additive.** `OutputMode.ECHARTS` and `OutputMode.ALTAIR` and their
  renderers/prompts must remain untouched. The new behavior is **opt-in** via
  `output_mode=structured_chart`. Zero regressions.
- **Dual emission with deterministic fallback.** Alongside the structured config,
  emit a native ECharts spec **derived deterministically server-side** from the
  structured config (no extra LLM tokens, guaranteed config↔spec consistency) so the
  frontend can fall back during the migration window.
- **Real data via tools.** The chart must use real domain data: the agent fetches it
  through tools (e.g. `database_query`) — same flow as the Altair renderer — then maps
  columns into the config and embeds the rows.
- **Data in two places (configurable).** Rows embedded in the config (mirrors
  `AppChartConfig`) AND populated into the existing `AIMessage.data` / envelope `data`
  field for clients that read it.
- **Map support included.** The contract accepts `type: "map"`, represented agnostically
  as `x`=region column, `y`=value column, plus a new `mapName` field
  (e.g. `"world"`, `"USA"`, `"Argentina"`) selecting the GeoJSON.
- **Resilient validation.** On a config that fails pydantic validation, retry with a
  STRUCTURED_CHART repair prompt. ⚠️ **VERIFIED CAVEAT:** the existing
  `OutputFormatter.format_with_retry` loop is **dormant** — it is never called from the
  agent flow (the bot uses plain `formatter.format()` at `base.py:404` and `:1166`;
  `format_with_retry` appears only in its own docstring + unit tests). So retry must be
  *explicitly enabled* — see Open Questions. This is NOT free reuse.
- **Async-first, Google-style docstrings, strict type hints, Pydantic** (project rules).
- **Renderers ship from the satellite** `ai-parrot-visualizations` (PEP 420 namespace);
  core only gains the enum value + dispatch entry + the pydantic model.

---

## Options Explored

### Option A: New `STRUCTURED_CHART` mode — LLM emits agnostic config, renderer derives ECharts deterministically

The agent runs in a new `OutputMode.STRUCTURED_CHART`. Its system prompt instructs the
LLM to (1) fetch data with tools, then (2) emit **only** a JSON object validated against a
new `StructuredChartConfig` pydantic model (the agnostic contract + embedded rows). A new
`StructuredChartRenderer` (in the satellite) validates the JSON, populates `response.data`
with the rows, and **deterministically transforms** the config into a native ECharts
`option` (placed in `response.code`) as a migration fallback. No HTML is rendered — the
frontend's `<AppChart>` renders from the structured `output`.

✅ **Pros:**
- One LLM contract, one source of truth; the ECharts fallback can never diverge from the
  structured config because it is generated from it.
- Zero extra LLM tokens for the fallback (pure server-side transform).
- Cleanly additive: new enum value + new `_MODULE_MAP` entry + new renderer module.
  ECHARTS/ALTAIR fully untouched.
- Reuses the entire existing plumbing: `register_renderer`, `get_system_prompt`
  injection in `BaseBot`, `format_with_retry` retry loop, and the JSON response envelope.
- Maps handled with the same `x`/`y` + `mapName` shape; the deterministic transform can
  lean on the existing `EChartsMapsMixin` for the geo fallback.

❌ **Cons:**
- A deterministic `structured → ECharts` transformer must cover each chart `type`
  (bar/line/area/scatter/pie/donut/radar/map) — non-trivial but bounded and unit-testable.
- The renderer mutates `response.code` (side-effect) to carry the fallback spec; needs a
  documented, tested contract (see Open Questions).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (v2, already used) | `StructuredChartConfig` model + validation | `model_json_schema()` already used elsewhere in `outputs.py` |
| `ai-parrot-visualizations` (satellite, in-repo) | Hosts the new renderer | PEP 420 namespace merge into `parrot.outputs.formats` |
| — (no new 3rd-party dep) | Deterministic transform is plain Python/dicts | Avoids adding `pyecharts` etc. |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/models/outputs.py` — add enum value + host the pydantic model (alongside `ObjectDetectionResult` et al.).
- `packages/ai-parrot/src/parrot/outputs/formats/__init__.py` — `register_renderer`, `_MODULE_MAP` dispatch.
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/echarts.py` — renderer pattern (`execute_code`, `_extract_json_code`, `render`).
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/mixins/emaps.py` — `EChartsMapsMixin` / `get_echarts_system_prompt_with_geo` for the map fallback.
- `packages/ai-parrot/src/parrot/outputs/formatter.py` — `DEFAULT_RETRY_PROMPTS` + `format_with_retry`.

---

### Option B: LLM emits BOTH the structured config and a raw ECharts spec in one response

Same new mode, but the system prompt asks the LLM to return **two blocks**: the structured
config and a hand-built ECharts `option`. The renderer validates both and forwards them.

✅ **Pros:**
- No deterministic transformer to write — the LLM does the mapping.
- The LLM can produce richer ECharts specs than a generic transform.

❌ **Cons:**
- The two outputs **drift**: the ECharts spec may not match the structured config,
  defeating the "single source of truth" goal and creating confusing chat renders.
- ~2× the output tokens and latency per chart.
- Two validation paths and two failure modes to retry.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (v2) | Validate the structured block | same as Option A |
| existing `EChartsRenderer.execute_code` | Validate the ECharts block | reuse, but now on a second payload |

🔗 **Existing Code to Reuse:**
- Same modules as Option A, plus `EChartsRenderer.execute_code` for the second payload.

---

### Option C: Translate at the edge — keep ECHARTS, add a server-side ECharts→AppChartConfig adapter in the HTTP handler

Leave the agent emitting ECharts as today. Add a converter in the response path
(`handlers/agent.py`) that parses the emitted ECharts `option` and **down-converts** it to
`AppChartConfig`, attaching it as a new field while keeping `output` as the raw spec.

✅ **Pros:**
- The agent / prompts stay completely unchanged.
- Frontend gets the agnostic config "for free".

❌ **Cons:**
- **Reverse-engineering an arbitrary ECharts `option`** into a clean agnostic config is
  lossy and brittle (ECharts is far more expressive than `AppChartConfig`); the LLM's
  freeform specs won't map cleanly.
- Still requires the LLM to produce ECharts → does not remove the chat's dependency on
  ECharts-shaped output; it only adds a fragile translation layer.
- Logic lands in the server handler rather than the reusable renderer layer, splitting
  responsibility away from `parrot.outputs`.
- Hardest to keep correct as charts get complex.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (v2) | Target `AppChartConfig` model | same model, different producer |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/handlers/agent.py` — response envelope (`output`, `data`, `code`, `output_mode`).

---

## Recommendation

**Option A** is recommended.

It is the only option that achieves the actual goal — a **single, agnostic source of
truth** the frontend can render with one library — while staying cheap and consistent.
By having the LLM emit *only* the structured config and **deriving** the ECharts fallback
deterministically, the config and its fallback can never diverge (the failure mode that
sinks Option B), and there is no fragile reverse-engineering of arbitrary specs (the
failure mode that sinks Option C). It costs no extra LLM tokens for the fallback, lands
entirely in the reusable renderer layer following the proven `EChartsRenderer` pattern,
and is strictly additive so ECHARTS/ALTAIR keep working untouched.

The tradeoff accepted: we must write and maintain a deterministic `structured → ECharts`
transformer per chart type. This is bounded (a fixed set of types), fully unit-testable,
and the natural place for the complexity — far preferable to runtime divergence or lossy
reverse translation.

---

## Feature Description

### User-Facing Behavior
A client (the chat) requests `output_mode=structured_chart`. The agent answers with a
response whose:
- `output` = a `StructuredChartConfig` JSON object (chart `type`, `x`, `y[]`, flags,
  palette controls, **embedded data rows**) — directly consumable by `<AppChart>`.
- `data` = the same flat rows (for clients that read the envelope `data` field).
- `code` = a deterministically-derived native ECharts `option` JSON (migration fallback).
- `output_mode` = `"structured_chart"`.

The frontend `ChatBubble` can render via LayerChart/`<AppChart>` from `output` and drop
its `echarts` + `vega` runtime dependencies once it no longer needs the `code` fallback.

### Internal Behavior
1. `BaseBot.ask()/conversation()` receives `output_mode=STRUCTURED_CHART` and injects the
   new system prompt via `self.formatter.get_system_prompt(output_mode)` (existing path,
   `base.py:292/979`). The prompt instructs: use tools to fetch data, then emit a single
   JSON object matching the `StructuredChartConfig` schema (schema embedded via
   `model_json_schema()`), with rows under the config's `data` field.
2. The LLM (after tool calls) returns the JSON; it lands in `response.code` (code
   extraction) or the message text.
3. On finalize (`base.py:1160-1171`), `formatter.format(STRUCTURED_CHART, response)`
   dispatches to the new `StructuredChartRenderer`.
4. The renderer extracts the JSON (reusing the `_extract_json_code` pattern), validates it
   into `StructuredChartConfig`, then:
   - sets `output` = validated config (`model_dump(mode="json")`),
   - populates `response.data` with the rows (if not already present),
   - deterministically transforms the config into an ECharts `option` and writes it to
     `response.code` (the fallback; maps via `EChartsMapsMixin`).
5. The HTTP handler serializes the generic JSON envelope (`agent.py:2591-2614`):
   `output`, `data`, `response`, `output_mode`, `code` — no handler change required for
   the happy path (the INFOGRAPHIC special-case at `2547` is not triggered).

### Edge Cases & Error Handling
- **Invalid/malformed config JSON** → repaired via a STRUCTURED_CHART repair prompt.
  ⚠️ Requires wiring retry into the flow (the dormant `format_with_retry` is not invoked
  today) — either call it for this mode in `base.py`, or handle validation+repair inside
  the renderer. The repair prompt (`DEFAULT_RETRY_PROMPTS[OutputMode.STRUCTURED_CHART]`)
  is new and must be added regardless.
- **`y` references a column absent from rows** → validation error surfaced to the retry
  loop (model-level validator).
- **`type=map` without `mapName`** → validation error (conditional requirement).
- **`colorBySign=true` without `negativeColor`** → fall back to a default negative color
  (documented), not an error.
- **Empty rows** → emit the config with empty `data`; frontend renders an empty-state.
- **Transform can't map a type to ECharts** → still return the structured `output` (the
  primary contract); leave `code` null and log a warning (fallback is best-effort).

---

## Capabilities

### New Capabilities
- `structured-chart-output`: a library-agnostic `OutputMode.STRUCTURED_CHART` that emits a
  `StructuredChartConfig` mirroring the frontend `AppChartConfig`, plus a deterministically
  derived ECharts fallback.

### Modified Capabilities
<!-- none — strictly additive -->

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/outputs.py` | modifies | Add `OutputMode.STRUCTURED_CHART = "structured_chart"`; add `StructuredChartConfig` (+ enums) pydantic model |
| `packages/ai-parrot/src/parrot/outputs/formats/__init__.py` | modifies | Add `OutputMode.STRUCTURED_CHART: ('.structured_chart',)` to `_MODULE_MAP` |
| `packages/ai-parrot-visualizations/.../outputs/formats/structured_chart.py` | extends (new file) | `StructuredChartRenderer` + system prompt + deterministic `structured→ECharts` transform |
| `packages/ai-parrot/src/parrot/outputs/formatter.py` | modifies | Add `DEFAULT_RETRY_PROMPTS[OutputMode.STRUCTURED_CHART]` repair prompt |
| `packages/ai-parrot/src/parrot/bots/base.py` | depends on | No change expected — generic `output_mode != DEFAULT` path already routes to the formatter (verify `code` mutation reaches envelope) |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | depends on | No change for happy path; verify dict `output` serializes cleanly (it does — `2585` safety net) |
| `AIMessage` / `ChatMessage` | depends on | Reuse existing `output`/`data`/`code`/`output_mode` fields — no schema change |

**No breaking changes. No new third-party dependency.**

---

## Code Context

### User-Provided Code
```text
# Source: user-provided — frontend AppChartConfig contract to mirror
type: "bar" | "horizontalBar" | "line" | "area" | "scatter" | "pie" | "donut" | "radar" | "map"
x: str                      # categorical / label column
y: list[str]                # one or more value columns (multi-series)
stacked?: bool
trendline?: bool
splitSeries?: bool          # dual Y axis
showLegend?: bool
xAxisMode?: "category" | "time"
palette?: list[str]
colorBySign?: bool          # color bars by sign
negativeColor?: str
# data rows: list[dict]  (each row an object keyed by column)
```

### Verified Codebase References

#### Classes & Signatures
```python
# packages/ai-parrot/src/parrot/models/outputs.py:39
class OutputMode(str, Enum):
    ALTAIR = "altair"          # line 53
    MAP = "map"                # line 59
    ECHARTS = "echarts"        # line 62
    INFOGRAPHIC = "infographic"  # line 70
    # ADD: STRUCTURED_CHART = "structured_chart"
# Pydantic output models also live here (e.g. ObjectDetectionResult:208,
# ImageGenerationPrompt:220) → StructuredChartConfig belongs here too.

# packages/ai-parrot/src/parrot/outputs/formats/__init__.py
RENDERERS: Dict[OutputMode, Type[Renderer]] = {}            # line 16
_PROMPTS: Dict[OutputMode, str] = {}                        # line 17
_MODULE_MAP: dict = { ... OutputMode.ECHARTS: ('.echarts',), ... }  # lines 20-44
def register_renderer(mode: OutputMode, system_prompt: Optional[str] = None):  # line 47
def get_renderer(mode: OutputMode) -> Type[Renderer]:       # line 62 (lazy-imports via _MODULE_MAP)
def get_output_prompt(mode: OutputMode) -> Optional[str]:   # line 76

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/echarts.py
ECHARTS_BASE_PROMPT = """..."""                             # line 31
@register_renderer(OutputMode.ECHARTS, system_prompt=ECHARTS_SYSTEM_PROMPT)  # line 105
class EChartsRenderer(EChartsMapsMixin, BaseChart):         # line 106
    def execute_code(self, code: str, ...) -> Tuple[Any, Optional[str]]:  # line 109 (json.loads + validate)
    async def render(self, response, ..., **kwargs) -> Tuple[Any, Optional[Any]]:  # line 253
        # extracts code = getattr(response, 'code', None) (265), else _extract_json_code
    @staticmethod
    def _extract_json_code(content: str) -> Optional[str]:  # line 335

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/chart.py
class BaseChart(BaseRenderer):                              # line 20
    def to_html(self, chart_obj, mode='partial', **kwargs)  # line 408

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/mixins/emaps.py
class EChartsMapsMixin:                                     # line 609
    def _render_chart_content_geo(self, ...)                # line 750
def get_echarts_system_prompt_with_geo(base_prompt: str) -> str:  # line 835

# packages/ai-parrot/src/parrot/outputs/formatter.py
DEFAULT_RETRY_PROMPTS = { OutputMode.ECHARTS: "...", OutputMode.JSON: "...", ... }  # line 49
class OutputFormatter:                                      # line 129
    def get_system_prompt(self, mode) -> Optional[str]:     # line 242 (-> get_output_prompt)
    async def format(self, mode, data, **kwargs) -> Tuple[str, Optional[str]]:  # line 267
    async def format_with_retry(self, mode, data, original_prompt=None, ...) -> OutputRetryResult:  # line 608

# packages/ai-parrot/src/parrot/bots/base.py
async def ask/conversation(..., output_mode: OutputMode = OutputMode.DEFAULT, ...)  # 139 / 735 / 1307
# system prompt injection: self.formatter.get_system_prompt(output_mode)  # 292 / 979
# finalize: if output_mode != DEFAULT: content, wrapped = await self.formatter.format(output_mode, response)  # 1166
#           response.output = content; response.response = wrapped; response.output_mode = output_mode  # 1169-1171

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                                 # line 72
    output: Any                                             # line 79
    response: Optional[str]                                 # line 82
    data: Optional[...]                                     # line 87
    code: Optional[str]                                     # line 90 ("JSON definition for a Altair/Vega Chart")
    output_mode: OutputMode                                 # line 210

# packages/ai-parrot/src/parrot/storage/models.py
@dataclass
class ChatMessage:                                          # line 73
    output: Optional[Any] = None                            # line 87
    output_mode: Optional[str] = None                       # line 88
    data: Optional[Any] = None                              # line 89
    code: Optional[str] = None                              # line 90

# packages/ai-parrot-server/src/parrot/handlers/agent.py
# INFOGRAPHIC special branch:
if getattr(response, "output_mode", None) == OutputMode.INFOGRAPHIC:  # line 2547
# generic JSON envelope:
obj_response = {"input":..., "output": output, "data": response.data, "response": response.response,
                "output_mode": output_mode, "code": str(response.code) if response.code else None, ...}  # 2591-2614
# safety net coerces non-serializable output to str  # line 2585
```

#### Verified Imports
```python
# Confirmed to work:
from parrot.models.outputs import OutputMode                        # core
from parrot.outputs.formats import register_renderer, get_renderer  # core __init__.py:47/62
from parrot.outputs.formatter import OutputFormatter, OutputRetryConfig, DEFAULT_RETRY_PROMPTS  # formatter.py
# Inside the satellite renderer module:
from . import register_renderer            # resolves to core formats/__init__ via PEP 420 namespace
from ...models.outputs import OutputMode   # echarts.py:8 uses this exact path
from .chart import BaseChart               # echarts.py:6
from .mixins.emaps import EChartsMapsMixin, get_echarts_system_prompt_with_geo  # echarts.py:25
```

#### Key Attributes & Constants
- `OutputMode` is a `str, Enum` — new member value must be the string `"structured_chart"` (outputs.py:39).
- The satellite `formats/` dir has **NO `__init__.py`** → it merges into core's `parrot.outputs.formats` namespace via `extend_path` (core `__init__.py:1-2`). New renderer goes in that dir and is picked up by adding the `_MODULE_MAP` entry.
- `get_renderer` lazy-imports the module(s) named in `_MODULE_MAP[mode]`, which triggers the `@register_renderer` decorator (formats/__init__.py:62-74).
- `format()` returns `(content, wrapped)`; `base.py` assigns them to `response.output` / `response.response`.

### Does NOT Exist (Anti-Hallucination)
- ~~`StructuredChartConfig`~~ — does not exist yet; to be created in `models/outputs.py`.
- ~~`OutputMode.STRUCTURED_CHART`~~ — not yet a member.
- ~~`ChartConfig` / `SeriesConfig` / `AppChartConfig`~~ — **no** intermediate structured chart model exists anywhere in ai-parrot today.
- ~~`parrot.outputs.formats.structured_chart`~~ — module to be created in the satellite.
- `GenerateChartInput` (`packages/ai-parrot-tools/src/parrot_tools/chart.py`) **exists but is NOT applicable** — it is the matplotlib/plotly `ChartTool` that produces static images, unrelated to echarts/altair/structured chat output.
- ~~`DEFAULT_RETRY_PROMPTS[OutputMode.STRUCTURED_CHART]`~~ — not present; to be added (formatter.py:49).
- ⚠️ **`format_with_retry` is DORMANT** — verified it is called **nowhere** in production
  code (`bots/`, `handlers/`); only in its own docstring (`formatter.py:158,638`) and in
  `tests/outputs/test_formatter_retry.py`. The agent flow calls plain
  `self.formatter.format()` (`base.py:404, 1166`). Adding a STRUCTURED_CHART retry prompt
  alone does **NOT** make retry happen — it must be wired. Note even `OutputMode.ECHARTS`'s
  existing retry prompt is dormant for the same reason.
- No `__init__.py` exists in the satellite `parrot/outputs/formats/` directory — do **not** create one (would shadow the core namespace package).

---

## Parallelism Assessment

- **Internal parallelism**: Limited. The work is a tight vertical slice (enum value →
  pydantic model → renderer + transform → retry prompt → tests). The renderer depends on
  the model and enum; the transform depends on the model. Best done sequentially in one
  worktree.
- **Cross-feature independence**: Touches `models/outputs.py`, `outputs/formats/__init__.py`,
  and `outputs/formatter.py` — files shared with infographic/echarts work. Additive edits
  (new enum member, new dict entry, new model) minimize conflict risk, but the recently
  active infographic/echarts changes on `dev` mean rebasing before merge is advisable.
- **Recommended isolation**: `per-spec` — all tasks sequential in the existing
  `feat-215-structured-chart-output` worktree.
- **Rationale**: The pieces are small and interdependent; splitting them across worktrees
  would add coordination overhead with no parallelism gain, and would multiply the
  conflict surface on the three shared core files.

---

## Open Questions

- [x] Flow type & base branch — *Owner: Juan2coder*: `type: feature`, `base_branch: dev` (FEAT-215).
- [x] Emit structured only vs. structured + native spec — *Owner: Juan2coder*: structured config + native ECharts spec (fallback), where the ECharts spec is **derived deterministically** from the structured config server-side.
- [x] Where do data rows travel — *Owner: Juan2coder*: embedded in the config **and** populated into `AIMessage.data` (configurable, both by default).
- [x] How the LLM produces the config with real data — *Owner: Juan2coder*: tools fetch data first (like Altair), then map columns into the config and embed rows.
- [x] Map coverage — *Owner: Juan2coder*: include `type="map"`, represented as `x`=region, `y`=value + a new `mapName` field selecting the GeoJSON.
- [x] Validation failure behavior — *Owner: Juan2coder*: retry with a new STRUCTURED_CHART repair prompt — **but** see the open question below: the retry loop is not wired into the agent flow today, so this needs explicit wiring (not free reuse).
- [x] Backwards compatibility — *Owner: Juan2coder*: strictly additive + opt-in via `output_mode=structured_chart`; ECHARTS/ALTAIR untouched.
- [x] **Retry wiring (VERIFIED GAP)** — *Owner: Juan2coder*: resolved → **option (b)**: do
  validation + LLM repair *inside* the `StructuredChartRenderer`, self-contained, with **no
  change to `base.py`** (avoids the regression surface of touching the shared generic path,
  and keeps the dormant `format_with_retry` untouched). Implications the spec must cover:
  the renderer needs an `AbstractClient` reference for the repair round-trip, but renderers
  are instantiated today with no args (`formatter.py:239` `renderer_cls()`). Decide the
  injection path. VERIFIED: the bot's client is `self._llm` (`base.py:328,584,1024,1451`,
  **not** `self.client`); `format_kwargs` is a *caller-supplied* param splatted into
  `render()` (`base.py:405,1167`) and does NOT carry the llm by default; renderers are
  built with `renderer_cls()` (no args, `formatter.py:239`). So the candidates are:
  **(i) truly zero base.py change** — the renderer lazily instantiates its own
  `AbstractClient` for repair; or **(ii) one-line base.py addition** — inject `self._llm`
  into `format_kwargs` for STRUCTURED_CHART so `render()` receives it. Decide in the spec
  (lean (i) to honor the "self-contained" intent; (ii) is acceptable if reusing the bot's
  configured client/model matters). **Graceful degradation still applies as the floor**: if
  repair attempts are exhausted (or no client is available), return the best-effort
  structured `output` (and native fallback) rather than hard-failing. Bounded retry count
  (default 2, mirroring `OutputRetryConfig.max_retries`).
- [ ] **Fallback wiring mechanism** — *Owner: Juan2coder*: confirm how the deterministic ECharts spec reaches the envelope `code`. Candidate: the renderer mutates `response.code` (it receives the full `AIMessage` by reference; `base.py:407-409` overwrite only `output`/`response`/`output_mode`, so a `code` mutation survives). Needs a documented, tested contract since `format()`'s return tuple only feeds `output`/`response`. Decide in the spec.
- [ ] **Exact field naming & casing** — *Owner: Juan2coder*: the frontend contract is camelCase (`horizontalBar`, `splitSeries`, `xAxisMode`, `colorBySign`, `negativeColor`). Decide whether `StructuredChartConfig` serializes camelCase (pydantic alias) to match `<AppChart>` 1:1, or snake_case with a documented frontend adapter. Lean: pydantic `alias`/`populate_by_name` → emit camelCase.
- [ ] **`mapName` vocabulary** — *Owner: Juan2coder*: enumerate the supported GeoJSON map names and how they line up with the existing `EChartsMapsMixin` geo registry, to keep the map fallback working.
- [ ] **`xAxisMode="time"` row format** — *Owner: Juan2coder*: define expected date/time representation in rows (ISO string vs epoch) for both `<AppChart>` and the ECharts fallback.
