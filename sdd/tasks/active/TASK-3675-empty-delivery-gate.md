# TASK-3675: Empty-delivery gate — never report `merged` for an attempt that changed nothing

**Feature**: FEAT-597 — dev-loop sdd-coder fixes (empty-delivery gate + declared `sdd/` targets)
**Spec**: `sdd/specs/dev-loop-sdd-coder-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**discovered_from**: issue:ee4d4879fc89

---

## Context

Spec §1-A / §2 M1 / §3 Module 1. `SddCoderEngine._consolidate` (engine.py:~2289) diffs the
attempt branch against its fork point and calls `check_fidelity(expected, changed)`. When a
seat delivers nothing (`changed == []`), `[] ⊆ expected` is vacuously true, the merge is a no-op
and the task is reported `outcome="merged"` with `commits=0, changed_files=[]` — FEAT-581's
TASK-3534 on codex `gpt-5.6-terra`. Two sites close it: an attempt-level check in `_run_task`
(so the existing retry ladder runs on a fresh seat, exactly like a dispatch error) and a merge-
boundary backstop in `_consolidate` (covers the native `merge()` path). Ledger issue
`issue:ee4d4879fc89` (major).

---

## Scope

- Add `SddCoderEngine._delivered_paths(ctx, task, *, branch, path) -> List[str]` (committed ∪ dirty ∪ declared-but-ignored paths of one attempt).
- `_run_task`: after a successful `_run_attempt`, if `_delivered_paths` is empty, turn the attempt into an error (`error` starts `empty_delivery:`, `terminal="failed"`) so the existing `if err:` retry ladder runs unchanged.
- `_consolidate`: if `changed` is empty and `branch` is not already an ancestor of `ctx.feature_branch`, return `TaskResult(outcome="failed", diagnostics="empty_delivery: …")` before fidelity/lint/merge.
- `_classify_failure_reason`: return `None` for an error starting `empty_delivery:` (no suspension).
- Tests (§4) + docs rows for the new diagnostic in `docs/dev_loop/sdd-coder-orchestrator.md` and `.claude/agents/sdd-worker.md`.

**NOT in scope**: the `sdd/` protected-prefix rule (TASK-3676); any change to `TaskOutcome`/`ERROR_CODES`; a new suspension reason; `roster.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `_delivered_paths` helper; `_run_task` attempt-level gate; `_consolidate` backstop; `_classify_failure_reason` early return |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py` | MODIFY | `test_engine_merge_refuses_empty_delivery` |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` | MODIFY | `FakeDispatcher` behaviour `"empty"`; two retry-ladder tests; classify test |
| `docs/dev_loop/sdd-coder-orchestrator.md` | MODIFY | Outcomes table: `empty_delivery:` row |
| `.claude/agents/sdd-worker.md` | MODIFY | outcome bullet for `failed` + `empty_delivery:` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine  # verified: test_engine_dispatch.py:13
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat       # verified: test_engine_dispatch.py:14
from parrot.flows.dev_loop.models import DevelopmentOutput                          # verified: test_engine_dispatch.py:12
# engine.py already imports (verified engine.py:56): check_banned_imports, check_fidelity, parse_task_files
# engine.py already has `asyncio`, `Path`, `List`, `Optional`, module-level `async def _git(*args, cwd) -> (rc, out, err)` (engine.py:~130-141)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
async def _consolidate_diff_base(feature_branch: str, branch: str, *, cwd: str) -> str   # :144 (documents the empty-diff re-merge fallback)
class SddCoderEngine:
    @staticmethod
    def _dirty_paths(porcelain_z: str) -> List[str]                                        # :2140
    async def _commit_declared_changes(self, task, expected, *, branch, path, feature) -> Optional[TaskResult]  # :2173 (ignored-declared lookup :2224-2228)
    async def _consolidate(self, ctx, manager, task, *, branch, path) -> TaskResult        # :~2289
        # :2314 blocked = await self._commit_declared_changes(...)
        # :2325 diff_base = await _consolidate_diff_base(ctx.feature_branch, branch, cwd=ctx.worktree)
        # :2327 changed = [p for p in diff.splitlines() if p.strip()]
        # :2328 report = check_fidelity(expected, changed)
        # :2387 rc, _out, err = await _git("merge-base", "--is-ancestor", branch, ctx.feature_branch, cwd=ctx.worktree)
        # :2401 return TaskResult(task_id=task.task_id, outcome="merged", ...)
    def _classify_failure_reason(self, error: str, error_class: str, outcome: Optional[str] = None) -> Optional[str]  # :3023; :3038 "# Check for fidelity violation from consolidation"
    async def _run_task(self, ctx, task, seat, *, job_id, execution_id=None, pool=None) -> TaskResult  # :~3338
        # :3359 rec, out, err, manager, branch, path = await self._run_attempt(...); :3363 attempts.append(rec)
        # :3365 `if not err:` → :3371 result = await self._consolidate(ctx, manager, task, branch=branch, path=path)  (this call line occurs 2×: :3371 and :3510)
        # :3373.. `if err:` retry ladder (unchanged)

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py
class AttemptRecord(BaseModel):   # :297
    seat_label: str; backend: str = ""; model: str = ""; error: str = ""; terminal: str = "completed"; error_class: str = ""
