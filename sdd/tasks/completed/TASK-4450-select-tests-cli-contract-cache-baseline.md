# TASK-4450: `select_tests.py` — contract, green cache and baseline verdict

**Feature**: FEAT-699 — Tests Optimization in the SDD Flow (spec-declared Validation Contract)
**Spec**: `sdd/specs/tests-optimization-sdd-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4445, TASK-4447, TASK-4448, TASK-4449
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (CLI half), §5 AC "feature tier fresh by default" (design research S9). `select_tests.py`
is what `/sdd-done`, the `sdd-worker` fallback lane and `qa-runner` invoke. Today it never reads an index,
so it cannot know the contract, and its exit code is raw pytest red/green.

---

## Scope

New flags (keep every existing flag and its behaviour):
- `--index PATH` — per-spec index; when omitted, auto-discover: the single `sdd/tasks/index/*.json` under
  `--worktree` whose header `feature_id` equals `--feature` (none/ambiguous ⇒ no contract + a note).
- `--fresh` / `--use-cache` (mutually exclusive). Default: `--use-cache` for `--tier merge`, `--fresh` for
  `--tier feature` and `--tier task` (S9: the closeout table must be a real run).
- `--baseline` / `--no-baseline` (default: baseline ON when `--run` and any invocation fails). `--base` is the
  baseline ref; when an index is given and `--base` was not passed explicitly, use `origin/<header base_branch>`.

Behaviour:
1. Load the header via `contract.load_index_header`; `contract_from_index_header` → contract (a `ValueError`
   prints `error: <msg>` to stderr and exits 2 — fail closed, never silently fallback).
2. `plan_tests(..., contract=contract)`.
3. With cache on and `--feature` known: `namespace = cache_namespace(feature_id=, base_ref=, contract_digest=contract.digest if contract else "none")`;
   `plan = green_cache.filter_cached(worktree, plan, namespace=..., contract=contract)`; print `# cached: <target>`
   lines in plain mode.
4. Run as today, but: record with `suite=report.suite_name(invocation)`; collect failed node ids from
   `suite.nodes` (status failed/error); a failed invocation whose junit is missing/unparsable/unmapped ⇒ gate failure.
5. Baseline: after all invocations, when there are failed node ids and baseline is on,
   `verdicts = baseline.classify_failures(worktree=, base_ref=, failed_nodeids=, timeout_s=args.timeout_baseline or 600)`;
   re-record each affected suite with `baseline=` filled (`append_suite` with a `dataclasses.replace`d result);
   print a summary line `# baseline: new_red=<n> baseline_red=<m> unknown=<k>`.
6. Exit code: `0` when nothing failed, or when every failure is `baseline_red`; `1` when `baseline.gate_failed(...)`
   or any failure could not be classified (no junit / unmapped / baseline off); `2` usage/contract error (unchanged for empty task-tier plan).
7. Green cache record: after the run (cache on or off — recording is always useful), call
   `green_cache.record_green(worktree, namespace=, plan=<the executed plan>, nodes=<all nodes>, unmapped=<sum>, baseline_reds=<baseline_red nodeids>)`.
   `--no-ledger` also disables cache WRITES (report-only mode).
8. When `--feature` and `--report-task` are given, `report.append_cached(...)` the plan's `cached` targets.
- Add `--timeout-baseline SECONDS` (default 600).
- Tests in `tests/sdd_scripts/test_select_tests.py` (extend its `fixture_monorepo`).

**NOT in scope**: supervisor/engine path (TASK-4451); docs (TASK-4452).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/select_tests.py` | MODIFY | Flags + behaviour 1–8 |
| `tests/sdd_scripts/test_select_tests.py` | MODIFY | CLI tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# by-path kernel (select_tests.py:18-27): kernel = _load_kernel()  -> top-level `test_scope`
import test_scope.report as report_mod        # already lazily imported at select_tests.py:109
import test_scope.green_cache as green_cache  # TASK-4447
import test_scope.baseline as baseline        # TASK-4448
# kernel.contract.load_index_header / contract_from_index_header (TASK-4440)
```

### Existing Signatures to Use
```python
# scripts/sdd/select_tests.py
def _build_parser() -> argparse.ArgumentParser:   # line 30 (flags at 32-52)
def main(argv: list[str] | None = None) -> int:   # line 56
#   line 74-79: plan = kernel.plan_tests(worktree=, changed_files=kernel.changed_files(worktree, args.base), tier=, declared=)
#   line 148-202: per-invocation run loop; line 170 parse_junit(junit, suite=invocation.distribution, ...)
#   line 177-185: report_mod.append_suite(args.feature, args.report_task, suite, ...)
#   line 186-202: escalation-ledger branches (now dead for FEAT-699 plans; leave them — legacy-safe)
# kernel (after deps): plan_tests(..., contract=), green_cache.cache_namespace/filter_cached/record_green,
#   baseline.classify_failures/gate_failed/summarize, report.suite_name/append_cached, SuiteResult.nodes/unmapped/baseline
```

### Does NOT Exist
- ~~`--index`, `--fresh`, `--use-cache`, `--baseline`, `--timeout-baseline` flags~~ — created here
- ~~baseline classification inside `plan_tests`~~ — it is a post-run step in callers only

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/select_tests.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_select_tests.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:scripts/sdd/select_tests.py#main",
    "sym:scripts/sdd/select_tests.py#_build_parser"
  ]
}
```

---

## Implementation Notes

- Keep `main` readable: extract `_resolve_index(args, worktree, kernel)`, `_run_invocations(...)` and
  `_apply_baseline(...)` helpers inside this script (each with a Google docstring).
- Recording remains best-effort (never changes the exit code by itself), EXCEPT that a failed invocation
  without node evidence now makes the gate fail (it already would: its pytest exit code is non-zero).
- `argparse` default for `--base` must become `None` so "not passed explicitly" is detectable; resolve to
  `origin/dev` when no index header supplies a base.

---

## Implementation Blueprint

### Steps (in order)
1. Flags; `--base` default `None` + resolution — *why*: baseline must target the index's `base_branch`.
2. Index/contract resolution + `plan_tests(contract=)` — *why*: S2 entry-point routing.
3. Cache filter + record; baseline classification + exit code — *why*: S9 fresh closeout, new-red gate.
4. Tests.

### `scripts/sdd/select_tests.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'parser.add_argument("--tier", required=True, choices=("task", "merge", "feature"))' select_tests.py)
# REPLACE `parser.add_argument("--base", default="origin/dev")` (select_tests.py:33) with:
    parser.add_argument("--base", default=None, help="diff + baseline ref (default: origin/<index base_branch> or origin/dev)")
    parser.add_argument("--index", type=Path, default=None, help="per-spec index (FEAT-699 test_contract source)")
    cache = parser.add_mutually_exclusive_group()
    cache.add_argument("--use-cache", dest="use_cache", action="store_true", default=None)
    cache.add_argument("--fresh", dest="use_cache", action="store_false")
    base = parser.add_mutually_exclusive_group()
    base.add_argument("--baseline", dest="baseline", action="store_true", default=True)
    base.add_argument("--no-baseline", dest="baseline", action="store_false")
    parser.add_argument("--timeout-baseline", type=int, default=600, metavar="SECONDS")
```
```python
def _resolve_index(args: argparse.Namespace, worktree: Path, kernel: ModuleType) -> tuple[dict, list[str]]:
    """Return (index header or {}, notes). Explicit --index wins; else auto-discover by --feature."""
    # FILL IN — bounded by Scope "--index" bullet; ValueError from load_index_header propagates
    raise NotImplementedError
# FILL IN in main(): steps 1–8 of Scope, in that order; exit codes per step 6
```

### FILL IN checklist
- [ ] `_resolve_index`, base resolution, contract load (exit 2 on ValueError)
- [ ] cache defaults per tier; `--no-ledger` disables cache writes
- [ ] `suite_name` in recording; failed-node collection; baseline + re-record; exit code
- [ ] `append_cached` when recording
- [ ] tests: contract plan used (`--index`), malformed contract exit 2, second `--tier merge --run` reports `# cached:`,
      `--tier feature` default fresh, baseline-red-only failure exits 0 (monkeypatch `baseline.classify_failures`),
      new red exits 1

---

## Acceptance Criteria

- [ ] With an index carrying `test_contract`, the printed plan contains the contract operands and no import targets.
- [ ] Second merge-tier `--run` in the same worktree prints `# cached:` for the unchanged green file.
- [ ] `--tier feature` does not consult the cache unless `--use-cache`.
- [ ] Exit 0 when all failures are baseline reds; 1 on any new red/unknown; 2 on malformed contract.
- [ ] Existing `test_select_tests.py` tests pass.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_select_tests.py -q`

---

## Test Specification

```python
def test_merge_run_uses_cache_second_time(fixture_monorepo, capsys): ...
def test_feature_tier_fresh_by_default(fixture_monorepo, capsys): ...
def test_baseline_red_only_exits_zero(fixture_monorepo, monkeypatch): ...
def test_malformed_contract_exits_2(fixture_monorepo): ...
# FILL IN bodies — fixture_monorepo must be a git repo for the cache (git init + commit in the fixture)
```

---

## Agent Instructions

Standard. Close with `scripts/sdd/close_task.sh TASK-4450 tests-optimization-sdd-flow verified`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
