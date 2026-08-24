# TASK-2409: Resume-without-duplicates + submit-gate end-to-end tests

**Feature**: FEAT-455 — Web-Automation Real-Browser Fixture-Site Integration Tests
**Spec**: `sdd/specs/web-automation-fixture-site-tests.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-2407, TASK-2408
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** — the two hardest FEAT-453 Integration Tests:
`test_expense_import_resumes_from_checkpoint` (AC-12, verifying FEAT-453's
own review-remediation `make_import_progress_listener()` mechanism end to
end) and `test_submit_gate_end_to_end` (AC-8/AC-20, a real
`ConfirmationGuard` pause/approve cycle against a real browser session).

Both need the full `ExecutionPlanToolkit`/`ToolManager`/
`WorkingMemoryToolkit` stack wired together — not just a driver + site +
broker, as in TASK-2408 — mirroring the construction pattern
`packages/ai-parrot/tests/tools/execution_plan/test_integration.py`
already demonstrates for `ExecutionPlanToolkit` alone.

Implements spec **Module 3**.

---

## Scope

- Implement `test_expense_import_resumes_from_checkpoint`:
  1. Build a real `BusinessAutomationToolkit` (real `plans_dir` fixture —
     reuse `packages/ai-parrot-tools/tests/business_automation/fixtures/acme-books/`
     — real `credential_broker=fake_broker`, real `PlaywrightDriver`
     against `local_fixture_site`).
  2. Build an `ImportPlanBundle` via `build_import_plan()` against a small
     (e.g. 3-row) fixture Excel file, with `make_import_progress_listener()`
     wired as the run's `on_node_event`.
  3. Simulate a mid-run kill: **prefer** raising inside a monkeypatched
     row-handler after N rows over actually cancelling a background task
     (see spec §8 Open Questions — the former is far less flaky). Confirm
     in this task's Completion Note which approach was used and why.
  4. Re-call `build_import_plan()` for the same statement digest; assert
     `already_completed_rows` reflects exactly the rows that completed
     before the simulated kill, and that re-running the resumed plan
     registers each remaining row exactly once — total registrations
     across both runs equals the original row count (no duplicates, no
     gaps).
- Implement `test_submit_gate_end_to_end`:
  1. Construct a `BusinessAutomationToolkit` with a real `human_manager`
     (`parrot.human.manager.HumanInteractionManager`) wired to a scripted,
     auto-approving test `HumanChannel` implementation (or the minimal
     `_ApprovingHumanManager`-style stand-in already used in
     `conftest.py` — verify whether that stand-in is sufficient here or a
     more complete real `HumanInteractionManager` + `HumanChannel` pair is
     needed to prove the REAL pause/approve cycle, not just a mock
     shortcut; document the choice).
  2. Run a `SUBMIT`-kind operation against `local_fixture_site`; assert no
     browser action happens beyond the confirmation checkpoint until the
     scripted approval is recorded, then assert the operation completes
     and the fixture site shows the expected effect (e.g. the "submit"
     route was actually hit).
- Both tests must poll `ExecutionPlanToolkit.plan_status(run_id)` rather
  than assume synchronous completion — `soft_timeout` (default 60s) may
  return a `RunningSummary` for a slow real-browser run (see
  `test_integration.py`'s own handling of this).

**NOT in scope**: modifying `ExecutionPlanToolkit`'s checkpoint/resume
behavior (FEAT-399's `checkpoint=False` is deliberate and unchanged — this
task proves resumability via `make_import_progress_listener`'s manifest,
not via any `ExecutionPlanToolkit`-native mechanism); modifying any
FEAT-453 production code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/business_automation/test_fixture_site_e2e.py` | CREATE | Both end-to-end tests |
| `packages/ai-parrot-tools/tests/business_automation/fixtures/scripted_channel.py` | CREATE | Scripted auto-approving `HumanChannel` test double (only if the existing `_ApprovingHumanManager` stand-in proves insufficient — verify first) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase, checked on
> `dev` immediately after FEAT-453 merged (PR #1225). Use these exact
> imports and signatures. **DO NOT** invent, guess, or assume anything not
> listed here. If you need something absent, VERIFY it exists with
> `grep`/`read` and update this section FIRST.

### Verified Imports

```python
from parrot.tools.execution_plan.toolkit import ExecutionPlanToolkit   # verified: parrot/tools/execution_plan/toolkit.py:61
from parrot.tools.working_memory.tool import WorkingMemoryToolkit      # verified: parrot/tools/working_memory/tool.py:44
from parrot.tools.manager import ToolManager                           # verified: parrot/tools/manager.py:233
from parrot.human.manager import HumanInteractionManager               # verified: parrot/human/manager.py:51
from parrot.human.channels.base import HumanChannel                    # verified: parrot/human/channels/base.py:47
from parrot_tools.business_automation.toolkit import BusinessAutomationToolkit
from parrot_tools.business_automation.ingest import build_import_plan, make_import_progress_listener
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py
class ExecutionPlanToolkit(AbstractToolkit):     # line 61
    def __init__(self, *, tool_manager: Any, working_memory: "WorkingMemoryToolkit",
                 planner_llm=None, plans_dir=None, allowed_tools=None,
                 soft_timeout: float = 60.0, permission_context=None,
                 on_node_event: Optional[Callable[..., Any]] = None,
                 max_completed_runs: int = 50, **kwargs) -> None: ...   # line 93-106
    async def plan_execute(self, objective: Optional[str] = None,
                            plan_name: Optional[str] = None,
                            params: Optional[Dict[str, Any]] = None) -> ToolResult: ...  # line 432 — CORRECTED, see below
    async def _run_plan(self, plan: ExecutionPlan, *, source: str) -> ToolResult: ...    # line 165 — the REAL integration point for a pre-built plan, see below
    async def plan_status(self, run_id: str) -> ToolResult: ...        # line 385 — poll this, do not assume sync completion

# packages/ai-parrot/src/parrot/human/manager.py
class HumanInteractionManager:                    # line 51
    def __init__(self, channels: Optional[Dict[str, HumanChannel]] = None,
                 redis_url: Optional[str] = None,
                 reject_detector: Optional[RejectIntentDetector] = None,
                 on_event: Optional[Callable[[str, Any], Awaitable[None]]] = None) -> None: ...

# ALREADY-PROVEN full-stack construction pattern — mirror this exactly,
# do not invent a different wiring:
# packages/ai-parrot/tests/tools/execution_plan/test_integration.py
```

### CORRECTION: `plan_execute()` cannot run a pre-built `ExecutionPlan`

**Verified by reading `toolkit.py:432-458` directly** (this task's own
contract's `plan_execute(self, plan: ExecutionPlan)` was wrong — no such
parameter exists): `plan_execute()` only accepts `objective`
(LLM-authored) or `plan_name` (a versioned file resolved via `plans_dir`)
— never a pre-built in-memory `ExecutionPlan` object, which is exactly
what `ingest.py`'s `build_import_plan()` returns. Both of
`plan_execute()`'s own code paths ultimately call the private
`_run_plan(plan, source=...)` (line 165) once a plan has been
acquired/validated — **this task calls `_run_plan()` directly**, the same
way `plan_execute()` itself does internally, rather than writing the plan
to a file just to satisfy `plan_name`'s file-based loading path.
`RunRecord.source` is a `Literal["objective", "plan_name"]` — pass
`source="plan_name"` (the closer semantic match; there is no third literal
for "pre-built object").

### Does NOT Exist

- ~~`ExecutionPlanToolkit.plan_execute(plan: ExecutionPlan)`~~ — does not
  exist; see the correction above.
- ~~a `resume_from` parameter on `ExecutionPlanToolkit.plan_execute`~~ —
  still does not exist (FEAT-399's deliberate design, unchanged by
  FEAT-453). Resumability in this test comes entirely from
  `make_import_progress_listener`'s manifest + re-calling
  `build_import_plan()`, never from `ExecutionPlanToolkit` itself.
- ~~synchronous completion guaranteed from `plan_execute()`~~ — a slow
  real-browser run may exceed `soft_timeout` and return a
  `RunningSummary`; poll `plan_status(run_id)`.
- ~~a bespoke SUBMIT-gate decision model~~ — Decision D2 (FEAT-453) forbids
  this; the real `ConfirmationGuard` (already used unmodified by
  `BusinessAutomationToolkit`) is the only gate — verify its exact
  `confirm()` signature via `parrot.auth.confirmation` before writing the
  scripted-approval test double, do not guess it.
- ~~a `ToolManager` that must dispatch `run_operation` synchronously to
  completion~~ — `BusinessAutomationToolkit.run_operation()` itself is
  fire-and-forget (`{"status": "started", "run_id": ...}` immediately,
  real work in a background `asyncio.Task`). A plan node's registered tool
  function must poll `toolkit._runs[run_id]` to completion itself
  (mirroring `smoke.py`'s `run_smoke_check()`, FEAT-453 TASK-2395), or
  `AgentsFlow` marks the node "done" the instant the run merely *starts*.
- ~~`register_tool(..., function=toolkit.run_operation)` (the bound method
  directly)~~ — this would hit exactly the fire-and-forget gap above; wrap
  it in a poll-to-completion closure instead (see the implementing test
  file's `_make_run_operation_tool()`).

---

## Implementation Notes

### Pattern to Follow

Mirror `packages/ai-parrot/tests/tools/execution_plan/test_integration.py`
for the `ExecutionPlanToolkit` + `ToolManager` + `WorkingMemoryToolkit`
construction — this is the single most important reference for this task;
do not invent a different wiring pattern.

### Key Constraints

- **Poll, don't assume.** Both tests must handle the `RunningSummary`
  (in-progress) response shape from `plan_execute()`/`plan_status()`, not
  just the completed-manifest shape.
- **Prefer the less-flaky kill simulation** (raise-after-N-rows) per the
  spec's own Open Questions — document the choice made either way in this
  task's Completion Note.
- **No real third-party site** — every browser navigation targets
  `local_fixture_site` only.

### References in Codebase

- `packages/ai-parrot/tests/tools/execution_plan/test_integration.py` —
  the construction pattern to mirror.
- `packages/ai-parrot-tools/tests/business_automation/conftest.py` — the
  `_ApprovingHumanManager`/`SpyConfirmationGuard` stand-ins already used
  by FEAT-453's own mocked tests; verify whether these are sufficient for
  a REAL end-to-end pause/approve cycle or whether a more complete
  `HumanInteractionManager`+`HumanChannel` pair is needed.
- `packages/ai-parrot-tools/src/parrot_tools/business_automation/ingest.py`
  — `make_import_progress_listener()` (FEAT-453 AC-12 remediation), the
  mechanism this task's resume test proves end to end.

---

## Acceptance Criteria

- [ ] `test_expense_import_resumes_from_checkpoint` passes: after a
      simulated mid-run kill, re-running `build_import_plan()` for the
      same statement digest registers each remaining row exactly once —
      total registrations across both runs equals the original row count.
- [ ] `test_submit_gate_end_to_end` passes: the operation is provably
      paused (no browser action beyond the confirmation point) until the
      scripted approval is recorded, then completes against the fixture
      site.
- [ ] Both tests poll `plan_status()`/equivalent rather than assuming
      synchronous completion.
- [ ] Neither test contacts any host other than `local_fixture_site`.
- [ ] `ruff check` clean on every new file.
- [ ] FEAT-453's spec AC-17 and AC-20 are noted as MET in this task's
      Completion Note (FEAT-453's own spec file is not edited).

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
import pytest


class TestExpenseImportResumesFromCheckpoint:
    async def test_no_duplicate_registrations_after_simulated_kill(
        self, local_fixture_site, fake_broker, real_playwright_driver, three_row_xlsx
    ):
        ...  # build the plan, wire make_import_progress_listener, simulate
             # a kill after row 1, rebuild, run the remainder, assert total
             # registrations == 3 with no duplicates


class TestSubmitGateEndToEnd:
    async def test_submit_pauses_then_completes_on_approval(
        self, local_fixture_site, real_playwright_driver
    ):
        ...  # run a SUBMIT operation, assert it's paused, script an
             # approval, assert it then completes and hits the fixture
             # site's submit effect
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-automation-fixture-site-tests.spec.md` — especially §3 Module 3, §6 Codebase Contract, and §7 Known Risks/Gotchas (the `soft_timeout` polling gotcha in particular).
2. **Check dependencies** — verify TASK-2407 and TASK-2408 are in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code:
   - Confirm every import still resolves (`grep`/`read` the source).
   - Confirm every listed signature still matches.
   - If anything changed, update this contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists.
4. **Update status** in `sdd/tasks/index/web-automation-fixture-site-tests.json` → `"in-progress"`.
5. **Implement** per scope, contract, and notes — nothing more.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/TASK-2409-resume-and-submit-gate-e2e-tests.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (autonomous, via /sdd-start)
**Date**: 2026-08-24
**Notes**: Implemented `test_fixture_site_e2e.py` with both required tests
plus a small sanity test, all against a real, raw Playwright `Browser`, a
real `ExecutionPlanToolkit`/`ToolManager`/`WorkingMemoryToolkit` stack, and
the real `local_fixture_site`. `scripted_channel.py` was **not** created —
see the human-manager decision below.

**`test_expense_import_resumes_from_checkpoint`** (AC-12): Built a
test-local DRAFT operation ("record_row") navigating to
`local_fixture_site`'s `/cookie-check` per row — deliberately not reusing
the acme-books fixtures' own `clients_flow` (hardcoded
`http://acme-books.test/...`, never resolvable by a real browser). Used
the REAL `build_import_plan()` to generate the plan (never hand-rolled
`PlanNode`s), and the REAL `make_import_progress_listener()` wired as
`ExecutionPlanToolkit(on_node_event=...)`. Simulated a mid-run kill by
raising inside the registered `run_operation` tool function on its 2nd
invocation (row index 1) — **the row-index-2 node never dispatched at
all**, confirmed empirically (`resumed.already_completed_rows == 1`
after the kill, not 0 or 3), because `build_import_plan()`'s own
sequential `depends_on` chaining means a failed node blocks its
dependents — exactly the "raise-after-N-rows" approach the spec's Open
Questions recommended over actually cancelling a background task.
Re-building the plan for the same statement digest correctly returned
only the 2 remaining nodes; running those to completion against a fresh
(non-flaky) tool brought the manifest to `fully_completed=True`,
`already_completed_rows=3` — no duplicates, no gaps.

**`test_submit_gate_end_to_end`** (AC-8/AC-20): Built a test-local SUBMIT
operation ("confirm_and_visit") navigating to `/cookie-check`. **Human-manager
decision** (explicitly flagged as an implementer's call in this task's own
scope): reused FEAT-453's own `_ApprovingHumanManager`-style stand-in
(`conftest.py`) rather than building a full real `HumanChannel` protocol
implementation from scratch. Rationale: `run_operation()`'s own sequential
code structure — already proven correct by FEAT-453's existing
`test_denied_submit_never_opens_browser`/`test_fails_closed_without_human_manager`
— guarantees the confirmation check completes *before* `_ensure_open()`
regardless of how long approval takes; a full multi-second
`HumanChannel`/`register_response_handler()` round trip would add
substantial implementation risk for no additional ordering guarantee. The
real value THIS test adds over FEAT-453's own mocked tests is that a real
post-approval Playwright session actually opens and reaches the real
fixture site — which it does. Strengthened the stand-in with an *active*
assertion (not just structural/ordering inference): the approving
callback itself asserts `toolkit._opened is False` at the exact moment
it's invoked, proving no browser session existed yet when the gate was
checked. `approval_calls == [False]` (called exactly once, browser closed
at that moment) and `toolkit._opened is True` afterward, both asserted.

**Two significant Codebase Contract corrections found and verified
empirically** (both already updated in this task's own Codebase Contract
above before implementing, per Cardinal Rule 4):
1. `ExecutionPlanToolkit.plan_execute()` does **not** accept a pre-built
   `ExecutionPlan` at all (this task's original contract was wrong) — only
   `objective` or `plan_name`. Both tests call the private `_run_plan(plan,
   source="plan_name")` directly instead, the exact method
   `plan_execute()` itself delegates to internally once a plan is
   acquired. (`RunRecord.source` is a `Literal["objective", "plan_name"]`
   — no third option for a pre-built object.)
2. `BusinessAutomationToolkit.run_operation()` is fire-and-forget
   (`{"status": "started", "run_id": ...}` immediately). A plan node's
   registered tool function must poll `toolkit._runs[run_id]` to
   completion itself, mirroring `smoke.py`'s `run_smoke_check()` pattern
   (FEAT-453 TASK-2395) — otherwise `AgentsFlow` marks every node "done"
   the instant a real, multi-second browser operation merely *starts*.
   `_make_run_operation_tool()` implements this wrapper (bounded 20s
   ceiling per row).

Real `ToolManager()` (not `_FakeToolManager`) constructed standalone with
no arguments and `.register_tool(name="run_operation", ..., function=...)`
— mirroring `test_integration.py`'s own `BasicAgent.tool_manager.register_tool()`
pattern (the `_FakeToolManager` there is used only for that file's separate
fan-out/resumability test, not the "real tool dispatch" one).

**Environment note (same pre-existing gap as FEAT-453's own session)**:
`packages/ai-parrot/tests/tools/execution_plan/`'s own test suite (run to
confirm no regression from this task's consumption of `ExecutionPlanToolkit`)
initially hit the known Cython `.so` build-artifact gap
(`parrot.utils.types`/`parrot.utils.parsers.toml` — compiled extensions
present in the main repo checkout but not per-worktree, since `.so` files
are gitignored). Resolved identically to FEAT-453's own precedent: copied
the same 2 `.so` files from the main repo into this worktree (confirmed
gitignored via `git check-ignore -v`, no risk of accidental commit) — not
committed, a local-environment fix only.

Full regression: `packages/ai-parrot-tools/tests/business_automation/` (91
passed) + `tests/scraping/` (919 total passed across both dirs, same 7
pre-existing/unrelated `CrawlEngine`/FEAT-013 failures) and
`packages/ai-parrot/tests/tools/execution_plan/` (71 passed, confirming
zero regression to `ExecutionPlanToolkit`'s own suite). `ruff check`
clean (all-modern-style, no pre-existing debt to preserve in this
brand-new file).

**FEAT-453 spec AC-17/AC-20 status**: both are now genuinely exercised
end-to-end against a real browser (AC-17 via TASK-2408's
`test_authenticated_flow_end_to_end`/`test_stub_regression_full_plan` plus
this task's resume/submit-gate tests; AC-20's `SmokeCheck` mechanism is
exercised indirectly here via the same `run_operation()`/`toolkit._runs`
polling pattern `run_smoke_check()` itself uses, though `SmokeCheck`
specifically was not re-tested standalone in this feature — its own
TASK-2395 mocked-executor tests remain the direct coverage). FEAT-453's
own spec file was not edited, per this task's own instruction.

**Deviations from spec**: `scripted_channel.py` was not created (the task
explicitly made this conditional on the existing stand-in proving
insufficient — it did not); the human-manager decision above is
documented exactly as the task's own scope requested ("document the
choice"). No other deviations — both required tests pass, using only the
real production `_run_plan()`/`make_import_progress_listener()`/
`_credential_resolver_from_broker()` (unused here but available)
integration points, no FEAT-453 production code modified.
