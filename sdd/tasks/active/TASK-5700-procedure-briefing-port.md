# TASK-5700: Deliver procedure guidance through task briefings (TASK-5650 port)

**Feature**: FEAT-887 — SDD Experience Memory (`experience.pitfall`)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: in-progress
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5607, TASK-5608
**Assigned-to**: unassigned
**Discovered-from**: `issue:94b993feac9d`

---

## Context

FEAT-891 (procedural-graph-plane, merged to dev in PR #2130) closed TASK-5650 — "procedure block at
task start", spec §3 Module 11 / goal G9 — as `done-with-issues`, because the delivery channel it needs
is FEAT-887's task briefing: `SddCoderEngine._experience_briefing_for` and the "Prime with Experience
Briefing" step of `/sdd-start` (TASK-5607, TASK-5608). The working implementation, commit `ac826c4735`,
lives only on branch `fix/pr-2130-procedure-integration`. That branch was never opened as a PR, and the
issue that tracked it was closed against a commit that is not on `origin/dev`.

This task ports that commit onto FEAT-887, so the procedure briefing ships with the feature that
provides its channel. Ledger issue `issue:94b993feac9d` records the gap.

---

## Scope

- `SddCoderEngine._procedure_briefing_for(ctx, task) -> str`: local-only procedure guidance for the task.
  It returns `""` when the procedure plane is absent, stale or disabled (`procedure.enabled: false`),
  or when anything raises. It never runs remote probes.
- Both dispatch paths (the native seat and the MCP seats) join the experience block and the procedure
  block with a blank line and drop empty blocks. The result stays in the existing `experience_briefing`
  variable, so seats with no procedure plane receive exactly the same bytes as before.
- The `/sdd-start` briefing step also runs `parrot sdd procedure brief --task-file <task-file>`, in all
  six twins: `.claude/commands`, `.agent/workflows`, `.agents/skills`, and the three `_assets` copies.
- The tests from `ac826c4735`, rebased onto this branch: the engine briefing at both seats, task-worktree
  state, skill-procedure build and discovery, configured skill directories, and cross-producer duplicate
  rejection. The `experience_cli` wheel-only scenario from the original commit is not ported; this branch
  already defines one with the `<task-file>` placeholder. The `procedure` scenario gains a `<task-file>`
  placeholder for the new documented invocation.

**NOT in scope**: the procedure plane itself (FEAT-891, already on dev); the compound-command
enforcement fix `214342d8a8` (already on dev as PR #2132); FEAT-891's per-spec index entry for TASK-5650
(a historical record of that task; it stays `done-with-issues`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `_procedure_briefing_for`; join it at both seats |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` | MODIFY | both seats carry the procedure block |
| `packages/ai-parrot/tests/sdd/test_procedure_cli.py` | MODIFY | engine briefing + skill-procedure tests |
| `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py` | MODIFY | `<task-file>` placeholder for `procedure` |
| `.claude/commands/sdd-start.md` | MODIFY | `parrot sdd procedure brief` in the briefing step |
| `.agent/workflows/sdd-start.md` | MODIFY | twin |
| `.agents/skills/sdd-start/SKILL.md` | MODIFY | twin |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-start.md` | MODIFY | twin |
| `packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/sdd-start.md` | MODIFY | twin |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-start/SKILL.md` | MODIFY | twin |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.procedure.index import is_stale, read_index   # index.py:131, :120
from parrot.knowledge.wiki.procedure.plane import ProcedurePlane         # plane.py:82
from parrot.knowledge.wiki.procedure.resolver import resolve             # resolver.py:30
from parrot.sdd.config import ProcedureSettings, load_sdd_config         # config.py:25, :303
from parrot.sdd.scripts.procedure import render_brief                    # procedure.py:188
from parrot.sdd.scripts.procedure_probes import SddProbeRunner, scope_for  # procedure_probes.py:33, :133
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
async def _experience_briefing_for(self, ctx: _FeatureCtx, task: PlannedTask) -> str  # line 3984
# call sites: `experience_briefing = await self._experience_briefing_for(ctx, task)` (lines 2593, 3840)

# packages/ai-parrot/src/parrot/knowledge/wiki/procedure/plane.py
@classmethod
def for_root(cls, start: Path | None = None) -> "ProcedurePlane | None"
def render_brief(resolution: Resolution, *, max_lines: int) -> str
def scope_for(checkout: Path, *, feature: str | None = None, task: str | None = None, ...)
```

### Does NOT Exist

- ~~`SddCoderEngine._procedure_briefing_for`~~ on this branch before this task.
- ~~a separate `procedure_briefing` dispatch argument~~: the procedure block rides the existing
  `experience_briefing` string; do not add a new parameter to the dispatchers.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_procedure_cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._experience_briefing_for",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/procedure.py#render_brief",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/procedure_probes.py#scope_for"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- Advisory context must never break dispatch: `_procedure_briefing_for` catches everything and logs at
  `debug`.
- Blocking work (config load, plane discovery, index read, resolution) runs through `asyncio.to_thread`.
- Resolution uses the task worktree (`ctx.worktree`) and `allow_remote=False`, never the main checkout.
- The six `sdd-start` twins stay byte-identical pairwise (`tests/sdd_scripts/test_check_asset_sync.py`).

---

## Implementation Blueprint

### Steps (in order)

1. `git cherry-pick --no-commit ac826c4735`. `engine.py`, `test_engine_dispatch.py` and
   `test_wheel_only_foreign_repo.py` apply on their own.
2. Resolve `test_procedure_cli.py` by keeping both sides: the imports `asyncio` and `subprocess`, then
   this branch's `test_branch_pushed_unknown_on_git_failure` followed by the ported tests.
3. Drop the cherry-picked `experience_cli` scenario (a duplicate key, F601) and add `<task-file>` to the
   `procedure` scenario's placeholders.
4. Add the `parrot sdd procedure brief --task-file <task-file>` line and one explanatory paragraph or
   bullet to the six `sdd-start` twins.

### FILL IN checklist

- [x] Conflict resolution keeps every test from both sides.
- [x] Twins stay identical pairwise.

---

## Acceptance Criteria

- [ ] Native and MCP seat dispatch both carry the procedure block when the plane resolves a step, and are
      unchanged when it resolves nothing.
- [ ] Removing the engine change makes the engine briefing tests fail (mutation check).
- [ ] `/sdd-start` (all six twins) documents `parrot sdd procedure brief --task-file <task-file>`.
- [ ] `ruff check` is clean on the touched Python files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py -q`
- `pytest tests/sdd_scripts/test_check_asset_sync.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py
def test_engine_briefing_both_seats(...): ...  # parametrized: "" and "### Procedure\nNext: Close the task."

# packages/ai-parrot/tests/sdd/test_procedure_cli.py
def test_engine_procedure_briefing(...): ...
def test_engine_uses_task_worktree_state(repo, tmp_path): ...
def test_skill_build_check_and_discovery_invalidation(repo, capsys): ...
def test_configured_skill_directories(repo, capsys): ...
def test_cross_producer_duplicate_is_rejected(repo): ...
```

---

## Agent Instructions

Follow `docs/sdd/WORKFLOW.md` § "Implementing a task by hand" inside
`.parrot/worktrees/feat-FEAT-887-sdd-experience-memory`.

---

## Completion Note

*(Agent fills this in when done)*