class TaskResult(BaseModel):      # outcome: TaskOutcome (:30-39 — "failed" exists), branch, worktree_path, diagnostics: str, attempts, unexpected_files, conflict_files, lint
class RosterSeat(BaseModel):      # label, kind, backend: Optional[str], model: Optional[str]

# tests
# conftest.py: git_sandbox_feature -> (worktree: Path, feature_branch: str, base_path: Path, index_path: Path); TASK-0001..0005 declare pkg/t{n}.py; helper _write_and_commit(repo, filename, content, message)
# test_engine_plan_merge.py:107 test_engine_native_prepare_then_merge — prepare_native → write+commit → merge() pattern; imports `_git` for log/status checks
# test_engine_dispatch.py:19 class FakeDispatcher (behaviours ok|fail|block|extra|banned; :48 `if self.behaviour == "fail":`), :67 fake_builder_factory({backend: behaviour}), :82 _roster(("a","nova"),("b","codex"),("c","google-compat")), :126 test_engine_retry_on_other_seat_then_failed (`{"nova": "fail"}` → attempt 1 lands on nova; asserts len(attempts)==2), :886 existing `engine._classify_failure_reason(...)` calls
```

### Does NOT Exist
- ~~`empty_delivery` in `ERROR_CODES` / `TaskOutcome`~~ — it is a **prefix** of `TaskResult.diagnostics` / `AttemptRecord.error`, like `branch_not_merged:`; do not add a code.
- ~~`SddCoderEngine._delivered_paths`~~ — created by this task.
- ~~`FakeDispatcher("empty")`~~ — created by this task.
- ~~`.agent/agents/sdd-worker/agent.md` as a twin~~ — different dev-flow file; do not edit.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py", "action": "MODIFY"},
    {"path": "docs/dev_loop/sdd-coder-orchestrator.md", "action": "MODIFY"},
    {"path": ".claude/agents/sdd-worker.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#_consolidate_diff_base",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#AttemptRecord",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#TaskResult"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The attempt-level gate runs **before** `_consolidate` so no extraction commit is ever created for an empty attempt and the ladder sees the attempt as errored (spec §7).
- `_consolidate` ordering stays: read task md → extract → diff → **empty gate** → fidelity → lint → banned imports → merge.
- Ancestor guard in `_consolidate`: an attempt branch already merged by hand legitimately diffs empty (`_consolidate_diff_base` docstring) — never fail that case.
- Run tests from the worktree with `PYTHONPATH=packages/ai-parrot/src`.

### References in Codebase
- `engine.py:2173-2286` `_commit_declared_changes` — the dirty/ignored-declared git calls to mirror in `_delivered_paths`.
- `engine.py:2380-2400` — the `branch_not_merged` `failed` result: same diagnostics-prefix convention.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_delivered_paths` next to `_dirty_paths` — *why*: one helper defines "delivered" (committed past fork ∪ dirty ∪ declared-but-ignored) for the attempt-level gate.
2. Insert the attempt-level gate in `_run_task` above the existing `if not err:` — *why*: setting `err` there makes the unchanged `if err:` ladder retry on another seat, as for a dispatch failure (AC2).
3. Insert the backstop in `_consolidate` after `changed = […]` — *why*: the native `merge()` path never goes through `_run_task` (AC1).
4. Add the `empty_delivery:` early return to `_classify_failure_reason` — *why*: AC3, no suspension.
5. Add `FakeDispatcher` behaviour `"empty"` and the tests; then the docs rows.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY — helper)
```python
# occurrences: 1 (verified: grep -c 'def _dirty_paths(porcelain_z: str) -> List\[str\]:' engine.py)
# AFTER — insert as a new method right after the `_dirty_paths` staticmethod ends (its `return paths`, engine.py:~2171)
    async def _delivered_paths(self, ctx: _FeatureCtx, task: PlannedTask, *, branch: str, path: str) -> List[str]:
        """Every path one attempt delivered, or ``[]`` when the seat produced nothing.

        Union of: files committed on ``branch`` past its fork from ``ctx.feature_branch``
        (``git merge-base``), paths dirty in the sub-worktree ``path`` (same status call
        as ``_commit_declared_changes``), and declared files hidden by ``.gitignore``.
        An empty result is an empty delivery (spec FEAT-597 AC2): nothing to extract,
        nothing that could pass fidelity except vacuously.

        Args:
            ctx: Resolved feature context (feature branch + worktree).
            task: The planned task; its markdown supplies the declared files.
            branch: The attempt branch.
            path: The attempt sub-worktree.

        Returns:
            Repo-relative paths in first-seen order, de-duplicated.
        """
        _rc, fork, _err = await _git("merge-base", ctx.feature_branch, branch, cwd=ctx.worktree)
        _rc, diff, _err = await _git("diff", "--name-only", f"{fork.strip()}..{branch}", cwd=ctx.worktree)
        committed = [p for p in diff.splitlines() if p.strip()]
        _rc, status, _err = await _git("status", "--porcelain", "-z", "--untracked-files=all", cwd=path)
        dirty = self._dirty_paths(status)
        task_md = await asyncio.to_thread(Path(ctx.worktree, task.task_file).read_text, "utf-8")
        declared = sorted(p for p in parse_task_files(task_md) if not p.startswith("sdd/"))
        ignored: List[str] = []
        if declared:
            _rc, out, _err = await _git(
                "ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--", *declared, cwd=path
            )
            ignored = [p for p in out.split("\0") if p]
        return list(dict.fromkeys(committed + dirty + ignored))
```
**Why this shape**: mirrors the three git probes `_commit_declared_changes` already trusts, so "delivered" and "extractable" can never disagree. `not p.startswith("sdd/")` is deliberately the same filter as engine.py:2218 today; TASK-3676 narrows both together.

