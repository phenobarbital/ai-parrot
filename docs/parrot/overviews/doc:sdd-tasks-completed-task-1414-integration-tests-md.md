---
type: Wiki Overview
title: 'TASK-1414: Integration tests — envelope serialization + regression guard'
id: doc:sdd-tasks-completed-task-1414-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §4 Integration Tests + §5 Acceptance Criteria. Confirms the end-to-end
  contract at the
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
---

# TASK-1414: Integration tests — envelope serialization + regression guard

**Feature**: FEAT-215 — Structured Chart Output Mode
**Spec**: `sdd/specs/structured-chart-output.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1411, TASK-1412, TASK-1413
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests + §5 Acceptance Criteria. Confirms the end-to-end contract at the
serialization boundary: a `structured_chart` response (config in `output`, rows in `data`,
`code=null`) and a degraded response (`output=null` + error message) both serialize through the
generic JSON envelope, and that adding the new mode did NOT regress ECHARTS/ALTAIR.

---

## Scope

- `test_envelope_serializes_structured_chart`: an `AIMessage`-like object with
  `output_mode=STRUCTURED_CHART`, `output`=camelCase config dict (no `data` key), `data`=rows,
  `code=None` serializes cleanly via the project JSON encoder (`code: null`, `output` is the config,
  `data` carries the rows).
- `test_envelope_serializes_degraded_structured_chart`: degraded response (`output=None` or
  `{"error": ...}` + `response` message) still serializes; a consumer can detect the failure from
  `output==null`/`output.error` + `response` **without** rendering an invalid config.
- `test_echarts_altair_unchanged`: `get_renderer`/`get_output_prompt` for `OutputMode.ECHARTS` and
  `OutputMode.ALTAIR` still resolve to the same classes/prompts (regression guard).

**NOT in scope**: implementation (TASK-1411..1413). Do NOT add new production code, do NOT spin up an
aiohttp server if a unit-level serialization check suffices (prefer testing the envelope-building /
`json_encoder` path directly over a full HTTP round-trip).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/outputs/formats/test_structured_chart.py` | MODIFY | Add integration-level tests (or a sibling `test_structured_chart_envelope.py` if cleaner) |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified on `dev` 2026-06-02.

### Verified Imports
```python
from parrot.models.outputs import OutputMode
from parrot.outputs.formats import get_renderer, get_output_prompt
# JSON encoder used by handlers (verify availability in the test env):
from datamodel.parsers.json import json_encoder   # handlers/agent.py:20 imports this
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/agent.py — the envelope the test mirrors
"output": output,                                        # line 2593
"data": response.data,                                   # line 2594
"response": response.response,                           # line 2595
"output_mode": output_mode,                              # line 2596
"code": str(response.code) if response.code else None,   # line 2597  ← None-safe
# safety-net coercion for non-serializable output:        line 2585
from datamodel.parsers.json import json_encoder           # line 20

# ECHARTS / ALTAIR registration (regression anchors)
@register_renderer(OutputMode.ECHARTS, ...)   # echarts.py:105 → EChartsRenderer
@register_renderer(OutputMode.ALTAIR, ...)    # altair.py:50  → AltairRenderer
```

### Does NOT Exist
- ~~a dedicated `structured_chart` branch in `handlers/agent.py`~~ — none; it uses the generic
  envelope (the INFOGRAPHIC special-case at `agent.py:2547` is NOT triggered).
- ~~changes to the envelope for this feature~~ — handler is unchanged; the test asserts the
  EXISTING generic path already handles `code=null` + dict `output`.

---

## Implementation Notes

### Pattern to Follow
```python
from datamodel.parsers.json import json_encoder
from parrot.models.outputs import OutputMode

def _envelope(output, data, response, code, output_mode):
    # mirror handlers/agent.py:2591-2614 (only the fields under test)
    return {"output": output, "data": data, "response": response,
            "output_mode": output_mode,
            "code": str(code) if code else None}

def test_envelope_serializes_structured_chart():
    cfg = {"type": "bar", "x": "m", "y": ["v"]}   # camelCase config, NO "data" key
    env = _envelope(cfg, [{"m": "Jan", "v": 1}], None, None, OutputMode.STRUCTURED_CHART.value)
    blob = json_encoder(env)                       # must not raise
    assert '"code": null' in blob or env["code"] is None
    assert "data" not in env["output"]

def test_envelope_serializes_degraded_structured_chart():
    env = _envelope(None, None, "Invalid structured chart config: ...", None,
                    OutputMode.STRUCTURED_CHART.value)
    json_encoder(env)                              # must not raise on output=None
    assert env["output"] is None and env["response"]
```

### Key Constraints
- Keep tests at the serialization/registry level — no live HTTP server needed.
- If `json_encoder` import is unavailable in the test env, fall back to `json.dumps` with the same
  assertions and note it.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/agent.py:2591-2614` — envelope shape.
- `packages/ai-parrot/tests/outputs/formats/test_echarts.py` — existing renderer-test style.

---

## Acceptance Criteria

- [ ] `test_envelope_serializes_structured_chart` passes: config in `output` (no `data` key), rows
      in `data`, `code: null`, encoder does not raise.
- [ ] `test_envelope_serializes_degraded_structured_chart` passes: `output=null` + `response`
      message, encoder does not raise, failure detectable without rendering.
- [ ] `test_echarts_altair_unchanged` passes: ECHARTS/ALTAIR renderers + prompts resolve unchanged.
- [ ] Full suite green: `pytest` (no regressions).
- [ ] `ruff check` clean on the test file.

---

## Test Specification

See the patterns above; the three tests are the deliverable. Add fixtures as needed (reuse
`bar_config_json` / `map_config_json` from the shared test module).

---

## Agent Instructions

1. **Read the spec** §4 + §5.
2. **Check** TASK-1411..1413 are in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** (confirm `json_encoder` import + envelope lines).
4. **Update index** → `in-progress`.
5. **Implement** the three tests.
6. **Verify** acceptance criteria; run the full `pytest`.
7. **Move** to `sdd/tasks/completed/`, update index → `done`.
8. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-06-02
**Notes**: All three integration tests added to test_structured_chart.py: test_envelope_serializes_structured_chart, test_envelope_serializes_degraded_structured_chart, test_echarts_altair_unchanged. json_encoder from datamodel.parsers.json is available in test env. All 20 tests pass.
**Deviations from spec**: none
