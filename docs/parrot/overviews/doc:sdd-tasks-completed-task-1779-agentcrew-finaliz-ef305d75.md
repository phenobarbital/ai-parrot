---
type: Wiki Overview
title: 'TASK-1779: `AgentCrew._finalize_infographic` Integration'
id: doc:sdd-tasks-completed-task-1779-agentcrew-finalize-infographic-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot.bots.flows.crew.crew import AgentCrew # crew.py:93'
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.bots.flows.crew.crew
  rel: mentions
- concept: mod:parrot.bots.flows.crew.result_infographic
  rel: mentions
- concept: mod:parrot.bots.flows.result_agent
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
---

# TASK-1779: `AgentCrew._finalize_infographic` Integration

**Feature**: FEAT-308 — AgentCrew ResultAgent End-of-Flow Multi-Tab Infographic Node
**Spec**: `sdd/specs/agentcrew-node-infographic.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1776, TASK-1777, TASK-1778
**Assigned-to**: unassigned

---

## Context

> Spec §3 Module 4. This is the central integration task. `AgentCrew` gains
> `generate_infographic` and `result_agent_name` init params, a new
> `_finalize_infographic(result)` coroutine, and one call-site in each of the
> four `run_*()` methods — after synthesis but before `_fire_hooks()`. The
> method resolves the `ResultAgent` from `AgentRegistry`, builds the
> deterministic blocks, invokes the ResultAgent to author Tab 1, renders the
> infographic, and populates `result.infographic`. Any exception is
> swallowed, logged, and leaves `infographic=None`.

---

## Scope

- Add `generate_infographic: bool = False` and `result_agent_name: str = "result-agent"` to `AgentCrew.__init__`.
- Implement `async def _finalize_infographic(self, result: FlowResult) -> None`.
- Add one call-site in each of `run_flow`, `run_sequential`, `run_parallel`, `run_loop` — after synthesis, before `_fire_hooks(result)`.
- Exclude the ResultAgent's `node_id` from `execution_memory` and per-agent tabs.
- Graceful degradation: wrap the entire finalize step in try/except, log on failure, leave `result.infographic = None`.
- Write unit tests for the flag-off noop, graceful degradation, and unknown-agent-name paths.

**NOT in scope**: The `crew_report` template (TASK-1775), tab assembly (TASK-1777), `ResultAgent` (TASK-1778), `FlowResult.infographic` field (TASK-1776). Those must be done first.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` | MODIFY | Add init params + `_finalize_infographic` + call-sites |
| `tests/unit/test_agentcrew_infographic.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.crew.crew import AgentCrew             # crew.py:93
from parrot.bots.flows.core.result import FlowResult           # result.py:273
from parrot.registry import agent_registry                     # registry/__init__.py:7
from parrot.bots.flows.crew.result_infographic import (
    build_deterministic_tabs,                                  # TASK-1777
    merge_tab1_blocks,                                         # TASK-1777
)
from parrot.bots.flows.result_agent import ResultAgent         # TASK-1778
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py
class AgentCrew(PersistenceMixin, SynthesisMixin):             # L93
    def __init__(self, name="AgentCrew", agents=None, ...,
                 llm=None, persist_results=True,
                 result_storage=None, **kwargs): ...           # L132
        # self.final_agents: Set[str] = set()                  # L187
        # self.execution_memory = ExecutionMemory(...)         # L194
        # self._llm = llm  (or resolved later)
    async def _fire_hooks(self, result: Any) -> None: ...      # L282
    async def run_sequential(self, ...) -> FlowResult: ...     # L1172
    async def run_loop(self, ...) -> FlowResult: ...           # L1500
    async def run_parallel(self, ...) -> FlowResult: ...       # L1966
    async def run_flow(self, ...) -> FlowResult: ...           # L2289

# packages/ai-parrot/src/parrot/registry/__init__.py
agent_registry = AgentRegistry(...)                            # L7
agent_registry.get(name: str) -> Optional[Type]                # resolve by name
```

