# TASK-4802: `AgentTalk` passthrough of `suggestions` (four body builders)

**Feature**: FEAT-752 — Follow-up Suggestion Chips
**Spec**: `sdd/specs/followup-suggestion-chips.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4794
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (handler half) and AC "byte-identical body when not opted in". `AgentTalk` builds four response
bodies; each must carry an additive `suggestions` key **only when the list is non-empty**, exactly like the existing
`a2ui_envelope` passthrough (FEAT-527 G6). All four sites are in one file, so one task.

---

## Scope

- Add a small module-level helper `_suggestions_payload(message) -> list[dict] | None` in `handlers/agent.py`.
- Apply it at the four sites: stream finaliser, A2UI JSON branch, JSON path, infographic JSON.
- Tests in `tests/handlers/test_suggestions_passthrough.py`, incl. the golden "no key when empty" comparison.

**NOT in scope**: `chat_models.py` (TASK-4801); ChatStorage persistence of chips (Non-Goal); Telegram/Teams/A2A.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | Helper + four passthrough sites |
| `packages/ai-parrot-server/tests/handlers/test_suggestions_passthrough.py` | CREATE | Passthrough tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models import AIMessage, Suggestion                # AIMessage verified: models/__init__.py:9; Suggestion via TASK-4794
from parrot.models.basic import CompletionUsage               # verified: models/basic.py:48
from parrot.handlers.agent import AgentTalk                   # verified: packages/ai-parrot-server/src/parrot/handlers/agent.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/agent.py  (class AgentTalk)
async def _handle_stream_response(self, bot, query, session_id, user_id, search_type, return_sources, use_vector_context,
    use_conversation_history, output_mode, format_kwargs, memory, llm, agent_name="", client_message_id=None,
    avatar_bifurcate=False, tenant=None, **kwargs)                                          # line 2607
#   (1) stream finaliser :2727-2729
#         a2ui_envelope = getattr(ai_message, "a2ui_envelope", None)
#         if a2ui_envelope is not None:
#             envelope["a2ui_envelope"] = a2ui_envelope
#         separator = b"\n\x00"                                                            # :2730
#   (2) A2UI JSON branch :2869-2878 — `return self.json_response({ "input": ..., "output": ..., "output_mode": ...,
#         "a2ui_envelope": getattr(response, "a2ui_envelope", None), "artifact_id": ..., "metadata": a2ui_metadata, })`
#   (3) JSON path :2975-2977 (12-space indent)
#         _a2ui_envelope = getattr(response, "a2ui_envelope", None)
#         if _a2ui_envelope is not None:
#             obj_response["a2ui_envelope"] = _a2ui_envelope
#   (4) infographic JSON :3280-3284 (8-space indent), preceded by
#         # FEAT-527: dual-emit — additive key only, byte-identical body when no
#         # envelope was produced (G6).
# Existing tests to copy harness from: tests/handlers/test_structured_envelope_passthrough.py,
#   tests/handlers/test_agent_a2ui_stream.py, tests/test_agenttalk_dual_emit.py
```

### Does NOT Exist
- ~~`AgentTalk._format_response` building from `AgentChatResponse`~~ — bodies are plain dicts; do not refactor them.
- ~~a `suggestions` key in any body today~~ — added here, conditionally.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/agent.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/handlers/test_suggestions_passthrough.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/agent.py#AgentTalk._handle_stream_response",
    "sym:packages/ai-parrot-server/src/parrot/handlers/agent.py#AgentTalk.post"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the helper at module level (near the other module helpers, above `class AgentTalk`) — *why*: one rule, four sites.
2. Patch sites (1), (3), (4) with the additive pattern; restructure (2) to build the dict first — *why*: key must be
   omitted when empty.
3. Tests modelled on `test_structured_envelope_passthrough.py` / `test_agent_a2ui_stream.py`; run Validation Commands.

### `packages/ai-parrot-server/src/parrot/handlers/agent.py` (MODIFY — helper)
```python
# occurrences: 1 (verified: grep -c '^class AgentTalk' agent.py)
# BEFORE — insert above `class AgentTalk(BaseView):` (verified: agent.py:117), after `class PausedEnvelope` (:81)
def _suggestions_payload(message: Any) -> Optional[list[dict[str, Any]]]:
    """JSON-ready follow-up chips (FEAT-752), or None when absent/empty so the key is omitted."""
    chips = getattr(message, "suggestions", None)
    if not chips:
        return None
    return [c.model_dump(mode="json") if hasattr(c, "model_dump") else dict(c) for c in chips]
```
`Any` and `Optional` are already imported (`from typing import Dict, Any, List, Optional, ...`, verified: agent.py:11).

### Site (1) stream finaliser (MODIFY)
```python
# occurrences: 1 (verified: grep -c '                a2ui_envelope = getattr(ai_message, "a2ui_envelope", None)' agent.py)
# AFTER — insert below `                    envelope["a2ui_envelope"] = a2ui_envelope` (agent.py:2729), before `separator` (:2730)
                _suggestions = _suggestions_payload(ai_message)
                if _suggestions is not None:
                    envelope["suggestions"] = _suggestions
```

### Site (2) A2UI JSON branch (MODIFY)
```python
# occurrences: 1 (verified: grep -c '                    "a2ui_envelope": getattr(response, "a2ui_envelope", None),' agent.py)
# REPLACE `return self.json_response({ ... })` (agent.py:2869-2878) with: build the same dict into `a2ui_body`
# (keys and order unchanged), then
            _suggestions = _suggestions_payload(response)
            if _suggestions is not None:
                a2ui_body["suggestions"] = _suggestions
            return self.json_response(a2ui_body)
```

### Site (3) JSON path (MODIFY)
```python
# occurrences: 1 for the 12-space line (verified: grep -c '^            _a2ui_envelope = getattr(response, "a2ui_envelope", None)' agent.py)
# AFTER — insert below `                obj_response["a2ui_envelope"] = _a2ui_envelope` that follows it (agent.py:2977)
            _suggestions = _suggestions_payload(response)
            if _suggestions is not None:
                obj_response["suggestions"] = _suggestions
```

### Site (4) infographic JSON (MODIFY)
```python
# occurrences: 2 for the bare anchor `_a2ui_envelope = getattr(response, "a2ui_envelope", None)` — disambiguated by
# context: the 8-space occurrence preceded by `# FEAT-527: dual-emit — additive key only, byte-identical body when no`
# / `# envelope was produced (G6).` (agent.py:3280-3282).
# AFTER — insert below its `            obj_response["a2ui_envelope"] = _a2ui_envelope` (agent.py:3284), before `return web.json_response(`
        _suggestions = _suggestions_payload(response)
        if _suggestions is not None:
            obj_response["suggestions"] = _suggestions
```

### FILL IN checklist
- [ ] Site (2) dict restructure with identical keys/order.
- [ ] Test bodies below (copy the harness of the existing passthrough tests).

---

## Acceptance Criteria

- [ ] With chips on the `AIMessage`: `suggestions` present (JSON-serialisable list) in the stream final envelope, JSON
      body, A2UI JSON body and infographic body.
- [ ] Without chips: none of the four bodies contains a `suggestions` key — golden comparison against the body
      produced before this change (dict equality with the pre-change keys).
- [ ] Text chunks of the stream are unchanged.
- [ ] Existing passthrough tests in the Validation Commands stay green; `ruff check` clean on touched lines.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/handlers/test_suggestions_passthrough.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_structured_envelope_passthrough.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_agent_a2ui_stream.py -q`
- `pytest packages/ai-parrot-server/tests/test_agenttalk_dual_emit.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/handlers/test_suggestions_passthrough.py
from parrot.handlers.agent import _suggestions_payload
from parrot.models import AIMessage, Suggestion
from parrot.models.basic import CompletionUsage


def _msg(**kw):
    return AIMessage(input="q", output="a", model="m", provider="p", usage=CompletionUsage(), **kw)


def test_payload_none_when_empty():
    assert _suggestions_payload(_msg()) is None


def test_payload_json_ready():
    out = _suggestions_payload(_msg(suggestions=[Suggestion(label="A", prompt="a")]))
    assert out == [{"label": "A", "prompt": "a", "output_mode": None, "kind": "followup", "source": "provider",
                    "action": None}]


def test_stream_and_json_passthrough_suggestions():
    # FILL IN: drive the four builders with the harness of test_structured_envelope_passthrough.py /
    #          test_agent_a2ui_stream.py / test_agenttalk_dual_emit.py; key present iff non-empty
    ...


def test_no_optin_body_is_byte_identical():
    # FILL IN: golden comparison — body keys for a chip-less AIMessage equal the pre-FEAT-752 key set
    ...
```

---

## Agent Instructions

Follow `sdd/templates/task.md` § Agent Instructions (worktree via `ensure_worktree --slug followup-suggestion-chips
--feature-id FEAT-752`, `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`, commit only listed files,
`scripts/sdd/close_task.sh TASK-4802 followup-suggestion-chips verified`).

---

## Completion Note

*(Agent fills this in when done)*
