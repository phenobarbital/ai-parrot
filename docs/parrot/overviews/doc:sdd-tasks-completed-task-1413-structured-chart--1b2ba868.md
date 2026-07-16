---
type: Wiki Overview
title: 'TASK-1413: `StructuredChartRenderer` + system prompt + dispatch registration'
id: doc:sdd-tasks-completed-task-1413-structured-chart-renderer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Spec §2 (Overview, New Public Interfaces) + §3 Modules 3 & 4. The heart
  of the feature: a renderer'
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
- concept: mod:parrot.outputs.formats.structured_chart
  rel: mentions
---

# TASK-1413: `StructuredChartRenderer` + system prompt + dispatch registration

**Feature**: FEAT-215 — Structured Chart Output Mode
**Spec**: `sdd/specs/structured-chart-output.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1411, TASK-1412
**Assigned-to**: unassigned

---

## Context

Spec §2 (Overview, New Public Interfaces) + §3 Modules 3 & 4. The heart of the feature: a renderer
shipped from the `ai-parrot-visualizations` satellite that validates the LLM-emitted JSON into
`StructuredChartConfig`, sets `response.output` to the camelCase config **without `data`**, routes
the rows to `response.data`, and leaves `response.code` null. Plus the system prompt (registered
with the renderer) and the `_MODULE_MAP` dispatch entry so `get_renderer` lazy-loads it.

Module 3 (dispatch) and Module 4 (renderer + prompt) are combined here: the `_MODULE_MAP` entry is
inert without the renderer module, and both are exercised by the same tests.

---

## Scope

- Create `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py`:
  - `STRUCTURED_CHART_SYSTEM_PROMPT` module constant.
  - `@register_renderer(OutputMode.STRUCTURED_CHART, system_prompt=STRUCTURED_CHART_SYSTEM_PROMPT)`
    on `class StructuredChartRenderer(BaseChart)`.
  - `async def render(self, response, *, environment="html", **kwargs) -> Tuple[Any, Optional[Any]]`.
- Add the dispatch entry to core `_MODULE_MAP`: `OutputMode.STRUCTURED_CHART: ('.structured_chart',)`.
- Unit tests: dispatch resolution, prompt registration (+ schema embedded), success path
  (output excludes `data`, `response.data` carries rows, code stays null, no-clobber), extraction
  from `code`/text, graceful degradation.

**The system prompt MUST**:
- embed the schema via `StructuredChartConfig.model_json_schema()`,
- demand **JSON-only** output (single JSON object, no prose),
- instruct **fetch-via-tools first** (use `database_query`/available tools, then map columns) —
  mirror the Altair prompt's "USE TOOLS, do not ask the user" guidance,
- require **ISO 8601** date strings for `x` when `xAxisMode="time"`,
- state that rows go **inside** the JSON under `data`.

**The renderer MUST**:
- extract JSON: `getattr(response, "code", None)` first, else extract from message text
  (copy the `_extract_json_code` static-method pattern from `echarts.py:336`),
- validate into `StructuredChartConfig`,
- **success**: `response.output = config.model_dump(mode="json", by_alias=True, exclude={"data"})`;
  populate `response.data = config.data` **only if `response.data` is empty**; leave
  `response.code` untouched (null); return `(response.output, None)`,
- **failure (parse/validation)**: do NOT raise — set `response.output = None`
  (an `{"error": <msg>}` dict is an acceptable variant), put the human-readable message in
  `response.response`, leave `data`/`code` null, return `(None, error_message)`.

**NOT in scope**: enum (TASK-1411), model (TASK-1412), integration/envelope tests (TASK-1414). Do NOT
mix in `EChartsMapsMixin`, do NOT build any ECharts/Vega spec, do NOT add a retry loop / LLM-repair,
do NOT touch `bots/base.py`, `outputs/formatter.py`, or `handlers/agent.py`. Do NOT create an
`__init__.py` in the satellite `formats/` dir.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py` | CREATE | Renderer + system prompt |
| `packages/ai-parrot/src/parrot/outputs/formats/__init__.py` | MODIFY | Add `_MODULE_MAP` entry |
| `packages/ai-parrot/tests/outputs/formats/test_structured_chart.py` | MODIFY | Renderer + dispatch + prompt tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified on `dev` 2026-06-02.

