# TASK-4451: ValidationSupervisor + engine — declared tests, contract, cache, baseline

**Feature**: FEAT-699 — Tests Optimization in the SDD Flow (spec-declared Validation Contract)
**Spec**: `sdd/specs/tests-optimization-sdd-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4445, TASK-4447, TASK-4448, TASK-4449
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (supervisor half), §5 AC "`_plan_selection` passes task declarations and the contract"
(design research S2). Verified gap: `ValidationSupervisor._plan_selection` (background.py:718-728) calls
`plan_tests(worktree=, changed_files=, tier=)` with NO declared commands and NO contract — so the real
`sdd-worker` merge gate (`coder_run_validation`) runs only mirror/impact. The engine already resolves the
per-spec index (`ctx.index_path`, `_resolve_feature` engine.py:1487-1544) and validates `task_ids` against
it; this task hands the supervisor the index path so it can read the tasks' `## Validation Commands` and
the header's `test_contract`.

**Decided deviations from the spec's Edit Sites table** (recorded here so nobody re-adds them):
- `sdd_coder/toolkit.py` needs NO change — `coder_run_validation`'s signature is unchanged; the engine
  supplies the index path internally.
- `test_scope/guard.py` needs NO change — the guard plans the TASK tier, where the contract is not used
  (spec §2 table); it picks up the file-level mirror automatically through `plan_tests` (TASK-4445).

---

## Scope

- `ValidationSupervisor.start(...)`: add keyword `index_path: Optional[Path] = None` (NOT part of
  `_payload_hash` — derived server-side, same rationale as `base_ref`, see its docstring at background.py:517-521).
- `_plan_selection(..., index_path, task_ids)`: when `index_path` is given, read the header
  (`contract.load_index_header`), resolve the contract (`contract_from_index_header`; a `ValueError` is an
  admission failure → raise `ValueError` so the engine maps it to `invalid_arguments`), read each
  `task_ids` entry's task file (from the index's `tasks[].file`, relative to `worktree`) and
  `parse_validation_commands` → `declared`. Call `plan_tests(..., declared=declared, contract=contract)`.
  Merge tier: apply `green_cache.filter_cached` with namespace from (`feature_id`, base, contract digest);
  feature tier: fresh (S9). Write the cached targets into the selection header log (`# cached: <t>`).
- After each invocation: record with `suite=report.suite_name(invocation)`; keep node evidence; on a non-zero
  exit with failed nodes, run `baseline.classify_failures` via `asyncio.to_thread` bounded by the REMAINING
  deadline (skip ⇒ `unknown` when < 30 s remain); store verdicts in the recorded `SuiteResult.baseline`.
- Terminal outcome: an invocation whose failures are ALL `baseline_red` counts as passed for the handle's
  terminal receipt (log line `# baseline: only baseline reds — gate passes`); any `new_red`/`unknown`/
  unclassifiable failure keeps it failed. `record_green` after each invocation (merge and feature tiers).
  Write `report.append_cached` for the plan's cached targets per task id.
- `base_ref` for baseline classification: `origin/<header base_branch>` (falls back to `_DEFAULT_BASE_REF`).
- `SddCoderEngine.run_validation`: pass `index_path=Path(ctx.index_path)` to `start()`.
- Update the class docstring paragraph at background.py:459-472 ("Known, bounded scope decisions") — it now
  DOES read declared Validation Commands.
- Tests: extend `test_background_validation.py`; new `test_background_contract.py`.

