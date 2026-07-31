---
type: Wiki Overview
title: 'TASK-1063: Add `synthesize_results` util in `core/storage/synthesis.py`'
id: doc:sdd-tasks-completed-task-1063-synthesize-results-util-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements Spec §3 Module 7. The new `AgentsFlow` drops `SynthesisMixin`
  inheritance (spec §8 D11) and offers two consumer paths for LLM-based result synthesis:'
relates_to:
- concept: mod:parrot.bots.flows.core.storage
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.synthesis
  rel: mentions
---

# TASK-1063: Add `synthesize_results` util in `core/storage/synthesis.py`

**Feature**: FEAT-163 — AgentsFlow Refactor — DAG Engine on flows.core
**Spec**: `sdd/specs/agentsflow-refactor-spec3.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1061
**Assigned-to**: unassigned

---

## Context

Implements Spec §3 Module 7. The new `AgentsFlow` drops `SynthesisMixin` inheritance (spec §8 D11) and offers two consumer paths for LLM-based result synthesis:

1. As a `run_flow(on_complete=[synthesize_results])` hook.
2. As an in-graph `SynthesisNode` DAG node (registered via `@register_node("synthesis")`, implemented in TASK-1066).

Both paths call the same `synthesize_results(ctx, result) -> str` util — a single source of truth, no code duplication. This task adds that util to the existing `parrot/bots/flows/core/storage/synthesis.py` alongside the already-present `SYNTHESIS_PROMPT` (line 23) and `SynthesisMixin` (line 34). `SynthesisMixin` stays in place untouched (still inherited by `AgentCrew`).

---

## Scope

- Add `async def synthesize_results(ctx: FlowContext, result: FlowResult) -> str` to `parrot/bots/flows/core/storage/synthesis.py`. The function:
  - Reads the existing `SYNTHESIS_PROMPT` template (already at line 23).
  - Builds a prompt by substituting the per-node responses from `result.responses` (a dict of `node_id → response`) into the template.
  - Calls a synthesis LLM client. **The exact client lookup is an implementation detail** — read how the existing `SynthesisMixin.synthesize(...)` does it (line 34+) and reuse the same pattern (likely via `ctx.synthesis_client` or by inspecting the bound bot's LLM). Mirror that code path to preserve behavior.
  - Returns the summary string.
  - Optionally sets `result.summary = <string>` if `FlowResult` exposes that attribute (verify with `read`).
- The function MUST be safe to call from both:
  - An `on_complete` hook context (where `result` is the final `FlowResult` after `run_flow` aggregation).
  - A DAG-node `execute()` context (where `result` is a partial / in-progress aggregation provided by `SynthesisNode`).
- Export the function from `parrot/bots/flows/core/storage/synthesis.py`. Optionally also re-export from `parrot/bots/flows/core/storage/__init__.py` for convenience (mirror the existing re-exports of `ExecutionMemory`, `PersistenceMixin`, etc.).

**NOT in scope**:
- The `SynthesisNode` Node subclass (TASK-1066).
- Removing `SynthesisMixin` from `parrot/bots/flows/crew/crew.py` (future spec).
- Any prompt-template improvements — reuse the existing `SYNTHESIS_PROMPT` verbatim.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/synthesis.py` | MODIFY | Add `synthesize_results` async function |
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/__init__.py` | MODIFY | Optionally re-export `synthesize_results` |
| `packages/ai-parrot/tests/bots/flows/core/storage/test_synthesis.py` | CREATE or MODIFY | Tests for the new util |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from ..context import FlowContext       # parrot/bots/flows/core/context.py:26 (extended by TASK-1061)
from ..result import FlowResult         # parrot/bots/flows/core/result.py:273
# SYNTHESIS_PROMPT is already at synthesis.py:23 — re-export only if needed.
```

### Existing Signatures (consume — do not modify)

```python
# packages/ai-parrot/src/parrot/bots/flows/core/storage/synthesis.py
SYNTHESIS_PROMPT = """Based on the research findings from our specialist agents above,
..."""   # line 23 — the existing template

class SynthesisMixin:                                                # line 34
    # KEPT in place for AgentCrew.
    # Read its body to understand HOW the synthesis LLM call is made;
    # the new `synthesize_results` util MUST reuse the same pattern
    # so behavior matches.
    async def synthesize(self, results, ...) -> str: ...
    # (exact method name and signature — verify by reading the file)

# packages/ai-parrot/src/parrot/bots/flows/core/result.py
class FlowResult:                                                    # line 273
    # Verify it has: nodes, responses (dict[node_id, response]), errors,
    # status, output. Check whether `summary: str | None` exists; if not,
    # do NOT add it — return the string from `synthesize_results` and let
    # callers attach it themselves.

# packages/ai-parrot/src/parrot/bots/flows/core/context.py:26
class FlowContext:
    # TASK-1061 added agent_registry + resolve_agent.
    # The synthesis LLM client may be attached via a different mechanism
    # (e.g., ctx.bot or ctx.llm or ctx.synthesis_client) — read SynthesisMixin
    # to see what it accesses.
```

### Does NOT Exist (yet)

- ~~`synthesize_results` async function~~ — added by this task.
- ~~`FlowResult.summary` field~~ — possibly does not exist; verify before assuming.

---

## Implementation Notes

### Pattern to Follow

Read `SynthesisMixin.synthesize` (or whatever the existing synthesis method is called) inside `synthesis.py` and mirror its LLM call pattern. The new util should be a top-level async function (not a method) that takes the LLM client / context as parameters instead of `self`:

```python
async def synthesize_results(
    ctx: FlowContext,
    result: FlowResult,
) -> str:
    """LLM-summarize all agent responses in a FlowResult.

    Builds a prompt from SYNTHESIS_PROMPT and the per-node responses
    in `result.responses`, calls the synthesis LLM via the context,
    returns the summary string.

    This util is the single source of truth used by both:
      - `AgentsFlow.run_flow(on_complete=[synthesize_results])` hooks.
      - `SynthesisNode.execute()` for in-graph summarization.
    """
    # 1. Build the prompt from SYNTHESIS_PROMPT + result.responses
    # 2. Look up the synthesis client (mirror SynthesisMixin's lookup)
    # 3. await client.ask(prompt=...) or equivalent
    # 4. Return the summary string
```

### Key Constraints

- Reuse the existing `SYNTHESIS_PROMPT` template verbatim — DO NOT modify the prompt text.
- Mirror `SynthesisMixin`'s LLM-client-access pattern exactly. If `SynthesisMixin.synthesize` accesses `self.llm`, then `synthesize_results` accesses the equivalent attribute on `ctx` (e.g., `ctx.bot.llm` or whatever the existing pattern uses).
- If the lookup needs an attribute that doesn't yet exist on `FlowContext`, add it as an optional attribute (`synthesis_client: Optional[AbstractClient] = None`) in `core/context.py` — but coordinate with TASK-1061's changes to avoid stepping on its work.
- If the synthesis client is None / unavailable, raise a clear error: `RuntimeError("No synthesis client bound on FlowContext")`.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/flows/core/storage/synthesis.py:34` — `SynthesisMixin` (existing pattern).
- `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` — `AgentCrew` consumes `SynthesisMixin`; grep for the call site to see how it triggers synthesis.
- `packages/ai-parrot/src/parrot/bots/flows/core/result.py:273` — `FlowResult` shape (verify field names).

---

## Acceptance Criteria

- [ ] `synthesize_results(ctx: FlowContext, result: FlowResult) -> str` exists in `parrot/bots/flows/core/storage/synthesis.py` and is `async`.
- [ ] The function reuses `SYNTHESIS_PROMPT` (line 23) verbatim — no template duplication.
- [ ] The function returns a non-empty string when given a `FlowResult` with at least one node response and a valid LLM client.
- [ ] The function raises a clear error when no synthesis client is available on the context.
- [ ] `SynthesisMixin` (line 34) is unchanged.
- [ ] If exported from `__init__.py`, `from parrot.bots.flows.core.storage import synthesize_results` works.
- [ ] Unit tests pass: `pytest packages/ai-parrot/tests/bots/flows/core/storage/test_synthesis.py -v`.
- [ ] No linting errors.

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/flows/core/storage/test_synthesis.py
import pytest
from unittest.mock import AsyncMock

from parrot.bots.flows.core.storage.synthesis import (
    SYNTHESIS_PROMPT,
    synthesize_results,
)


class StubResult:
    """Minimal FlowResult-like for testing."""
    responses = {"agent_a": "found data", "agent_b": "analyzed it"}
    errors = {}
    nodes = []
    status = "success"


class StubContext:
    """Minimal FlowContext stub with a synthesis client."""
    def __init__(self, client):
        self.synthesis_client = client  # adjust attribute name to match SynthesisMixin's lookup


class TestSynthesizeResults:
    async def test_returns_string_with_client(self):
        client = AsyncMock()
        client.ask.return_value = type("R", (), {"content": "summary text"})()
        ctx = StubContext(client=client)
        out = await synthesize_results(ctx, StubResult())
        assert isinstance(out, str)
        assert out  # non-empty

    async def test_uses_synthesis_prompt(self):
        client = AsyncMock()
        client.ask.return_value = type("R", (), {"content": "summary"})()
        ctx = StubContext(client=client)
        await synthesize_results(ctx, StubResult())
        # Verify the prompt template was used as the basis
        call_args = client.ask.call_args
        prompt = call_args.kwargs.get("question") or call_args.args[0]
        # Some token of SYNTHESIS_PROMPT should appear in the assembled prompt
        assert "research findings" in prompt.lower() or "specialist" in prompt.lower()

    async def test_raises_without_client(self):
        ctx = StubContext(client=None)
        with pytest.raises((RuntimeError, AttributeError)):
            await synthesize_results(ctx, StubResult())
```

---

## Agent Instructions

1. Confirm TASK-1061 is in `sdd/tasks/completed/` (the new `FlowContext` shape may matter for the client-lookup mechanism).
2. **First action**: read `parrot/bots/flows/core/storage/synthesis.py` end-to-end. Identify EXACTLY how `SynthesisMixin` calls the LLM. This determines the `ctx.<attribute>` your util reads.
3. Read `parrot/bots/flows/crew/crew.py` for the call site where `AgentCrew` invokes synthesis (grep for `synthesize`). Confirm the parameters and return type.
4. Read `parrot/bots/flows/core/result.py:273` for the actual `FlowResult` field names — do not assume `responses` if the field is `node_responses` etc.
5. Implement `synthesize_results` mirroring the mixin's pattern.
6. Run the unit tests; adjust the test stubs if the real client-lookup attribute differs from `synthesis_client`.
7. Move this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-12
**Notes**: synthesize_results() added to synthesis.py. Uses SYNTHESIS_PROMPT verbatim, builds context from result.responses, calls ctx.synthesis_client.ask(question=...). Raises RuntimeError when synthesis_client is None. Sets result.summary if attribute exists. Also added synthesis_client: Optional[Any] = field(default=None) to FlowContext (context.py). Re-exported from storage/__init__.py. 9/9 tests pass.
**Deviations from spec**: synthesis_client added to FlowContext in context.py (permitted by spec's note). Uses question= kwarg to match the real ask() interface pattern.
