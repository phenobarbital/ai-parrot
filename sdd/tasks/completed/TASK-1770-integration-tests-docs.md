# TASK-1770: End-to-end integration tests + documentation

**Feature**: FEAT-306 — Crew Per-Agent Result Persistence & Deterministic Execution Document
**Spec**: `sdd/specs/crew-per-agent-result-persistence.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1765, TASK-1766, TASK-1767, TASK-1768, TASK-1769
**Assigned-to**: unassigned

---

## Context

Implements **Module 6** of FEAT-306. All building blocks exist after TASK-1769; this task
proves the full loop — run a crew → incremental per-agent writes + consolidated write →
`fetch()` by execution_id → `from_storage()` reconstruction equals `from_memory()` — and
documents the feature for users.

---

## Scope

- Extend `tests/bots/flows/core/storage/test_integration.py` with the FEAT-306 e2e scenarios
  (see Test Specification). Use a fake in-memory `ResultStorage` implementing `save` + `fetch`
  — NO external DB in CI.
- Verify the spec §5 acceptance criteria that span modules:
  - `from_storage()` document equals `from_memory()` document field-by-field for the same run.
  - `aclose()` drains in-flight per-agent persist tasks.
  - Backward compat: run modes still return `FlowResult`; `result.output` / `result.summary`
    behave as before; a `ResultStorage` subclass WITHOUT `fetch()` still works for saves.
- Documentation — update `docs/architecture/07-agentcrew.md` (the file that documents
  `ResultStorage` / `CREW_RESULT_STORAGE`): new section covering:
  - the two-plane persistence model (`crew_agent_results` incremental + consolidated
    `crew_executions`), the crew-level `execution_id`, `persist_agent_results` opt-out;
  - `fetch()` read API and backend notes (Redis key scheme + SCAN, Postgres execution_id
    column, legacy documents not fetchable);
  - `CrewExecutionDocument`: `build_execution_document()`, `from_storage()`, `to_markdown()`
    with a short example.
- Run the FULL storage test suite plus the crew example tests and record results.

**NOT in scope**: new features, fixes beyond what the e2e tests reveal in FEAT-306 code
(regressions found in pre-existing code → note in Completion Note, do not fix here),
HTTP handlers, AgentsFlow.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/bots/flows/core/storage/test_integration.py` | MODIFY | FEAT-306 e2e scenarios |
| `docs/architecture/07-agentcrew.md` | MODIFY | Persistence + reconstruction documentation |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact references. Verify anything not listed before using it.

### Verified Imports
```python
from parrot.bots.flows.crew.crew import AgentCrew
from parrot.bots.flows.core.storage import CrewExecutionDocument, ExecutionMemory  # TASK-1768 re-export
from parrot.bots.flows.core.storage.backends import ResultStorage
from parrot.bots.flows.core.result import FlowResult, NodeResult
```

### Existing Signatures to Use
```python
# All FEAT-306 surface (verify each exists — they are produced by TASK-1765..1769):
NodeResult.to_dict() -> Dict[str, Any]                                   # TASK-1765
ResultStorage.fetch(collection, execution_id) -> list[dict]              # TASK-1766
PersistenceMixin._save_agent_result(node_result, *, execution_id, method, ...)  # TASK-1767
CrewExecutionDocument.from_memory(...) / from_storage(...) / to_markdown()      # TASK-1768
AgentCrew(persist_agent_results=..., result_storage=...) / build_execution_document()  # TASK-1769
result.metadata["execution_id"]                                          # TASK-1769

# Existing test assets to reuse:
# tests/bots/flows/core/storage/test_integration.py — existing e2e style for FEAT-147
# tests/bots/flows/core/storage/test_persistence_mixin.py:11 — _FakeStorage (extend with fetch)
# tests/bots/flows/core/storage/conftest.py — shared fixtures (READ before adding new ones)
```

### Does NOT Exist
- ~~Live Redis/Postgres/DocumentDB in CI~~ — integration tests use the in-memory fake only.
- ~~`CrewExecutionDocument.__eq__` custom semantics~~ — dataclass default equality; compare
  `to_dict()` outputs for the equality assertion to avoid float/enum surprises.
