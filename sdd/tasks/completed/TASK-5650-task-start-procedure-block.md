# TASK-5650: Procedure block at task start (through the FEAT-887 briefing path)

**Feature**: FEAT-891 — Procedural Graph Plane
**Spec**: `sdd/specs/procedural-graph-plane.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5644, TASK-5651
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11 and goal G9. Every seat receives a short procedure block when a task starts:
where the task is, the next valid step, and the mandatory rules ahead. It is delivered through the
briefing path that FEAT-887 (`sdd-experience-memory`) creates — **not** through a second channel.

> **GATE — read this first.** This task depends on code from another feature that was not merged
> when the task was written (FEAT-887 had 24 pending tasks and no code at `9a3a611b0c`). Run the
> two checks in Step 0. If either fails, **stop**: do not implement anything, do not create an
> alternative briefing channel, close the task as `done-with-issues` and write in the Completion
> Note that FEAT-887 has not landed.

---

## Scope

- Add `_procedure_briefing_for` to the sdd-coder engine and join its text to the experience
  briefing.
- Add one step to the `/sdd-start` command text, next to the `parrot sdd experience brief` step:
  `parrot sdd procedure brief --task-file <task file>`; regenerate the packaged twins.
- Add one engine test.

**NOT in scope**: a new hook or event, prompt-submit injection, changes to `render_brief`,
anything FEAT-887 owns.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `_procedure_briefing_for`, joined to the experience briefing |
| `.claude/commands/sdd-start.md` | MODIFY | One step next to the experience brief |
| `.agent/workflows/sdd-start.md` | MODIFY | Same step (Antigravity twin) |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-start.md` | MODIFY | Generated twin (`--write`) |
| `packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/sdd-start.md` | MODIFY | Generated twin (`--write`) |
| `packages/ai-parrot/tests/sdd/test_procedure_cli.py` | MODIFY | Engine briefing test |
| `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py` | MODIFY | Only if the documented placeholder is not resolved by the `procedure` scenario |

---

## Codebase Contract (Anti-Hallucination)

> Base `9a3a611b0c` (dev). **Every FEAT-887 reference below is UNVERIFIED** — it is taken from
> `sdd/specs/sdd-experience-memory.spec.md` and from FEAT-887 task files (TASK-5607 engine,
> TASK-5608 `sdd-start` assets), not from code. Verify each one in Step 0 and correct this section
> before writing code.

### Verified Imports
```python
from parrot.sdd.scripts.procedure import render_brief            # TASK-5644
from parrot.knowledge.wiki.procedure.resolver import resolve     # TASK-5641
from parrot.sdd.scripts.procedure_probes import SddProbeRunner, scope_for   # TASK-5641
from parrot.knowledge.wiki.procedure.plane import ProcedurePlane # TASK-5640
from parrot.sdd.config import load_sdd_config                    # sdd/config.py:278
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
#   (unverified — FEAT-887 not merged) an async method that returns the experience briefing text for one task:
#       async def _experience_briefing_for(self, ctx: _FeatureCtx, task: PlannedTask) -> str
#   and the call site where its result is put into the coder's task context.
#   `grep -c '_experience_briefing_for' …/engine.py` returned 0 at 9a3a611b0c.

# .claude/commands/sdd-start.md  (unverified — FEAT-887 not merged)
#   a step that runs `parrot sdd experience brief --task-file <…>`; `grep -c 'experience brief'` returned 0 at 9a3a611b0c.

# Dependency-provided by this feature (verified by their own tasks):
def render_brief(resolution: Resolution, *, max_lines: int) -> str          # '' when there is nothing to say
def resolve(specs, scope, runner, *, allow_remote: bool = True, stale: bool = False) -> Resolution
class ProcedurePlane: @classmethod for_root(cls, start=None) -> "ProcedurePlane | None"; async def specs(self) -> list[ProcedureSpec]
# scripts/sdd/check_asset_sync.py --write regenerates the packaged twins of .claude/commands/sdd-*.md and .agent/workflows/sdd-*.md
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.experience`~~, ~~`SddCoderEngine._experience_briefing_for`~~,
  ~~`parrot sdd experience brief`~~ — specified by FEAT-887; absent at `9a3a611b0c`.
