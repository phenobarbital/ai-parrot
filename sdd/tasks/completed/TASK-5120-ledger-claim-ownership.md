# TASK-5120: Parallel `/sdd-fix` sessions must not close or release each other's ledger claims

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md` (rev 0.12 — ledger fixes)
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5119
**Assigned-to**: unassigned
**Discovered-from**: `issue:5439a91953a4`

---

## Context

On 2026-11-03 two `/sdd-fix` sessions started on two issues of one fix group (`issue:c34721a5b110`,
`issue:e493230f1b6a`). Each claimed one issue, then widened its scope to the whole group, and both fixed and closed
both issues: PR #1934 merged, PR #1935 was a conflicting duplicate. `LedgerIndex.claim_issue` is atomic, but every
`/sdd-fix` claims, closes and unclaims as the constant actor `agent:sdd-fix`, and `close_issue`/`unclaim_issue`
never check who holds the claim — so a session cannot tell its own claim from another's, and nothing stops it from
closing an issue someone else claimed.

---

## Scope

- `LedgerIndex.close_issue` / `unclaim_issue` take `force: bool = False`; when the issue is `claimed` by an actor
  other than the caller and `force` is false they raise `ClaimHeldByOther` (inside the same ledger transaction).
  An `open` issue still closes for any actor.
- `LedgerService.close_issue` / `unclaim` pass `force` through.
- CLI `wikitoolkit ledger close|unclaim` gain `--force`; a refusal exits 1 and names the claimant. `--force` with a
  remote ledger is refused (the MCP `ledger_close` schema is unchanged — forcing is a local, deliberate act).
- `/sdd-done`'s closer (`close_resolved_issues.py`) passes `--force`: its two keys are the authority for the SDD-lane
  hand-off of an issue a `/sdd-fix` session claimed. `/sdd-done`'s brief close passes `--actor agent:sdd-brief`
  (the brief's claimant).
- `/sdd-fix` twins (+ `_assets` copies): mint a per-session actor `agent:sdd-fix:<8 hex>` once and use it for every
  claim/close/unclaim; scope is fixed at claim time — never widen (or offer to) without claiming each added issue,
  and drop any whose claim fails; never `--force` past a foreign claim.

**NOT in scope**: `fix_planner.group_issues` (grouping is unchanged — claimed issues are already excluded from
`ready_work`); the MCP tool schemas / golden manifests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` | MODIFY | `ClaimHeldByOther`, ownership check, `force` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | pass `force` through |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `--force` on close/unclaim, refusal message |
| `packages/ai-parrot/src/parrot/sdd/scripts/close_resolved_issues.py` | MODIFY | `--force` on the hand-off close |
| `.claude/commands/sdd-fix.md`, `.agent/workflows/sdd-fix.md`, `.agents/skills/sdd-fix/SKILL.md` (+ `_assets` copies) | MODIFY | per-session actor, fixed scope |
| `.claude/commands/sdd-done.md` (+ `_assets` copy) | MODIFY | brief close as `agent:sdd-brief` |
| `tests/knowledge/wiki/test_ledger_fix_lifecycle.py`, `tests/knowledge/wiki/test_cli_ledger.py` | MODIFY | new tests |
| `tests/knowledge/wiki/test_cli_plan_fix.py`, `tests/knowledge/wiki/test_ledger_integration.py`, `tests/sdd_scripts/test_close_resolved_issues.py` | MODIFY | follow the new contract |

---

## Codebase Contract (Anti-Hallucination)

Verified on `feat-FEAT-633-parrot-installer` at `2cb0d18d09` (2026-11-03).

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py
class LedgerIndex:
    async def claim_issue(self, issue_id: str, claimed_by: str) -> bool
    async def close_issue(self, issue_id: str, actor: str, reason: str, resolved_by: str | None = None) -> bool
    async def unclaim_issue(self, issue_id: str, actor: str, reason: str) -> bool
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
class LedgerService:
    async def close_issue(self, issue_id: str, reason: str, actor: str, resolved_by: str | None = None) -> bool
    async def unclaim(self, issue_id: str, reason: str, actor: str) -> bool
```

---

## Acceptance Criteria

- [ ] A session cannot close or unclaim an issue claimed by another actor (`ClaimHeldByOther`; CLI exit 1 naming the claimant).
- [ ] The claimant closes/unclaims normally; `force=True` / `--force` overrides; an unclaimed issue closes for anyone.
- [ ] `/sdd-done` still closes handed-off issues (closer passes `--force`) and brief issues (`--actor agent:sdd-brief`).
- [ ] `/sdd-fix` twins use a per-session actor and forbid scope widening without a claim; twin bodies stay identical; `_assets` in sync.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest tests/knowledge/wiki/test_ledger_fix_lifecycle.py tests/knowledge/wiki/test_cli_ledger.py tests/knowledge/wiki/test_cli_plan_fix.py tests/knowledge/wiki/test_ledger_integration.py tests/knowledge/wiki/test_ledger_service.py tests/sdd_scripts/test_close_resolved_issues.py tests/sdd/test_ledger_workflow_twins.py tests/sdd_scripts/test_check_asset_sync.py tests/sdd_scripts/test_sdd_done_brief_contract.py -q`

## Agent Instructions

Work in `feat-FEAT-633-parrot-installer`; run tests with `PYTHONPATH=packages/ai-parrot/src`; stage only the files
above; close with `parrot sdd task close TASK-5120 parrot-installer verified`.

---

## Completion Note
**Completed by**: Claude Opus 5.5 (/sdd-fix, sequential)
**Date**: 2026-11-03
**Notes**: `ClaimHeldByOther` + `_check_claim_owner` in `ledger/index.py`, checked inside the close/unclaim ledger transaction; `force` threaded through `LedgerService` and CLI `--force` (refused with a remote ledger; MCP `ledger_close` schema unchanged, so golden manifests are untouched — an MCP close of a foreign claim now returns an error result). `close_resolved_issues.py` passes `--force` (SDD-lane hand-off); `/sdd-done` brief close acts as `agent:sdd-brief`. `/sdd-fix` twins: per-session `agent:sdd-fix:<8 hex>` actor, scope fixed at claim time, never `--force` past a foreign claim; `_assets` copies synced, twin bodies identical. 4 lifecycle + 3 CLI tests; mutation-checked (disabling the guard fails the two ownership tests). Three existing tests updated to the new contract (closer/unclaimer now the claimant). Validation: 153 passed after merging origin/dev; ruff clean. `fix_planner.group_issues` unchanged: claimed issues are already excluded from `ready_work`.