### `engine.py` (MODIFY — `_run_task` attempt-level gate)
```python
# occurrences: 1 (verified: grep -c '        if not err:' engine.py → 1, engine.py:3365)
# BEFORE — insert immediately ABOVE the existing `        if not err:` line in `_run_task` (after `attempts.append(rec)`, engine.py:3363)
        if not err and not await self._delivered_paths(ctx, task, branch=branch, path=path):
            err = (
                f"empty_delivery: seat {seat.label} ({seat.backend}/{rec.resolved_model or rec.model or seat.model}) "
                f"delivered no file change for {task.task_id}"
            )
            # FILL IN: error_class — bounded by AttemptRecord.error_class ("exception type name only"); use "EmptyDelivery"
            rec = rec.model_copy(update={"error": err, "terminal": "failed", "error_class": "EmptyDelivery"})
            attempts[-1] = rec
            self.logger.warning("%s: %s", task.task_id, err)
```
**Why**: the ladder below keys on `err`; nothing else changes, so attempt-1 gets its `failed` outcome row, `_eligible_retry_labels`/`_select_retry_seat`/native retry all behave as for `RuntimeError("boom")` (existing test :126).

### `engine.py` (MODIFY — `_consolidate` backstop)
```python
# occurrences: 1 (verified: grep -c 'changed = \[p for p in diff.splitlines() if p.strip()\]' engine.py, engine.py:2327)
# AFTER — insert below `        changed = [p for p in diff.splitlines() if p.strip()]`, ABOVE `report = check_fidelity(expected, changed)`
        if not changed:
            # A branch already merged by hand diffs empty through `_consolidate_diff_base`'s
            # fallback; only an UNMERGED empty branch is an empty delivery (spec FEAT-597 AC1).
            rc, _out, _err = await _git("merge-base", "--is-ancestor", branch, ctx.feature_branch, cwd=ctx.worktree)
            if rc != 0:
                shown = ", ".join(expected[:8]) + (" …" if len(expected) > 8 else "")
                return TaskResult(
                    task_id=task.task_id,
                    outcome="failed",
                    branch=branch,
                    worktree_path=path,
                    diagnostics=(
                        f"empty_delivery: {branch} changes no file relative to {diff_base[:12]} "
                        f"(declared {len(expected)} file(s): {shown}); nothing was merged"
                    ),
                )
```
**Why**: `[] ⊆ expected` must never reach the merge; the ancestor guard is the only exception the codebase documents.

