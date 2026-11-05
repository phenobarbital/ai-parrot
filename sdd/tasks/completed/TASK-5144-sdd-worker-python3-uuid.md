# TASK-5144: sdd-worker — use `python3` in execution_id UUID guidance

**Feature**: FEAT-797 — sdd-worker agent: drop bare `python` from execution_id guidance
**Spec**: `sdd/specs/agents-sdd-worker-fixes.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:6480940ab36a`

---

## Context

The C29 `bare-python` gate (`test_no_c29_findings_in_shipped_files`) fails because
`sdd-worker.md:335` tells the worker to run `python -c 'import uuid; print(uuid.uuid4())'`.

## Scope

- Replace `python -c` with `python3 -c` on line 335 of both copies of `sdd-worker.md`.

**NOT in scope**: audit rules, allowlists, any other asset.

## Files to Create / Modify

| File | Action |
|---|---|
| `.claude/agents/sdd-worker.md` | MODIFY |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md` | MODIFY |

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
- `.claude/agents/sdd-worker.md:335` — `` `python -c 'import uuid; print(uuid.uuid4())'` (fallback: `cat /proc/sys/kernel/random/uuid`). NEVER compose it by ``
- `packages/ai-parrot/src/parrot/sdd/audit.py:71` — `bare-python` matches `python`, never `python3`.

### Does NOT Exist
- No allowlist for C29 kinds in `test_no_repo_script_refs.py` (only `_C16_ALLOWLIST`); do not add one.

## Implementation Notes

Keep the two files byte-identical.

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py -q` passes.
- [ ] The two `sdd-worker.md` copies are byte-identical.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py -q`

## Completion Note

Done 2026-11-03 (commit fc52eed3f7). Line 335 of both `sdd-worker.md` copies now says `python3 -c`.
`pytest packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py -q` → 11 passed (was 1 failed).
Note: the two copies were already not byte-identical before this task — line 32 of the repo copy pins
the local venv path for the worktree-guard hook, the shipped asset uses bare `parrot`. That difference is
intentional and was left alone; apart from it the files match.
