# TASK-4726: RoostToolkit origin tools and the AgentTool query path (M11c)

**Feature**: FEAT-747 — Roost — local inter-agent sub-protocol over Squawk
**Spec**: `sdd/specs/local-inter-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4725
**Assigned-to**: unassigned

---

## Context

Implements the LLM-facing half of spec §3 **Module 11**. The LLM never emits a performative as text: it calls a
tool and the harness maps it to the act (spec L3, AC-3) — `report` → inform, `call_for_proposals` → cfp (never
`delegate`, FEAT-590 owns that word), `watch` → subscribe, `send` with a four-value enum, `find_agents` for a
directory lookup. The grant is never a tool parameter. `AgentTool._execute` issues a `query` through the caller's
endpoint when the target agent is Roost-enabled, stores the native answer in WorkingMemory and returns a pointer
string (the `-> str` contract is kept, AC-28).

---

## Scope

- Create `parrot/roost/toolkit.py` with `RoostToolkit(AbstractToolkit)`.
- Modify `AgentTool._execute` to take the Roost path after the empty-question guard.
- Write `tests/roost/test_toolkit.py` and `tests/roost/test_agent_tool_roost.py`.

**NOT in scope**: mounting remote capability tools (FEAT-746 catalog tools via the bridge); Matrix `ask_agent` (TASK-4728)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/toolkit.py` | CREATE | RoostToolkit |
| `packages/ai-parrot/src/parrot/tools/agent.py` | MODIFY | Roost query path in `_execute` |
| `packages/ai-parrot/tests/roost/test_toolkit.py` | CREATE | Toolkit tests |
| `packages/ai-parrot/tests/roost/test_agent_tool_roost.py` | CREATE | AgentTool Roost path + legacy path unchanged |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `6cbd94131` (2026-10-26). Use these exact imports and
> signatures. Do NOT invent any import, attribute or method not listed here — verify first.

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit          # verified: parrot/tools/__init__.py:151
from parrot.tools.agent import AgentTool                  # verified: tools/agent.py:52
from parrot.roost.endpoint import RoostEndpoint, RoostFailure   # TASK-4725
from parrot.roost.messages import AgentAddress
from parrot.roost.performatives import Performative
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/agent.py   (has `from __future__ import annotations`)
class AgentTool(AbstractTool):                            # line 52
    def __init__(self, agent: "AbstractBot", tool_name=None, tool_description=None, use_conversation_method=True,
                 context_filter=None, execution_memory=None, **kwargs)   # line 64; self.agent = agent (74)
    async def _execute(self, **kwargs) -> str:            # line 157
        # ...  question = kwargs.pop('question', '') ...
        if not question:
            return "Error: No question provided to agent tool"   # anchor, occurrences 1
# AbstractToolkit: public async methods become LLM tools; docstrings are the tool descriptions (CONTEXT.md)
# parrot/roost/endpoint.py (TASK-4725)
class RoostEndpoint:
    async def send(self, performative, *, receivers=(), capability_filter=None, content=None, protocol=None, ...) -> RoostMessage
    async def query(self, question, *, receiver: AgentAddress, timeout=None, expected_schema=None) -> Any
    async def cfp(self, *, capability_filter: str, task: Any, bid_window_ms: int = 500, scorer=None) -> Award
    async def subscribe(self, *, blackboard_key=None, capability_filter=None, handler=None) -> str
    registry: Optional[AgentRegistry]; working_memory: Optional[WorkingMemoryToolkit]
