---
type: Wiki Overview
title: 'Brainstorm: Structured Chart Output Mode'
id: doc:sdd-proposals-structured-chart-output-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `navigator-frontend-next` app migrated every chart to **LayerChart**
  behind a
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
- concept: mod:parrot.outputs.formats.structured_chart
  rel: mentions
- concept: mod:parrot.outputs.formatter
  rel: mentions
---

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
- **Single agnostic emission — NO native fallback (SCOPE-CUT 2026-06-02).** The agent emits
  **only** the validated `StructuredChartConfig`; `response.code` is left **null**. The
  deterministic `structured→ECharts` transform and its `EChartsMapsMixin` geo dependency are
  **out of scope**. Justified by the impact investigation (see "Impact Investigation
  Findings" below): every backend consumer tolerates `code=null`, channels render images
  (not specs), and `structured_chart` is client-requested so it never reaches a non-frontend
  channel.
- **Real data via tools.** The chart must use real domain data: the agent fetches it
  through tools (e.g. `database_query`) — same flow as the Altair renderer — then maps
  columns into the config and embeds the rows.
- **Data in two places (configurable).** Rows embedded in the config (mirrors
  `AppChartConfig`) AND populated into the existing `AIMessage.data` / envelope `data`
  field for clients that read it.
- **Map support included (frontend-only).** The contract accepts `type: "map"`, represented
  agnostically as `x`=region column, `y`=value column, plus a new `mapName` field
  (e.g. `"world"`, `"USA"`, `"Argentina"`) selecting the GeoJSON. `mapName` exists **purely
  as a field the frontend (`AppChartGeo`) consumes** — there is no server-side geo render and
  no `EChartsMapsMixin` involvement (fallback removed).
- **Resilient validation (v1 = strict + graceful degradation).** On a config that fails
  pydantic validation, **degrade gracefully** — return the best-effort structured `output`
  with an error flag rather than hard-failing. **LLM-repair is DEFERRED to a follow-up** to
  avoid injecting an `AbstractClient` into the renderer and touching `base.py`. (Context: the
  existing `OutputFormatter.format_with_retry` loop is **dormant** — never called from the
  agent flow; bot uses plain `formatter.format()` at `base.py:404`/`:1166`; it appears only
  in its own docstring + unit tests. So there is no free retry to reuse anyway.)
- **Async-first, Google-style docstrings, strict type hints, Pydantic** (project rules).
- **Renderers ship from the satellite** `ai-parrot-visualizations` (PEP 420 namespace);
  core only gains the enum value + dispatch entry + the pydantic model.

---

## Options Explored

### Option A (RECOMMENDED, scope-cut): New `STRUCTURED_CHART` mode — LLM emits ONLY the agnostic config, no native fallback

The agent runs in a new `OutputMode.STRUCTURED_CHART`. Its system prompt instructs the
LLM to (1) fetch data with tools, then (2) emit **only** a JSON object validated against a
new `StructuredChartConfig` pydantic model (the agnostic contract + embedded rows). A new
`StructuredChartRenderer` (in the satellite) validates the JSON and populates
`response.data` with the rows. **`response.code` is left null** — no native spec is derived.
No HTML is rendered — the frontend's `<AppChart>` renders from the structured `output`.

✅ **Pros:**
- One LLM contract, one source of truth; nothing can diverge because there is no second
  representation.
- **Smallest possible surface**: dropping the deterministic transform removes the largest
  implementation cost and the geo-fallback complexity (`EChartsMapsMixin`).
- Cleanly additive: new enum value + new `_MODULE_MAP` entry + new renderer module.
  ECHARTS/ALTAIR fully untouched.
- Reuses existing plumbing: `register_renderer`, `get_system_prompt` injection in `BaseBot`,
  and the JSON response envelope (which already serializes `code=null`).
- The renderer is trivial: validate → populate `data` → return. No `response.code` mutation,
  no transformer, no client injection.

❌ **Cons:**
- During the migration window, any consumer that *only* knew how to paint a raw ECharts/Vega
  spec gets nothing renderable from `code` — **verified safe**: the only such consumer is the
  frontend chat, which is the driver of this change and renders from `output`. No backend
  consumer breaks (see Impact Investigation Findings).
- No automatic LLM-repair on a malformed config in v1 (graceful degradation only) — deferred.

📊 **Effort:** Low–Medium (reduced from Medium after the scope cut).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (v2, already used) | `StructuredChartConfig` model + validation | `model_json_schema()` already used elsewhere in `outputs.py` |
| `ai-parrot-visualizations` (satellite, in-repo) | Hosts the new renderer | PEP 420 namespace merge into `parrot.outputs.formats` |
| — (no new 3rd-party dep) | none needed (no transform) | — |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/models/outputs.py` — add enum value + host the pydantic model (alongside `ObjectDetectionResult` et al.).
- `packages/ai-parrot/src/parrot/outputs/formats/__init__.py` — `register_renderer`, `_MODULE_MAP` dispatch.
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/echarts.py` — renderer pattern only (`_extract_json_code`, `render` signature). **Do NOT** pull in the `execute_code` ECharts validation or `EChartsMapsMixin` — out of scope.
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/altair.py` — closest reference for the "fetch-via-tools then emit" system-prompt style.

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

**Option A (scope-cut: no native fallback)** is recommended.

It is the only option that achieves the actual goal — a **single, agnostic source of
truth** the frontend can render with one library. The LLM emits *only* the structured
config; nothing can diverge because there is no second representation (the failure mode that
sinks Option B), and there is no fragile reverse-engineering of arbitrary specs (the failure
mode that sinks Option C). It lands entirely in the reusable renderer layer and is strictly
additive so ECHARTS/ALTAIR keep working untouched.

The original plan emitted a deterministic `structured→ECharts` fallback in `response.code`
as a migration safety net. The **impact investigation (2026-06-02) found this unnecessary**:
verdict **(B)** — removal is safe, and the safety condition (`structured_chart` is
client-requested and never reaches a non-frontend channel) is **structurally guaranteed**
(channels force their own `output_mode`; no router auto-selects the new mode; every backend
consumer tolerates `code=null`). Cutting the fallback removes the largest implementation
cost and the geo-fallback complexity for zero real risk. If a fallback is ever needed it can
be reintroduced additively (all consumers already tolerate `code=null`).

---

## Feature Description

### User-Facing Behavior
A client (the chat) requests `output_mode=structured_chart`. The agent answers with a
response whose:
- `output` = a `StructuredChartConfig` JSON object (chart `type`, `x`, `y[]`, flags,
  palette controls, **embedded data rows**) — directly consumable by `<AppChart>`.
- `data` = the same flat rows (for clients that read the envelope `data` field).
- `code` = **null** (no native fallback spec).
- `output_mode` = `"structured_chart"`.

The frontend `ChatBubble` renders via LayerChart/`<AppChart>` from `output` and can drop its
`echarts` + `vega` runtime dependencies.

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
   - sets `output` = validated config (`model_dump(mode="json", by_alias=True)`),
   - populates `response.data` with the rows (if not already present).
   - **Leaves `response.code` as null** — no transform.
5. The HTTP handler serializes the generic JSON envelope (`agent.py:2591-2614`):
   `output`, `data`, `response`, `output_mode`, `code` (already `None`-safe at `:2597`) —
   no handler change required (the INFOGRAPHIC special-case at `2547` is not triggered).

### Edge Cases & Error Handling
- **Invalid/malformed config JSON** → **v1: graceful degradation** — return a best-effort
  result (the raw/partial structured `output` plus an error flag/message) instead of
  hard-failing. **LLM-repair is deferred** to a follow-up (no client injection in v1).
- **`y` references a column absent from rows** → pydantic model-level validation error →
  graceful-degradation path.
- **`type=map` without `mapName`** → validation error (conditional requirement).
- **`colorBySign=true` without `negativeColor`** → default negative color (documented), not
  an error.
- **Empty rows** → emit the config with empty `data`; frontend renders an empty-state.

---

## Capabilities

### New Capabilities
- `structured-chart-output`: a library-agnostic `OutputMode.STRUCTURED_CHART` that emits a
  `StructuredChartConfig` mirroring the frontend `AppChartConfig` (config + embedded rows),
  with `response.code` left null (no native fallback).

### Modified Capabilities
<!-- none — strictly additive -->

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/outputs.py` | modifies | Add `OutputMode.STRUCTURED_CHART = "structured_chart"`; add `StructuredChartConfig` (+ enums) pydantic model |
| `packages/ai-parrot/src/parrot/outputs/formats/__init__.py` | modifies | Add `OutputMode.STRUCTURED_CHART: ('.structured_chart',)` to `_MODULE_MAP` |
| `packages/ai-parrot-visualizations/.../outputs/formats/structured_chart.py` | extends (new file) | `StructuredChartRenderer` (validate + populate `data`) + system prompt. **No** transform, **no** `EChartsMapsMixin`, **no** `response.code` mutation |
| `packages/ai-parrot/src/parrot/outputs/formatter.py` | none (v1) | LLM-repair deferred → **no** `DEFAULT_RETRY_PROMPTS` entry in v1 |
| `packages/ai-parrot/src/parrot/bots/base.py` | depends on / no change | Generic `output_mode != DEFAULT` path already routes to the formatter; no `code` mutation needed |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | depends on / no change | Generic envelope handles dict `output` (`:2585` safety net) and `code=null` (`:2597`). Optional follow-up: add `'structured_chart'` to the artifact tuple at `:2675` to persist these turns as artifacts (additive) |
| `AIMessage` / `ChatMessage` | depends on | Reuse existing `output`/`data`/`code`/`output_mode` fields — no schema change |

**No breaking changes. No new third-party dependency.**

---

## Impact Investigation Findings (2026-06-02 — read-only audit on `dev`)

Evidence backing the decision to **cut the native ECharts fallback** (`code=null`). Verdict
**(B): safe, and the safety condition is structurally guaranteed.**

- **Envelope already `None`-safe**: `handlers/agent.py:2597` →
  `"code": str(response.code) if response.code else None`. Dict `output` passes the
  serialization safety-net at `:2585`.
- **Channels render IMAGES, not specs**: `integrations/parser.py:21-76` `ChartData`
  (`path`/`base64`/`mime_type`); `_parse_chart_item` (`:193-217`) only accepts file-path /
  image chart items. No channel parses ECharts/Vega from `code`. The matplotlib/plotly
  `ChartTool` (`parrot_tools/chart.py`) produces the images.
- **`structured_chart` cannot leak to a non-frontend channel**: channels hardcode their own
  mode — Telegram `OutputMode.TELEGRAM` (`telegram/wrapper.py:1740,1846,2282,…`), Slack
  `OutputMode.SLACK` (`slack/assistant.py:180,234,255`), WhatsApp `OutputMode.WHATSAPP`
  (`whatsapp/wrapper.py:215`), Teams `OutputMode.MSTEAMS` (`msteams/wrapper.py:528`).
  Client-requested mode enters only via HTTP (`handlers/agent.py:499,1646,1675-1677`). No
  router auto-selects the new mode.
- **Storage/streaming do not re-render**: `storage/chat.py:243-245` persists
  `output`/`output_mode`/`data`/`code` verbatim and replays them as-is (`:363`); `code` is
  already nullable. `handlers/stream.py` & `handlers/chat.py` do not read chart output
  fields (text-token streaming).
- **No server-side echarts-from-`code` render**: ECharts `to_html` needs a browser/CDN;
  the only server-side echarts generation is `infographic_html.py:961` `_build_echarts_option`,
  which builds from infographic block data — **independent** of any chart-response `code`.
- **Other `.code` readers tolerate null**: parser (`:386`), MS Teams (`:959`), TABLE renderer
  (`table.py:310`), app generators (`generators/abstract.py:48-51`, `generators/base.py:151,174`),
  orchestrator (`bots/flows/agents/orchestrator.py:225`) — all gated to other modes or
  null-tolerant.
- **Tests**: no test asserts a "chart mode always carries `code`" invariant; no
  `structured_chart` test exists yet.
- **Optional additive follow-up**: to persist `structured_chart` turns as artifacts, add
  `'structured_chart'` to the tuple at `handlers/agent.py:2675` (it uses `response.data`, not
  `code`). Purely additive; not required.

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
# ⚠️ OUT OF SCOPE (v1) — the map FALLBACK was cut. `mapName` is a passthrough field for
#    the frontend only; no server-side geo render. Listed for reference, NOT to be used.
class EChartsMapsMixin:                                     # line 609 — do NOT mix in
def get_echarts_system_prompt_with_geo(base_prompt: str) -> str:  # line 835 — do NOT use

# packages/ai-parrot/src/parrot/outputs/formatter.py
class OutputFormatter:                                      # line 129
    def get_system_prompt(self, mode) -> Optional[str]:     # line 242 (-> get_output_prompt)
    async def format(self, mode, data, **kwargs) -> Tuple[str, Optional[str]]:  # line 267 — the call used by the bot
# ⚠️ DEFERRED (v1): DEFAULT_RETRY_PROMPTS (line 49) + format_with_retry (line 608) — NOT
#    touched. LLM-repair is a follow-up; v1 degrades gracefully inside the renderer.

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

…(truncated)…
