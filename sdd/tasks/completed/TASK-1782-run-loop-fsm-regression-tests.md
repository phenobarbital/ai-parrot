# TASK-1782: Regression Tests for `run_loop()` FSM Reset

**Feature**: FEAT-309 — Fix `AgentCrew.run_loop()` Frozen-FSM Reassignment Bug
**Spec**: `sdd/specs/agentcrew-run-loop-frozen-fsm-fix.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1781
**Assigned-to**: unassigned

---

## Context

> Spec §3 Module 2 / §4 Test Specification. With TASK-1781's one-line fix
> in place, this task adds regression coverage proving `run_loop()` no
> longer raises `pydantic_core.ValidationError` across 0/1/many agents and
> multiple iterations, and that each iteration's FSM genuinely starts
> fresh (no state leakage from a prior iteration). Also includes a
> regression guard confirming `run_flow`/`run_sequential`/`run_parallel`
> remain unaffected (they don't touch this code path at all).

---

## Scope

- Create `tests/unit/test_run_loop_fsm_reset.py` with:
  - `test_run_loop_single_agent_single_iteration` — 1 agent, `max_iterations=1`
    completes without `ValidationError`.
  - `test_run_loop_multiple_agents_multiple_iterations` — 3 agents,
    `max_iterations=3` completes without error across all iterations.
  - `test_run_loop_fsm_is_fresh_each_iteration` — after iteration 1, a
    node's FSM reaches a final/terminal state (`completed`/`failed`);
    after iteration 2's reset, the *same node_id*'s FSM object is a
    genuinely new instance starting at `idle` (not the same object,
    not carrying over state).
  - `test_run_flow_sequential_parallel_unaffected` — smoke-level regression
    guard: `run_flow`/`run_sequential`/`run_parallel` still work
    (byte-for-byte unaffected by this fix, since none of them touch the
    per-iteration FSM-reset code path).

**NOT in scope**: Modifying `crew.py` further (that was TASK-1781's job —
if the fix isn't already in place when this task starts, STOP and verify
TASK-1781 is actually complete first). Flipping FEAT-308's
`test_run_loop_generates_infographic` xfail back to a real assertion —
optional polish per the spec's Open Questions, not required for this
task's acceptance criteria (may be done as a follow-up if time permits,
but do not treat it as blocking).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/unit/test_run_loop_fsm_reset.py` | CREATE | Regression tests for `run_loop()`'s FSM reset fix |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, class names, and method signatures.
> Verified against `packages/ai-parrot/src/parrot/` on 2026-07-14.

### Verified Imports
```python
from parrot.bots.flows.crew.crew import AgentCrew                # crew.py:93 (approx)
from parrot.bots.flows.core.fsm import AgentTaskMachine           # fsm.py:40
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py
async def run_loop(
    self,
    initial_task: str,
    condition: str,
    max_iterations: int = 2,
    user_id: str = None,
    session_id: str = None,
    agent_sequence: Optional[List[str]] = None,
    pass_full_context: bool = True,
    generate_summary: bool = True,
    synthesis_prompt: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 8192,
    temperature: float = 0.1,
    **kwargs
) -> FlowResult: ...                                              # ~L1722
    # `condition` is REQUIRED (no default) — natural-language description
    # of the stop condition. With a mocked/fake LLM that never returns
    # "yes"/"stop", the loop simply runs for `max_iterations` iterations
    # without ever short-circuiting — deterministic and safe for tests.

# self.workflow_graph: Dict[str, CrewAgentNode] — populated by add_agent()
#   in __init__ (crew.py, when `agents=[...]` is passed to the constructor).
# Each CrewAgentNode's `.fsm` is an AgentTaskMachine instance (or None
#   before model_post_init runs — but it's never None after construction).

# packages/ai-parrot/src/parrot/bots/flows/core/fsm.py
class AgentTaskMachine(StateMachine):                             # L40
    idle = State("idle", initial=True)                            # L67
    completed = State("completed", final=True)                    # L70
    failed = State("failed")                                      # L71
    def __init__(self, agent_name: str, **kwargs: object) -> None: ...  # L84
    # .current_state is inherited from python-statemachine's StateMachine
    # base class — use `str(fsm.current_state.id)` to compare state names
    # (this exact pattern is already used in
    # packages/ai-parrot/tests/test_crew_sequential_regression.py, e.g.
    # `str(node1.fsm.current_state.id) == "completed"`).
```