```

### Does NOT Exist
- ~~`AbstractBot.roost_endpoint` — not an attribute today; read it with `getattr(bot, 'roost_endpoint', None)`~~
- ~~a `delegate` tool — FEAT-590 vocabulary; forbidden name (AC-29)~~
- ~~a `performative` free-text parameter or any grant/scope parameter in tool schemas (AC-3, AC-12)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/roost/toolkit.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/tools/agent.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/roost/test_toolkit.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/roost/test_agent_tool_roost.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/agent.py#AgentTool",
    "sym:packages/ai-parrot/src/parrot/tools/agent.py#AgentTool._execute"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Toolkit methods return small dicts (`{'status': ..., 'conversation_id': ...}`) — the native result of a query/request goes to WorkingMemory, not into the LLM context.
- `send(performative=...)` uses `Literal['inform','request','query','subscribe']` so the schema is an enum.
- AgentTool Roost path: `ep = getattr(self.agent, 'roost_endpoint', None)` is the TARGET's endpoint (its address); the CALLER endpoint is `kwargs.pop('_roost_caller', None) or getattr(self, 'roost_caller', None)`; take the path only when both exist; on `RoostFailure` return `f"Error: {exc}"`; on success store via the caller's `working_memory.store_result` and return `f"Answer stored in working memory as '{key}'"`.
- Legacy behaviour when either endpoint is missing must be byte-for-byte unchanged (`tests/test_agent_tool_ai_message.py` green).
- Async-first; Pydantic v2 models; `self.logger` / module `logger`, never `print`; Google docstrings; type hints everywhere; 120-column lines.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/working_memory/tool.py:374` — `store_result` signature

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Never change a signature, class name or file
> path the blueprint fixes (they come from the spec's §3 Interface Skeletons).

### Steps (in order)
1. Write `toolkit.py`.
2. Insert the AgentTool block after the empty-question guard.
3. Tests: tool schema has no grant/performative-text params; report sends inform and returns immediately; AgentTool Roost path vs legacy path.

### `packages/ai-parrot/src/parrot/roost/toolkit.py` (CREATE)
```python
"""LLM-facing Roost origin tools (FEAT-747 M11). The harness maps each tool to a Performative."""
from __future__ import annotations

from typing import Any, Literal, Optional

from parrot.tools.toolkit import AbstractToolkit  # verified: parrot/tools/__init__.py:151

from .endpoint import RoostEndpoint, RoostFailure
from .messages import AgentAddress
from .performatives import Performative


class RoostToolkit(AbstractToolkit):
    """Talk to other agents of this trust domain. Never exposes the inter-agent grant."""

    def __init__(self, endpoint: RoostEndpoint, **kwargs: Any) -> None:
        self._endpoint = endpoint
        super().__init__(**kwargs)

    async def send(self, performative: Literal["inform", "request", "query", "subscribe"], receiver: str,
                   content: str, body: Optional[str] = None) -> dict:
        """Send a message to another agent when no more specific tool fits."""
        raise NotImplementedError  # FILL IN

    async def report(self, receiver: str, fact: str) -> dict:
        """Tell another agent a fact or result. Fire-and-forget: no reply is expected or awaited."""
        raise NotImplementedError  # FILL IN

    async def call_for_proposals(self, capability_filter: str, task: str, bid_window_ms: int = 500) -> dict:
        """Ask every agent advertising a capability to bid on a task; returns the award (winner, decided_by)."""
        raise NotImplementedError  # FILL IN

    async def watch(self, key: str) -> dict:
        """Subscribe to a shared blackboard key; changes arrive as notifications."""
        raise NotImplementedError  # FILL IN

    async def find_agents(self, query: str) -> list[dict]:
        """Find agents that can answer by capability or keyword (no LLM involved)."""
        raise NotImplementedError  # FILL IN — registry.find_capability(query, caller=endpoint.agent_name)
```
**Why**: Docstrings ARE the LLM tool descriptions — keep them short and behavioural; method names are spec-fixed.

### `packages/ai-parrot/src/parrot/tools/agent.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            return "Error: No question provided to agent tool"' tools/agent.py)
# AFTER — insert below `            return "Error: No question provided to agent tool"` (verified: tools/agent.py:177)

        # FEAT-747: Roost query path — only when both caller and target endpoints exist
        roost_caller = kwargs.pop("_roost_caller", None) or getattr(self, "roost_caller", None)
        roost_target = getattr(self.agent, "roost_endpoint", None)
        if roost_caller is not None and roost_target is not None:
            return await self._execute_roost(roost_caller, roost_target, question)
```
**Why**: Additive and guarded: without both endpoints nothing changes. Add `async def _execute_roost(self, caller, target, question) -> str` as a new method right after `_execute` (FILL IN its body per Key Constraints 3).

### FILL IN checklist
- [ ] toolkit method bodies
- [ ] `AgentTool._execute_roost`
- [ ] tests

---

## Acceptance Criteria

- [ ] No RoostToolkit schema contains a grant/scope parameter or a free-text performative (AC-3)
- [ ] `report` returns without awaiting a reply
- [ ] `call_for_proposals` is the cfp tool; no `delegate*` symbol added
- [ ] AgentTool with both endpoints returns the pointer string and stores the native answer; without them the legacy path is unchanged
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/roost/toolkit.py packages/ai-parrot/src/parrot/tools/agent.py packages/ai-parrot/tests/roost/test_toolkit.py packages/ai-parrot/tests/roost/test_agent_tool_roost.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree prefix with
> `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`.

- `pytest packages/ai-parrot/tests/roost/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/roost/test_agent_tool_roost.py -q`
- `pytest packages/ai-parrot/tests/test_agent_tool_ai_message.py -q`

---

## Test Specification

```python
from unittest.mock import AsyncMock, MagicMock

from parrot.roost.toolkit import RoostToolkit


def test_schemas_have_no_grant():
    tk = RoostToolkit(MagicMock())
    for t in tk.get_tools():
        props = str(t.get_schema())
        assert "grant" not in props and "scope" not in props


async def test_report_is_fire_and_forget():
    ep = MagicMock(); ep.send = AsyncMock(return_value=MagicMock(conversation_id="c"))
    out = await RoostToolkit(ep).report("b", "salary is 100")
    assert out["status"] == "sent"
    assert ep.send.await_args.args[0].value == "inform"
# FILL IN: AgentTool roost path (both endpoints) vs legacy path (stub agent) in test_agent_tool_roost.py
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug local-inter-agent --feature-id FEAT-747 --spec sdd/specs/local-inter-agent.spec.md --index sdd/tasks/index/local-inter-agent.json`)
2. **Read the spec** at `sdd/specs/local-inter-agent.spec.md` (§2 Data Models and the §3 module this task implements)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/local-inter-agent.json`
4. **Verify the Codebase Contract** — re-run `grep -c` on every MODIFY anchor before editing; a count that
   differs means the anchor moved, `0` means stop and report
5. **Update status** in the index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:`, never rename
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4726 local-inter-agent verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (FEAT-747 execution 0b6f3a52)
**Date**: 2026-10-26
**Notes**: Delivered by engine; merge-tier green.
Seat: gpt-5.6-sol (codex) · Attempts: 1

**Deviations from spec**: none
