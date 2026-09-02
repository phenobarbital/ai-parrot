# TASK-2725: Codex dispatcher — extract display fields from `codex_event`

**Feature**: FEAT-496 — Dev-Loop Dispatch Event Legibility
**Spec**: `sdd/specs/dev-loop-dispatch-event-legibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2723
**Assigned-to**: unassigned

---

## Context

Spec §1 root cause 4, §2 "Layer 3", §3 Module 4.

`CodexCodeDispatcher._publish_codex_event` (`codex.py:388-401`) publishes the
entire raw CLI event under a single nested key: `{"codex_event": {...}}`. The
console's `briefOf` has no branch for it and renders
`codex_event=[object Object]`. The dispatcher already *classifies* the event
correctly (`_codex_event_kind`, `codex.py:403-411`, which reads
`event["item"]["type"]` against `_TOOL_ITEM_TYPES`) — it just throws away
everything it learned when building the payload.

This task is one of three sibling tasks (TASK-2725/2726/2727) applying the
same treatment to the three CLI-subprocess backends. They touch disjoint
files and can run concurrently.

---

## Scope

- Add a `_extract_codex_display(event)` helper to `codex.py` returning
  `tool_name`, `tool_input`, `text` and any status/exit information the item
  carries.
- Rewrite `_publish_codex_event` (`codex.py:388`) to publish those extracted
  keys **alongside** the preserved raw `codex_event`.
- Route `CodexCodeDispatcher._publish_event` (`codex.py:517`) through
  `normalize_payload`.
- Accept `labels: Optional[DispatchLabels] = None` on
  `CodexCodeDispatcher.dispatch` (`codex.py:70`) and bind/reset it beside the
  existing `_SESSION_HOST_CTX` token.
- Extend `packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py`.

**NOT in scope**: `gemini.py` (TASK-2726), `google_coding.py` (TASK-2727),
`claude.py` (TASK-2724), `llm.py` (TASK-2728), session state, console HTML.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py` | MODIFY | extractor, `_publish_codex_event`, `_publish_event`, `labels` kwarg |
| `packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py` | MODIFY | add legibility assertions |

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
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py
class CodexCodeDispatcher:                                    # line 38
    _TOOL_ITEM_TYPES = {                                      # lines 46-51
        "command_execution",
        "file_change",
        "mcp_tool_call",
        "web_search",
    }

    async def dispatch(self, *, brief, profile: CodexCodeDispatchProfile,
                       output_model, run_id, node_id, cwd,
                       session_host=None) -> T:               # line 70
        stream_key = f"flow:{run_id}:dispatch:{node_id}"      # line 82

    async def _stream_stdout_events(self, stdout, *, stream_key,
                                    run_id, node_id) -> None: # line 358
        # non-JSON line -> dispatch.message {"raw_line": line}          # 376-383
        # otherwise -> await self._publish_codex_event(...)             # line 385

    async def _publish_codex_event(self, stream_key, event: Dict[str, Any],
                                   run_id, node_id) -> None:  # line 388
        await self._publish_event(
            stream_key, kind=self._codex_event_kind(event),
            run_id=run_id, node_id=node_id,
            payload={"codex_event": event},                   # line 399  ← the defect
        )

    def _codex_event_kind(self, event: Dict[str, Any]) -> str:# line 403
        event_type = event.get("type")                        # line 404
        item = event.get("item")                              # line 405
        item_type = item.get("type") if isinstance(item, dict) else None  # 406
        if event_type == "item.started" and item_type in self._TOOL_ITEM_TYPES:
            return "dispatch.tool_use"                        # lines 407-408
        if event_type == "item.completed" and item_type in self._TOOL_ITEM_TYPES:
            return "dispatch.tool_result"                     # lines 409-410
        return "dispatch.message"                             # line 411

    async def _publish_event(self, stream_key, *, kind, run_id,
                             node_id, payload) -> None:       # line 517
