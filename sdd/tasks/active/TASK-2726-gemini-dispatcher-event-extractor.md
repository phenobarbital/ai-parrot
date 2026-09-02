# TASK-2726: Gemini dispatcher — extract display fields from `gemini_event`

**Feature**: FEAT-496 — Dev-Loop Dispatch Event Legibility
**Spec**: `sdd/specs/dev-loop-dispatch-event-legibility.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2723
**Assigned-to**: unassigned

---

## Context

Spec §1 root cause 4, §2 "Layer 3", §3 Module 4.

`GeminiCodeDispatcher._publish_gemini_event` (`gemini.py:317-330`) publishes
the entire raw CLI event under one nested key: `{"gemini_event": {...}}`.
Like the Codex dispatcher, it already classifies the event correctly
(`_gemini_event_kind`, `gemini.py:332-338`, keying on
`event["type"] in ("tool_call", "tool_response")`) and then discards
everything it knew.

Sibling of TASK-2725 (codex) and TASK-2727 (agy) — disjoint files, safe to run
concurrently.

---

## Scope

- Add `_extract_gemini_display(event)` to `gemini.py`, returning `tool_name`,
  `tool_input`, `text` and any response/status detail.
- Rewrite `_publish_gemini_event` (`gemini.py:317`) to publish those keys
  **alongside** the preserved raw `gemini_event`.
- Route `GeminiCodeDispatcher._publish_event` (`gemini.py:454`) through
  `normalize_payload`.
- Accept `labels: Optional[DispatchLabels] = None` on
  `GeminiCodeDispatcher.dispatch` (`gemini.py:75`) and bind/reset it beside
  the existing `_SESSION_HOST_CTX` token.
- Extend `packages/ai-parrot/tests/flows/dev_loop/test_gemini_dispatcher.py`.

**NOT in scope**: any other dispatcher, session state, console HTML.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py` | MODIFY | extractor, `_publish_gemini_event`, `_publish_event`, `labels` kwarg |
| `packages/ai-parrot/tests/flows/dev_loop/test_gemini_dispatcher.py` | MODIFY | add legibility assertions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# add (created by TASK-2722 / TASK-2723):
from parrot.flows.dev_loop.dispatchers._shared import (
    bind_labels, normalize_payload, summarize_tool_input,
)
from parrot.flows.dev_loop.models import DispatchLabels
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py
class GeminiCodeDispatcher:                                   # line 38
    async def dispatch(self, *, brief, profile: Any, output_model,
                       run_id, node_id, cwd,
                       session_host=None) -> T:               # line 75
        stream_key = f"flow:{run_id}:dispatch:{node_id}"      # line 87

    async def _stream_stdout_events(self, stdout, *, stream_key,
                                    run_id, node_id) -> str:  # line 276
        # non-JSON line -> dispatch.message {"raw_line": line}          # 294-301
        # event["type"] == "message" and event["role"] == "assistant"
        #   -> accumulate event["content"] into assistant_chunks         # 305-309
        # then -> await self._publish_gemini_event(...)                 # line 311

    async def _publish_gemini_event(self, stream_key, event: Dict[str, Any],
                                    run_id, node_id) -> None: # line 317
        await self._publish_event(
            stream_key, kind=self._gemini_event_kind(event),
            run_id=run_id, node_id=node_id,
            payload={"gemini_event": event},                  # line 328  ← the defect
        )

    def _gemini_event_kind(self, event: Dict[str, Any]) -> str:# line 332
        event_type = event.get("type")                        # line 333
        if event_type == "tool_call":
            return "dispatch.tool_use"                        # lines 334-335
        if event_type == "tool_response":
            return "dispatch.tool_result"                     # lines 336-337
        return "dispatch.message"                             # line 338

    async def _publish_event(self, stream_key, *, kind, run_id,
                             node_id, payload) -> None:       # line 454