- ~~A pre-tool or prompt-submit hook for briefings~~ — neither feature registers one.
- ~~`parrot sdd task start`~~ — not a CLI verb.
- ~~A second briefing channel~~ — forbidden by spec §5.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py", "action": "MODIFY"},
    {"path": ".claude/commands/sdd-start.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-start.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-start.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/sdd-start.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_procedure_cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- **Exclusive task** (`parallel: false`): it edits the shared `/sdd-start` command twins and
  regenerates the packaged assets.
- In a worktree prefix tests with `PYTHONPATH=packages/ai-parrot/src`.
- The engine method uses **local probes only**, returns `""` on any error, when no plane exists,
  when the plane is stale, or when `procedure.enabled` is false, and logs at debug level. It must
  never raise into the dispatch path.
- The two briefings are joined with one blank line; an empty procedure block adds nothing (no
  trailing blank line).
- In the command text, use the **same task-file placeholder** as the neighbouring
  `parrot sdd experience brief` line. The wheel-only smoke resolves documented invocations through
  `SCENARIOS["procedure"].placeholders` (added by TASK-5651); if that placeholder is not already
  resolved there or in `COMMON`, add it to the `procedure` scenario.
- Do not edit the packaged twins by hand: edit the two sources, `git add` them, then
  `python scripts/sdd/check_asset_sync.py --write`; `git status --short` must show only this
  task's files.

---

## Implementation Blueprint

### Steps (in order)
0. **Gate** — run:
   `grep -c '_experience_briefing_for' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`
   and `grep -c 'experience brief' .claude/commands/sdd-start.md`. Both must be ≥ 1. Otherwise stop
   as described in the Context. — *why*: this task attaches to code another feature creates.
1. Read the experience briefing method and its call site; rewrite the "Existing Signatures"
   section of this file with the real names, line numbers and occurrence counts — *why*: the
   contract below is a forecast, not a verification.
2. Add `_procedure_briefing_for` and join its result — *why*: one channel, two blocks.
3. Add the command step in both sources, regenerate the twins.
4. Add the test; run the validation commands.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)
```python
# FILL IN: disambiguate — after Step 1, quote the verified anchor (the `_experience_briefing_for` definition) with its
# path:NN and occurrence count, and insert the method below right after it.
    async def _procedure_briefing_for(self, ctx: _FeatureCtx, task: PlannedTask) -> str:
        """render_brief(resolve(...)) for the task with local probes only; '' on any error or when
        'procedure.enabled' is false. The result is joined to the experience briefing with a blank line."""
        try:
            # FILL IN: settings (load_sdd_config(<worktree root>).procedure or defaults) -> return "" when disabled;
            # ProcedurePlane.for_root(<worktree root>) -> None / stale index -> "";
            # specs = await plane.specs(); scope = scope_for(<worktree root>, feature=<ctx slug>, task=<task id>);
            # resolution = await asyncio.to_thread(resolve, specs, scope, SddProbeRunner(<worktree root>), allow_remote=False);
            # return render_brief(resolution, max_lines=settings.brief_max_lines)
            ...
        except Exception:  # noqa: BLE001 — a briefing never breaks a dispatch
            self.logger.debug("procedure briefing skipped", exc_info=True)
            return ""

# FILL IN: at the verified call site of `_experience_briefing_for`, join the two texts:
#     parts = [text for text in (experience, await self._procedure_briefing_for(ctx, task)) if text]
#     briefing = "\n\n".join(parts)
```
**Why**: the signature is fixed by spec §3 M11. The attribute names of `ctx` and `task` (worktree
root, feature slug, task id) are FEAT-887 / engine internals — read them, do not guess them.