### Does NOT Exist
- ~~`AgentCrew.generate_infographic`~~ — does not exist; this task adds it.
- ~~`AgentCrew._finalize_infographic()`~~ — does not exist; this task adds it.
- ~~`AgentCrew.result_agent_name`~~ — does not exist; this task adds it.
- ~~`agent_registry.resolve()`~~ — check exact method name; may be `.get()` or `.get_bot()`.

---

## Implementation Notes

### `_finalize_infographic` Logic
```python
async def _finalize_infographic(self, result: FlowResult) -> None:
    """Populate result.infographic; swallow+log on failure."""
    if not self.generate_infographic:
        return
    try:
        # 1. Resolve ResultAgent from registry
        agent_cls = agent_registry.get(self.result_agent_name)
        if agent_cls is None:
            self.logger.warning("ResultAgent '%s' not found in registry; skipping infographic.", self.result_agent_name)
            return
        # 2. Instantiate with crew's LLM (or default)
        result_agent = agent_cls(name=self.result_agent_name, llm=self._llm)
        # 3. Build deterministic blocks from execution_memory
        det_blocks = build_deterministic_tabs(
            self.execution_memory,
            final_output=result.output,
            exclude_node_id=result_agent.node_id,  # or a known constant
        )
        # 4. ResultAgent authors Tab 1 + renders
        render_result = await result_agent.generate_infographic(
            summary=result.summary,
            deterministic_blocks=det_blocks,
            crew_name=self.name,
        )
        result.infographic = render_result
    except Exception as exc:
        self.logger.error("Infographic generation failed: %s", exc, exc_info=True)
        # result.infographic remains None — crew result intact
```

### Call-Site Pattern
In each `run_*()` method, add AFTER synthesis and BEFORE `_fire_hooks`:
```python
# ... existing synthesis step ...
await self._finalize_infographic(result)
await self._fire_hooks(result)
return result
```

### Key Constraints
- **NEVER alter `result.status`** on infographic failure — only the infographic
  field is affected.
- The try/except wraps the entire finalize block, not individual steps.
- The ResultAgent must NOT be added to `self.execution_memory` or
  `self.final_agents`.
- Four call-sites: `run_flow` (~L2289), `run_sequential` (~L1172),
  `run_parallel` (~L1966), `run_loop` (~L1500). Each needs the same
  one-liner before `_fire_hooks`.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` — all run methods
- Look for the pattern `await self._fire_hooks(result)` to find exact insertion points

---

## Acceptance Criteria

- [ ] `AgentCrew(generate_infographic=False)` → `result.infographic is None`, no ResultAgent resolved
- [ ] `AgentCrew(generate_infographic=True)` → `result.infographic` populated in all four modes
- [ ] Unknown `result_agent_name` → warning logged, skip, no raise
- [ ] Render/LLM exception → logged, `result.infographic is None`, `result.status` unchanged
- [ ] ResultAgent excluded from `execution_memory` and per-agent tabs
- [ ] Existing `AgentCrew` behaviour unchanged when `generate_infographic=False` (default)
- [ ] Unit tests pass: `pytest tests/unit/test_agentcrew_infographic.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`

---

## Test Specification

```python
# tests/unit/test_agentcrew_infographic.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestFinalizeInfographicFlagOff:
    @pytest.mark.asyncio
    async def test_flag_off_is_noop(self):
        """generate_infographic=False → infographic is None, no agent resolved."""
        from parrot.bots.flows.crew.crew import AgentCrew
        crew = AgentCrew(name="test", generate_infographic=False)
        result = MagicMock()
        result.infographic = None
        await crew._finalize_infographic(result)
        assert result.infographic is None


