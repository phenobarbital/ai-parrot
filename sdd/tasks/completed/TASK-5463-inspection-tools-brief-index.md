# TASK-5463: `coder_task_context` and `coder_delivery_report` pass the index slug, so brief indexes resolve

**Feature**: FEAT-871 — `coder_task_context` and `coder_delivery_report` Find Brief Indexes
**Spec**: `sdd/specs/sdd-coder-engine-fixes-5.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:36d572b7feae`

---

## Context

`SddCoderEngine.task_context` and `.delivery_report` pass `feature=Path(ctx.index_path).stem` to `inspection`, which
re-resolves the index through `resolve_index_path(worktree, feature)`. For a brief index
`sdd/briefs/<slug>.index.json` the stem is `<slug>.index`, the lookup finds nothing, and both tools raise
`CoderFailure("index_unreadable", ...)`. FEAT-869 added `engine._index_slug(index_path)`, the inverse of
`resolve_index_path`; passing it fixes both calls. Implements spec §2, Module 1.

---

## Scope

- `engine.py`: replace both `feature=Path(ctx.index_path).stem,` arguments (in `task_context` and `delivery_report`)
  with `feature=_index_slug(ctx.index_path),`.
- `test_brief_index_resolution.py`: a helper that moves the `git_sandbox_feature` index to
  `sdd/briefs/demo.index.json` and starts an execution, plus two engine tests per spec §4.

**NOT in scope**: `inspection.py`; `_index_slug`; `resolve_index_path`; `nodes/planner.py:327`; tool schemas or
snapshot shapes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | both inspection calls pass `_index_slug(ctx.index_path)` |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_brief_index_resolution.py` | MODIFY | helper + 2 new engine tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

Verified against `origin/dev` @ `b37db6293a`.

### Verified Imports
```python
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine  # verified: test_brief_index_resolution.py:13
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat  # verified: test_brief_index_resolution.py:14
from .conftest import _run_git  # verified: conftest.py:113 (test_feedback.py imports it locally inside a test)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
def _index_slug(index_path: str) -> str  # :188 (module-level; no import needed inside engine.py)
async def SddCoderEngine.begin_execution(...)  # :669 — called as begin_execution("demo", str(worktree), execution_id)
async def SddCoderEngine.task_context(self, feature: str, worktree: str, task_id: str, execution_id: str) -> Dict[str, Any]  # :1733
#   feature=Path(ctx.index_path).stem,  # :1768
async def SddCoderEngine.delivery_report(self, feature: str, worktree: str, task_id: str, execution_id: str) -> Dict[str, Any]  # :1781
#   feature=Path(ctx.index_path).stem,  # :1820
async def SddCoderEngine.prepare_native(...)  # :2437 — prepare_native("demo", str(worktree), "TASK-0001", execution_id); result has .task_id, .branch, .attempt_uid
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/inspection.py
async def task_context(...) -> dict[str, object]  # :141 — keys include "feature", "index_path" (relative to worktree, :192), "status"
async def delivery_report(...) -> dict[str, object]  # :251 — keys include "feature", "task_id", "branch"
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py
FEATURE_SLUG = "demo"  # :78 — index file sdd/tasks/index/demo.json, header feature "demo"
async def _run_git(*args: str, cwd: Path) -> None  # :113
async def git_sandbox_feature(tmp_path)  # :141 — returns (worktree, feature_branch, base_path, index_path)
def noop_probe() -> RosterProbe  # :210 (fixture)
```

### Does NOT Exist
- No engine-level test of `task_context` / `delivery_report`; no brief-index coverage for either.
- `sdd/briefs/` does not exist in the `git_sandbox_feature` tree — create it before `git mv`.
- No `CoderFailure` import in `test_brief_index_resolution.py` (not needed: a raised `CoderFailure` fails the test).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_brief_index_resolution.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.task_context",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.delivery_report",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#_index_slug"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Commit the index move before building the engine: `begin_execution` / `prepare_native` work from the committed
  tree.
- One valid UUID execution id per test.
- Tests run in the worktree with `PYTHONPATH=packages/ai-parrot/src`.

### References in Codebase
- `test_record_review_writes_index_file_slug` (`test_feedback.py:330`) — the same rename-commit-engine shape.
- `test_engine_resolve_feature_matches_brief_by_feature_id` (`test_brief_index_resolution.py:94`) — brief resolution
  at the engine level.

---

## Implementation Blueprint

### Steps (in order)
1. Tests first; confirm both fail on the unmodified source with `index_unreadable`.
2. `engine.py`: replace both anchors.
3. Run the Validation Commands, `ruff check`, `black --check -l 120`.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)
```python
# REPLACE `                feature=Path(ctx.index_path).stem,` (verified: :1768 and :1820) — occurrences: 2 (both)
                feature=_index_slug(ctx.index_path),
