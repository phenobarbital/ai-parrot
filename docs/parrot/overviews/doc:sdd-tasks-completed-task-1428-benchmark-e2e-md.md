---
type: Wiki Overview
title: 'TASK-1428: First benchmarks (DB + Jira) + end-to-end wiring'
id: doc:sdd-tasks-completed-task-1428-benchmark-e2e-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The capstone that proves the whole state-based path end to end (brainstorm
  §13.6). Two benchmark
relates_to:
- concept: mod:parrot.bots.database.agent
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.postgres
  rel: mentions
- concept: mod:parrot.eval
  rel: mentions
- concept: mod:parrot_tools.jiratoolkit
  rel: mentions
---

# TASK-1428: First benchmarks (DB + Jira) + end-to-end wiring

**Feature**: FEAT-217 — Generic Agent Evaluation Harness
**Spec**: `sdd/specs/generic-evaluation-harness.spec.md`
**Spec section**: §3 Module 12, §4 Integration Tests (brainstorm §13.6–§13.7)
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1419, TASK-1420, TASK-1422, TASK-1424, TASK-1425
**Assigned-to**: unassigned

---

## Context

The capstone that proves the whole state-based path end to end (brainstorm §13.6). Two benchmark
datasets + an `AgentFactory` that binds a real toolkit agent to the `InMemoryStateSandbox`, run
through `EvalRunner` + `StateBasedEvaluator`, producing a `pass^k` number.

---

## Scope

- Author benchmark datasets under `packages/ai-parrot/tests/eval/benchmarks/`:
  - `db_crud.jsonl` — DB CRUD tasks (seed_state + goal_state), `kind="in_memory_state"`.
  - `jira_triage.yaml` — Jira triage scenarios with `user_scenario` for `ConversationalRollout`.
- Provide example `AgentFactory` functions (`make_db_agent(sandbox)`, `make_jira_agent(sandbox)`) that
  construct a real `DatabaseAgent` / Jira agent, call `sandbox.bind(toolkit)`, and return the bot.
- Integration tests:
  - `test_db_crud_benchmark_e2e` — `SingleTurnRollout` (or scripted) over `db_crud.jsonl`; assert a
    `pass^k` value is produced and the seeded backend is mutated to the goal state.
  - `test_jira_triage_benchmark_e2e` — `ConversationalRollout` + `LLMUserSimulator` with a MOCK
    client/judge (no real LLM/network); assert `pass^k` produced.
- Use a deterministic/mock LLM where a real model would otherwise be needed, so CI is hermetic.

**NOT in scope**: real-LLM runs, the CI regression gate, Postgres persistence assertions (covered by
TASK-1427's own test).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/eval/benchmarks/db_crud.jsonl` | CREATE | DB CRUD dataset |
| `packages/ai-parrot/tests/eval/benchmarks/jira_triage.yaml` | CREATE | Jira triage dataset |
| `packages/ai-parrot/tests/eval/factories.py` | CREATE | `make_db_agent` / `make_jira_agent` |
| `packages/ai-parrot/tests/eval/test_benchmarks_e2e.py` | CREATE | E2E integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.eval import (EvalRunner, EvalRunConfig, StateBasedEvaluator,
                         InMemoryStateSandboxProvider, DatabaseToolkitBinder, JiraToolkitBinder,
                         JSONLDatasetLoader, YAMLDatasetLoader, SingleTurnRollout,
                         ConversationalRollout, LLMUserSimulator)
from parrot.bots.database.agent import DatabaseAgent             # bots/database/agent.py:114
from parrot.bots.database.toolkits.postgres import PostgresToolkit  # bots/database/toolkits/postgres.py
from parrot_tools.jiratoolkit import JiraToolkit                  # ai-parrot-tools/.../jiratoolkit.py:630
```

### Existing Signatures to Use
```python
# bots/database/agent.py
class DatabaseAgent(BasicAgent):                                  # line 114
    def __init__(self, ..., toolkits: Optional[List[DatabaseToolkit]] = None, ...): ...  # line 138
    self.toolkits: List[DatabaseToolkit] = toolkits or []         # line 150
# Sandbox binding entrypoint (from TASK-1419):
# InMemoryStateSandbox.bind(toolkit) -> delegates to the configured ToolkitBinder
```

### Does NOT Exist
- ~~A ready-made eval benchmark in the repo~~ — author the two datasets here.
- ~~Real Jira/DB test servers in CI~~ — bind to the in-memory backend; mock the LLM client.

---

## Implementation Notes

### Key Constraints
- Tests must be hermetic: no real DB, no real Jira, no real LLM. Bind toolkits to the in-memory
  backend; inject a mock/deterministic `AbstractClient` for the agent and the user simulator.
- `AgentFactory` signature is `Callable[[Sandbox], Awaitable[AbstractBot]]` — bind inside it.
- Assert the headline metric is `pass^k` and that the final backend snapshot matches the goal state.

### References in Codebase
- Brainstorm §13.6 — the exact end-to-end assembly snippet.
- `parrot/bots/database/agent.py` — agent construction with `toolkits=`.

---

## Acceptance Criteria

- [ ] `db_crud` benchmark runs end-to-end via `EvalRunner` + `StateBasedEvaluator` and yields a
      `pass^k` number; the bound backend reaches the goal state.
- [ ] `jira_triage` benchmark runs end-to-end with `ConversationalRollout` + mock `LLMUserSimulator`
      and yields a `pass^k` number.
- [ ] No real network/DB/LLM calls in CI (hermetic).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/eval/test_benchmarks_e2e.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/tests/eval/factories.py`

---

## Test Specification

```python
import pytest
from parrot.eval import (EvalRunner, EvalRunConfig, StateBasedEvaluator,
                         InMemoryStateSandboxProvider, DatabaseToolkitBinder, JSONLDatasetLoader,
                         SingleTurnRollout)

async def test_db_crud_benchmark_e2e():
    ds = await JSONLDatasetLoader().load("packages/ai-parrot/tests/eval/benchmarks/db_crud.jsonl")
    report = await EvalRunner(
        dataset=ds, agent_factory=make_db_agent, rollout=SingleTurnRollout(),
        evaluator=StateBasedEvaluator(),
        sandbox_provider=InMemoryStateSandboxProvider(binder=DatabaseToolkitBinder()),
        config=EvalRunConfig(k=2, max_concurrency=4),
    ).run()
    assert report.pass_k is not None
```

---

## Agent Instructions

Standard SDD flow: verify the contract, set index `in-progress`, implement (datasets + factories +
tests), run tests + ruff, move to `completed/`, set index `done`, fill the note. This task closes the
feature — confirm the spec §5 acceptance criteria are satisfied end to end.

---

## Completion Note

*(Agent fills this in when done)*
