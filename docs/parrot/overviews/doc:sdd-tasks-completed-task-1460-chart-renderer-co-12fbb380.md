---
type: Wiki Overview
title: 'TASK-1460: Chart renderer reads config from `output`/`structured_output` (drop
  `response.code` dependency)'
id: doc:sdd-tasks-completed-task-1460-chart-renderer-config-input-source-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 2** of FEAT-224 (G3). Today `StructuredChartRenderer.render`
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
- concept: mod:parrot.outputs.formats.structured_chart
  rel: mentions
---

# TASK-1460: Chart renderer reads config from `output`/`structured_output` (drop `response.code` dependency)

**Feature**: FEAT-224 — Structured Config Homologation (`artifacts[]` envelope)
**Spec**: `sdd/specs/structured-config-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of FEAT-224 (G3). Today `StructuredChartRenderer.render`
reads its config from `response.code` (steps 1a/1b). FEAT-224 reclaims
`response.code` for genuine interpretable code, so the renderer must instead read
its config from `response.output` (where `PandasAgent` sets the LLM's
`StructuredChartConfig`) or `response.structured_output`, keeping the text
fallback. This task changes ONLY the renderer's input source — the deterministic
x/y reconciliation, the `(out, error)` contract and never-raise behavior stay
intact.

> Coupled with TASK-1461 (which removes the `response.code` staging in the
> agent). Land them adjacently; the test below guards the renderer in isolation
> by feeding the config via `response.output`.

---

## Scope

- Change `StructuredChartRenderer.render` to source the presentation config, in
  priority order:
  1. `response.output` when it is a `StructuredChartConfig` instance or a dict.
  2. `response.structured_output` when it is a `StructuredChartConfig`/dict.
  3. text fallback via `self._extract_json_code(self._get_content(response))`.
- Do NOT read `response.code` for the config any longer.
- Preserve: row extraction from `response.data` (`_extract_rows`), x/y validation
  & deterministic fallback (`_safe_x`/`_safe_y`), `(out_without_data, explanation)`
  return, `(None, error)` on failure, never raise.
- Unit tests proving the renderer works with config in `response.output` and with
  `response.code = None`.

**NOT in scope**: removing the agent-side `response.code` staging (TASK-1461);
the `artifacts[]` envelope (TASK-1461).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py` | MODIFY | Change config input source (steps 1a/1b) |
| `packages/ai-parrot/tests/outputs/formats/test_structured_chart_input_source.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.outputs import StructuredChartConfig  # models/outputs.py:309
from parrot.outputs.formats import register_renderer      # outputs/formats/__init__.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py
@register_renderer(OutputMode.STRUCTURED_CHART, system_prompt=STRUCTURED_CHART_SYSTEM_PROMPT)
class StructuredChartRenderer(StructuredOutputBase, BaseChart):
    async def render(self, response, *, environment="html", **kwargs) -> Tuple[Any, Optional[Any]]:
        # CURRENT (to change):
        #   raw_code = getattr(response, "code", None)        # ← stop using as config source
        #   1a: isinstance(raw_code, dict)  -> model_validate
        #   1b: raw_code as str / _get_content fallback -> model_validate_json
        #   2:  df = self._extract_rows(response)             # KEEP
        #   3:  rows, _, _ = canonical_records(df)            # KEEP
        #   4:  x = self._safe_x(...); y = self._safe_y(...)  # KEEP
    def _safe_x(self, x_hint, cols, rows) -> str: ...
    def _safe_y(self, y_hint, x, cols, rows) -> list: ...

# Mixin helpers available (structured_base.py)
class StructuredOutputBase:
    def _extract_rows(self, response) -> Optional[pd.DataFrame]: ...   # line 39
    def _route_envelope(self, response, cfg, explanation) -> tuple[Optional[dict], Optional[str]]: ...  # line 64
    @staticmethod
    def _extract_json_code(content: str) -> Optional[str]: ...        # line 99

# AIMessage fields the renderer may read (models/responses.py)
#   output: Any              # line 79  (LLM StructuredChartConfig lands here)
#   structured_output: Any   # line 194
#   data: Any                # line 86  (rows — via _extract_rows)
#   response: Optional[str]  # line 82  (explanation)
#   code: Optional[str]      # line 90  (NO LONGER the config source)
```

