# TASK-2723: `normalize_payload()` + `summarize_tool_input()` — the display contract

**Feature**: FEAT-496 — Dev-Loop Dispatch Event Legibility
**Spec**: `sdd/specs/dev-loop-dispatch-event-legibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2722
**Assigned-to**: unassigned

---

## Context

Spec §2 "Layer 2" and §3 Module 2.

Every dev-loop dispatcher already funnels **all** of its publishing through a
single `_publish_event` method (five separate copies, one per dispatcher — see
"Does NOT Exist" below). That single choke point is where this task's
normalizer runs: it guarantees a display-ready `summary` on every event and
stamps the active dispatch's `DispatchLabels`, without any dispatcher having
to think about it.

This is the contract every backend task (TASK-2724..2728) then implements
against. It is a pure function with no I/O — write it and its tests first, so
the backend tasks have a stable target.

---

## Scope

- Add `normalize_payload(kind, payload)` to
  `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py`.
- Add `summarize_tool_input(tool_name, tool_input, *, max_chars=120)` to the
  same module.
- Add the clamp constants (`SUMMARY_MAX_CHARS = 160`, `TEXT_MAX_CHARS = 400`,
  `TOOL_INPUT_MAX_CHARS = 120`) as module-level names so every backend task
  uses the same numbers.
- Write thorough unit tests, including the "never raises" property.

**NOT in scope**: calling `normalize_payload` from any dispatcher — each
backend task wires its own `_publish_event`. Do not edit `claude.py`,
`codex.py`, `gemini.py`, `google_coding.py` or `llm.py` in this task.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py` | MODIFY | add the normalizer, the digest helper and the clamp constants |
| `packages/ai-parrot/tests/flows/dev_loop/test_normalize_payload.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# verified: dispatchers/_shared.py:19
from parrot.flows.dev_loop.models import DispatchEvent
# created by TASK-2722, same module:
from parrot.flows.dev_loop.dispatchers._shared import current_labels
from parrot.flows.dev_loop.models import DispatchLabels
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py:735
class DispatchEvent(BaseModel):
    kind: Literal[                                            # lines 745-754
        "dispatch.queued", "dispatch.started", "dispatch.message",
        "dispatch.tool_use", "dispatch.tool_result",
        "dispatch.output_invalid", "dispatch.failed", "dispatch.completed",
    ]
    ts: float; run_id: str; node_id: str                      # lines 755-757
    payload: Dict[str, Any]                                   # line 758

# The five INDEPENDENT _publish_event methods this normalizer will be called
# from (wired by later tasks — listed here so the signature matches):
#   dispatchers/claude.py:1077        async def _publish_event(self, stream_key, *, kind, run_id, node_id, payload)
#   dispatchers/codex.py:517          (same shape)
#   dispatchers/gemini.py:454         (same shape)
#   dispatchers/google_coding.py:77   (same shape)
#   dispatchers/llm.py:2395           (same shape)

# Payload shapes that already exist and MUST survive normalization untouched:
#   claude.py:1136-1157   {"message_class": ..., "tools": [...], "text": ...}
#   codex.py:399          {"codex_event": {...}}
#   gemini.py:328         {"gemini_event": {...}}
#   google_coding.py:414  {"agy_event": {...}}
#   llm.py:353-360        {"turn": int, "text": str}
#   llm.py:445-455        {"tool_call_id", "tool_name", "arguments"}
#   llm.py:500-510        {"tool_call_id", "tool_name", "result"}
#   claude.py:218-229     dispatch.queued  {"profile": {...}, "dispatcher": "claude-code"}
#   claude.py:252-257     dispatch.started {"cwd": ..., "subagent": ...}
```

### Does NOT Exist

- ~~a shared dispatcher base class~~ — each of `ClaudeCodeDispatcher`
  (`claude.py:94`), `CodexCodeDispatcher` (`codex.py:38`),
  `GeminiCodeDispatcher` (`gemini.py:38`), `GoogleCodingDispatcher`
  (`google_coding.py:41`) and `LLMCodeDispatcher` (`llm.py:48`) defines its
  **own** `_publish_event`. There is no single place to patch.
- ~~`normalize_payload`~~ / ~~`summarize_tool_input`~~ — this task creates them.
- ~~a `summary` key on any existing payload~~ — no dispatcher emits one today.
- ~~`"dispatch.activity"` / `"dispatch.progress"`~~ — not members of
  `DispatchEvent.kind`; this feature adds **no** new kinds.