### `.claude/commands/sdd-start.md` and `.agent/workflows/sdd-start.md` (MODIFY)
```markdown
<!-- FILL IN: disambiguate — quote the verified `parrot sdd experience brief` step (path:NN, occurrence count) in each file
     and add directly below it, in the same list/code-block style: -->
parrot sdd procedure brief --task-file <same placeholder as the line above>
<!-- with one sentence: "Prints the procedure block for this task (next valid step and mandatory rules); empty when the
     repository has no procedure plane." -->
```

### `packages/ai-parrot/tests/sdd/test_procedure_cli.py` (MODIFY)
```python
# Append at the end of the file. Anchor (re-verify): `def test_render_brief_limits_lines() -> None:` (TASK-5644)
# occurrences: 1 expected (verify: grep -c 'def test_render_brief_limits_lines' packages/ai-parrot/tests/sdd/test_procedure_cli.py)

async def test_engine_procedure_briefing(repo: Path) -> None:
    """The engine block equals `procedure brief` for the same task, and is '' when the plane is absent or disabled."""
    # FILL IN: build the engine / ctx / task the way FEAT-887's engine tests do (read them first); three cases.
```

### FILL IN checklist
- [ ] Step 0 gate passed, or the task is closed `done-with-issues` with nothing implemented
- [ ] This file's "Existing Signatures" rewritten with verified anchors before any code
- [ ] `engine.py` — the method body and the join at the call site
- [ ] Both command sources edited; twins regenerated with `--write`
- [ ] `test_procedure_cli.py::test_engine_procedure_briefing`
- [ ] The documented placeholder resolves in the wheel-only smoke (`SCENARIOS["procedure"]`)

---

## Acceptance Criteria

- [ ] The procedure block reaches a coder through the same briefing as the experience pitfalls; no second channel exists.
- [ ] The block is empty (and nothing breaks) when there is no plane, the plane is stale, or `procedure.enabled` is false.
- [ ] `/sdd-start` documents `parrot sdd procedure brief --task-file …` in both sources, and the packaged twins are in sync.
- [ ] If FEAT-887 has not landed: nothing is implemented and the Completion Note says so.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_procedure_cli.py -q`
- `pytest tests/sdd_scripts/test_check_asset_sync.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug procedural-graph-plane --feature-id FEAT-891`), never on `dev`.
2. Check TASK-5644 and TASK-5651 are `done` in `sdd/tasks/index/procedural-graph-plane.json`.
3. Run Step 0. If the gate fails, stop: close with `parrot sdd task close TASK-5650 procedural-graph-plane forced`, set the index status to `done-with-issues`, and explain in the Completion Note.
4. Otherwise fix this file's contract first, implement only the files listed above, and complete every `FILL IN`.
5. Run `ruff check --fix` on the touched Python files and the Validation Commands.
6. Commit the code, then close with `parrot sdd task close TASK-5650 procedural-graph-plane verified` and fill in the Completion Note.

---

## Completion Note

**Status: done-with-issues — NOT IMPLEMENTED (gate failed).**

The task's Step 0 GATE requires FEAT-887 (`sdd-experience-memory`) briefing code to exist. Verified on this branch
(base includes all other FEAT-891 tasks):

- `_experience_briefing_for` has 0 matches in `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`.
- `experience brief` has 0 matches in `.claude/commands/sdd-start.md`.

Per the task instructions, nothing was implemented and no alternative briefing channel was created. Two coder
attempts (gpt-5.6-sol, gpt-5.6-terra) returned `empty_delivery`, consistent with the gate. No files were changed.

Follow-up once FEAT-887 lands: implement `_procedure_briefing_for` in `sdd_coder/engine.py`, add the
`parrot sdd procedure brief --task-file <task file>` step to the `sdd-start` command twins, regenerate packaged
assets (`check_asset_sync.py --write`), and add the engine test. Filed in the ledger as a feature_gap.
