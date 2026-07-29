---
type: Wiki Overview
title: 'TASK-1780: End-to-End Integration Tests for Crew Infographic'
id: doc:sdd-tasks-completed-task-1780-infographic-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot.bots.flows.crew.crew import AgentCrew # crew.py:93'
relates_to:
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.memory
  rel: mentions
- concept: mod:parrot.bots.flows.crew.crew
  rel: mentions
- concept: mod:parrot.bots.flows.result_agent
  rel: mentions
- concept: mod:parrot.storage.backends
  rel: mentions
- concept: mod:parrot.tools.infographic_toolkit
  rel: mentions
---

# TASK-1780: End-to-End Integration Tests for Crew Infographic

**Feature**: FEAT-308 — AgentCrew ResultAgent End-of-Flow Multi-Tab Infographic Node
**Spec**: `sdd/specs/agentcrew-node-infographic.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1779
**Assigned-to**: unassigned

---

## Context

> Spec §4 Integration Tests. With all modules integrated (TASK-1775–1779),
> this task verifies the complete flow: a multi-agent `AgentCrew` with
> `generate_infographic=True` runs end-to-end and produces a populated
> `result.infographic` with the correct tab structure. Tests cover
> `run_flow`, `run_sequential`, `run_parallel`, and `run_loop`, plus
> verification that Tab 1 uses the crew's existing synthesis output.

---

## Scope

- Write integration tests per the spec's §4 Integration Tests table:
  - `test_run_flow_generates_infographic` — 3-agent DAG → infographic with correct tabs.
  - `test_all_modes_generate_infographic` — parametrized over all four modes.
  - `test_insights_tab_uses_synthesis` — Tab 1 seeded from `result.summary`.
- Create shared fixtures: `crew_with_infographic`, `fake_llm`.
- Add documentation note for AgentCrew infographic usage.

**NOT in scope**: Fixing any issues found — file bugs if tests fail.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/integration/test_crew_infographic_e2e.py` | CREATE | Integration tests |
| `tests/integration/conftest.py` | MODIFY | Add shared fixtures (if not already present) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.crew.crew import AgentCrew              # crew.py:93
from parrot.bots.flows.core.result import FlowResult            # result.py:273
from parrot.tools.infographic_toolkit import InfographicRenderResult  # infographic_toolkit.py:91
from parrot.bots.flows.core.storage.memory import ExecutionMemory     # memory.py:19
from parrot.bots.flows.core.result import NodeResult            # result.py:39
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py
class AgentCrew(PersistenceMixin, SynthesisMixin):              # L93
    def __init__(self, ..., generate_infographic=False,
                 result_agent_name="result-agent", ...): ...
    async def run_flow(self, ...) -> FlowResult: ...            # L2289
    async def run_sequential(self, ...) -> FlowResult: ...      # L1172
    async def run_parallel(self, ...) -> FlowResult: ...        # L1966
    async def run_loop(self, ...) -> FlowResult: ...            # L1500

# FlowResult — with new infographic field (TASK-1776)
@dataclass
class FlowResult:
    output: Any
    # ...
    infographic: Optional[InfographicRenderResult] = None
```

### Does NOT Exist
- ~~`AgentCrew.render_infographic()`~~ — no such method; infographic is generated internally by `_finalize_infographic`.
- ~~`FlowResult.get_tab_count()`~~ — no such method; inspect `infographic` object directly.

---

## Implementation Notes

### Fixture Strategy
```python
@pytest.fixture
def fake_llm():
    """Deterministic AbstractClient stub returning canned Tab-1 blocks."""
    # Mock client whose .ask() / .completion() returns a fixed string
    # representing the Executive Summary tab content
    ...

@pytest.fixture
def crew_with_infographic(fake_llm):
    """3 stub agents + crew(generate_infographic=True, llm=fake_llm)."""
    # Create 3 lightweight agents that return short text
    # Build AgentCrew with generate_infographic=True
    ...
```

### Key Constraints
- Integration tests should use mocked LLM clients (no real API calls).
- Stub agents should return deterministic, small text results.
- Tests must verify tab structure (count, labels, content presence),
  not exact HTML output.
- Use `pytest.mark.asyncio` for all async tests.
- Mark integration tests with `@pytest.mark.integration` if that convention exists.

### References in Codebase
- Existing integration tests in `tests/integration/` for patterns
- `tests/conftest.py` for shared fixtures

---

## Acceptance Criteria

- [ ] `test_run_flow_generates_infographic` passes — 3-agent DAG produces infographic with Exec Summary + Final Result + 3 agent tabs
- [ ] `test_all_modes_generate_infographic` passes — all four modes produce a populated `result.infographic`
- [ ] `test_insights_tab_uses_synthesis` passes — Tab 1 content is seeded from `result.summary`
- [ ] No real API calls in tests (all LLM interactions mocked)
- [ ] All integration tests pass: `pytest tests/integration/test_crew_infographic_e2e.py -v`
- [ ] No linting errors: `ruff check tests/integration/test_crew_infographic_e2e.py`

---

## Test Specification

```python
# tests/integration/test_crew_infographic_e2e.py
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def fake_llm():
    llm = AsyncMock()
    llm.completion.return_value = "Executive Summary: All agents completed successfully."
    return llm


