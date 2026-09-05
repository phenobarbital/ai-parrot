# TASK-2858: `AgentTalk` dual-emit envelopes — `a2ui_envelope` on INFOGRAPHIC, `metadata` on A2UI

**Feature**: FEAT-527 — Infographic → A2UI migration (dual-emit)
**Spec**: `sdd/specs/infographic-a2ui-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2857
**Assigned-to**: unassigned

---

## Context

Spec §1 G2/G6, §2 Overview step 3, §2 Data Models, §3 Module 1. After TASK-2857 an
infographic `AIMessage` carries both emissions; the HTTP layer must expose both without
changing the documented shapes: the INFOGRAPHIC JSON envelope gains one additive key, and
the A2UI early return gains `metadata` so an HTML consumer can iframe `html_url`. The
FEAT-473 G9 widening block (`agent.py:2834-2840`) is the precedent.

---

## Scope

- `AgentTalk._format_infographic_response` (`handlers/agent.py:3052-3135`): after building
  `obj_response` (`:3118-3135`) add `obj_response["a2ui_envelope"] = envelope` **only when**
  `getattr(response, "a2ui_envelope", None) is not None`. Update the docstring's JSON example
  (`:3063-3084`). The `Accept: text/html` branch (`:3086-3108`) is untouched.
- `OutputMode.A2UI` early return (`:2733-2741`): add `"metadata": {**(response.metadata or {}),
  "model", "provider", "session_id", "turn_id", "response_time"}` mirroring the INFOGRAPHIC
  metadata block at `:3125-3131`, and `"artifact_id": getattr(response, "artifact_id", None)`.
  Do not remove existing keys.
- Keep the streaming gate at `:1625-1628` unchanged; add a test asserting it.
- Extend `packages/ai-parrot/tests/handlers/test_infographic_handler.py` and add
  `packages/ai-parrot-server/tests/test_agenttalk_dual_emit.py` (handler-level, following
  `test_agenttalk_infographic_explanation.py`).

**NOT in scope**: `InfographicTalk` routes (`handlers/infographic.py`) — its `/render` lane is
TASK-2864/2865; the chunked streaming path (`:2606-2614` already forwards `a2ui_envelope`);
`A2UIHandler` (`handlers/a2ui.py`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | `:2733-2741` A2UI return metadata; `:3118-3135` additive `a2ui_envelope` |
| `packages/ai-parrot/tests/handlers/test_infographic_handler.py` | MODIFY | envelope contract tests |
| `packages/ai-parrot-server/tests/test_agenttalk_dual_emit.py` | CREATE | A2UI-return metadata + streaming gate tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.handlers.agent import AgentTalk              # packages/ai-parrot-server/src/parrot/handlers/agent.py
from parrot.models.outputs import OutputMode             # models/outputs.py:58,:64
from parrot.models.responses import AIMessage, CompletionUsage   # models/responses.py (used by tests/handlers/test_infographic_handler.py:31)
from parrot.models.infographic import JSBundle           # models/infographic.py:1118 (imported inside :3094)
from parrot.handlers.csp import build_csp_headers, frame_ancestors_from_env   # imported inside :3093
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/agent.py  (class AgentTalk)
if output_mode in (OutputMode.INFOGRAPHIC, OutputMode.INTERACTIVE): use_stream = False      # :1625-1628 (KEEP)
if isinstance(response, AgentResponse): response = response.response                         # :2726-2727
if getattr(response, "output_mode", None) == OutputMode.A2UI:
    return self.json_response({"input": ..., "output": response.response or "", "output_mode": OutputMode.A2UI.value,
                               "a2ui_envelope": getattr(response, "a2ui_envelope", None)})     # :2733-2741 ← EXTEND
if getattr(response, "output_mode", None) == OutputMode.INFOGRAPHIC:
    return self._format_infographic_response(response=..., format_kwargs=..., user_id=..., user_session=...,
                                             response_time_ms=..., agent_name=..., session_id=..., client_message_id=...)  # :2745-2755
_a2ui_envelope = getattr(response, "a2ui_envelope", None); if not None: obj_response["a2ui_envelope"] = _a2ui_envelope  # :2834-2840 (PATTERN)
@staticmethod
def _extract_infographic_explanation(response: "AIMessage") -> str                           # :3023-3050
def _format_infographic_response(self, response, format_kwargs, user_id=None, user_session=None,
                                 response_time_ms=None, agent_name=None, session_id=None, client_message_id=None) -> web.Response  # :3052
    want_html = accept_header.startswith("text/html") or fmt_param == "html"                 # :3086-3089
    obj_response = {"input", "output", "response", "output_mode": "infographic", "artifact_id", "data",
                    "metadata": {**metadata, "model", "provider", "session_id", "turn_id", "response_time"},
                    "sources": [], "tool_calls": []}                                          # :3118-3135 ← ADD a2ui_envelope after
# tests/handlers/test_infographic_handler.py fixtures: sample_infographic_response :36 ; mock_agent :56 (MagicMock agent + AIMessage)
```

