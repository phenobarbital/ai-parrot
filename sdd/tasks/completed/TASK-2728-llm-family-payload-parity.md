# TASK-2728: LLM-family parity — normalize + label the OpenAI-compatible dispatchers

**Feature**: FEAT-496 — Dev-Loop Dispatch Event Legibility
**Spec**: `sdd/specs/dev-loop-dispatch-event-legibility.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2723
**Assigned-to**: unassigned

---

## Context

Spec §1 root cause 4 (final sentence), §2 "Layer 3", §3 Module 5.

`LLMCodeDispatcher` is the one backend that already publishes usable payloads
— `{"tool_call_id", "tool_name", "arguments"}` on tool use,
`{"tool_call_id", "tool_name", "result"}` on tool result, `{"turn", "text"}`
on a message (`llm.py:353-510`). It needs the least work: route its
`_publish_event` through `normalize_payload` so it gains `summary` + labels
like everyone else.

The trap is coverage. **Four subclasses override `dispatch()`** — Nova, Grok,
Z.ai and Moonshot — and each override must also accept and bind `labels`.
Missing one leaves that backend silently unlabelled with no test failure
unless the parity test enumerates all four. That enumeration is the point of
this task.

---

## Scope

- Route `LLMCodeDispatcher._publish_event` (`llm.py:2395`) through
  `normalize_payload`.
- Accept `labels: Optional[DispatchLabels] = None` on
  `LLMCodeDispatcher.dispatch` (`llm.py:110`) and bind/reset it beside the
  existing `_SESSION_HOST_CTX` token.
- Add the same kwarg + binding to **all four** overriding subclasses:
  `NovaCodeDispatcher.dispatch` (`nova.py:219`),
  `GrokCodeDispatcher.dispatch` (`grok.py:52`),
  `ZaiCodeDispatcher.dispatch` (`zai.py:96`),
  `MoonshotCodeDispatcher.dispatch` (`moonshot.py:111`).
- Add a parity test that **enumerates every `LLMCodeDispatcher` subclass** and
  asserts each one's `dispatch` accepts `labels`, so a future backend cannot
  be added without it.

**NOT in scope**: `claude.py`, `codex.py`, `gemini.py`, `google_coding.py`;
`mantle.py` (it defines no development dispatcher — see "Does NOT Exist");
session state; console HTML.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` | MODIFY | `_publish_event` wiring + `labels` kwarg on `dispatch` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/nova.py` | MODIFY | `labels` kwarg on the overriding `dispatch` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/grok.py` | MODIFY | idem |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/zai.py` | MODIFY | idem |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/moonshot.py` | MODIFY | idem |
| `packages/ai-parrot/tests/flows/dev_loop/test_llm_family_parity.py` | CREATE | subclass-enumerating parity test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# add (created by TASK-2722 / TASK-2723):
from parrot.flows.dev_loop.dispatchers._shared import bind_labels, normalize_payload
from parrot.flows.dev_loop.models import DispatchLabels

# verified subclass relationships:
# nova.py:48      from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
# grok.py:11      from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
# zai.py:12       from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
# moonshot.py:12  from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
class LLMCodeDispatcher:                                      # line 48
    async def dispatch(self, *, brief, profile, output_model,
                       run_id, node_id, cwd,
                       session_host=None) -> T:               # line 110

    # payloads it already emits — all keep working, they just gain `summary`:
    #   dispatch.message     {"turn": int, "text": content[:4000]}   # 353-360
    #   dispatch.completed   {"output_model": ..., "usage": {...}}   # 362-375
    #   dispatch.tool_use    {"tool_call_id", "tool_name",
    #                         "arguments"}                           # 445-455
    #   dispatch.tool_result {"tool_call_id", "tool_name",
    #                         "result"}                              # 500-510
    #   dispatch.tool_result (truncated-call path)                   # 420-435

    @staticmethod
    def _tool_call_id(call: Any) -> str:                      # line 2168
    @staticmethod
    def _tool_call_name(call: Any) -> str:                    # line 2172

    async def _publish_event(self, stream_key, *, kind, run_id,
                             node_id, payload) -> None:       # line 2395