---

## Implementation Notes

### Signature and contract

```python
SUMMARY_MAX_CHARS = 160
TEXT_MAX_CHARS = 400
TOOL_INPUT_MAX_CHARS = 120


def normalize_payload(kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return ``payload`` plus the guaranteed display keys and the active
    dispatch's labels.

    Guarantees:
      * the result always contains a non-empty ``summary`` (<= 160 chars);
      * every key already present in ``payload`` survives unchanged;
      * ``DispatchLabels.as_payload()`` keys are merged in, but NEVER
        overwrite a key the backend already set;
      * ``task_file`` is stamped only on ``dispatch.queued`` /
        ``dispatch.started`` (spec §7 payload-growth constraint);
      * it never raises — on any internal error it returns the input payload
        plus a generic summary.
    """
```

### Summary composition

Build the summary from whatever is present, in this precedence order, then
clamp to `SUMMARY_MAX_CHARS`:

1. `payload["summary"]` if the backend already set one (backends may
   pre-compute a better one — never overwrite it).
2. `tool_name` (+ ` ` + `tool_input` digest) for `dispatch.tool_use`.
3. `tool_name` (+ ` → error` / ` → ok`) for `dispatch.tool_result`.
4. `text` (first line, collapsed whitespace) for `dispatch.message`.
5. `error` / `error_message` for `dispatch.failed` / `dispatch.output_invalid`.
6. A kind-specific fallback (e.g. `"queued (claude-code)"`,
   `"started in <basename of cwd>"`, `"completed — 12 turns, 1m03s"`).
7. Last resort: the bare event kind without its `dispatch.` prefix.

Prefix the summary with the task/seat when labels are bound and the caller
did not already include them, e.g. `"[TASK-1857 · w1] Read parrot/flows/…"`.

### `summarize_tool_input`

Recognise the common shapes and fall back gracefully:

| Tool arg key | Digest |
|---|---|
| `file_path`, `path`, `notebook_path` | the path, tail-truncated |
| `command`, `cmd` | the command, head-truncated |
| `pattern` + `path` | `"<pattern> in <path>"` |
| `url` | the URL |
| `prompt`, `description` | first line |
| anything else | `"<first key>=<value>"`, clamped |

Accepts `dict`, a JSON `str`, or anything else (returns `""`).

### Key Constraints

- **Totality.** Wrap the whole body in `try/except Exception` and return
  `{**payload, "summary": <kind fallback>}` on failure. This function runs
  inside telemetry paths that must never break a dispatch (spec AC10).
- Never mutate the caller's dict — build and return a new one.
- Never log at anything above DEBUG; this is on a hot path.
- English-only strings — no i18n layer (spec §8, resolved).
- Full type hints, Google-style docstrings.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:445-510` — the only backend that already emits `tool_name`/`arguments`/`result`; the shape the normalizer should feel native to.
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py:76-99` — the existing swallow-everything discipline to mirror.

---

## Acceptance Criteria

