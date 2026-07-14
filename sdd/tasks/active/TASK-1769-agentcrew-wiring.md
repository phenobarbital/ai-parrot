# TASK-1769: AgentCrew wiring — execution_id, incremental persist, consolidated write

**Feature**: FEAT-306 — Crew Per-Agent Result Persistence & Deterministic Execution Document
**Spec**: `sdd/specs/crew-per-agent-result-persistence.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1765, TASK-1767, TASK-1768
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** of FEAT-306 — the integration layer. Wires the crew-level
`execution_id`, the incremental `_save_agent_result` calls, and the consolidated
`CrewExecutionDocument` final write into all four `AgentCrew` run modes, plus the
`build_execution_document()` public accessor and the `persist_agent_results` opt-out.

---

## Scope

All changes in `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`:

- `__init__` (line 132): add param `persist_agent_results: bool = True` →
  `self._persist_agent_results = persist_agent_results` (next to the FEAT-147 persistence
  attrs at lines ~218-223). Update the docstring.
- **Each of the 4 run modes** — `run_sequential`, `run_parallel`, `run_flow`, `run_loop`:
  1. At the start (near the `session_id = session_id or str(uuid.uuid4())` lines, e.g.
     1234/1573): `execution_id = str(uuid.uuid4())`.
  2. Stamp `result.metadata["execution_id"] = execution_id` on the `FlowResult` before the
     final persist (and before `return`).
  3. At EVERY `self.execution_memory.add_result(...)` site inside these methods (grep for
     the current list — verified sites include 1376, 1438 sequential; 1687, 1808, 1868 loop),
     schedule the incremental write with the existing tracked-task pattern:
     ```python
     _agent_task = asyncio.get_running_loop().create_task(
         self._save_agent_result(
             agent_result, execution_id=execution_id, method='run_sequential',
             user_id=user_id, session_id=session_id,
         )
     )
     self._persist_tasks.add(_agent_task)
     _agent_task.add_done_callback(self._persist_tasks.discard)
     ```
     For the flow-mode helper sites (lines ~809, ~867) where `add_result` is called on
     `context.shared_data['execution_memory']`: the helper must receive/see `execution_id`
     — thread it via `context.shared_data` (a new `'crew_execution_id'` entry set by
     `run_flow`) or an explicit parameter, whichever the existing helper signature supports
     with least churn. Do NOT persist when the entry is absent (e.g. helper reused outside
     a run) — skip silently.
  4. Final persist: replace the bare `result` argument at the `_save_result` call sites
     (1488 run_sequential, 1954 run_loop, 2277 run_parallel, 2514 run_flow) with the
     consolidated document:
     ```python
     document = CrewExecutionDocument.from_memory(
         execution_id=execution_id, crew_name=self.name, method='run_sequential',
         memory=self.execution_memory, result=result,
         user_id=user_id, session_id=session_id,
     )
     _persist_task = asyncio.get_running_loop().create_task(
         self._save_result(document, 'run_sequential',
                           execution_id=execution_id,
                           user_id=user_id, session_id=session_id)
     )
     ```
     (`_save_result` signature unchanged — `execution_id` flows through `**kwargs` into the
     stored doc; `document.to_dict()` is picked up by the existing `hasattr(result, "to_dict")`.)
  5. Track the last execution id: `self._last_execution_id = execution_id` (initialise to
     `None` in `__init__`).
- Add public accessor:
  ```python
  def build_execution_document(self) -> Optional[CrewExecutionDocument]:
      """Assemble the document for the LAST run from in-process state (LLM-free)."""
  ```
  Returns `None` when `self.last_crew_result` is `None`; otherwise
  `CrewExecutionDocument.from_memory(...)` using `self._last_execution_id`,
  `self.execution_memory`, `self.last_crew_result`, and the method recorded in
  `self.last_crew_result.metadata.get("mode", "unknown")` (grep how each run mode fills
  `metadata` — use `metadata["execution_id"]` as source of truth for the id).
- DO NOT touch the `run` (line ~2772) and `ask` (line ~3282) `_save_result` sites — out of
  scope per spec Non-Goals.
- Tests in `tests/bots/flows/core/storage/test_agentcrew_lifecycle.py` (extend) or a new
  `tests/bots/flows/core/storage/test_crew_agent_persistence.py` — use stub agents + a fake
  `ResultStorage` instance passed via the `result_storage` constructor param.

**NOT in scope**: `AgentsFlow` (`flows/flow/flow.py`) — explicitly out of scope; backend
changes (TASK-1766); persistence.py (TASK-1767); document.py (TASK-1768); e2e integration
tests + docs (TASK-1770).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` | MODIFY | All wiring described in Scope |
| `tests/bots/flows/core/storage/test_crew_agent_persistence.py` | CREATE | Run-mode wiring tests with fake storage + stub agents |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact references. Verify anything not listed before using it.
> Line numbers verified 2026-07-14 — re-grep before editing; this file is large and active.

