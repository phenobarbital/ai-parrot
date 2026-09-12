# TASK-3183: Banned-import gates in `_run_attempt` and `_consolidate` + docs/prompt updates

**Feature**: FEAT-553 — sdd-coder Shared Conventions & Turn Budget
**Spec**: `sdd/specs/sdd-coder-shared-conventions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3182
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (engine half, corrected by §10 R1). Two gates, one check:
in `_run_attempt` a banned import becomes an **attempt error** so the retry
ladder gives a different seat a shot; in `_consolidate` — the shared merge
boundary that `merge()` also reaches for native tasks and re-merges — it is a
**`fidelity_violation`**, so nothing with a banned import can merge no matter
which entry point produced the branch. The orchestrator prompt (both copies)
and the orchestrator doc describe the new cause; the doc also gets the
conventions section and the 40-turn note (AC-11).

---

## Scope

- `engine.py`: call `check_banned_imports` after a successful dispatch in `_run_attempt`; call it after the fidelity report in `_consolidate`.
- `sdd-worker.md` (`.claude/agents/` AND `_subagent_data/`, byte-identical): extend the `fidelity_violation` bullet.
- `docs/dev_loop/sdd-coder-orchestrator.md`: outcome row, new "Conventions & lint backstop" section, 40-turn note.
- Engine tests for both gates.

**NOT in scope**: `ruff.toml`, `check_banned_imports` itself (TASK-3182); the `max_turns` code change (TASK-3184).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | two gates |
| `.claude/agents/sdd-worker.md` | MODIFY | `fidelity_violation` bullet |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | MODIFY | identical edit (parity test) |
| `docs/dev_loop/sdd-coder-orchestrator.md` | MODIFY | outcome row + new section + turn note |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py` | MODIFY | `_consolidate` / `merge()` gate tests |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` | MODIFY | `_run_attempt` gate test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.sdd_coder.fidelity import check_banned_imports, check_fidelity, parse_task_files   # check_banned_imports: TASK-3182; the other two verified: engine.py:40
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine      # verified: tests import it (test_engine_plan_merge.py)
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat, TaskResult, AttemptRecord   # verified: models.py:23, :115, :129
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
from parrot.flows.dev_loop.sdd_coder.fidelity import check_fidelity, parse_task_files        # line 40 — extend
async def _git(*args: str, cwd: str) -> Tuple[int, str, str]                                # line 69
async def _consolidate(self, ctx, manager, task, *, branch, path) -> TaskResult:            # line 337
    _rc, diff, _err = await _git("diff", "--name-only", f"{ctx.feature_branch}...{branch}", cwd=ctx.worktree)   # line 358
    report = check_fidelity(parse_task_files(task_md), [p for p in diff.splitlines() if p.strip()])            # line 374
    if not report.ok:                                                                        # line 375
        return TaskResult(task_id=task.task_id, outcome="fidelity_violation", branch=branch, worktree_path=path, …)   # lines 376-…
    # … merge under lock follows; `return TaskResult(task_id=task.task_id, outcome="merged", …)` at line 405
async def merge(self, feature, worktree, task_id) -> TaskResult                             # line 407 → calls self._consolidate at line 428
async def _run_attempt(self, ctx, task, seat, *, attempt, job_id) -> Tuple[AttemptRecord, Optional[DevelopmentOutput], str, SubWorktreeManager, str, str]:   # line 520
    branch = f"{ctx.feature_branch}--{task.task_id}-a{attempt}"                             # line 528
    output = await dispatcher.dispatch(…, cwd=path, session_host=collector, labels=…)       # lines 553-578
    except Exception as exc:  # noqa: BLE001 …                                              # line 579
        error = f"{type(exc).__name__}: {exc}"; collector.error = error                     # lines 582-583
    return collector.record(), output, error, manager, branch, path                        # line 587
async def _run_task(self, ctx, task, seat, *, job_id) -> TaskResult                         # line 588 — `if err:` → retry_seat (:596) → attempt 2

# sdd_coder/models.py
TaskOutcome = Literal["queued", "running", "merged", "merge_conflict", "failed", "fidelity_violation", "retry_native"]   # line 13 — do NOT add a member
class TaskResult: task_id, outcome, branch, worktree_path, attempts, conflict_files, unexpected_files?, diagnostics: str = "", development_output   # lines 129-140 (`unexpected_files` used by test_engine_plan_merge.py:153)

# .claude/agents/sdd-worker.md:242 == _subagent_data/sdd-worker.md:242 (byte parity enforced by tests/flows/dev_loop/test_subagent_parity.py):
#   "   - `fidelity_violation` → treat as `failed` (a coder touched `sdd/` or unlisted files; never merge it by hand)."
# docs/dev_loop/sdd-coder-orchestrator.md
#   line 125: "| `fidelity_violation` | The coder touched `sdd/` or a file not on its task's list | Treated as `failed` — never merged by hand |"
#   line 141: "## Telemetry" ; line 150: "## Troubleshooting" ; line 170: "## Related"

# tests/flows/dev_loop/sdd_coder/
#   conftest.py: fixture git_sandbox_feature → (worktree, feature_branch, base_path, index_path); tasks TASK-0001..0005 list `pkg/t{n}.py`
#   test_engine_plan_merge.py:141-155 test_engine_fidelity_violation_keeps_branch — the exact shape to copy (engine._resolve_feature, _manager_for, manager.create, _write_and_commit, engine.merge)
#   test_engine_dispatch.py:20-54 FakeDispatcher(behaviour) writes pkg/t{n}.py with "# {task_id}\n" and commits; :65 fake_builder_factory; :115 test_engine_retry_on_other_seat_then_failed
```

