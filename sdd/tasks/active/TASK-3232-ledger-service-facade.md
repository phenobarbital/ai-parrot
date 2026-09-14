# TASK-3232: LedgerService facade, scoped queries, and snapshot export

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3226, TASK-3227, TASK-3229, TASK-3231
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. `LedgerService` is the application facade for commands, tools, and lifecycle scripts. It opens the shared-root ledger with FEAT-557's project-derived policy.

## Scope

- Implement all public service methods in spec §2: open, ready, claim, acknowledge, close, context, blockers, export, compact, and audit.
- Construct `LedgerStore` from `find_shared_root`, `load_project_config`, and FEAT-557 `sqlite_policy_from_config`, without ledger-specific SQLite settings.
- Implement feature-scoped blockers, deterministic snapshot export, context budgeting, and audit lag/settings reporting.
- Honor Module 2.2 busy behavior while retaining log-first durability.

**NOT in scope**: Click/MCP rendering, SDD ingestion, federation routing, or SQLite policy implementation.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | CREATE | Public ledger facade. |
| `tests/knowledge/wiki/test_ledger_service.py` | CREATE | Service and deterministic-export tests. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
`find_project_root` and `load_project_config` exist in `project.py:640,667`; `LedgerIndex` and `LedgerLog` are created by TASK-3231 and TASK-3229. After FEAT-557 merges, import `sqlite_policy_from_config` from `project.py` and `WikiStoreBusy` from `store.py`.

### Existing Signatures to Use
`load_project_config(root: Path) -> WikiProjectConfig` is the project-config entry point. `LedgerIndex.claim_issue(issue_id, claimed_by) -> bool` is the claim delegate.

### Does NOT Exist
- ~~`LedgerService`~~ — this task creates it.
- ~~`ledger_busy_timeout` or direct pragma inspection~~ — use FEAT-557 policy/settings APIs.

## Acceptance Criteria

- [ ] The service targets the shared ledger directory from a linked worktree.
- [ ] Non-human acknowledgement is refused and leaves status open.
- [ ] Critical blockers are limited to the requested feature's spec/tasks/reviews.
- [ ] Same-state snapshots are byte-identical and report unchanged on second export.
- [ ] `pytest tests/knowledge/wiki/test_ledger_service.py -q` passes.

## Test Specification

Use a temporary shared root and `.parrot/wiki.json` policy injection; never add a custom ledger SQLite key.

