# TASK-5111: Worker/start-twin tests assert the noun-grouped `parrot sdd` CLI spellings

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md` (amendment C26 — noun-grouped CLI)
**Status**: done
**Priority**: low
**Estimated effort**: S (<1h)
**Depends-on**: TASK-5098
**Assigned-to**: agent:sdd-fix
**Discovered-from**: `issue:209fdbe18647`

---

## Context

C26 (TASK-5098) rewrote the shipped SDD assets to `parrot sdd <noun> <verb>`: the worker prompt
and the `/sdd-start` twins now say `parrot sdd task finalize`, `parrot sdd task close` and
`parrot sdd task review validate|prepare`. Three tests still asserted the removed spellings
(`parrot sdd run finalize_task`, `parrot sdd run close_task`, `review_checkpoint validate`) and failed
on both `dev` and this branch. Found during the `/sdd-done FEAT-633` feature-tier run.

## Scope

- Update the asserted strings to the noun-grouped spellings.
- Keep the fallback-loop negative guard meaningful: also reject `task review prepare`.

**NOT in scope**: any change to the prompts or the CLI itself.

## Files to Create / Modify

- `packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py` (MODIFY)
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py` (MODIFY)

## Codebase Contract (Anti-Hallucination)

### Verified spellings in the shipped assets (this branch)
- `.claude/agents/sdd-worker.md:409` — `parrot sdd task finalize --evidence …`
- `.claude/agents/sdd-worker.md:626` — `parrot sdd task review prepare …`
- `.claude/agents/sdd-worker.md:645` — `parrot sdd task review validate …`
- `.claude/commands/sdd-start.md:270,288` — `parrot sdd task finalize`, `parrot sdd task close`
- `.agent/workflows/sdd-start.md`, `.agents/skills/sdd-start/SKILL.md` — same spellings

### Does NOT Exist
- `parrot sdd run finalize_task` / `parrot sdd run close_task` — removed by C26, no alias.

## Acceptance Criteria

- [x] `test_worker_prompt_completion_has_explicit_no_engine_variant` passes.
- [x] `test_worker_prompt_uses_finalize_task_not_manual_jq_close_in_orchestrator_loop` passes.
- [x] `test_start_twins_preserve_semantic_gates` passes (including the `task close` assertion).
- [x] `ruff check` clean on both files.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src pytest -q \
  packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py \
  packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py
```

## Completion Note

Filed and implemented by `/sdd-fix issue:209fdbe18647` on the feature branch (FEAT-633 is done
but unmerged, PR #1927). Implementing commit `cf92e4442a`. Before: 3 failed / 15 passed on
`b818d239e5`. After: 18 passed; ruff clean. The `close_task` assertion in
`test_start_twins_preserve_semantic_gates` was also stale. The earlier `finalize_task` failure
had hidden it, and it is fixed in the same commit.