@pytest.fixture
def stub_agents():
    """3 stub agents returning short text results."""
    agents = []
    for i in range(3):
        agent = MagicMock()
        agent.name = f"researcher-{i}"
        agent.node_id = f"researcher-{i}"
        agents.append(agent)
    return agents


class TestRunFlowGeneratesInfographic:
    @pytest.mark.asyncio
    async def test_run_flow_infographic_populated(self, stub_agents, fake_llm):
        """3-agent DAG with generate_infographic=True → infographic populated."""
        from parrot.bots.flows.crew.crew import AgentCrew
        crew = AgentCrew(
            name="test-crew", agents=stub_agents,
            generate_infographic=True, llm=fake_llm,
        )
        result = await crew.run_flow(prompt="test query")
        assert result.infographic is not None
        assert result.infographic.template_name == "crew_report"


class TestAllModesGenerateInfographic:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["run_sequential", "run_parallel", "run_loop"])
    async def test_mode_generates_infographic(self, mode, stub_agents, fake_llm):
        """Each mode yields a populated result.infographic."""
        from parrot.bots.flows.crew.crew import AgentCrew
        crew = AgentCrew(
            name="test-crew", agents=stub_agents,
            generate_infographic=True, llm=fake_llm,
        )
        method = getattr(crew, mode)
        result = await method(prompt="test query")
        assert result.infographic is not None


class TestInsightsTabUsesSynthesis:
    @pytest.mark.asyncio
    async def test_tab1_seeded_from_summary(self, stub_agents, fake_llm):
        """Tab 1 content is seeded from the crew's summary, not a second synthesis."""
        from parrot.bots.flows.crew.crew import AgentCrew
        crew = AgentCrew(
            name="test-crew", agents=stub_agents,
            generate_infographic=True, llm=fake_llm,
        )
        result = await crew.run_sequential(prompt="test query")
        assert result.infographic is not None
        # The Tab-1 content should reflect the summary
        # (exact assertion depends on how the blocks encode tab content)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentcrew-node-infographic.spec.md` §4 Integration Tests
2. **Check dependencies** — ALL prior tasks (TASK-1775–1779) must be complete
3. **Examine existing integration tests** in `tests/integration/` for fixture and assertion patterns
4. **Build minimal fixtures** — no real LLM calls; stub agents returning short text
5. **Run integration tests** and verify all pass
6. **Update status** and move to completed when done

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-14
**Notes**: Created `tests/integration/conftest.py` (`DummyAgent`/
`_DummyToolManager` — modeled after
`packages/ai-parrot/tests/_crew_test_helpers.DummyAgent`, not importable
from this top-level tree — plus `stub_agents`/`fake_llm` fixtures) and
`tests/integration/test_crew_infographic_e2e.py`. Corrected the task's own
Test Specification: plain `MagicMock()` stub agents with only
`.name`/`.node_id` are insufficient for `AgentCrew.add_agent()` (needs
`.tool_manager`, `.add_event_listener`, `EVENT_*` constants); built a full
`DummyAgent`. `fake_llm` is a `MagicMock(spec=AbstractClient)` with
`__aenter__`/`__aexit__`/`ask` wired so `SynthesisMixin._synthesize_results`'s
`async with self._llm as client:` pattern works without any real API call.
Two module-scoped (not conftest-level) autouse fixtures keep the suite
hermetic: `_stub_artifact_backend` (patches
`parrot.storage.backends.build_conversation_backend`/`build_overflow_store`
and `parrot.bots.flows.result_agent.ArtifactStore` so `_LazyArtifactStore`
never touches a real DB/filesystem) and `_stub_result_agent_llm` (patches
`ResultAgent.ask` at the class level so Tab-1 authoring bypasses the real
`BaseBot.ask()` stack — out of scope for this integration test).

**Found and documented a genuine pre-existing bug, out of FEAT-308 scope**:
`AgentCrew.run_loop()`'s per-iteration FSM reset
(`node.fsm = AgentTaskMachine(...)`, crew.py, introduced by TASK-1062's
migration to a frozen `CrewAgentNode` Pydantic model) raises
`pydantic_core.ValidationError: Instance is frozen` on every invocation —
the codebase already has an `object.__setattr__` escape hatch for
frozen-node mutation elsewhere (`flows/core/node.py:227`) that this code
path doesn't use. Confirmed via `git diff dev` that this line is untouched
by FEAT-308. Marked `test_run_loop_generates_infographic` as
`xfail(strict=True, reason=...)` documenting the root cause, rather than
fixing crew.py's unrelated loop internals (not listed in any FEAT-308
task's file list) — flagging for a follow-up bug-fix spec.

Result: 5 passed, 1 xfailed. Verified no regressions to sibling
`tests/integration/*.py` files (ran the full directory minus the
pre-existing-broken `oauth2/` package and `test_invoke.py`'s 59
pre-existing, unrelated `AbstractClient.client`-setter errors — both
confirmed via `git diff dev` to be untouched by this feature). ruff clean.

The AC's "Documentation updated (AgentCrew infographic usage note)" is
satisfied by this test file's detailed module docstring (usage + hermetic
testing rationale); a dedicated docs/ page was not in this task's Files
list and is left as a follow-up if the user wants user-facing docs.

**Deviations from spec**: none in implemented code; one integration
scenario (run_loop) is xfailed due to a pre-existing, unrelated bug — see
above. Recommend filing a follow-up spec/task for the `run_loop` FSM-reset
fix.