### Verified Imports
```python
# core:
from parrot.models.outputs import OutputMode, StructuredChartConfig   # outputs.py
from parrot.outputs.formats import get_renderer, get_output_prompt    # formats/__init__.py:62,76
# inside the new satellite module (packages/ai-parrot-visualizations/.../formats/structured_chart.py):
from . import register_renderer            # resolves to core formats/__init__ via PEP 420 (echarts.py:7)
from ...models.outputs import OutputMode, StructuredChartConfig   # echarts.py:8 uses '...models.outputs'
from .chart import BaseChart               # echarts.py:6
from typing import Any, Optional, Tuple
import json, re, logging
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/formats/__init__.py
_MODULE_MAP: dict = {                                  # line 20
    OutputMode.ALTAIR:   ('.altair',),                # line 28
    OutputMode.ECHARTS:  ('.echarts',),               # line 35
    # ADD: OutputMode.STRUCTURED_CHART: ('.structured_chart',)
}
def register_renderer(mode, system_prompt=None):       # line 47 (decorator; stores cls + prompt)
def get_renderer(mode) -> Type[Renderer]:              # line 62 (lazy-imports _MODULE_MAP modules)
def get_output_prompt(mode) -> Optional[str]:          # line 76

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/altair.py  (CLOSEST pattern to copy)
ALTAIR_SYSTEM_PROMPT = """..."""                        # line 10 (module constant; "USE TOOLS" guidance)
@register_renderer(OutputMode.ALTAIR, system_prompt=ALTAIR_SYSTEM_PROMPT)   # line 50
class AltairRenderer(BaseChart):                        # line 51

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/echarts.py  (render + extract pattern)
async def render(self, response, ..., **kwargs) -> Tuple[Any, Optional[Any]]:  # line 253
    code = getattr(response, 'code', None)              # line 265 (read code first)
    # if not code: content = self._get_content(response); code = self._extract_json_code(content)
@staticmethod
def _extract_json_code(content: str) -> Optional[str]:  # line 336 (copy this regex extraction)

# packages/ai-parrot/src/parrot/models/responses.py — AIMessage fields the renderer mutates
class AIMessage(BaseModel):       # line 72
    output: Any                   # line 79   ← set to config dict (no data) / None on failure
    response: Optional[str]       # line 82   ← error message on failure
    data: Optional[Any]           # line 86   ← rows (only if empty)
    code: Optional[str]           # line 90   ← leave null

# packages/ai-parrot/src/parrot/bots/base.py — caller (DO NOT EDIT). render() result is assigned:
#   content, wrapped = await self.formatter.format(output_mode, response, **format_kwargs)  # 404 / 1166
#   response.output = content; response.response = wrapped; response.output_mode = output_mode  # 407-409 / 1169-1171
#   NOTE: lines 407-408 OVERWRITE output & response with render()'s return tuple. So set
#   response.data / response.code by MUTATING `response` inside render(); return the config (output)
#   and the error message (wrapped/response) via the TUPLE so they survive.
```

### Does NOT Exist
- ~~`StructuredChartRenderer`~~ / ~~`parrot.outputs.formats.structured_chart`~~ — created by this task.
- ~~`EChartsMapsMixin` use here~~ — out of scope; do NOT import/mix it in.
- ~~`DEFAULT_RETRY_PROMPTS[OutputMode.STRUCTURED_CHART]` / `format_with_retry` use~~ — no retry in v1
  (the retry loop is dormant anyway — never called by the bot).
- ~~`__init__.py` in the satellite `formats/` dir~~ — must NOT exist (would shadow the core
  namespace package; merges via `extend_path`, core `__init__.py:1-2`).
- ~~`BaseChart._extract_json_code`~~ — that static method lives on `EChartsRenderer` (echarts.py:336),
  NOT on `BaseChart`. Copy the pattern into the new renderer (BaseChart has `_extract_code`/`_get_content`).

---

## Implementation Notes

### Pattern to Follow
```python
# structured_chart.py
from . import register_renderer
from ...models.outputs import OutputMode, StructuredChartConfig
from .chart import BaseChart

_SCHEMA = StructuredChartConfig.model_json_schema()
STRUCTURED_CHART_SYSTEM_PROMPT = f"""STRUCTURED CHART OUTPUT MODE ...
- Use available tools (e.g. database_query) to FETCH real data first, then map columns.
- Emit ONLY a single JSON object matching this schema (no prose, no markdown):
{json.dumps(_SCHEMA, indent=2)}
- Put the data rows inside the JSON under "data".
- For xAxisMode="time", the x column values MUST be ISO 8601 strings.
"""

@register_renderer(OutputMode.STRUCTURED_CHART, system_prompt=STRUCTURED_CHART_SYSTEM_PROMPT)
class StructuredChartRenderer(BaseChart):
    async def render(self, response, *, environment: str = "html", **kwargs):
        code = getattr(response, "code", None) or self._extract_json_code(self._get_content(response))
        if not code:
            return None, "No structured chart configuration found in response"
        try:
            cfg = StructuredChartConfig.model_validate_json(code)
        except Exception as e:           # parse OR validation
            return None, f"Invalid structured chart config: {e}"
        out = cfg.model_dump(mode="json", by_alias=True, exclude={"data"})
        if not getattr(response, "data", None) and cfg.data:
            response.data = cfg.data
        return out, None                 # response.code stays null; output has NO data key
    # + copy _extract_json_code(content) static method from echarts.py:336
```

