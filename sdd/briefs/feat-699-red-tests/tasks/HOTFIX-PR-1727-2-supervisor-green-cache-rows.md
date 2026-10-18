# HOTFIX-PR-1727-2: Rewrite the supervisor spec §4 integration rows against the green cache

**Feature**: PR-1727 — FEAT-699 red tests
**Spec**: `sdd/briefs/feat-699-red-tests.brief.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:1e684c2b1d72`

---

## Context

`test_supervisor_ledger.py::test_second_merge_validation_skips_unchanged_suites` and
`::test_red_first_run_forces_full_second_run` drive the REAL `plan_tests` through
`ValidationSupervisor` and assert that the escalation ledger makes a second plan
smaller / a red run re-arms it. FEAT-699 removed suite escalation from `plan_tests`
(a core hit is only a note; `escalated` / `skipped_escalations` are always empty), so
the first test fails `assert 1 < 1` (`:375`) and the second finds the seeded ledger
record untouched (`:416`). The replacement mechanism is the green cache applied by
`ValidationSupervisor._plan_selection` at merge tier (`background.py:788-800`) and fed
by `_record_green_cache` (`:1110`) from junit node evidence. Brief decision 3: keep the
two integration rows, re-targeted at the green cache.

---

## Scope

- Replace `_cap_forcing_plan` (`:300-318`) with `_real_plan_with_argv(argv)`: same
  wrapper shape (real `plan_tests`, every invocation's argv replaced by the controlled
  child, `**_extra` swallowing `declared=` / `contract=`), default `ScopePolicy()`.
- Replace the `cap_worktree` fixture (`:321-335`) with `cache_worktree`: a real git repo
  containing `pyproject.toml`, `packages/a/pyproject.toml`, `packages/a/src/pa/__init__.py`,
  `packages/a/src/pa/leaf.py`, `packages/a/tests/test_leaf.py` (`import pa.leaf`),
  `task.md` with `## Validation Commands` → `` - `pytest packages/a/tests/test_leaf.py -q` ``,
  and `sdd/tasks/index/demo.json` with header
  `{"feature": "demo", "feature_id": "FEAT-604", "base_branch": "main", "tasks": [{"id": "TASK-0001", "file": "task.md"}]}`
  (no `test_contract` → fallback mode). All committed.
- Add two `python -c` children that honour `--junitxml=<path>` (pattern:
  `test_background_contract.py::_JUNIT_FAILURE_CHILD`, lines 163-170) writing an xunit1
  report with `<testcase file='packages/a/tests/test_leaf.py' classname='packages.a.tests.test_leaf' name='test_leaf'>`:
  `_JUNIT_GREEN_CHILD` (no `<failure/>`, `tests='1' failures='0'`, exit 0) and
  `_JUNIT_RED_CHILD` (`<failure/>`, `failures='1'`, exit 1).
- Rewrite test 1 as `test_second_merge_validation_skips_cached_targets`: green child;
  `supervisor.start(feature="FEAT-604", ..., tier="merge", index_path=<index>)`; settle;
  `status.outcome == "completed"`; then
  `second = await supervisor._plan_selection(worktree=..., tier="merge", index_path=<index>, task_ids=["TASK-0001"], feature_id="FEAT-604")`
  and assert `second.cached == ("packages/a/tests/test_leaf.py",)`,
  `second.invocations == ()`, `len(second.invocations) < len(first.invocations)` where
  `first` is the same `_plan_selection` call made BEFORE `start`
  (`first.cached == ()` and exactly one invocation).
- Rewrite test 2 as `test_red_run_leaves_no_green_cache_entry`: seed a matching green
  entry first by running `_plan_selection` + `green_cache.record_green(worktree, namespace=ns, plan=first, nodes=[("packages/a/tests/test_leaf.py::test_leaf", "passed")])`
  with `ns = green_cache.cache_namespace(feature_id="FEAT-604", base_ref="origin/main", contract_digest="")`,
  and assert the seeded entry is visible (`_plan_selection(...).cached == ("packages/a/tests/test_leaf.py",)`);
  then run `supervisor.start` with the red child, settle, `status.outcome == "failed"`;
  assert the store no longer holds the entry:
  `green_cache._read_store(worktree_git_dir(worktree) / green_cache.CACHE_FILENAME, ns) == {}`
  and a fresh `_plan_selection` has `cached == ()` with the same single invocation.
