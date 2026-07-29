# TASK-1896: Console Engine — Session, Slash Commands, Gates (`console.py`)

**Feature**: FEAT-374 — `parrot devloop`: Interactive CLI Console for Dev-Loop Flows
**Spec**: `sdd/specs/devloop-cli-console.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1893, TASK-1894, TASK-1895
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 / Goals G4+G5. `DevLoopConsole` is the session brain: it
runs the wizard, dispatches runs as asyncio tasks through `DevLoopRunner`,
owns the modal terminal (Live view vs. prompts), resolves HITL gates, and
implements the slash commands. Attach semantics are **same-process only**
(resolved spec Q&A): `/runs` lists runs started in this console session via
the runner's in-memory catalogue.

---

## Scope

- Implement `packages/ai-parrot/src/parrot/cli/devloop/console.py`:
  - `class DevLoopConsole` with
    `async def start(self, *, brief_file: str | None = None, revision: bool = False) -> int`.
  - **Session flow**: preflight (abort with rendered table if failed) →
    `build_runtime()` → if `brief_file` given, load+validate brief from
    YAML/JSON; else run `PydanticWizard(WorkBrief)` (seed
    reporter/escalation defaults via bootstrap's `default_identities`) →
    dispatch `asyncio.create_task(runner.run(brief, initial_task=...))` →
    attach a `RunView`.
  - **Modal terminal discipline** (spec §7): exactly one writer at a time —
    RunView Live renders while idle; wizard/gate/confirm prompts `pause()`
    the Live, prompt via prompt_toolkit (`patch_stdout`), then `resume()`.
  - **Gate interaction**: watch `run_view.pending_gates()`; on a pending
    gate, pause Live, render a Rich panel (gate kind, message, TTL via
    `gate_ttl_for(kind)`), prompt approve/reject + optional comment, call
    `await runner.resolve_gate(run_id, gate_id, resolution, resolved_by=<identity>, comment=...)`.
    Errors (already-resolved/expired/unknown) render as a notice — never
    crash the session. `resolved_by` defaults to `$USER` env with a visible
    notice (spec §8 open question default).
  - **Slash commands** (registry pattern from `parrot/cli/commands.py`):
    `/new` (wizard → new run), `/runs` (table from `runner.registry_state()`
    + `runner.active_runs()`), `/attach <run-id>` (switch RunView to
    `runner.get_host(run_id)`; unknown id → notice), `/cancel [run-id]`
    (confirm → `runner.cancel_run(run_id, requested_by=<identity>)`),
    `/revise` (wizard over `RevisionBrief` → `runner.run_revision(brief)`),
    `/help`, `/quit` (confirm if runs active).
  - **Ctrl-C**: first ^C → confirm cancel of the attached run; decline →
    continue; at top level with no runs → exit.
  - Multiple concurrent runs allowed; a 4th+ run shows "queued (cap N)"
    while awaiting the runner's semaphore (derive from `active_runs()`).
  - On run completion render the `FlowResult` summary (status, responses
    per node, errors) — shape per `examples/dev_loop/quickstart.py:222-228`.
- Unit tests `packages/ai-parrot/tests/cli/devloop/test_console.py` with a
  **stub runner** (AsyncMock with real `SessionHost` objects) and piped
  input — no real flow, Redis, or LLM.

**NOT in scope**: click argument parsing (TASK-1897); integration tests with
the fake flow (TASK-1898); any core dev_loop change (G7).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/devloop/console.py` | CREATE | DevLoopConsole engine |
| `packages/ai-parrot/tests/cli/devloop/test_console.py` | CREATE | stub-runner unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.cli.wizard import PydanticWizard            # TASK-1893 (verify completed)
from parrot.cli.devloop.bootstrap import (              # TASK-1894
    preflight, build_runtime, DevLoopRuntime, default_identities,
)
from parrot.cli.devloop.renderer import RunView          # TASK-1895
from parrot.flows.dev_loop import DevLoopRunner, gate_ttl_for  # flows/dev_loop/__init__.py:27
from parrot.flows.dev_loop.models import WorkBrief, RevisionBrief  # models.py:129,274
from prompt_toolkit.patch_stdout import patch_stdout
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
def gate_ttl_for(kind: GateKind) -> int                        # line 79
class DevLoopRunner:                                            # line 156
    def get_host(self, run_id: str) -> Optional[SessionHost]    # line 213
    def registry_state(self) -> RunRegistryState                # line 223
    async def resolve_gate(self, run_id: str, gate_id: str,     # line 455
                 resolution: str,        # "approved" | "rejected"
                 resolved_by: str, comment: str = "",
                 origin=None) -> ActionEnvelope
    async def cancel_run(self, run_id: str,                     # line 491
                 requested_by: str) -> ActionEnvelope
    def active_runs(self) -> Set[str]                           # line 512
    def is_active(self, run_id: str) -> bool                    # line 516
    async def run(self, brief: WorkBrief, *,                    # line 522
                  run_id: Optional[str] = None, initial_task: str = "",
                  extra_shared=None) -> FlowResult
    async def run_revision(self, brief: RevisionBrief, *,       # line 594
                  run_id: Optional[str] = None) -> FlowResult