- ~~docs file `docs/architecture/crew-persistence.md`~~ — does not exist; the persistence
  docs live in `docs/architecture/07-agentcrew.md` (verified via grep for CREW_RESULT_STORAGE).

---

## Implementation Notes

### Pattern to Follow
Follow the existing FEAT-147 integration-test structure in `test_integration.py` — read it
fully before adding scenarios; reuse its stub-agent helpers if present.

### Key Constraints
- Deterministic tests: stub agents return fixed strings; no LLM, no network, no sleeps
  beyond `await crew.aclose()` for draining.
- The equality test must tolerate the consolidated write racing agent writes — call
  `await crew.aclose()` before fetching.
- Docs: match the existing tone/structure of `07-agentcrew.md`; include one runnable
  snippet showing `to_markdown()` output shape (abridged).

### References in Codebase
- `tests/bots/flows/core/storage/test_integration.py` — structure to extend.
- `docs/architecture/07-agentcrew.md` — documentation target (grep `ResultStorage` for the
  section to extend).

---

## Acceptance Criteria

- [ ] E2E: 2-agent sequential run → `fetch("crew_agent_results", eid)` returns 2 docs; `fetch("crew_executions", eid)` returns 1 doc
- [ ] `from_storage(storage, eid).to_dict() == crew.build_execution_document().to_dict()`
- [ ] `to_markdown()` of the reconstructed doc contains both agents' sections, final result, and summary
- [ ] `aclose()` drains all persist tasks (no pending tasks after)
- [ ] Storage subclass without `fetch()` completes a run without errors (saves only)
- [ ] Full suite green: `pytest tests/bots/flows/core/storage/ tests/bots/flows/core/test_result_serialisation.py -v`
- [ ] `docs/architecture/07-agentcrew.md` updated with the new persistence + reconstruction section
- [ ] Evidence saved to `artifacts/logs/` (pytest output)

---

## Test Specification

```python
# tests/bots/flows/core/storage/test_integration.py — ADD:

class TestFeat306EndToEnd:
    async def test_persist_and_reconstruct_roundtrip(self, fake_storage, two_stub_agents):
        crew = AgentCrew(name="e2e", agents=two_stub_agents,
                         result_storage=fake_storage, llm=None)
        result = await crew.run_sequential("do the thing", generate_summary=False)
        await crew.aclose()
        eid = result.metadata["execution_id"]

        assert len(await fake_storage.fetch("crew_agent_results", eid)) == 2
        assert len(await fake_storage.fetch("crew_executions", eid)) == 1

        rebuilt = await CrewExecutionDocument.from_storage(fake_storage, eid)
        in_process = crew.build_execution_document()
        assert rebuilt.to_dict() == in_process.to_dict()

        md = rebuilt.to_markdown()
        assert "## Final Result" in md and "## Summary" in md

    async def test_storage_without_fetch_still_saves(self, two_stub_agents):
        class WriteOnly(ResultStorage):
            def __init__(self): self.saved = []
            async def save(self, c, d): self.saved.append((c, d))
            async def close(self): pass
        crew = AgentCrew(name="wo", agents=two_stub_agents, result_storage=WriteOnly(), llm=None)
        result = await crew.run_sequential("x", generate_summary=False)
        await crew.aclose()
        assert isinstance(result, FlowResult)

    async def test_crash_case_agent_docs_only(self, fake_storage):
        # Simulate: agent docs present, consolidated doc absent →
        # from_storage still returns a document (ordered by timestamp)
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1765 through TASK-1769 must ALL be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/crew-per-agent-result-persistence.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1770-integration-tests-docs.md`
8. **Update index** → `"done"` and set the feature's `completed_at`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-14
**Notes**: Added `TestFeat306EndToEnd` to `test_integration.py` (5 tests):
`test_persist_and_reconstruct_roundtrip` (2-agent sequential run → fetch
both collections → `from_storage()` equals `crew.build_execution_document()`
field-by-field, excluding `timestamp` which is inherently a fresh
wall-clock value on each independent `from_memory()` call),
`test_aclose_drains_in_flight_agent_persist_tasks`,
`test_storage_without_fetch_still_saves` (backward-compat with a
save-only `ResultStorage` subclass), `test_crash_case_agent_docs_only`
(consolidated doc absent → reconstructed from standalone agent docs
alone), `test_backward_compat_flowresult_unchanged`. Uses
`parrot.bots.flows.crew.crew.AgentCrew` (current import path) + local
stub agents + an in-memory fake `ResultStorage` — no external DB, no LLM.