### Does NOT Exist
- ~~a `banned_import` / `lint_violation` `TaskOutcome`~~ — reuse `fidelity_violation`; the cause is in `diagnostics`.
- ~~`ruff.toml` inside the test sandbox~~ — the sandbox repo has none; each gate test must write one (see TASK-3182's `_BANNED_CFG`) or ruff finds nothing.
- ~~`FakeDispatcher` behaviour `"banned"`~~ — add it (writes `import httpx` into the task file) or subclass in the test.
- ~~a docs section "Conventions & lint backstop"~~ — created here.

---

## Implementation Notes

### Key Constraints
- `_run_attempt`: run the check only when `dispatch()` returned without exception; changed files = `git diff --name-only <feature_branch>...HEAD` in `path` (the sub-worktree). On findings: `error = "BannedImport: " + "; ".join(v)`, `collector.error = error`, `output = None`.
- `_consolidate`: reuse the `diff` list already computed at :358; run ruff in `path` (files exist there), NOT in `ctx.worktree`.
- Never merge by hand; the outcome row wording must say a `fidelity_violation` may also mean a banned import.

---

## Implementation Blueprint

### Steps (in order)
1. Extend the import at `engine.py:40` — *why*: single source for the check (TASK-3182).
2. Add the `_consolidate` gate first — *why*: it is the boundary every path crosses (spec §10 R1).
3. Add the `_run_attempt` gate — *why*: MCP seats get the retry ladder.
4. Edit both `sdd-worker.md` copies identically, then the doc — *why*: `test_subagent_parity.py` fails on drift.
5. Tests; run `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/ packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -v`.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'report = check_fidelity(parse_task_files(task_md)' …/engine.py)
# REPLACE lines 374-375 (`report = …` and `if not report.ok:`) so the flow becomes:
        changed = [p for p in diff.splitlines() if p.strip()]
        report = check_fidelity(parse_task_files(task_md), changed)
        if not report.ok:
            # (existing fidelity_violation return, unchanged)
            ...
        # FEAT-553 (spec §10 R1): the shared merge boundary — `merge()` reaches here directly for
        # native tasks and re-merges, so the banned-import gate lives HERE, not only in _run_attempt.
        violations = await check_banned_imports(path, changed)
        if violations:
            return TaskResult(
                task_id=task.task_id,
                outcome="fidelity_violation",
                branch=branch,
                worktree_path=path,
                diagnostics="BannedImport: " + "; ".join(violations),
            )

# occurrences: 1 (verified: grep -c 'labels=self._labels_for(task, seat, attempt),' …/engine.py)
# AFTER — inside the `try:` of _run_attempt, directly after the `output = await dispatcher.dispatch(...)` call closes (verified: engine.py:578), still inside the try:
            _rc, diff, _err = await _git("diff", "--name-only", f"{ctx.feature_branch}...HEAD", cwd=path)
            violations = await check_banned_imports(path, [p for p in diff.splitlines() if p.strip()])
            if violations:
                # An attempt error, NOT a fidelity outcome: a different seat may fix it (retry ladder in _run_task).
                error = "BannedImport: " + "; ".join(violations)
                collector.error = error
                output = None
```
**Why**: `_run_task` (:588-616) already treats a non-empty `error` as "retry on another seat, then failed"; `_consolidate` returning `fidelity_violation` is the existing non-merge outcome the orchestrator knows how to handle.

### `.claude/agents/sdd-worker.md` + `_subagent_data/sdd-worker.md` (MODIFY, identical)
```markdown
# occurrences: 1 per file (verified: grep -c 'fidelity_violation` → treat as `failed`' <file>)
# REPLACE line 242 with:
   - `fidelity_violation` → treat as `failed` (a coder touched `sdd/` or unlisted files, OR its diff adds a banned import — `diagnostics` starts with `BannedImport:`; never merge it by hand, fix it yourself in attempt 3).
```

### `docs/dev_loop/sdd-coder-orchestrator.md` (MODIFY)
```markdown
# occurrences: 1 — REPLACE line 125 with:
| `fidelity_violation` | The coder touched `sdd/` or a file not on its task's list, **or** its diff adds a banned import (`diagnostics` starts with `BannedImport:`) | Treated as `failed` — never merged by hand |