### `engine.py` (MODIFY — `_classify_failure_reason`)
```python
# occurrences: 1 (verified: grep -c '        # Check for fidelity violation from consolidation' engine.py, engine.py:3038)
# BEFORE — insert ABOVE that comment line
        if error.startswith("empty_delivery:"):
            return None  # FEAT-597 AC3: an empty delivery never suspends a model
```

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'if self.behaviour == "fail":' test_engine_dispatch.py, :48)
# AFTER — insert below the two lines `if self.behaviour == "fail":` / `raise RuntimeError("boom")`
        if self.behaviour == "empty":
            # Claims the file in its output but writes and commits nothing (FEAT-597 / issue:ee4d4879fc89).
            n_empty = brief.task_id.rsplit("-", 1)[-1].lstrip("0") or "0"
            return DevelopmentOutput(files_changed=[f"pkg/t{int(n_empty)}.py"], commit_shas=[], summary=brief.task_id)
# also extend the class docstring's behaviour list with `- "empty": …`

# APPEND at end of file:
async def test_run_task_empty_delivery_retries_on_another_seat(git_sandbox_feature, noop_probe):
    """An attempt that changes nothing is a failed attempt, retried on a fresh seat (spec FEAT-597 AC2)."""
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    builder = fake_builder_factory({"nova": "empty"})  # attempt 1 lands on nova (same setup as :126)
    engine = SddCoderEngine(roster=_roster(("a", "nova"), ("b", "codex"), ("c", "google-compat")),
                            probe=noop_probe, worktree_base_path=str(base_path), dispatcher_builder=builder)
    job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
    result = await engine.wait(job.job_id, 5)
    task = result.tasks[0]
    # FILL IN: assert outcome == "merged", len(attempts) == 2, attempts[0].error.startswith("empty_delivery:"),
    #          attempts[0].terminal == "failed", attempts[1].seat_label != attempts[0].seat_label,
    #          and "impl TASK-0001" in `git log --oneline feature_branch` — bounded by AC2


async def test_run_task_empty_delivery_twice_is_failed(git_sandbox_feature, noop_probe):
    # FILL IN: fake_builder_factory({"nova": "empty", "codex": "empty", "google-compat": "empty"}); outcome == "failed";
    #          both attempts' error start with "empty_delivery:"; feature log has no "impl TASK-0001" — bounded by AC1/AC2