### Does NOT Exist
- ~~`?output_mode=` query parameter~~ — dead on the chat endpoint; tests must send `output_mode` in the JSON body.
- ~~SSE streaming on the chat endpoint~~ — chunked only; the only SSE route is `GET /api/v1/agents/{agent_id}/a2ui`.
- ~~`response.html_url`~~ — the URL is in `response.metadata["html_url"]` (set by TASK-2857 / `base.py:912-915`).
- ~~`AgentTalk._format_a2ui_response`~~ — there is no such helper; the A2UI return is inline at `:2733-2741`.

---

## Implementation Notes

### Pattern to Follow
```python
# agent.py:2834-2840 — conditional additive key
_a2ui_envelope = getattr(response, "a2ui_envelope", None)
if _a2ui_envelope is not None:
    obj_response["a2ui_envelope"] = _a2ui_envelope
```

### Key Constraints
- Byte-identical INFOGRAPHIC body when no envelope is present (G6): add the key only when set.
- The `text/html` branch must keep `build_csp_headers(js_bundles=..., frame_ancestors=...)`.
- Handler tests: instantiate `AgentTalk` the way `packages/ai-parrot-server/tests/test_agenttalk_infographic_explanation.py`
  does (unit-level, no aiohttp server) and call `_format_infographic_response` with a fake `self.request`
  exposing `.headers` and `.query`.

### References in Codebase
- `packages/ai-parrot-server/tests/test_agenttalk_infographic_explanation.py` — AgentTalk unit-test style.
- `docs/infographic_handler_api.md` — the documented JSON shape (update in TASK-2869, not here).

---

## Acceptance Criteria

- [ ] INFOGRAPHIC JSON body == previous shape + `a2ui_envelope` when present; key absent when `None`
- [ ] `Accept: text/html` / `?format=html` body and CSP headers unchanged
- [ ] A2UI early return includes `metadata` (with `html_url` when set) and `artifact_id`; existing four keys intact
- [ ] Streaming forced off for INFOGRAPHIC/INTERACTIVE (test)
- [ ] `timeout -s KILL 600 pytest packages/ai-parrot/tests/handlers/test_infographic_handler.py packages/ai-parrot-server/tests/test_agenttalk_dual_emit.py packages/ai-parrot-server/tests/test_agenttalk_infographic_explanation.py -q` green
- [ ] `ruff check packages/ai-parrot-server/src/parrot/handlers/agent.py`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_agenttalk_dual_emit.py
def test_infographic_envelope_includes_a2ui(handler, aimessage_with_envelope):
    resp = handler._format_infographic_response(response=aimessage_with_envelope, format_kwargs={})
    body = json.loads(resp.text)
    assert body["output_mode"] == "infographic"
    assert body["a2ui_envelope"]["version"] == "v1.0"
    assert set(body) >= {"input", "output", "response", "artifact_id", "data", "metadata", "sources", "tool_calls"}

def test_infographic_envelope_omits_key_when_none(handler, aimessage_without_envelope):
    body = json.loads(handler._format_infographic_response(response=aimessage_without_envelope, format_kwargs={}).text)
    assert "a2ui_envelope" not in body

def test_a2ui_return_carries_html_metadata(...):
    # drive the OutputMode.A2UI branch; assert body["metadata"]["html_url"] and body["artifact_id"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2857 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `agent.py:2733-2755` and `:3052-3135` still match
4. **Update status** in `sdd/tasks/index/infographic-a2ui-migration.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2858-agenttalk-dual-emit-envelope.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