- Both tests `monkeypatch.setenv("SDD_TEST_REPORT_DIR", str(tmp_path / "reports"))`,
  `monkeypatch.setattr(background_module, "changed_files", lambda wt, base_ref: ["packages/a/src/pa/leaf.py"])`,
  `monkeypatch.setattr(background_module, "plan_tests", _real_plan_with_argv(<child>))`,
  `monkeypatch.setattr(background_module, "protected_argv", lambda cwd, argv: list(argv))`;
  the red test additionally
  `monkeypatch.setattr(background_module.baseline, "classify_failures", lambda **kwargs: tuple(BaselineVerdict(n, "new_red") for n in kwargs["failed_nodeids"]))`
  (there is no `origin/main` in the temp repo to classify against).
- Drop the now-unused `record_green_escalation` import only if no other test in the file
  uses it (the M1 tests at the top DO use `read_ledger` / `record_green_escalation` — keep them).

**NOT in scope**: `background.py`, `green_cache.py`, `select.py` (no production change);
the legacy `_record_invocation_outcome` ledger writes (issue:9b27d46a6bb2) — the new
tests must not assert `read_ledger(...)` either way; the other tests in this file.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py` | MODIFY | replace the two spec §4 integration rows and their fixture/helper with green-cache rows |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.sdd_coder import background as background_module  # verified: test_supervisor_ledger.py:16
from parrot.flows.dev_loop.sdd_coder.background import BackgroundRegistry, ValidationSupervisor  # :17
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore  # :18
from parrot.flows.dev_loop.test_scope import green_cache  # verified: background.py:47 imports `baseline, green_cache` from this package
from parrot.flows.dev_loop.test_scope.context import worktree_git_dir  # verified: context.py:21
from parrot.flows.dev_loop.test_scope.baseline import BaselineVerdict  # verified: test_background_contract.py uses BaselineVerdict(nodeid, verdict)
from parrot.flows.dev_loop.test_scope.datatypes import PytestInvocation, ScopePlan  # :20
from parrot.flows.dev_loop.test_scope.policy import ScopePolicy  # :21
from parrot.flows.dev_loop.test_scope.select import plan_tests as real_plan_tests  # :22
```

### Existing Signatures to Use
```python
# background.py:493
async def start(self, *, feature: str, worktree: Path, execution_id: str, task_ids: list[str],
                tier: Literal["merge", "feature"], timeout_seconds: int, request_id: str,
                base_ref: Optional[str] = None, index_path: Optional[Path] = None) -> BackgroundRegistration
# background.py:753 — applies green_cache.filter_cached ONLY when tier == "merge" AND index_path is not None
async def _plan_selection(self, *, worktree: Path, tier: str, base_ref: Optional[str] = None,
                          index_path: Optional[Path] = None, task_ids: Sequence[str] = (),
                          feature_id: str = "") -> ScopePlan
# background.py:994 — "FEAT-604" matches _FEATURE_ID_RE (:78) and is returned as-is
def _resolve_feature_id(worktree: Path, feature: str) -> str
# background.py:837 — header["base_branch"] == "main" → "origin/main"
def _base_ref_from_header(header: dict[str, object]) -> str
# background.py:1021 — appends "-o junit_family=xunit1 --junitxml=<report_root()/FEAT-604/junit/TASK-0001--<suite>--0.xml>"
def _argv_with_junit(self, feature_id, task_id, invocation, ordinal, *, enabled=True)
# background.py:1110 — records result.nodes via green_cache.record_green; result None → no-op
async def _record_green_cache(self, *, worktree, namespace, plan, invocation, result)
# green_cache.py:38
def cache_namespace(*, feature_id: str, base_ref: str, contract_digest: str) -> str
# green_cache.py:156 — drops targets whose stored key matches; returns plan unchanged when the store is empty
def filter_cached(worktree: Path, plan: ScopePlan, *, namespace: str, contract=None, policy=None, index=None) -> ScopePlan
# green_cache.py:223 — never raises; needs pyproject.toml + packages/<d>/pyproject.toml blobs in git
def record_green(worktree: Path, *, namespace: str, plan: ScopePlan, nodes: Sequence[tuple[str, str]],
                 unmapped: int = 0, baseline_reds: Collection[str] = (), index=None) -> None
# green_cache.py:130
def _read_store(path: Path, namespace: str) -> dict[str, dict[str, str]]
CACHE_FILENAME = "parrot-test-scope-green.json"  # green_cache.py:31, lives under worktree_git_dir(worktree)
# report.py:72 — honours SDD_TEST_REPORT_DIR; report.py:111 — nodeid = f"{file}::{name}" when classname == file-as-module
def report_root() -> Path
# test_scope/select.py:126
def plan_tests(*, worktree: Path, changed_files: Sequence[str], tier: str, declared=(), contract=None, policy=None) -> ScopePlan
```

### Does NOT Exist
- ~~`plan.skipped_escalations == ("a",)`~~ — FEAT-699 never populates it; do not assert it.
- ~~`ScopePolicy(impact_cap=0, core_fanin_threshold=999)` forcing a cap escalation~~ — the cap only trims
  import targets now; no suite escalation exists.