async def test_classify_failure_reason_empty_delivery_not_suspendable(git_sandbox_feature, noop_probe):
    # FILL IN: build an engine as at :886 and assert
    #          engine._classify_failure_reason("empty_delivery: seat a (nova/m) delivered no file change for TASK-0001", "EmptyDelivery") is None — AC3
```

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py` (MODIFY)
```python
# APPEND at end of file (pattern: test_engine_native_prepare_then_merge, :107)
async def test_engine_merge_refuses_empty_delivery(git_sandbox_feature, noop_probe):
    """`merge()` on an attempt branch with no work is `failed`/`empty_delivery:` — never `merged` (spec FEAT-597 AC1)."""
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    roster = RosterConfig(seats=[RosterSeat(label="h", kind="native")])
    engine = SddCoderEngine(roster=roster, probe=noop_probe, worktree_base_path=str(base_path))
    prep = await engine.prepare_native("demo", str(worktree), "TASK-0001")
    result = await engine.merge("demo", str(worktree), "TASK-0001")
    assert result.outcome == "failed"
    assert result.diagnostics.startswith("empty_delivery:")
    # FILL IN: assert `git merge-base --is-ancestor <prep.branch> <feature_branch>` rc != 0 and the feature log
    #          is unchanged (no "engine-committed" / no "TASK-0001" commit) — bounded by AC1
```

### `docs/dev_loop/sdd-coder-orchestrator.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '^| `failed` |' docs/dev_loop/sdd-coder-orchestrator.md, :218)
# AFTER — insert a new table row below the `| `failed` | …` row
| `failed` + `diagnostics` starting `empty_delivery:` | The seat produced **no file change** (no commit, nothing in the tree, no declared file under an ignored path). On the MCP path the engine already ran the retry ladder; from `coder_merge` (native path) the branch was not merged | Treat as `failed`: attempt 3 is `sdd-worker`'s, or re-dispatch once via `coder_run_chunk` when the classification is `standard` |
```

### `.claude/agents/sdd-worker.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c -- '- `fidelity_violation` → treat as `failed`' .claude/agents/sdd-worker.md, :377)
# BEFORE — insert a new bullet ABOVE the `fidelity_violation` bullet
   - `failed` with `diagnostics` starting `empty_delivery:` → the seat delivered no file change (the engine never answers
     `merged` for an empty branch). On `coder_run_chunk` the retry ladder already ran; treat as `failed` below.
```

### FILL IN checklist
- [ ] `engine.py::_run_task` — `error_class` literal; bounded by `AttemptRecord.error_class` docstring ("exception type name only").
- [ ] `test_engine_dispatch.py` — three test bodies; bounded by AC1/AC2/AC3.
- [ ] `test_engine_plan_merge.py::test_engine_merge_refuses_empty_delivery` — ancestor + log assertions; bounded by AC1.

---

## Acceptance Criteria

- [ ] AC1: `_consolidate` never returns `merged` for an empty, not-yet-merged attempt branch; `diagnostics` starts `empty_delivery:`.
- [ ] AC2: an MCP attempt with no delivered path is recorded `failed` with `error` starting `empty_delivery:` and the retry ladder runs (second attempt on another seat).
- [ ] AC3: `_classify_failure_reason("empty_delivery: …", …) is None`.
- [ ] AC6 (partial): orchestrator doc + `sdd-worker.md` describe the diagnostic.
- [ ] Existing `test_engine_run_chunk_merges_clean_branches`, `test_engine_commits_gitignored_declared_work`, `test_engine_native_prepare_then_merge` still pass.
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_integration_chunk.py -q`

---

## Test Specification

See the Blueprint's test blocks: `test_engine_merge_refuses_empty_delivery`,
`test_run_task_empty_delivery_retries_on_another_seat`, `test_run_task_empty_delivery_twice_is_failed`,
`test_classify_failure_reason_empty_delivery_not_suspendable`.

---

## Agent Instructions

1. Read the spec (§1-A, §2 M1, §6). 2. Verify every anchor's occurrence count above (`grep -c`). 3. Implement from the Blueprint, complete the FILL IN checklist. 4. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`. 5. Commit only the five listed files.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