class TestFinalizeGracefulDegrade:
    @pytest.mark.asyncio
    async def test_render_exception_swallowed(self):
        """Render raises → logged, infographic=None, result.status unchanged."""
        from parrot.bots.flows.crew.crew import AgentCrew
        crew = AgentCrew(name="test", generate_infographic=True)
        crew.execution_memory = MagicMock()
        result = MagicMock()
        result.infographic = None
        result.summary = "test summary"
        result.output = "test output"
        original_status = result.status
        with patch("parrot.registry.agent_registry.get", side_effect=RuntimeError("boom")):
            await crew._finalize_infographic(result)
        assert result.infographic is None
        assert result.status == original_status


class TestUnknownAgentName:
    @pytest.mark.asyncio
    async def test_unknown_result_agent_name_skips(self):
        """result_agent_name not in registry → warn + skip."""
        from parrot.bots.flows.crew.crew import AgentCrew
        crew = AgentCrew(name="test", generate_infographic=True, result_agent_name="nonexistent")
        crew.execution_memory = MagicMock()
        result = MagicMock()
        result.infographic = None
        result.summary = ""
        result.output = ""
        with patch("parrot.registry.agent_registry.get", return_value=None):
            await crew._finalize_infographic(result)
        assert result.infographic is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentcrew-node-infographic.spec.md` §3 Module 4
2. **Check dependencies** — TASK-1776 (FlowResult field), TASK-1777 (tab assembly), TASK-1778 (ResultAgent) must be complete
3. **Verify the Codebase Contract** — confirm `_fire_hooks` location in each `run_*()` method; find exact insertion points
4. **Grep for `_fire_hooks`** in `crew.py` to locate all four call-sites
5. **Verify `agent_registry.get()` API** — confirm the method name and return type
6. **Implement** `__init__` params, `_finalize_infographic`, and the four call-sites
7. **Write and run** unit tests
8. **Update status** and move to completed when done

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-14
**Notes**: Added `generate_infographic: bool = False` /
`result_agent_name: str = "result-agent"` to `AgentCrew.__init__`, plus
`_finalize_infographic(result)` (right after `_fire_hooks` in source order)
and one call-site — `await self._finalize_infographic(result)` — inserted
immediately before each of the 4 identical `await self._fire_hooks(result)`
lines (run_sequential ~L1562, run_loop ~L2032, run_parallel ~L2359,
run_flow ~L2600), confirmed via grep before editing. Corrected a critical
stale contract: `agent_registry.get(name)` does not exist on
`AgentRegistry` — the verified lookup API is
`get_metadata(name) -> Optional[BotMetadata]`, `.factory` holding the
class (registry.py:513-514). Used **lazy, function-local imports** for
`parrot.bots.flows.result_agent` (registration side-effect),
`agent_registry`, and `build_deterministic_tabs` inside
`_finalize_infographic` — this both (a) guarantees the built-in
"result-agent" is registered regardless of app load order without a
crew.py-level import of result_agent.py (which would otherwise risk a
subtle circular import: crew.py -> result_agent.py ->
crew.result_infographic, while crew/__init__.py is still mid-executing
its own `from .crew import AgentCrew`), and (b) keeps this opt-in
feature's dependency footprint out of crew.py's module-level import graph.
The whole finalize block is wrapped in one try/except (per spec: never a
partial try per step) so any exception — unknown agent name, LLM failure,
render failure — logs and leaves `result.infographic` at its default
`None`, never touching `result.status`. Corrected the task's own test spec
too: patches now target `agent_registry.get_metadata`. Ran the existing
`tests/test_crew_hooks.py` + `tests/unit/test_agentcrew_from_definition.py`
+ `tests/bots/flows/core/storage/test_agentcrew_lifecycle.py` suites as a
regression check: 38 passed, 4 pre-existing failures confirmed unrelated
(stale `parrot.bots.orchestration` import, a module removed in FEAT-196,
untouched by this task). 6 new unit tests pass, ruff clean.

**Deviations from spec**: none (contract corrections documented above; no
behavioral deviation from Module 4's scope)