- ~~`supervisor.start(..., index_path=None)` using the green cache~~ — without `index_path`
  `_plan_selection` returns the raw plan (`background.py:779`).
- ~~a junit written by `python -c "import sys; sys.exit(0)"`~~ — `_EXIT0` produces no report, so
  `parse_junit` returns `no_junit` and nothing is recorded; use the junit-writing children.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor.start",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor._plan_selection",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor._record_green_cache",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py#cache_namespace",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py#filter_cached",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py#record_green",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py#plan_tests"
  ]
}
```

---

## Implementation Notes

### Children (module level, next to `_EXIT0` / `_EXIT1`)
```python
_JUNIT_TESTCASE = (
    "<testcase file='packages/a/tests/test_leaf.py' classname='packages.a.tests.test_leaf' name='test_leaf'>"
)
_JUNIT_GREEN_CHILD = (
    sys.executable, "-c",
    "import sys;"
    "p=[x for x in sys.argv if x.startswith('--junitxml=')][0].split('=',1)[1];"
    "open(p,'w').write(\"<testsuites><testsuite tests='1' failures='0'>" + _JUNIT_TESTCASE
    + "</testcase></testsuite></testsuites>\");"
    "sys.exit(0)",
)
_JUNIT_RED_CHILD = (... same with failures='1', "<failure/>" inside the testcase, sys.exit(1))
```
`nodeid_from_testcase("packages/a/tests/test_leaf.py", "packages.a.tests.test_leaf", "test_leaf")`
→ `"packages/a/tests/test_leaf.py::test_leaf"`, which `record_green` matches against the
planned target `packages/a/tests/test_leaf.py` (`startswith(target + "::")`).

### Why the plan has exactly one invocation
`changed_files` is patched to `["packages/a/src/pa/leaf.py"]`; the file-level mirror maps
it to `packages/a/tests/test_leaf.py`; the declared command from `task.md` names the same
file; `build_plan` dedupes by path → one `PytestInvocation(distribution="a", ...)`. The
fallback import index may add nothing else (only one test file exists).

### Settling
Use the existing `_settle(supervisor, execution_id, "req-1")` seam, or
`await supervisor.wait(execution_id, registration.handle, 15)` as `test_background_contract.py` does.

### Key Constraints
- Do not read or assert the escalation ledger (`read_ledger`) in the two new tests.
- Keep the file's other tests byte-identical.

---

## Acceptance Criteria

- [ ] `test_second_merge_validation_skips_cached_targets`: first plan has one invocation,
      `cached == ()`; after a green run the next merge plan has `cached == ("packages/a/tests/test_leaf.py",)` and no invocation.
- [ ] `test_red_run_leaves_no_green_cache_entry`: a seeded green entry is removed by a red run; the next plan is uncached and unchanged.
- [ ] Whole file green: `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py -q`.
- [ ] `test_background_contract.py` still green (shared helpers untouched).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_contract.py -q`

---

## Agent Instructions

When you pick up this task:

1. **Work in this worktree** — `.claude/worktrees/fix-PR-1727-feat-699-red-tests`
   (branch `fix-PR-1727-feat-699-red-tests`, based on the tip of
   `origin/feat-FEAT-699-tests-optimization-sdd-flow`).
2. **Run tests with the worktree's source**:
   `PYTHONPATH=packages/ai-parrot/src pytest <file> -q`. Copy the compiled Cython modules
   from the main checkout once (they are git-ignored):
   `(cd /home/jesuslara/proyectos/ai-parrot/packages/ai-parrot/src && find parrot -name '*.so' -exec cp --parents {} <wt>/packages/ai-parrot/src/ \;)`.
3. **Verify the Codebase Contract** before writing code.
4. **Implement**, run `ruff check --fix` on the file, run the Validation Commands.
5. **Commit the code** — stage only this file: `test(sdd_coder): HOTFIX-PR-1727-2 — supervisor integration rows use the green cache`.
6. **Update** `sdd/briefs/feat-699-red-tests.index.json` (`status: "done"`, `completed_at`), fill in the
   Completion Note below, commit `sdd: complete HOTFIX-PR-1727-2`.

---

## Completion Note

**Completed by**: sdd-worker (sequential fallback: engine cannot assess brief task ids)
**Date**: 2026-10-19
**Notes**: Two integration rows rewritten against the green cache with junit-writing fake children. test_supervisor_ledger + test_background_contract: 15 green.

**Deviations from spec**: Red-run test: a still-valid seeded entry makes start() skip the run (nothing executes), so the seeded entry is made stale by editing leaf.py before the red run; the red run then drops it. Same intent (red leaves no entry), different mechanism than the task sketch.