### Stub-Agent Test Infrastructure (reference, do not duplicate if avoidable)
```python
# packages/ai-parrot/tests/_crew_test_helpers.py provides `DummyAgent` /
# `DummyToolManager` — minimal stand-ins compatible with
# `AgentCrew.add_agent()` (implements `.tool_manager`, `.add_event_listener`,
# `EVENT_*` constants, async `.ask()`). This file lives OUTSIDE the
# top-level `tests/` tree (it's under `packages/ai-parrot/tests/`), so it
# is NOT importable from `tests/unit/test_run_loop_fsm_reset.py` without
# sys.path tricks.
#
# A near-identical `DummyAgent` was ALSO added at
# `tests/integration/conftest.py` (FEAT-308, TASK-1780) — THAT one IS
# importable from `tests/unit/` (same top-level `tests/` tree). Prefer
# reusing it via:
#   from tests.integration.conftest import DummyAgent
# and verify this import actually resolves before relying on it (the
# top-level `tests/` root conftest.py — see `conftest.py` at repo root —
# manipulates sys.path for the worktree; confirm `tests.integration` is
# importable as a package, i.e. `tests/integration/__init__.py` exists).
# If the import doesn't resolve cleanly, fall back to defining an
# equivalent minimal `DummyAgent` inline in this test file (see
# `tests/integration/conftest.py`'s `DummyAgent` for the exact shape to
# copy — do not invent a different interface).
```

### Does NOT Exist
- ~~`AgentTaskMachine.reset()`~~ — no such method.
- ~~`AgentCrew.run_loop(agents=...)`~~ — agents are registered via the
  constructor's `agents=` param or `add_agent()`, not passed to `run_loop()`
  itself.
- ~~A shared top-level `tests/conftest.py` `DummyAgent` fixture~~ — as of
  2026-07-14, the only importable-from-top-level-tests `DummyAgent` is the
  one in `tests/integration/conftest.py` (FEAT-308). Verify this is still
  true before assuming it; if a shared one has since been added elsewhere,
  prefer that instead.

---

## Implementation Notes

### Pattern to Follow
```python
"""tests/unit/test_run_loop_fsm_reset.py"""
import pytest
from parrot.bots.flows.crew.crew import AgentCrew

# Prefer importing DummyAgent from tests.integration.conftest if it
# resolves; otherwise define an equivalent minimal stub inline (see
# Codebase Contract above for the exact shape).


@pytest.mark.asyncio
async def test_run_loop_single_agent_single_iteration():
    agent = DummyAgent("researcher", response="ok")
    crew = AgentCrew(name="test-crew", agents=[agent], auto_configure=False)
    result = await crew.run_loop(
        "start", condition="never true", max_iterations=1, generate_summary=False,
    )
    assert result.status in ("completed", "partial", "failed")  # no exception raised


@pytest.mark.asyncio
async def test_run_loop_multiple_agents_multiple_iterations():
    agents = [DummyAgent(f"agent-{i}", response=f"ok-{i}") for i in range(3)]
    crew = AgentCrew(name="test-crew", agents=agents, auto_configure=False)
    result = await crew.run_loop(
        "start", condition="never true", max_iterations=3, generate_summary=False,
    )
    assert result is not None


@pytest.mark.asyncio
async def test_run_loop_fsm_is_fresh_each_iteration():
    agent = DummyAgent("researcher", response="ok")
    crew = AgentCrew(name="test-crew", agents=[agent], auto_configure=False)
    node = crew.workflow_graph["researcher"]
    fsm_before = node.fsm
    await crew.run_loop(
        "start", condition="never true", max_iterations=2, generate_summary=False,
    )
    # After 2 iterations, the node's fsm has been replaced at least once and
    # is a *different object* from the one captured before the run.
    node_after = crew.workflow_graph["researcher"]
    assert node_after.fsm is not fsm_before
```