Updated `docs/architecture/07-agentcrew.md` with new §7.7 covering the
two-plane persistence model, `persist_agent_results` opt-out, the
`fetch()` read API per backend (Redis SCAN/key-scheme, Postgres DDL,
DocumentDB query, base `NotImplementedError` default), and
`CrewExecutionDocument` usage (`build_execution_document()`,
`from_storage()`, an abridged `to_markdown()` example) plus a backward
-compatibility summary.

Full suite: `pytest tests/bots/flows/core/storage/
tests/bots/flows/core/test_result_serialisation.py -v` → 98 passed, 15
pre-existing failures (all `ModuleNotFoundError` for
`parrot.bots.orchestration.crew` / `parrot.bots.flow.fsm`, legacy modules
removed by earlier, unrelated refactors — confirmed via `git stash` in
TASK-1766/1769). Evidence saved to
`artifacts/logs/feat-306-task-1770-pytest-output.log` (gitignored per
repo convention, not committed). `ruff check` clean on all touched files.
Combined with `test_crew_agent_persistence.py`, `test_crew_hooks.py`, and
`test_agentcrew_from_definition.py`: 132 passed, same 15 pre-existing
failures.

**Deviations from spec — 2 genuine defects found by this task's own e2e
test and fixed (both in THIS feature's own new code, not pre-existing
legacy code, so fixing them is in-scope for satisfying this task's
explicit acceptance criterion `from_storage(...).to_dict() ==
crew.build_execution_document().to_dict()`)**:

1. **`packages/ai-parrot/src/parrot/bots/flows/core/storage/document.py`**
   (`CrewExecutionDocument.from_storage`, created in TASK-1768): the
   consolidated doc's `nodes`/`agents`/`responses`/`execution_log` fields
   (flattened out of the private `metadata["_flow_extra"]` bucket by
   `to_dict()`) were never re-nested back into `metadata["_flow_extra"]`
   on reconstruction, so a round-tripped `to_dict()` always came back
   with those 4 fields empty. Fixed by re-building `_flow_extra` from the
   stored doc's top-level keys before constructing the reconstructed
   instance.
2. **`packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`**
   (`build_execution_document()`, created in TASK-1769): used
   `self.last_crew_result.metadata.get('mode', 'unknown')` verbatim as
   the document's `method` (yielding `"sequential"`), while the persisted
   consolidated doc's `method` is the full `"run_sequential"` form passed
   at write time — normalised via `mode if mode.startswith('run_') else
   f'run_{mode}'`. Also added `self._last_user_id` /
   `self._last_session_id` tracking (set alongside
   `self._last_execution_id` in all 4 run modes) and threaded them into
   `build_execution_document()`'s `from_memory()` call — previously it
   passed neither, so the in-process document's `user_id`/`session_id`
   were always `None` while the persisted one carried the real values.

**Separately noted, NOT fixed (genuinely pre-existing, unrelated to
FEAT-306)**: `run_loop`'s "fresh FSM per iteration" line crashes with a
pydantic `frozen_instance` ValidationError on every invocation
(`CrewAgentNode` became a frozen Pydantic model in an earlier refactor).
Verified via `git stash` in TASK-1769 that this pre-dates this feature.
Flagged again here since it also blocks any live e2e test of `run_loop`
in this task's own scenarios — the `TestRunLoopWiring` tests (TASK-1769)
work around it via `crew.workflow_graph = {}`. Recommend a follow-up
ticket.