```

### Does NOT Exist

- ~~a shared dispatcher base class~~ — `GeminiCodeDispatcher` (`gemini.py:38`)
  is standalone and only mirrors the public `dispatch` contract (class
  docstring, `gemini.py:41-45`).
- ~~a `tool_name` key in any gemini payload~~ — today it is `gemini_event`
  or `raw_line` only.
- ~~a pinned Gemini CLI event schema in this repo~~ — the only shapes the
  code relies on are `type`, `role` and `content` (`gemini.py:305-309`).
  Read every other field with `.get()` and a default.
- ~~`normalize_payload` already imported here~~ — TASK-2723 creates it.

---

## Implementation Notes

### Extractor sketch

```python
@staticmethod
def _extract_gemini_display(event: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort display projection of one Gemini CLI stream event.

    Never raises; never assumes a field exists.
    """
```

| `event["type"]` | Extract |
|---|---|
| `tool_call` | `tool_name` from `name`/`tool`/`toolName`; `tool_input` from `args`/`arguments`/`input` via `summarize_tool_input` |
| `tool_response` | `tool_name` from the same keys when echoed; `is_error` from `error`/`status`; a clamped `result_snippet` from `response`/`output` |
| `message` (role `assistant`) | `text` from `content`, clamped to `TEXT_MAX_CHARS` |
| anything else | `text` from any string-ish `content`/`message`, else `{}` |

Then:

```python
payload: Dict[str, Any] = {"gemini_event": event}      # PRESERVED verbatim
payload.update(self._extract_gemini_display(event))    # additive only
```

### Key Constraints

- **`gemini_event` must survive verbatim** (spec AC9) — the expanded-JSON
  view and existing tests read it.
- Total function: `try/except Exception` → `{}`.
- Use `summarize_tool_input` so the digest clamps identically across backends.
- Bind labels in `dispatch()`, reset on every exit path (mirror
  `_SESSION_HOST_CTX` handling already in this file).
- Do not change `_gemini_event_kind` — its classification is correct.
- Gemini's `tool_call` may name the tool under several keys depending on CLI
  version; probe a small ordered list rather than assuming one.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py:305-309` — the only field names the existing code trusts.
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:445-510` — target payload shape.
- `packages/ai-parrot/tests/flows/dev_loop/test_gemini_dispatcher.py:168-169` — existing kind assertions that must keep passing.

---

## Acceptance Criteria

- [ ] A `tool_call` event yields a non-empty `tool_name` and a `tool_input` digest.
- [ ] A `tool_response` event yields `tool_name` when the CLI echoes it, and always a `summary`.
- [ ] An assistant `message` event yields a clamped `text`.
- [ ] `payload["gemini_event"]` is the verbatim parsed event on every kind.
- [ ] Every published payload carries a non-empty `summary`.
- [ ] A malformed/unknown event shape does not raise.
- [ ] `GeminiCodeDispatcher.dispatch` accepts `labels=` and binds/resets on every exit path.
- [ ] Existing assertions in `test_gemini_dispatcher.py` still pass unchanged.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_gemini_dispatcher.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_gemini_dispatcher.py  (additions)

class TestGeminiEventExtraction:
    def test_tool_call_yields_name_and_input(self):
        d = GeminiCodeDispatcher(...)
        out = d._extract_gemini_display(
            {"type": "tool_call", "name": "read_file",
             "args": {"path": "src/foo.py"}})
        assert out["tool_name"] == "read_file"
        assert "foo.py" in out["tool_input"]

    def test_tool_response_yields_summary(self):
        d = GeminiCodeDispatcher(...)
        out = d._extract_gemini_display(
            {"type": "tool_response", "name": "read_file", "response": "ok"})
        assert out.get("tool_name") == "read_file"

    def test_assistant_message_yields_text(self):
        d = GeminiCodeDispatcher(...)
        out = d._extract_gemini_display(
            {"type": "message", "role": "assistant", "content": "hello"})
        assert out["text"] == "hello"

    def test_raw_event_preserved(self, captured_events):
        """AC9."""
        ...

    @pytest.mark.parametrize("bad", [{}, {"type": None}, {"type": "tool_call"}])
    def test_malformed_never_raises(self, bad):
        d = GeminiCodeDispatcher(...)
        assert isinstance(d._extract_gemini_display(bad), dict)
```

---

## Agent Instructions

1. **Read the spec** — §1 root cause 4, §2 "Layer 3", §3 Module 4, §5 AC9.
2. **Check dependencies** — TASK-2723 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `gemini.py:317-338` and `:454`.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement**. Keep `gemini_event` intact; add, never replace.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