# The four overriding subclasses:
class NovaCodeDispatcher(LLMCodeDispatcher):                  # nova.py:61
    async def dispatch(...)                                   # nova.py:219
class GrokCodeDispatcher(LLMCodeDispatcher):                  # grok.py:16
    async def dispatch(...)                                   # grok.py:52
class ZaiCodeDispatcher(LLMCodeDispatcher):                   # zai.py:18
    async def dispatch(...)                                   # zai.py:96
class MoonshotCodeDispatcher(LLMCodeDispatcher):              # moonshot.py:18
    async def dispatch(...)                                   # moonshot.py:111
```

### Does NOT Exist

- ~~`MantleCodeDispatcher`~~ — `dispatchers/mantle.py` defines only
  `MantleAdversarialReviewProfile` (`mantle.py:65`) and
  `MantleAdversarialReviewDispatcher` (`mantle.py:106`, a review dispatcher
  whose own `review()` at `mantle.py:187` never calls a development
  `dispatch()`). There is nothing here for this task to change; Mantle is
  handled by TASK-2731.
- ~~a fifth `LLMCodeDispatcher` subclass~~ — as of 2026-09-02 there are
  exactly four. The parity test must discover them dynamically
  (`LLMCodeDispatcher.__subclasses__()`), not hardcode the list, so a new one
  fails the test instead of slipping through.
- ~~a `summary` key in any llm payload~~ — none today.
- ~~`normalize_payload` being called from `llm.py`~~ — TASK-2723 creates it.

---

## Implementation Notes

### The minimal change

`llm.py` is the easy half — one wiring line:

```python
async def _publish_event(self, stream_key, *, kind, run_id, node_id, payload):
    payload = normalize_payload(kind, payload)
    ...   # everything else unchanged
```

Because `llm.py` already emits `tool_name` and `arguments`,
`normalize_payload` will build a good `summary` with no extractor needed —
this is the backend the normalizer was designed to feel native to.

### The subclass sweep

For each of the four subclasses, add `labels: Optional[DispatchLabels] = None`
to the signature and bind it exactly as the base does. If a subclass's
override simply delegates to `super().dispatch(...)`, forward `labels=labels`
rather than binding twice.

### Parity test — the point of the task

```python
def test_every_llm_subclass_accepts_labels():
    import inspect
    from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
    # import the modules so the subclasses register
    import parrot.flows.dev_loop.dispatchers.nova      # noqa: F401
    import parrot.flows.dev_loop.dispatchers.grok      # noqa: F401
    import parrot.flows.dev_loop.dispatchers.zai       # noqa: F401
    import parrot.flows.dev_loop.dispatchers.moonshot  # noqa: F401

    for cls in [LLMCodeDispatcher, *LLMCodeDispatcher.__subclasses__()]:
        sig = inspect.signature(cls.dispatch)
        assert "labels" in sig.parameters, f"{cls.__name__}.dispatch lacks labels="
        assert sig.parameters["labels"].default is None
```

### Key Constraints

- Do not change any existing payload key — `turn`, `text`, `arguments`,
  `result`, `tool_call_id`, `output_model`, `usage` all stay.
- `llm.py` is a very large file (2400+ lines); keep the diff surgical.
- Reset the label token on every exit path, mirroring the session-host token.
- Full type hints; Google-style docstrings on anything new.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:336-360` — the per-turn logging that already exists; the `summary` should read like those log lines.
- `packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py:176-178`, `test_grok_code_dispatcher.py:192-194`, `test_zai_code_dispatcher.py:306-308`, `test_moonshot_code_dispatcher.py:314-316` — the existing per-backend kind assertions that must keep passing.

---

## Acceptance Criteria