```

### Does NOT Exist

- ~~a shared dispatcher base class~~ — `CodexCodeDispatcher` (`codex.py:38`)
  is standalone; it only *mirrors* `ClaudeCodeDispatcher`'s public contract
  (see its class docstring, `codex.py:41-45`). Do not try to inherit or
  refactor into a common base in this task.
- ~~`normalize_payload` already being called~~ — nothing in `codex.py` calls
  it today; TASK-2723 creates it.
- ~~a `tool_name` key in any codex payload~~ — the only key today is
  `codex_event` (or `raw_line` for a non-JSON stdout line).
- ~~a documented Codex CLI event schema in this repo~~ — the item shapes are
  inferred from `_TOOL_ITEM_TYPES` and the existing tests. Treat every field
  read as optional (`.get()` with a default); never index.

---

## Implementation Notes

### Extractor sketch

`_codex_event_kind` already tells you which of the three kinds you have.
Extract from `event["item"]` per item type, defensively:

| `item["type"]` | `tool_name` | `tool_input` / detail |
|---|---|---|
| `command_execution` | `"shell"` | `item.get("command")`, plus `exit_code` / `status` on completion |
| `file_change` | `"edit"` | changed path(s) from `item.get("changes")` or `item.get("path")` |
| `mcp_tool_call` | `item.get("server")`/`item.get("tool")` joined | `item.get("arguments")` |
| `web_search` | `"web_search"` | `item.get("query")` |
| anything else / no item | `""` | assistant `text` from `item.get("text")` or `event.get("message")` |

```python
@staticmethod
def _extract_codex_display(event: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort display projection of one Codex CLI stream event.

    Never raises and never assumes a field is present — the CLI's event
    schema is not pinned by this repo.
    """
```

Then:

```python
payload: Dict[str, Any] = {"codex_event": event}      # PRESERVED verbatim
payload.update(self._extract_codex_display(event))    # additive only
```

### Key Constraints

- **`codex_event` must survive verbatim** — the console's expanded-JSON view
  and the existing tests both read it (spec AC9).
- The extractor is total: wrap in `try/except Exception` and return `{}`.
- Reuse `summarize_tool_input` for the digest so codex and claude clamp
  identically.
- Bind labels in `dispatch()` and reset on **every** exit path, mirroring the
  `_SESSION_HOST_CTX` discipline already in this file.
- Do not change `_codex_event_kind`'s classification logic — it is correct.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:445-510` — the target payload shape.
- `packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py:163-164` — the existing kind assertions that must keep passing.

---

## Acceptance Criteria

- [ ] An `item.started` / `command_execution` event yields `tool_name` and a `tool_input` containing the command.
- [ ] An `item.completed` / `command_execution` event yields `tool_name` plus the exit/status detail.
- [ ] `payload["codex_event"]` is byte-for-byte the event that was parsed, on every kind.
- [ ] Every published payload carries a non-empty `summary`.
- [ ] A malformed/unknown event shape does not raise and still publishes a payload with a summary.
- [ ] `CodexCodeDispatcher.dispatch` accepts `labels=` and binds/resets it on every exit path.
- [ ] Existing assertions in `test_codex_dispatcher.py` (`"dispatch.tool_use" in kinds`, `"dispatch.tool_result" in kinds`) still pass unchanged.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py  (additions)

def _cmd_started(cmd="pytest -q"):
    return {"type": "item.started",
            "item": {"type": "command_execution", "command": cmd}}

def _cmd_completed(cmd="pytest -q", exit_code=0):
    return {"type": "item.completed",
            "item": {"type": "command_execution", "command": cmd,
                     "exit_code": exit_code, "status": "completed"}}


class TestCodexEventExtraction:
    def test_command_started_yields_tool_name_and_input(self):
        d = CodexCodeDispatcher(max_concurrent=1)
        out = d._extract_codex_display(_cmd_started())
        assert out["tool_name"]
        assert "pytest" in out["tool_input"]

    def test_command_completed_carries_exit_detail(self):
        d = CodexCodeDispatcher(max_concurrent=1)
        out = d._extract_codex_display(_cmd_completed(exit_code=1))
        assert out.get("exit_code") == 1 or "1" in str(out)

    def test_raw_event_is_preserved(self, captured_events):
        """AC9: the expanded JSON view still shows the provider event."""
        ...
        assert captured_events[-1][1]["codex_event"] == _cmd_started()

    @pytest.mark.parametrize("bad", [{}, {"type": "x"}, {"item": None},
                                     {"item": {"type": "unknown"}}])
    def test_malformed_event_never_raises(self, bad):
        d = CodexCodeDispatcher(max_concurrent=1)
        assert isinstance(d._extract_codex_display(bad), dict)

    def test_every_payload_has_a_summary(self, captured_events):
        ...
        assert all(p["summary"] for _k, p in captured_events)
```

---

## Agent Instructions

1. **Read the spec** — §1 root cause 4, §2 "Layer 3", §3 Module 4, §5 AC9.
2. **Check dependencies** — TASK-2723 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `codex.py:388-411` and `:517` before editing.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement**. Keep `codex_event` intact; add, never replace.
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