### Verified Imports
```python
# crew.py already imports (verify at top of file before adding duplicates):
import uuid                                            # crew.py:31
from parrot.bots.flows.core.storage import ExecutionMemory, PersistenceMixin, SynthesisMixin
from parrot.bots.flows.core.result import FlowResult
# NEW import this task adds:
from parrot.bots.flows.core.storage import CrewExecutionDocument   # re-exported by TASK-1768
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py
class AgentCrew(PersistenceMixin, SynthesisMixin):       # line 93
    def __init__(self, name="AgentCrew", agents=None, ..., persist_results: bool = True,
                 result_storage: Union[str, "ResultStorage", None] = None, **kwargs)  # line 132
    # FEAT-147 attrs — add the new ones HERE (lines ~218-223):
    #   self._persist_results / self._result_storage_arg / self._result_storage / self._persist_tasks
    self.execution_memory = ExecutionMemory(...)         # line 194 — RE-CREATED at start of each run mode (1238, 1577, ...)
    self.last_crew_result: Optional[FlowResult] = None   # line 211
    # session_id defaults:      lines 1234 (sequential), 1573 (loop)
    # add_result sites:         1376, 1438 (seq); 1687, 1808, 1868 (loop); 809, 867 (flow helper
    #                           via context.shared_data['execution_memory'] — see lines 791, 847)
    # _save_result sites:       1488 (run_sequential), 1954 (run_loop), 2277 (run_parallel),
    #                           2514 (run_flow), 2772 (run — DO NOT TOUCH), 3282 (ask — DO NOT TOUCH)
    # tracked-task pattern:     lines 1487-1496 — COPY THIS EXACTLY for agent persists
    # loop-mode synthetic ids:  execution_id = f"{agent_id}#iteration{n}"  # line 1641 — these are
    #                           NODE ids (ExecutionMemory keys), NOT the crew execution_id. The local
    #                           variable name collides — name the new one `crew_execution_id` inside
    #                           run_loop to avoid shadowing.
    _INTERNAL_SHARED_KEYS = frozenset({'execution_memory', 'shared_state'})  # line 90 — if you add
    #                           'crew_execution_id' to shared_data, ADD IT to this frozenset so it
    #                           never leaks into agent kwargs (see usage around line 1310).

# PersistenceMixin (persistence.py):
    async def _save_result(self, result, method, *, collection="crew_executions", **kwargs)  # line 65
    async def _save_agent_result(self, node_result, *, execution_id, method,
                                 collection="crew_agent_results", **kwargs)   # created by TASK-1767
    async def aclose(self) -> None                       # line 110 — already drains _persist_tasks

# CrewExecutionDocument (document.py, TASK-1768):
    @classmethod from_memory(cls, *, execution_id, crew_name, method, memory, result,
                             user_id=None, session_id=None) -> CrewExecutionDocument
```

### Does NOT Exist
- ~~crew-level `execution_id` variable/attr~~ — THIS TASK introduces it (`self._last_execution_id`).
- ~~`self._persist_agent_results`~~ — THIS TASK initialises it from the new param.
- ~~`build_execution_document()`~~ — THIS TASK creates it.
- ~~`FlowResult.execution_id` field~~ — stamp into `result.metadata["execution_id"]` instead.
- ~~per-agent persistence in `run`/`ask`~~ — out of scope, leave those methods untouched.
- ~~`_save_agent_result` creating its own asyncio task~~ — it is a plain coroutine; the
  wiring here owns `create_task` + `_persist_tasks` bookkeeping.