- [ ] Every payload published by `LLMCodeDispatcher` carries a non-empty `summary`.
- [ ] No existing payload key is removed or renamed (`turn`, `text`, `tool_call_id`, `tool_name`, `arguments`, `result`, `output_model`, `usage`).
- [ ] `LLMCodeDispatcher.dispatch` and **all four** subclass overrides accept `labels: Optional[DispatchLabels] = None`.
- [ ] The parity test discovers subclasses dynamically and would fail if a fifth backend were added without `labels`.
- [ ] A bound `DispatchLabels` appears in a `dispatch.tool_use` payload (`task_id`, `seat`).
- [ ] Existing per-backend tests still pass unchanged: `test_llm_code_dispatcher.py`, `test_grok_code_dispatcher.py`, `test_zai_code_dispatcher.py`, `test_moonshot_code_dispatcher.py`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_llm_family_parity.py
import inspect
import pytest

from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
import parrot.flows.dev_loop.dispatchers.nova      # noqa: F401
import parrot.flows.dev_loop.dispatchers.grok      # noqa: F401
import parrot.flows.dev_loop.dispatchers.zai       # noqa: F401
import parrot.flows.dev_loop.dispatchers.moonshot  # noqa: F401

from parrot.flows.dev_loop.models import DispatchLabels
from parrot.flows.dev_loop.dispatchers._shared import bind_labels, _DISPATCH_LABELS_CTX


ALL = [LLMCodeDispatcher, *LLMCodeDispatcher.__subclasses__()]


@pytest.mark.parametrize("cls", ALL, ids=lambda c: c.__name__)
def test_dispatch_accepts_labels(cls):
    sig = inspect.signature(cls.dispatch)
    assert "labels" in sig.parameters, f"{cls.__name__}.dispatch lacks labels="
    assert sig.parameters["labels"].default is None


def test_at_least_the_four_known_subclasses_are_covered():
    """Guards against an import regression silently shrinking the sweep."""
    names = {c.__name__ for c in LLMCodeDispatcher.__subclasses__()}
    assert {"NovaCodeDispatcher", "GrokCodeDispatcher",
            "ZaiCodeDispatcher", "MoonshotCodeDispatcher"} <= names


class TestLLMPayloadEnrichment:
    async def test_tool_use_payload_gains_summary_and_labels(self, captured_events):
        token = bind_labels(DispatchLabels(task_id="TASK-1", seat="development.w1"))
        try:
            ...   # drive the existing fake tool-call loop
        finally:
            _DISPATCH_LABELS_CTX.reset(token)
        _kind, p = captured_events[-1]
        assert p["summary"]
        assert p["task_id"] == "TASK-1"
        assert p["tool_name"]          # pre-existing key, unchanged

    async def test_existing_keys_are_untouched(self, captured_events):
        ...
        assert {"tool_call_id", "tool_name", "arguments"} <= set(p)
```

---

## Agent Instructions

1. **Read the spec** — §1 root cause 4 (last sentence), §3 Module 5, §7 "Subclass override drift".
2. **Check dependencies** — TASK-2723 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm the four subclass `dispatch` line numbers before editing; `llm.py` churns.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** — one wiring line in `llm.py`, then the four-subclass sweep, then the parity test.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-02
**Notes**: `LLMCodeDispatcher._publish_event` now routes through
`normalize_payload`; `dispatch()` accepts `labels: Optional[DispatchLabels]
= None`, bound/reset alongside `_SESSION_HOST_CTX` on both exit paths. All
four subclasses (`NovaCodeDispatcher`, `GrokCodeDispatcher`,
`ZaiCodeDispatcher`, `MoonshotCodeDispatcher`) add the same kwarg to their
overriding `dispatch` and forward `labels=labels` into `super().dispatch(...)`
— no existing key removed/renamed. Added
`test_llm_family_parity.py`, which discovers subclasses dynamically via
`LLMCodeDispatcher.__subclasses__()` (not a hardcoded list) so a future
fifth backend without `labels=` fails the sweep. 7 new tests pass; all 212
pre-existing llm/grok/zai/moonshot/nova tests pass unchanged; full `dev_loop`
suite green (same 3 pre-existing unrelated failures in
`test_recovery_lifecycle.py`).

**Deviations from spec**: none
