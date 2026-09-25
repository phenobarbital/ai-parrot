# TASK-3800: ValidationSupervisor records escalations + logs the selection summary

**Feature**: FEAT-604 — Merge-Tier Validation Cost
**Spec**: `sdd/specs/merge-tier-validation-cost.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3797, TASK-3798
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 — the headline defect: `pending_escalations` skips a suite
whose blobs match a recorded green run, but the background
`ValidationSupervisor` that actually runs merge-tier validations for
`sdd-worker` NEVER writes the ledger, so `skipped_escalations` is permanently
empty on that path. This task makes the supervisor attribute each
invocation's exit code and write the green/red record, reusing the exact
contract `select_tests.py --run` implements (now extended for cap escalations
by TASK-3799's reference shape). It also implements resolved Open Question 3:
`start()` writes a selection-summary header into the supervised log so
`coder_bg_status`'s bounded tail shows WHY a validation was cheap.

---

## Scope

- Thread the `ScopePlan` and the FIRST invocation into `_supervise` (today it
  receives only `remaining_invocations` — the first invocation's identity is
  lost, so per-invocation attribution is impossible).
- Add `async def _record_invocation_outcome(self, *, worktree, invocation,
  plan, exit_code) -> None` per the spec skeleton: green (exit 0) records the
  escalation's blobs (core + cap, mirroring TASK-3799's writer shape); red OR
  timed-out re-arms (`record_red_run`); an invocation with no escalated
  target records nothing; NEVER raises (log + swallow).
- Call it after the first invocation's `_await_one` and after each chained
  invocation's `_await_one` inside the loop.
- Ledger helpers are sync file I/O — call through `asyncio.to_thread`
  (pattern: `qa.py:633`).
- `start()`: write the selection header before the first invocation line, and
  in the empty-plan branch:
  `# selection tier=<tier> escalated=[...] skipped_escalations=[...]` plus one
  `# note: <note>` line per `plan.notes` entry.
- CREATE `test_supervisor_ledger.py` with the four M1 unit tests, the
  selection-header test, and the two spec §4 integration tests.

**NOT in scope**: any `test_scope/` module (TASK-3797/3798), CLI/QA writers
(TASK-3799), `coder_bg_status`/`BackgroundStatus` schema (explicitly rejected
in resolved Open Question 3 — log lines only), the chained one-at-a-time loop
itself (spec Non-Goal: no cross-distribution parallelism).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | per-invocation attribution + ledger writes + selection header |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py` | CREATE | M1 unit + integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope.select import changed_files, plan_tests  # verified: background.py:45 (existing)
# NEW imports this task adds to background.py (verify they exist post-TASK-3797):
from parrot.flows.dev_loop.test_scope.context import record_green_escalation, record_red_run  # verified: context.py:101,114
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py (post PR #1494)
_DEFAULT_BASE_REF = "origin/dev"                  # line 73
async def start(self, ...) -> BackgroundRegistration: ...   # line ~486; plan built at line 573:
#     plan = await self._plan_selection(worktree=worktree, tier=tier, base_ref=base_ref)
#     empty-plan branch writes b"# no applicable pytest invocations for this selection\n"  # line 579
#     first, *rest = plan.invocations              # line 586
#     header write: self._append_log, log_path, f"# $ {shlex.join(first.argv)} (distribution={first.distribution})\n"  # line 589
#     self._supervise(..., remaining_invocations=list(rest), worktree=worktree)  # lines 611-620
async def _supervise(self, *, execution_id, handle, process, log_path, deadline,
                     remaining_invocations: list["PytestInvocation"], worktree: Path) -> None:  # line ~719
#     first await: outcome, exit_code = await self._await_one(process=process, log_path=log_path, deadline=deadline)  # line 731
#     chained loop: for invocation in remaining_invocations:  (line 732); per-iteration result:
#     next_outcome, next_exit_code = await self._await_one(process=next_process, log_path=log_path, deadline=deadline)  # line 759
async def _await_one(...) -> Tuple[Literal["completed", "failed", "timed_out"], int]: ...  # line ~771
@staticmethod def _append_log(log_path: Path, text: str) -> None: ...  # line ~834
# TYPE_CHECKING import block already brings PytestInvocation, ScopePlan (line 49)

# after TASK-3797/3798:
plan.cap_hits: dict[str, tuple[str, ...]];  plan.cap_impacted: dict[str, str]
record_green_escalation(worktree, hit_dists, core_files, impact_files=(), impacted_hashes={})

# reference writer shape to mirror: scripts/sdd/select_tests.py:88-102 (as extended by TASK-3799)
# test fixture: packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py::git_sandbox_feature
# controlled-exit child pattern + protected_argv identity monkeypatch:
#   packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py
```

### Does NOT Exist
- ~~`ValidationSupervisor` importing anything from `test_scope.context`~~ —
  today it imports only `changed_files, plan_tests` (`background.py:45`);
  THIS TASK adds the context import. That absence is the defect, not a
  pattern to preserve.