### Key Constraints
- Use `pytest.mark.asyncio` for all async tests (matches `asyncio_mode = auto`
  in `pytest.ini` — explicit marker is optional but keep it for clarity,
  matching the convention already used in `tests/unit/test_agentcrew_infographic.py`).
- Keep `condition` a natural-language string that will never plausibly be
  interpreted as "yes"/"stop" by the loop's condition-check logic (e.g.
  `"never true"`) — with a crew constructed without a real/mocked `llm=`,
  `_evaluate_loop_condition()` catches any LLM failure internally and
  returns `False`, so the loop simply runs for the full `max_iterations`
  deterministically. No LLM mocking is required for these tests, but if
  `AgentCrew()` is constructed with no `llm=`, it WILL construct a real
  `GoogleGenAIClient()` internally (existing crew.py behavior, unrelated to
  this fix) — prefer passing a lightweight mock `llm=` (e.g.
  `MagicMock(spec=AbstractClient)`) to keep the test hermetic and fast,
  following the pattern in `tests/integration/conftest.py`'s `fake_llm`
  fixture (FEAT-308).
- Do not assert exact FSM state *names* beyond what's needed — focus
  assertions on "no exception raised" and "fsm object identity changes
  across iterations", which are the two things this bug fix actually
  guarantees.

### References in Codebase
- `packages/ai-parrot/tests/test_crew_sequential_regression.py` — existing
  pattern for asserting `str(node.fsm.current_state.id) == "completed"`.
- `tests/integration/conftest.py` (FEAT-308) — `DummyAgent`/`fake_llm`
  fixture patterns to reuse or mirror.

---

## Acceptance Criteria

- [ ] `test_run_loop_single_agent_single_iteration` passes.
- [ ] `test_run_loop_multiple_agents_multiple_iterations` passes.
- [ ] `test_run_loop_fsm_is_fresh_each_iteration` passes and genuinely
  proves object-identity change across iterations (not just "no exception").
- [ ] `test_run_flow_sequential_parallel_unaffected` passes, confirming no
  regression to the other three execution modes.
- [ ] All tests pass: `pytest tests/unit/test_run_loop_fsm_reset.py -v`
- [ ] No linting errors: `ruff check tests/unit/test_run_loop_fsm_reset.py`
- [ ] Existing regression suites for `run_flow`/`run_sequential`/`run_parallel`
  (`packages/ai-parrot/tests/test_crew_flow_regression.py`,
  `test_crew_sequential_regression.py`, `test_crew_parallel_regression.py`)
  still pass unmodified.

---

## Test Specification

```python
# tests/unit/test_run_loop_fsm_reset.py
# See "Pattern to Follow" above for the four required test functions.
# Add DummyAgent import/definition and a fake_llm fixture per the
# Codebase Contract and Key Constraints sections.
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentcrew-run-loop-frozen-fsm-fix.spec.md` §3 Module 2 / §4
2. **Check dependencies** — TASK-1781 must be complete (the one-line fix
   must already be in `crew.py`); verify by reading the current
   `run_loop()` FSM-reset block before writing any tests
3. **Verify the Codebase Contract** — confirm `DummyAgent` availability at
   `tests/integration/conftest.py`, confirm `run_loop()`'s exact signature
4. **Implement** the four test functions
5. **Run** the new tests AND the existing `run_flow`/`run_sequential`/
   `run_parallel` regression suites as a sanity check
6. **Update status** and move to completed when done

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
