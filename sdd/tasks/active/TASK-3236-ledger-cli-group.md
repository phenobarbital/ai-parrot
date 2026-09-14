# TASK-3236: wikitoolkit ledger command group

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3226, TASK-3232, TASK-3233
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9. The CLI is the operator and shell-script surface, including human-only acknowledgement and rebuild/ingest maintenance.

## Scope

- Add `wikitoolkit ledger` open, ready, claim, acknowledge, close, context, blockers, export, sync, rebuild, ingest-sdd, compact, and audit.
- Bind to `LedgerService` with typed Click parsing and actionable `WikiStoreBusy` exit behavior.
- Checkpoint only after successful rebuild/ingest, non-fatally; open/claim/close/sync do not checkpoint.
- Test registration, exits, acknowledgement restriction, export, and checkpoint call sites.

**NOT in scope**: service/reducer implementation, generic wiki CLI busy behavior, workflow documents, or log rotation.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | Ledger Click group/commands. |
| `tests/knowledge/wiki/test_cli_ledger.py` | CREATE | CLI suite. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
`wiki` is the Click group in `cli.py`; `LedgerService` is provided by TASK-3232.

### Existing Signatures to Use
`@wiki.group(name="symbols")` at `cli.py:2118` and `@wiki.group(name="ns")` at `cli.py:2320` are the group-registration patterns.

### Does NOT Exist
- ~~a `ledger` Click group~~ — this task creates it.
- ~~a dedicated `wikitoolkit ledger related` command~~ — use `wiki_related`.
- ~~CLI-owned SQLite busy strings or pragmas~~ — render FEAT-557's typed exception only.

## Acceptance Criteria

- [ ] Every Module 9 command is discoverable under `wikitoolkit ledger`.
- [ ] Busy open/close is a soft `index_pending` success; busy claim exits 2 without a false result.
- [ ] Only rebuild/ingest-sdd checkpoint and checkpoint failure is non-fatal.
- [ ] `pytest tests/knowledge/wiki/test_cli_ledger.py -q` passes.

## Test Specification

Use Click runner with a temporary shared root; mock only the service boundary.