- ~~a per-invocation outcome record in `BackgroundStatus`~~ — the supervisor
  reports ONE terminal outcome per handle; attribution lives only in the
  ledger and the log.
- ~~`skipped_escalations` as a `coder_bg_status` field~~ — resolved Open
  Question 3 chose log lines; do NOT touch the status schema.
- ~~a ledger entry for a `mirror`/`import`/`declared` target~~ — escalations
  only (`reason` in `("core", "escalated")`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor._supervise",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor.start",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor._await_one",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py#record_green_escalation",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py#record_red_run"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **A ledger failure is logged and swallowed, NEVER a failed validation**
  (spec §3 M1): wrap the whole `_record_invocation_outcome` body in
  try/except → `self.logger.warning` — it degrades the NEXT selection, it
  must never change THIS handle's outcome or exit code.
- **Timed-out counts as red** (re-arm): a suite that did not complete proved
  nothing; re-arming is the fail-open direction. A `timed_out` outcome also
  breaks the chained loop today — invocations never launched record NOTHING
  (their prior state stays whatever it was).
- Attribution is per invocation: `invocation.distribution` +
  `invocation.targets` reasons decide what to write, mirroring
  `select_tests.py` (spec §7: "instead of inventing a second contract").
- Async boundary: `asyncio.to_thread(record_green_escalation, ...)` /
  `asyncio.to_thread(record_red_run, ...)` (pattern `qa.py:633`).
- The nested-bwrap test pattern (`protected_argv` monkeypatched to identity,
  `python -c "import sys; sys.exit(N)"` children) is documented in
  `test_background_validation.py` — reuse it verbatim.

---

## Implementation Blueprint

### Steps (in order)
1. Extend `start()` to log the selection header and pass `plan` + `first`
   into `_supervise` — *why*: attribution needs the invocation identity that
   is currently dropped, and the header is resolved Open Question 3.
2. Add `_record_invocation_outcome` — *why*: single, never-raising write path
   mirroring the CLI contract.
3. Call it after the first `_await_one` and inside the chained loop — *why*:
   per-invocation attribution is exactly "after each invocation's own exit".
4. Write the tests (unit + the two integration rows of spec §4).

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '# no applicable pytest invocations for this selection' …/sdd_coder/background.py)
# REPLACE the empty-plan write — anchor `b"# no applicable pytest invocations for this selection\n"`
# (verified: background.py:579): write _selection_header(plan) + that line instead, via
# asyncio.to_thread(self._append_log, ...) after an empty write_bytes(b"").
```
```python
# occurrences: 1 (verified: grep -cF 'first, *rest = plan.invocations' …/sdd_coder/background.py)
# AFTER — insert the header write below `first, *rest = plan.invocations` (verified:
# background.py:586), BEFORE the existing `# $ …` line:
            await asyncio.to_thread(self._append_log, log_path, self._selection_header(plan))
```
```python
# NEW module-level-free helper on the class (place near _append_log, background.py:~834):
    @staticmethod
    def _selection_header(plan: "ScopePlan") -> str:
        """One `# selection …` line + one `# note: …` line per plan note (FEAT-604, OQ3)."""
        lines = [
            f"# selection tier={plan.tier}"
            f" escalated=[{', '.join(plan.escalated)}]"
            f" skipped_escalations=[{', '.join(plan.skipped_escalations)}]\n"
        ]
        lines += [f"# note: {note}\n" for note in plan.notes]
        return "".join(lines)
```
```python
# occurrences: 1 (verified: grep -cF 'remaining_invocations=list(rest),' …/sdd_coder/background.py)
# MODIFY the ensure_future call — anchor `remaining_invocations=list(rest),` (verified:
# background.py:618): add two kwargs
                first_invocation=first,
                plan=plan,
```
```python
# occurrences: 1 (verified: grep -cF 'remaining_invocations: list["PytestInvocation"],' …/sdd_coder/background.py)
# MODIFY _supervise's signature — anchor `        remaining_invocations: list["PytestInvocation"],`
# (verified: background.py:727 — NOTE: the spec's Edit Sites table says 664; the anchor moved
# after PR #1494, re-verified 2026-09-25): add
        first_invocation: "PytestInvocation",
        plan: "ScopePlan",
```
```python
# occurrences: 1 (verified: grep -cF 'outcome, exit_code = await self._await_one(process=process, log_path=log_path, deadline=deadline)' …/background.py)
# AFTER — insert below that first _await_one (verified: background.py:731):
        await self._record_invocation_outcome(
            worktree=worktree, invocation=first_invocation, plan=plan, exit_code=exit_code
        )