```
**Why**: `inspection` re-resolves the index from a slug; a brief index's stem is `<slug>.index`, which names no file.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_brief_index_resolution.py` (MODIFY)
Append at end of file (after `test_background_resolve_feature_id_returns_brief_id`, :127):
```python
async def _engine_on_brief_index(git_sandbox_feature: tuple, noop_probe, execution_id: str) -> tuple:
    """Move the sandbox index to ``sdd/briefs/demo.index.json``, commit, and start an execution on it."""
    # FILL IN: mkdir sdd/briefs; _run_git("mv", "sdd/tasks/index/demo.json", "sdd/briefs/demo.index.json");
    #   _run_git("commit", ...); SddCoderEngine(roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")],
    #   feedback={"enabled": False}), probe=noop_probe, worktree_base_path=str(base_path));
    #   await engine.begin_execution("demo", str(worktree), execution_id); return (engine, worktree)


async def test_engine_task_context_reads_brief_index(git_sandbox_feature: tuple, noop_probe) -> None:
    """`coder_task_context` resolves a brief index, not '<slug>.index' (issue:36d572b7feae)."""
    # FILL IN: assert snapshot["feature"] == "demo", snapshot["index_path"] == "sdd/briefs/demo.index.json",
    #   snapshot["status"] == "pending"


async def test_engine_delivery_report_reads_brief_index(git_sandbox_feature: tuple, noop_probe) -> None:
    """`coder_delivery_report` resolves a brief index and reports the execution's attempt (issue:36d572b7feae)."""
    # FILL IN: prep = await engine.prepare_native(...); report = await engine.delivery_report(...);
    #   assert report["feature"] == "demo", report["task_id"] == "TASK-0001", report["branch"] == prep.branch
```

---

## Acceptance Criteria

- [ ] AC-1: `task_context` and `delivery_report` pass `_index_slug(ctx.index_path)`; no `Path(ctx.index_path).stem`
      remains in `engine.py`.
- [ ] AC-2: on a brief index, `task_context` returns a snapshot whose `index_path` is `sdd/briefs/demo.index.json`
      and `delivery_report` returns the attempt for TASK-0001; neither raises `index_unreadable`.
- [ ] AC-3: both new tests fail with the source change reverted and pass with it; both Validation Commands pass.
- [ ] AC-4: `ruff check` is clean on the two files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_brief_index_resolution.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py -q`

---

## Test Specification

See spec §4: `test_engine_task_context_reads_brief_index`, `test_engine_delivery_report_reads_brief_index`. The rest
of both files is unchanged and must keep passing (notably `test_index_slug_inverts_resolve_index_path`).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug sdd-coder-engine-fixes-5 --feature-id FEAT-871`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing ANY code
5. **Update status** in `sdd/tasks/index/sdd-coder-engine-fixes-5.json` → `"in-progress"` (set `started_at`) and
   commit only that index file
6. **Implement** — follow the Implementation Blueprint
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5463 sdd-coder-engine-fixes-5 verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: /sdd-fix session (Claude, agent:sdd-fix:9824d687)
**Date**: 2026-11-10
**Notes**: Implemented spec §2, Module 1 in commit `1e9012a4cb`. `SddCoderEngine.task_context` and
`.delivery_report` now pass `feature=_index_slug(ctx.index_path)` to `inspection` instead of
`Path(ctx.index_path).stem`; no `.stem` call on `ctx.index_path` remains in `engine.py`. Evidence:
- before the source change (tests only): both new tests fail with
  `CoderFailure: per-spec index unreadable or missing for feature 'demo.index'` (`index_unreadable`).
- after: both new tests pass; both Validation Commands pass (`test_brief_index_resolution.py` 10, `test_feedback.py`
  36); `ruff check` and `black --check -l 120` are clean on both files; the other files covering these tools
  (`test_inspection_reports.py`, `test_toolkit.py`, `test_toolkit_exclusive.py`, `test_mcp_local.py`,
  `test_worker_prompt_orchestrator.py`) pass (66 tests).
- The per-spec path is unchanged: `_index_slug` returns the stem there (`test_index_slug_inverts_resolve_index_path`).

**Deviations from spec**: none