- [ ] `normalize_payload(kind, {})` returns a dict with a non-empty `summary` for **every** one of the eight `DispatchEvent.kind` values.
- [ ] `summary` is never longer than 160 characters.
- [ ] Every key present in the input payload is present, unchanged, in the output (`codex_event`, `message_class`, `turn`, `arguments`, … all survive).
- [ ] A backend-supplied `summary` is never overwritten.
- [ ] Bound `DispatchLabels` are merged into the output; a label key never overwrites a backend key of the same name.
- [ ] `task_file` appears only for `dispatch.queued` / `dispatch.started`.
- [ ] `normalize_payload` never raises — property-tested against `None`, non-dict values, deeply nested structures, and objects whose `__str__` raises.
- [ ] `summarize_tool_input` digests `{"file_path": ...}`, `{"command": ...}`, `{"pattern": ..., "path": ...}` and clamps to 120 chars.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_normalize_payload.py -v`
- [ ] Existing suite still green: `pytest packages/ai-parrot/tests/flows/dev_loop/ -q`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_normalize_payload.py
import pytest

from parrot.flows.dev_loop.models import DispatchLabels
from parrot.flows.dev_loop.dispatchers._shared import (
    bind_labels, normalize_payload, summarize_tool_input,
    SUMMARY_MAX_CHARS, _DISPATCH_LABELS_CTX,
)

KINDS = ["dispatch.queued", "dispatch.started", "dispatch.message",
         "dispatch.tool_use", "dispatch.tool_result",
         "dispatch.output_invalid", "dispatch.failed", "dispatch.completed"]


@pytest.mark.parametrize("kind", KINDS)
def test_every_kind_gets_a_summary(kind):
    out = normalize_payload(kind, {})
    assert out["summary"]
    assert len(out["summary"]) <= SUMMARY_MAX_CHARS


def test_preserves_backend_keys():
    raw = {"codex_event": {"type": "item.started"}, "message_class": "X"}
    out = normalize_payload("dispatch.message", raw)
    assert out["codex_event"] == raw["codex_event"]
    assert out["message_class"] == "X"


def test_does_not_overwrite_backend_summary():
    out = normalize_payload("dispatch.message", {"summary": "mine"})
    assert out["summary"] == "mine"


def test_labels_are_stamped():
    token = bind_labels(DispatchLabels(task_id="TASK-1857", seat="development.w1"))
    try:
        out = normalize_payload("dispatch.tool_use", {"tool_name": "Read"})
        assert out["task_id"] == "TASK-1857"
        assert out["seat"] == "development.w1"
    finally:
        _DISPATCH_LABELS_CTX.reset(token)


def test_task_file_only_on_lifecycle_kinds():
    token = bind_labels(DispatchLabels(task_file="sdd/tasks/active/TASK-1.md"))
    try:
        assert "task_file" in normalize_payload("dispatch.started", {})
        assert "task_file" not in normalize_payload("dispatch.tool_use", {})
    finally:
        _DISPATCH_LABELS_CTX.reset(token)


@pytest.mark.parametrize("bad", [None, 42, "a string", {"k": object()}])
def test_never_raises(bad):
    out = normalize_payload("dispatch.message", bad)
    assert isinstance(out, dict) and out["summary"]


class TestSummarizeToolInput:
    def test_file_path(self):
        assert "foo.py" in summarize_tool_input("Read", {"file_path": "a/b/foo.py"})

    def test_command(self):
        assert "pytest" in summarize_tool_input("Bash", {"command": "pytest -q"})

    def test_pattern_and_path(self):
        out = summarize_tool_input("Grep", {"pattern": "def x", "path": "src/"})
        assert "def x" in out and "src/" in out

    def test_clamped(self):
        assert len(summarize_tool_input("Bash", {"command": "x" * 500})) <= 120

    def test_json_string_input(self):
        assert "foo.py" in summarize_tool_input("Read", '{"file_path": "foo.py"}')

    def test_unknown_shape_degrades(self):
        assert summarize_tool_input("Weird", object()) == ""
```

---

## Agent Instructions

1. **Read the spec** — §2 "Layer 2", the normalized-payload contract table in §2 "Data Models", §3 Module 2, and the §7 payload-growth constraint.
2. **Check dependencies** — TASK-2722 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm the five `_publish_event` line numbers and the existing payload shapes before writing the summary rules.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** the two functions and the constants. Touch no dispatcher.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-02
**Notes**: Added `normalize_payload(kind, payload)` and
`summarize_tool_input(tool_name, tool_input, *, max_chars=120)` plus
`SUMMARY_MAX_CHARS`/`TEXT_MAX_CHARS`/`TOOL_INPUT_MAX_CHARS` constants to
`_shared.py`, with private helpers `_clamp`, `_build_summary`,
`_kind_fallback`, `_labels_prefix`, `_fmt_duration_ms`. Both functions are
total (wrapped in `try/except Exception`, never raise). `summarize_tool_input`
checks `pattern`(+`path`) before the bare `path` key so a Grep-style call
digests as `"<pattern> in <path>"` rather than falling into the path-only
branch. 22 new unit tests pass; full `dev_loop` suite green (same 3
pre-existing unrelated failures in `test_recovery_lifecycle.py`).

**Deviations from spec**: `summarize_tool_input`'s shape-recognition order
checks `pattern` before `file_path`/`path`/`notebook_path` (the spec's table
lists them in the reverse order) — necessary because a Grep call carries both
`pattern` and `path`, and the table's own worked example
(`"<pattern> in <path>"`) requires `pattern` to win. No test or acceptance
criterion specifies the opposite order.