---

## Implementation Notes

### Pattern to Follow
The tracked fire-and-forget pattern at crew.py:1487-1496 is the template for EVERY new
persist call. Never `await` a persist inline on the critical path.

### Key Constraints
- `FlowResult` remains the return type of all run modes — no signature changes.
- `persist_results=False` must disable BOTH planes; `persist_agent_results=False` only the
  per-agent plane (enforced inside `_save_agent_result`, TASK-1767 — no extra guards here
  beyond not building tasks when `self._persist_results` is False, matching current style).
- run_loop: use `crew_execution_id` as the local variable name (see contract — shadowing).
- flow mode: nodes execute via helpers that only receive `context` — thread the id through
  `context.shared_data['crew_execution_id']` and extend `_INTERNAL_SHARED_KEYS`.
- Keep diffs surgical: this file is ~3300 lines and actively developed; do not reformat,
  reorder, or "clean up" untouched code.

### References in Codebase
- `crew.py:1487-1496` — tracked-task persist pattern.
- `crew.py:1226-1500` — run_sequential full structure (reference run mode).
- `tests/bots/flows/core/storage/test_agentcrew_lifecycle.py` — existing crew + fake storage
  test style (stub agents, `result_storage=` injection).

---

## Acceptance Criteria

- [ ] All 4 run modes stamp `result.metadata["execution_id"]` (uuid4, unique per run)
- [ ] Every agent completion in the 4 run modes schedules exactly one `_save_agent_result` tracked task (fake storage receives one `crew_agent_results` doc per agent, all carrying the same execution_id)
- [ ] Final write to `crew_executions` is the `CrewExecutionDocument` dict (contains `agent_results` and `execution_id`)
- [ ] `build_execution_document()` returns a complete document after a run; `None` before any run
- [ ] `persist_agent_results=False` → zero `crew_agent_results` writes, crew doc still written
- [ ] `persist_results=False` → zero writes of any kind
- [ ] `run`/`ask` methods unchanged (`git diff` shows no hunks in them)
- [ ] `aclose()` drains agent-persist tasks (covered by existing `_persist_tasks` contract)
- [ ] All tests pass: `pytest tests/bots/flows/core/storage/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`

---

## Test Specification

```python
# tests/bots/flows/core/storage/test_crew_agent_persistence.py
# Build on the stub-agent + fake-storage patterns in test_agentcrew_lifecycle.py.

async def test_sequential_persists_one_doc_per_agent(fake_storage, two_stub_agents):
    crew = AgentCrew(name="c", agents=two_stub_agents, result_storage=fake_storage, llm=None)
    result = await crew.run_sequential("task")
    agent_docs = fake_storage.docs["crew_agent_results"]
    assert len(agent_docs) == 2
    eid = result.metadata["execution_id"]
    assert all(d["execution_id"] == eid for d in agent_docs)

async def test_consolidated_doc_written_with_agent_results(fake_storage, two_stub_agents):
    crew_docs = fake_storage.docs["crew_executions"]
    assert crew_docs[0]["result"]["agent_results"]  # embedded per-agent list

async def test_persist_agent_results_false(fake_storage, two_stub_agents):
    crew = AgentCrew(..., persist_agent_results=False)
    ...
    assert fake_storage.docs["crew_agent_results"] == []

async def test_build_execution_document_roundtrip(fake_storage, two_stub_agents):
    doc = crew.build_execution_document()
    assert doc.execution_id == result.metadata["execution_id"]
    assert len(doc.agent_results) == 2

async def test_execution_ids_unique_per_run(...):
    # two runs → two different metadata["execution_id"] values
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1765, TASK-1767, TASK-1768 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-grep every line number listed; crew.py is large and
   actively developed, offsets may have drifted
4. **Update status** in `sdd/tasks/index/crew-per-agent-result-persistence.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1769-agentcrew-wiring.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