### Key Constraints
- async; Google-style docstrings; strict type hints; `self.logger` for failures.
- `output` must NOT contain `data` (`exclude={"data"}`).
- Never raise out of `render()` — return `(None, message)` on failure.
- Do not set `response.code`.

### References in Codebase
- `altair.py:10,50-51` — system-prompt-constant + register pattern + "USE TOOLS" wording.
- `echarts.py:253-353` — `render` flow + `_extract_json_code`.
- `formats/__init__.py:20-44,62-74` — `_MODULE_MAP` + lazy `get_renderer`.

---

## Acceptance Criteria

- [ ] `get_renderer(OutputMode.STRUCTURED_CHART)` returns `StructuredChartRenderer` (lazy import works).
- [ ] `get_output_prompt(OutputMode.STRUCTURED_CHART)` returns a prompt that contains the schema and
      demands JSON-only.
- [ ] Valid config → `response.output` is camelCase dict **without a `data` key**; `response.data`
      carries the rows; `response.code` is null; `render` returns `(output, None)`.
- [ ] Existing non-empty `response.data` is NOT clobbered; `output` still excludes `data`.
- [ ] Malformed config → `(None, <message>)`, `response.output`/`data`/`code` null, no raise.
- [ ] Reads `response.code` first, else extracts JSON from message text.
- [ ] Strictly additive: no edits to `bots/base.py`, `outputs/formatter.py`, `handlers/agent.py`;
      ECHARTS/ALTAIR untouched.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/outputs/formats/test_structured_chart.py -v`.
- [ ] No `__init__.py` created in the satellite `formats/` dir.

---

## Test Specification

```python
from types import SimpleNamespace
import pytest
from parrot.models.outputs import OutputMode
from parrot.outputs.formats import get_renderer, get_output_prompt


def test_get_renderer_resolves_structured_chart():
    from parrot.outputs.formats.structured_chart import StructuredChartRenderer
    assert get_renderer(OutputMode.STRUCTURED_CHART) is StructuredChartRenderer


def test_system_prompt_embeds_schema():
    prompt = get_output_prompt(OutputMode.STRUCTURED_CHART)
    assert prompt and "xAxisMode" in prompt  # a schema alias appears → schema embedded
    assert "JSON" in prompt


@pytest.mark.asyncio
async def test_renderer_output_excludes_data(bar_config_json):
    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = SimpleNamespace(code=bar_config_json, data=None, output=None, response=None)
    output, wrapped = await r.render(resp)
    assert wrapped is None
    assert "data" not in output                      # 1:1 AppChartConfig mirror, no rows
    assert resp.data and len(resp.data) == 2         # rows routed to response.data
    assert getattr(resp, "code", None) == bar_config_json  # code untouched (renderer never sets it)


@pytest.mark.asyncio
async def test_renderer_malformed_graceful_degradation():
    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = SimpleNamespace(code="{not json", data=None, output=None, response=None)
    output, wrapped = await r.render(resp)            # must NOT raise
    assert output is None and wrapped                 # error message returned
```

> Note: the `bar_config_json` fixture is defined in this test module (added in TASK-1412 / here).

---

## Agent Instructions

1. **Read the spec** §2 + §3 Modules 3-4.
2. **Check** TASK-1411 and TASK-1412 are in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** (re-`grep` echarts.py / altair.py / __init__.py line numbers).
4. **Update index** → `in-progress`.
5. **Implement** the renderer, prompt, dispatch entry, tests.
6. **Verify** acceptance criteria; run `pytest` for the module.
7. **Move** to `sdd/tasks/completed/`, update index → `done`.
8. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-06-02
**Notes**: Created StructuredChartRenderer in satellite package. Added _MODULE_MAP entry in core __init__.py. System prompt embeds full JSON schema, demands JSON-only, instructs fetch-via-tools, requires ISO 8601 for time mode. Renderer: reads code first, falls back to text extraction, validates into StructuredChartConfig, dumps without data, routes rows to response.data without clobbering, graceful degradation. Added _render_chart_content stub to satisfy BaseChart abstract method. All 20 tests pass.
**Deviations from spec**: Added sys.path.insert in test file (parents[5] = worktree root) to wire the satellite path so satellite tests run. This is a necessary infrastructure addition since ai-parrot-visualizations is not installed in the venv.