# and inside the chained loop, insert the same call with `invocation` / `next_exit_code`
# directly below `next_outcome, next_exit_code = await self._await_one(` 's closing paren
# (occurrences: 1, verified: grep -cF 'next_outcome, next_exit_code = await self._await_one(' …/background.py; background.py:759).
```
```python
# NEW method (place after _supervise, before _await_one):
    async def _record_invocation_outcome(
        self, *, worktree: Path, invocation: "PytestInvocation", plan: "ScopePlan", exit_code: int
    ) -> None:
        """Record this invocation's escalation verdict in the per-worktree ledger.

        Green (exit 0) records the blobs that escalation covered; anything else
        re-arms (`record_red_run`) — a timed-out suite proved nothing, so
        re-running is the fail-open direction. An invocation with no escalated
        target records nothing. Never raises: a ledger failure is logged and
        swallowed — it degrades the NEXT selection, never THIS validation.
        """
        try:
            is_core = any(t.reason == "core" for t in invocation.targets)
            is_cap = any(t.reason == "escalated" for t in invocation.targets)
            if not (is_core or is_cap):
                return
            dist = invocation.distribution
            if exit_code != 0:
                await asyncio.to_thread(record_red_run, worktree, [dist])
                return
            core_files = [hit.path for hit in plan.core_hits if dist in hit.distributions]
            # FILL IN: impact_files / impacted_hashes from plan.cap_hits / plan.cap_impacted,
            # then the record_green_escalation to_thread call — mirror TASK-3799's CLI shape
            # verbatim (select_tests.py --run); skip the write when both file lists are empty.
        except Exception:  # noqa: BLE001 — ledger writes must never fail a validation
            self.logger.warning("could not record escalation outcome for %s", invocation.distribution, exc_info=True)
```
**Why**: threading `first`+`plan` is the minimal change that makes attribution
possible without touching the handle's single-terminal-outcome contract
("Does NOT Exist": no per-invocation `BackgroundStatus` record). The header
goes through `_append_log` so tests can read it with the same bounded-tail
reader `coder_bg_status` uses.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py` (CREATE)
```python
"""FEAT-604 M1 — the supervisor becomes a ledger writer (+ selection log header)."""

from __future__ import annotations

# FILL IN: imports + fixtures — reuse conftest.py::git_sandbox_feature and
# test_background_validation.py's controlled-exit-child pattern
# (`python -c "import sys; sys.exit(N)"`, background_module.protected_argv
# monkeypatched to identity) — bounded by spec §4 Test Data.


async def test_supervisor_records_green_escalation(...):
    """A green escalated invocation writes the distribution's blobs (core and/or cap)."""


async def test_supervisor_rearms_on_red_escalation(...):
    """A red escalated invocation drops the record (record_red_run)."""


async def test_supervisor_rearms_on_timeout(...):
    """A timed-out escalated invocation re-arms (proved nothing ⇒ fail-open)."""


async def test_supervisor_records_nothing_without_escalation(...):
    """A mirror/import-only invocation writes no ledger entry."""


async def test_supervisor_ledger_failure_never_fails_validation(...):
    """Unwritable ledger (e.g. read-only git dir) → logged and swallowed; receipt stays green."""


async def test_start_logs_selection_summary(...):
    """start() writes '# selection tier=…' + '# note: …' lines; the all-skipped empty plan
    is distinguishable from an empty diff (AC: selection-summary header)."""


async def test_second_merge_validation_skips_unchanged_suites(...):
    """Integration: two consecutive merge-tier validations on a temp repo — the second
    plans strictly fewer invocations (spec §4 integration row 1)."""


async def test_red_first_run_forces_full_second_run(...):
    """Integration: a red first validation re-arms everything; the second plans the same
    scope (spec §4 integration row 2)."""
```
**Why**: the four M1 unit rows + the OQ3 header test + both §4 integration
rows live together because they all need the same sandbox fixture stack.

### FILL IN checklist
- [ ] `_record_invocation_outcome` green branch — cap args mirroring `select_tests.py --run`; bounded by "no second contract" (spec §7)
- [ ] test fixtures/bodies — controlled-exit children only, never real suites; bounded by spec §4 Test Data

---

## Acceptance Criteria

- [ ] A merge-tier validation via `coder_run_validation` writes a ledger record for every escalated invocation, green or red (AC1)
- [ ] Red AND timed-out escalated invocations re-arm their distribution
- [ ] A ledger write failure never changes the validation's outcome (AC6)
- [ ] Every supervised log begins with the selection-summary header; empty plans included (AC: OQ3)
- [ ] No change to `BackgroundStatus` / `coder_bg_status` schema
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py -q` passes
- [ ] `ruff check` and `black -l 120 --check` clean on touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_merge_scope_and_bg_wait.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_status.py -q`

---

## Test Specification

See the CREATE block above — eight named tests with docstrings; bodies FILL IN.

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3797 and TASK-3798 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code; if anything drifted, update the contract FIRST
4. **Update status** in the per-spec index → `"in-progress"`
5. **Implement** from the Implementation Blueprint; never change a fixed signature or path
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
