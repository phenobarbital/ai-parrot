# TASK-1898: Integration Tests — Console E2E Against a Fake Flow

**Feature**: FEAT-374 — `parrot devloop`: Interactive CLI Console for Dev-Loop Flows
**Spec**: `sdd/specs/devloop-cli-console.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1897
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 / §4 Integration Tests. Unit tests (TASK-1893..1897) mock
the runner; this task proves the whole console works end-to-end against a
**real `DevLoopRunner`** driving a **stub flow** in-process — no Redis, no
`claude` CLI, no Jira, no network (pattern: `examples/dev_loop/e2e_demo.py`
simulates every external service).

---

## Scope

- Implement `packages/ai-parrot/tests/cli/devloop/integration/test_console_e2e.py`
  (+ `__init__.py`, `conftest.py`):
  - **Stub flow fixture**: a minimal `AgentsFlow`-compatible object (or a
    real tiny flow if cheap) accepted by `DevLoopRunner(flow)`, whose
    execution path applies a scripted action sequence to the run's
    `SessionHost` (obtained via `runner.get_host(run_id)` /
    `shared["session_host"]`) including: `NodeStarted/Completed` pairs,
    `DispatchDelta` text, `GateOpened` (then block until resolved),
    `RunClosed`. Study how `DevLoopRunner.run` seeds
    `shared["session_host"]` (runner.py:522-560) and how
    `examples/dev_loop/e2e_demo.py` fakes the flow before choosing the
    stub shape — prefer the simplest object that satisfies
    `runner.run()`'s use of `self.flow`.
  - **`test_console_e2e_fake_flow`**: piped wizard input → brief →
    dispatch → renderer paints scripted actions → gate prompt approve →
    flow completes → `FlowResult` summary rendered → exit code 0. Assert
    key markers in `Console(record=True)` export (node names, gate panel,
    PR/Jira lines if scripted, closed banner).
  - **`test_console_revision_e2e`**: `revise --brief revision.yaml` path
    through `runner.run_revision` on the stub (revision deps stubbed at
    `DevLoopRunner(...)` construction).
  - **`test_console_two_runs_attach_e2e`**: two dispatches; `/runs` +
    `/attach` against the real runner catalogue.
  - Bootstrap's `build_runtime`/`preflight` are monkeypatched to return the
    stub runtime (integration target is console↔runner↔host, not wiring).
- Ensure the suite runs in CI defaults: `pytest packages/ai-parrot/tests/cli/ -v`
  green with no external services and no `@pytest.mark.live` markers.

**NOT in scope**: real-service live tests (out of spec); modifying any
production module (if a bug is found, report it in the Completion Note and
fix only within FEAT-374's own modules).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/cli/devloop/integration/__init__.py` | CREATE | package |
| `packages/ai-parrot/tests/cli/devloop/integration/conftest.py` | CREATE | stub flow / runtime fixtures |
| `packages/ai-parrot/tests/cli/devloop/integration/test_console_e2e.py` | CREATE | e2e tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop import DevLoopRunner          # flows/dev_loop/__init__.py:27
from parrot.flows.dev_loop.models import WorkBrief, RevisionBrief  # models.py:129,274
from parrot.flows.dev_loop.session_state import SessionHost  # session_state.py:723
from parrot.cli.devloop.console import DevLoopConsole    # TASK-1896
from prompt_toolkit.input import create_pipe_input
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py:522
async def run(self, brief: WorkBrief, *, run_id=None,
              initial_task: str = "", extra_shared=None) -> FlowResult
# run() (lines 546-560): creates+registers the SessionHost BEFORE the flow
# executes, applies RunCreated, and seeds shared_data:
#   {"bug_brief": brief, ...}  — legacy key kept for node compat
# The host is reachable via runner.get_host(run_id) during the run.

# runner.py:594 — run_revision(brief: RevisionBrief, *, run_id=None) -> FlowResult
#   requires dispatcher/jira/git/redis kwargs at DevLoopRunner.__init__
#   (pass simple stubs/None-safe fakes; see runner.py:186-192).

# Precedent for a fully-faked in-process run:
# examples/dev_loop/e2e_demo.py — "self-contained end-to-end demo
#   (no external services)" per examples/dev_loop/README.md:31-33.
#   READ IT FIRST to copy its flow-faking approach.

# Integration-test layout precedent:
# packages/ai-parrot/tests/flows/dev_loop/integration/ (TASK-1856 e2e:
#   gated run, reconnect, crash rebuild) — naming + async fixtures style.
```

### Does NOT Exist
- ~~Redis/`claude` CLI/Jira in tests~~ — the suite must pass with none of
  them installed/reachable (that's the point).
- ~~`DevLoopRunner.run_fake()` / test mode~~ — no such thing; fake the
  *flow*, use the real runner.
- ~~`pytest.mark.live` for these tests~~ — live markers are for the
  existing real-service suite (`tests/flows/dev_loop/integration/`), not
  this task.

---

## Implementation Notes

### Pattern to Follow
- `examples/dev_loop/e2e_demo.py` — in-process fake of the whole loop.
- `packages/ai-parrot/tests/flows/dev_loop/integration/` — fixture and
  asyncio patterns for runner-level tests.
- `packages/ai-parrot/tests/flows/dev_loop/test_dual_publish.py` — how tests
  drive SessionHost/actions.

### Key Constraints
- Deterministic: scripted input, bounded timeouts (`asyncio.wait_for`), no
  sleeps longer than the renderer tick needs.
- The gate test MUST block the fake flow on the real gate mechanism
  (`GateOpened` → console approve → flow proceeds), not a bypass, so the
  console↔runner gate path is genuinely exercised.

### References in Codebase
- Spec §4 Integration Tests table; §7 gate-race risk.

---

## Acceptance Criteria

- [ ] `test_console_e2e_fake_flow` passes: wizard → run → gate approve →
  RunClosed → exit 0, with rendered markers asserted.
- [ ] `test_console_revision_e2e` exercises `run_revision` on the stub.
- [ ] `test_console_two_runs_attach_e2e` lists/switches two real-runner runs.
- [ ] Whole feature suite green: `pytest packages/ai-parrot/tests/cli/ -v`
  with no Redis/claude/Jira available.
- [ ] `ruff check` clean on test files.
- [ ] Spec §5 checklist reviewed — tick every criterion this task closes.

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/devloop/integration/test_console_e2e.py
import pytest

@pytest.fixture
async def stub_runtime():
    """Real DevLoopRunner over a scripted fake flow; bootstrap monkeypatched."""

async def test_console_e2e_fake_flow(stub_runtime, pipe_console): ...
async def test_console_revision_e2e(stub_runtime, pipe_console, tmp_path): ...
async def test_console_two_runs_attach_e2e(stub_runtime, pipe_console): ...
```

---

## Agent Instructions

1. **Read the spec** (§4, §5) and `examples/dev_loop/e2e_demo.py` FIRST.
2. **Check dependencies** — TASK-1897 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — esp. runner.py:522-560 shared-data
   seeding before designing the stub flow.
4. **Update index** → `"in-progress"`.  5. **Implement**.
6. **Verify** criteria (run the FULL cli test tree).
7. **Move to completed/**; index → `"done"`.  8. **Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