**NOT in scope**: CLI (TASK-4450); docs (TASK-4452); `HOTFIX-*`/brief flows (spec Non-Goal — `_TASK_ID_RE` unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | index-aware selection, cache, baseline, outcome |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | pass `index_path` |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py` | MODIFY | regressions for existing behaviour |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_contract.py` | CREATE | S2/S9 behaviour |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# background.py today:
from parrot.flows.dev_loop.test_scope.context import record_green_escalation, record_red_run  # line 47
from parrot.flows.dev_loop.test_scope.select import changed_files, plan_tests                 # line 48
# test_report is the module alias used at background.py:870/901/911 (import line: verify with grep '^from .*report' background.py)
# NEW (all from parrot.flows.dev_loop.test_scope.*, created by dependencies):
from parrot.flows.dev_loop.test_scope.contract import contract_from_index_header, load_index_header, parse_validation_commands
from parrot.flows.dev_loop.test_scope import green_cache, baseline
```

### Existing Signatures to Use
```python
# sdd_coder/background.py
_TASK_ID_RE = re.compile(r"^TASK-\d{1,5}$")       # line 69
_DEFAULT_BASE_REF = "origin/dev"                   # line 79
class ValidationSupervisor:                        # line 435
    async def start(self, *, feature, worktree, execution_id, task_ids, tier, timeout_seconds, request_id,
                    base_ref=None) -> BackgroundRegistration:     # line 492
    #   line 579: plan = await self._plan_selection(worktree=worktree, tier=tier, base_ref=base_ref)
    #   line 596: feature_id = await asyncio.to_thread(self._resolve_feature_id, worktree, feature)
    async def _plan_selection(self, *, worktree, tier, base_ref=None) -> ScopePlan:  # line 718
    #   line 728: return await asyncio.to_thread(plan_tests, worktree=worktree, changed_files=changed, tier=tier)
    async def _supervise(self, *, execution_id, handle, process, log_path, deadline, remaining_invocations,
                         first_invocation, plan, worktree, feature_id="", task_ids=None, tier="merge",
                         base_ref=_DEFAULT_BASE_REF, first_junit=None) -> None:  # line 737
    def _argv_with_junit(feature_id, task_id, invocation, ordinal, *, enabled=True)  # line 863 (static)
    async def _record_test_results(self, *, worktree, feature_id, task_ids, invocation, junit_path, exit_code,
                                   duration_s, timed_out, tier, base_ref) -> None:  # line 876 (suite=invocation.distribution at 903)
    async def _record_invocation_outcome(self, *, worktree, invocation, plan, exit_code) -> None:  # line 923
# sdd_coder/engine.py
async def run_validation(self, feature, worktree, execution_id, task_ids, tier, timeout_seconds, request_id)  # line 1149
#   line 1220-1229: registration = await self._validation_supervisor.start(..., base_ref=base_ref)
#   ctx.index_path: str  (dataclass field, engine.py:232)
```

### Does NOT Exist
- ~~`start(index_path=...)`~~ — added here
- ~~a supervisor that reads task files today~~ — it never did (class docstring background.py:459-472 says so)
- ~~`HOTFIX-*` ids in `_TASK_ID_RE`~~ — out of scope

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_contract.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor.start",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor._plan_selection",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor._supervise",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor._record_test_results",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.run_validation"
  ]
}
```

---

## Implementation Notes

- All sync kernel calls go through `asyncio.to_thread` (never block the loop — codebase conventions).
- Use `self.logger` for every new branch (admission failure, baseline skipped for deadline, cache stats).
- `index_path=None` (existing callers/tests) keeps today's behaviour exactly, minus suite escalation
  (that change comes from TASK-4445 and is expected).
- The sdd_coder tests need the hermetic-root fixture (memory: "sdd-coder evidence store always-on");
  copy the setup pattern from the existing `test_background_validation.py` tests.

---

## Implementation Blueprint

### Steps (in order)
1. `engine.run_validation` passes `index_path` — *why*: the engine already owns the resolved index.
2. `start()` kwarg + `_plan_selection` declared/contract/cache — *why*: S2.
3. Per-invocation `suite_name` recording, node collection, baseline, outcome override, `record_green` — *why*: new-red gate + cache.
4. Docstring update; tests.

### `engine.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'registration = await self._validation_supervisor.start(' engine.py)
# AFTER — insert below `                base_ref=base_ref,` inside that call (verified: engine.py:1228; FILL IN: confirm occurrence count of the kwarg line within the call)
                index_path=Path(ctx.index_path),
```

### `background.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'return await asyncio.to_thread(plan_tests, worktree=worktree, changed_files=changed, tier=tier)' background.py)
# REPLACE `_plan_selection` (background.py:718-728) with:
    async def _plan_selection(
        self,
        *,
        worktree: Path,
        tier: Literal["merge", "feature"],
        base_ref: Optional[str] = None,
        index_path: Optional[Path] = None,
        task_ids: Sequence[str] = (),
        feature_id: str = "",
    ) -> "ScopePlan":
        """Tier-scoped selection: task declarations ∪ spec contract (FEAT-699); never a free-form argv.

        Raises:
            ValueError: the index header carries a malformed ``test_contract`` (admission failure).
        """
        changed = await asyncio.to_thread(changed_files, worktree, base_ref or _DEFAULT_BASE_REF)
        declared: list[list[str]] = []
        contract = None
        # FILL IN: when index_path: load header, contract, read each task file's Validation Commands
        plan = await asyncio.to_thread(
            plan_tests, worktree=worktree, changed_files=changed, tier=tier, declared=declared, contract=contract
        )
        # FILL IN: merge tier → green_cache.filter_cached(...) via to_thread — bounded by S9 (feature tier fresh)
        return plan
```
```python
# FILL IN in start(): add `index_path: Optional[Path] = None` kwarg; call _plan_selection with index_path,
#   task_ids and the resolved feature_id (move the `_resolve_feature_id` call ABOVE planning).
# FILL IN in _record_test_results: suite=test_report.suite_name(invocation); return the parsed SuiteResult.
# FILL IN in _supervise: collect failed nodes, baseline (deadline-bounded), outcome override, record_green, append_cached.
```

### FILL IN checklist
- [ ] engine passes `index_path`
- [ ] `_plan_selection` declared/contract/cache
- [ ] `start()` ordering + kwarg (not in `_payload_hash`)
- [ ] `_supervise` baseline + outcome + cache record
- [ ] class docstring update
- [ ] tests: declared+contract reach `plan_tests` (spy), malformed contract ⇒ `ValueError`/no spawn,
      second merge validation logs `# cached:`, feature tier never filters, baseline-red-only ⇒ outcome completed,
      new red ⇒ failed, `index_path=None` back-compat

---

## Acceptance Criteria

- [ ] `test_supervisor_passes_declared_and_contract` (spec §4) passes.
- [ ] Baseline-red-only failures settle the handle as `completed`; a new red as `failed`.
- [ ] Existing `test_background_validation.py` and `test_supervisor_ledger.py` pass.
- [ ] No blocking call on the event loop (all kernel calls via `asyncio.to_thread`).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_contract.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py -q`

---

## Test Specification

```python
# test_background_contract.py
async def test_supervisor_passes_declared_and_contract(tmp_path, monkeypatch): ...
async def test_baseline_red_only_settles_completed(tmp_path, monkeypatch): ...
async def test_merge_validation_uses_green_cache(tmp_path, monkeypatch): ...
async def test_feature_tier_is_fresh(tmp_path, monkeypatch): ...
# FILL IN: reuse the supervisor/registry construction helpers from test_background_validation.py
```

---

## Agent Instructions

Standard. Close with `scripts/sdd/close_task.sh TASK-4451 tests-optimization-sdd-flow verified`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: toolkit.py and guard.py intentionally untouched (see Context).