# occurrences: 1 (verified: grep -c '^## Telemetry' docs/dev_loop/sdd-coder-orchestrator.md)
# BEFORE — insert directly above `## Telemetry` (verified: :141):
## Conventions & lint backstop (FEAT-553)

Every MCP seat receives the repo's coder rules (`.agent/rules/codebase-conventions.md`
+ `python-development.md`, via `parrot.flows.conventions.load_project_conventions`)
inline in its prompt, right after the `sdd-coder` body. The native seat reads the same
files from `.claude/rules/`. Prompts are advisory; the guarantee is ruff rule `TID251`
(`ruff.toml`, `[lint.flake8-tidy-imports.banned-api]`): `requests`, `httpx`, `starlette`,
`fastapi`, `uvicorn` and every `langchain*`/`langgraph`/`langsmith` import fail
`ruff check`, and the engine runs the same check after every attempt (attempt error →
retry on another seat) and again at the merge boundary (`fidelity_violation`, also for
native tasks and re-merges).

# occurrences: 1 (verified: grep -c '^## Troubleshooting' …) — AFTER the `## Troubleshooting` heading's first bullet list, append one bullet:
- **`LLM code dispatch exceeded max_turns=…`** — the in-process seats' library default is 40 turns
  (`LLMCodeDispatchProfile.max_turns`, FEAT-553); the roster path sets 60 via `build_dispatcher`
  (`DEV_LOOP_LLM_MAX_TURNS`). The effective value is in the `dispatch.completed` payload.
```

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py` (MODIFY)
```python
# AFTER — append at end of file
_BANNED_CFG = '[lint]\nselect = ["TID251"]\n[lint.flake8-tidy-imports.banned-api]\n"requests".msg = "use aiohttp"\n"httpx".msg = "use aiohttp"\n'


async def test_consolidate_rejects_banned_import(git_sandbox_feature, noop_probe):
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    await _write_and_commit(worktree, "ruff.toml", _BANNED_CFG, "ruff config")   # on the feature branch, so sub-worktrees inherit it
    engine = SddCoderEngine(roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")]), probe=noop_probe,
                            worktree_base_path=str(base_path))
    ctx = await engine._resolve_feature("demo", str(worktree))
    manager = engine._manager_for(ctx, "TASK-0003", 1)
    path = Path(await manager.create("TASK-0003.a1"))
    await _write_and_commit(path, "pkg/t3.py", "import requests\n", "banned import")
    result = await engine.merge("demo", str(worktree), "TASK-0003")     # the public native/re-merge entry point (:407)
    assert result.outcome == "fidelity_violation" and result.diagnostics.startswith("BannedImport:")
    _rc, log, _err = await _git("log", "--oneline", feature_branch, cwd=worktree)
    assert "banned import" not in log
```

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` (MODIFY)
```python
# AFTER — append at end of file
async def test_run_attempt_turns_banned_import_into_attempt_error(git_sandbox_feature, noop_probe):
    # FILL IN: commit the _BANNED_CFG ruff.toml on the feature branch; build a FakeDispatcher variant whose
    #   dispatch writes "import httpx\n" into pkg/t1.py for backend "nova" and a clean file for "codex";
    #   engine = SddCoderEngine(roster=_roster(("a","nova"),("b","codex")), probe=noop_probe, worktree_base_path=str(base_path), dispatcher_builder=<factory>)
    #   run plan + run_chunk for TASK-0001 (mirror test_engine_retry_on_other_seat_then_failed :115-132), await the job,
    #   assert result.attempts[0].error.startswith("BannedImport:") and result.attempts[1].seat_label == "b" and result.outcome == "merged"
    #   — bounded by AC-8 (attempt 2 runs on a different seat)
```

### FILL IN checklist
- [ ] `test_engine_dispatch.py::test_run_attempt_turns_banned_import_into_attempt_error` — body; bounded by AC-8
- [ ] Troubleshooting bullet placement in the doc — after the existing bullets, before `## Related`

---

## Acceptance Criteria

- [ ] `_consolidate` returns `fidelity_violation` with `BannedImport:` diagnostics for a branch adding a banned import, reached via `merge()` (spec AC-8b)
- [ ] `_run_attempt` records a `BannedImport:` attempt error and attempt 2 runs on a different seat (spec AC-8)
- [ ] Both `sdd-worker.md` copies byte-identical (`pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -k sdd-worker`)
- [ ] `docs/dev_loop/sdd-coder-orchestrator.md` has the new section, the outcome row and the 40-turn note (spec AC-11)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/ -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` clean

---

## Test Specification

See the two MODIFY test blocks above.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 M4, §7 "Two gates, one check", §10 R1)
2. **Check dependencies** — `TASK-3182` in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — `engine.py:358/374/578` anchors; `TaskOutcome` literal unchanged
4. **Update status** in `sdd/tasks/index/sdd-coder-shared-conventions.json` → `"in-progress"`
5. **Implement** — from the blueprint; never add a `TaskOutcome` member; never merge a violating branch
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3183-engine-banned-import-gates.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none