### Does NOT Exist
- ~~a separate `response.chart_config` field~~ — config arrives via `output`/`structured_output`.
- ~~`StructuredChartConfig.from_response(...)`~~ — not a method; use `model_validate`/`model_validate_json`.

---

## Implementation Notes

### Pattern to Follow
```python
# Replace the response.code parsing with an output/structured_output-first parser:
cfg: Optional[StructuredChartConfig] = None
candidate = getattr(response, "output", None)
if candidate is None or isinstance(candidate, str):
    candidate = getattr(response, "structured_output", None)

if isinstance(candidate, StructuredChartConfig):
    cfg = candidate
elif isinstance(candidate, dict):
    try:
        cfg = StructuredChartConfig.model_validate(candidate)
    except Exception as exc:
        return None, f"Invalid structured chart config (dict): {exc}"

if cfg is None:                       # text fallback (unchanged behavior)
    raw = self._extract_json_code(self._get_content(response))
    if not raw:
        return None, "No structured chart configuration found in response"
    try:
        cfg = StructuredChartConfig.model_validate_json(raw)
    except Exception as exc:
        return None, f"Invalid structured chart config: {exc}"
# ... unchanged from step 2 (rows) onward ...
```

### Key Constraints
- Never raise — return `(None, error_message)` on any failure.
- Rows ALWAYS from `response.data` via `_extract_rows`, never from `cfg.data`.
- Keep `_route_envelope` for the final output (excludes `data`, by_alias).
- `response.output` may legitimately be a `str` (plain text turn) — fall through
  to `structured_output` / text fallback in that case.

---

## Acceptance Criteria

- [ ] Renderer parses the config from `response.output` (instance or dict) and
      `response.structured_output`; no longer reads `response.code`.
- [ ] With config in `response.output` and `response.code = None`, `render`
      succeeds and returns `(config_dict_without_data, explanation)`.
- [ ] x/y reconciliation, never-raise, and `_route_envelope` behavior unchanged.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/outputs/formats/test_structured_chart_input_source.py -v`
- [ ] FEAT-215/223 parity tests still pass: `pytest packages/ai-parrot/tests/outputs/formats/test_structured_parity.py -v`
- [ ] No lint errors on the modified renderer.

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/formats/test_structured_chart_input_source.py
import pytest
from types import SimpleNamespace
import pandas as pd
from parrot.models.outputs import StructuredChartConfig


def _resp(**kw):
    base = dict(output=None, structured_output=None, code=None,
                data=pd.DataFrame({"month": ["Jan", "Feb"], "sales": [1, 2]}),
                response="explained")
    base.update(kw)
    return SimpleNamespace(**base)


async def test_reads_config_from_output_instance():
    from parrot.outputs.formats.structured_chart import StructuredChartRenderer
    cfg = StructuredChartConfig(type="bar", x="month", y=["sales"])
    out, wrapped = await StructuredChartRenderer().render(_resp(output=cfg))
    assert out is not None and "data" not in out
    assert out["x"] == "month"
    assert wrapped == "explained"


async def test_reads_config_from_output_dict_with_code_none():
    from parrot.outputs.formats.structured_chart import StructuredChartRenderer
    out, _ = await StructuredChartRenderer().render(
        _resp(output={"type": "bar", "x": "month", "y": ["sales"]}, code=None))
    assert out is not None and out["type"] == "bar"


async def test_no_config_returns_none_not_raise():
    from parrot.outputs.formats.structured_chart import StructuredChartRenderer
    out, err = await StructuredChartRenderer().render(_resp(output="just text"))
    assert out is None and isinstance(err, str)
```

---

## Agent Instructions

1. Read the spec for full context.
2. Verify the Codebase Contract anchors before editing.
3. Update status in the per-spec index → `in-progress`.
4. Implement per scope.
5. Verify acceptance criteria (incl. parity tests).
6. Move this file to `sdd/tasks/completed/`.
7. Update index → `done`; fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