# run() auto-mints run_id "run-<hex8>" when omitted; the console needs the
# id BEFORE dispatch to attach — mint it yourself (uuid4().hex[:8]) and
# pass run_id= explicitly.

# packages/ai-parrot/src/parrot/bots/flows/core/result.py:353
class FlowResult: ...   # .status (FlowStatus), .responses: dict, .errors: dict

# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
# RunRegistryState:469  RunSummary:455 — read class bodies for exact fields
# before rendering the /runs table.

# Slash registry pattern:
# packages/ai-parrot/src/parrot/cli/commands.py
class SlashCommand: ...              # line 23
class SlashCommandDispatcher: ...    # line 70
```

### Does NOT Exist
- ~~`DevLoopRunner.list_runs()` / `.attach()` / `.subscribe()`~~ — use
  `registry_state()` / `active_runs()` / `get_host()`.
- ~~`resolve_gate` returning a bool~~ — it returns an `ActionEnvelope` and
  raises/conflicts on invalid gates; handle exceptions.
- ~~Cross-process attach~~ — `registry_state()` is in-memory per-process;
  do NOT build Redis replay (explicit non-goal, spec §1).
- ~~`FlowResult.output` / `.text`~~ — fields are `.status`, `.responses`,
  `.errors` (result.py:353; verify body before use).
- ~~Reusing `AgentREPL`~~ — pattern reference only; do not subclass it.

---

## Implementation Notes

### Pattern to Follow
- Slash registry: `parrot/cli/commands.py::SlashCommandDispatcher` (line 70).
- Async input + streaming coexistence: `parrot/cli/repl.py::AgentREPL`
  (line 58) and prompt_toolkit `patch_stdout`.
- Gate panel rendering: `parrot/human/cli_companion.py::HITLCompanion`.

### Key Constraints
- One terminal writer at a time (modal discipline) — every prompt wraps
  `run_view.pause()` / `resume()`.
- All runner calls `await`ed on the same loop; run tasks tracked in a dict
  `run_id -> asyncio.Task` for `/runs`, `/quit` confirmation and result
  harvesting (`task.add_done_callback` → render FlowResult summary).
- Gate watch loop must poll (~250 ms) — gates surface via state, not events.
- `$USER` fallback identity: `os.environ.get("USER", "devloop-cli")`, shown
  once as a notice.

### References in Codebase
- `sdd/specs/devloop-cli-console.spec.md` §2, §3 M4, §7 (risks: gate races,
  Live contention, run() blocking).

---

## Acceptance Criteria

- [ ] Scripted GateOpened → prompt → `resolve_gate` called with chosen
  resolution/comment/resolved_by (stub assert).
- [ ] `resolve_gate` raising (already-resolved) renders a notice; session
  continues.
- [ ] Two stub runs: `/runs` lists both; `/attach` switches the rendered
  host; unknown id → notice.
- [ ] `/cancel` and Ctrl-C-confirm call `cancel_run`; decline continues.
- [ ] `/revise` collects `RevisionBrief` and calls `run_revision`.
- [ ] `brief_file` path loads/validates YAML brief and skips the wizard.
- [ ] Preflight failure renders the check table and exits non-zero without
  building the runtime.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/cli/devloop/test_console.py -v`
- [ ] `ruff check` clean; no imports from dispatcher internals.

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/devloop/test_console.py
import pytest
from parrot.cli.devloop.console import DevLoopConsole

@pytest.fixture
def stub_runner():
    """AsyncMock DevLoopRunner + real SessionHosts keyed by run_id."""

async def test_gate_approve_flow(stub_runner, pipe_console): ...
async def test_gate_conflict_notice(stub_runner, pipe_console): ...
async def test_runs_and_attach(stub_runner, pipe_console): ...
async def test_cancel_ctrl_c_confirm_and_decline(stub_runner, pipe_console): ...
async def test_revise_dispatches_run_revision(stub_runner, pipe_console): ...
async def test_brief_file_skips_wizard(tmp_path, stub_runner, pipe_console): ...
async def test_preflight_failure_aborts(monkeypatch, pipe_console): ...
```

---

## Agent Instructions

1. **Read the spec** (§2, §3 M4, §7).
2. **Check dependencies** — TASK-1893/1894/1895 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — esp. read `RunRegistryState`/`RunSummary`
   (session_state.py:455-480) and `FlowResult` (result.py:353) bodies.
4. **Update index** → `"in-progress"`.  5. **Implement** (TDD).
6. **Verify** criteria.  7. **Move to completed/**; index → `"done"`.
8. **Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
