# TASK-4895: Redundant ledger closes never block outbox delivery

**Feature**: FEAT-771 — wikitoolkit CLI fixes
**Spec**: `sdd/specs/wiki-cli-fixes.spec.md`
**Discovered-from**: `issue:28686ebe9af7`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §1.A, §2 Module 1. An `issue.closed` for an issue already terminal on dev makes the whole batch a
`conflict`, `integrate` stops at it, and `prepare` re-seals the event even after a manual batch edit.

---

## Scope

- `integration.py`: `MergePlan.redundant_closes: list[str]`; new pure `drop_redundant_closes(remote, plan)`;
  in `_attempt`, apply it right after `merge_batch` and before `find_transition_conflicts`; append only kept
  lines; verification `expected` and `verified_digest` exclude redundant ids; pass
  `skipped_event_ids=plan.redundant_closes` to `acknowledge`; set `skipped` on the success report; INFO log
  per skipped close.
- `outbox.py`: `LedgerReceipt.skipped_event_ids`, `LedgerDeliveryReport.skipped` (both default `[]`);
  `acknowledge(..., skipped_event_ids: Sequence[str] = ())`; `_skipped_ids_sync()` (union over
  `receipts/*.json`); `_prepare_sync` and `_status_sync` exclude those ids.
- `cli.py` `ledger_outbox_integrate`: continue past `conflict`/`unsupported`, break on `pending`; exit code =
  max of report codes. `_emit_delivery_reports` text mode prints skipped ids when present.
- `docs/sdd/ledger-outbox.md`: document redundant closes and the loop/exit rule.
- Tests per spec §4 (Module 1 rows).

**NOT in scope**: `find_transition_conflicts` (unchanged), a discard command, Module 2/3 changes.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py` | MODIFY |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/outbox.py` | MODIFY |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY |
| `docs/sdd/ledger-outbox.md` | MODIFY |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_integration.py` | MODIFY |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox.py` | MODIFY |
| `packages/ai-parrot/tests/knowledge/wiki/test_cli_ledger_outbox.py` | MODIFY |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
See spec §6.

### Existing Signatures
See spec §6 (`MergePlan` :36, `merge_batch` :68, `_apply` :119, `_attempt` :297 with `plan` :344,
`conflicts` :358, `expected` :509, `verified_digest` :524, `acknowledge` :527; outbox `LedgerReceipt` :66,
`acknowledge` :358, `_prepare_sync` :274, `_status_sync` :404; cli integrate loop break :3882).

### Does NOT Exist
`drop_redundant_closes`, `MergePlan.redundant_closes`, `LedgerReceipt.skipped_event_ids`,
`LedgerDeliveryReport.skipped`, `LedgerOutbox._skipped_ids_sync` — created here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/outbox.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py#LedgerIntegrator._attempt",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/outbox.py#LedgerOutbox._prepare_sync",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#ledger_outbox_integrate"
  ]
}
```

---

## Implementation Notes

- `drop_redundant_closes` replays `remote` with `_apply`, then for each new event: an `issue.closed` whose
  subject state is in `TERMINAL` → redundant (not applied); otherwise keep and `_apply`. Keep `new_lines`
  and `new_events` index-aligned; copy `duplicates`.
- Old receipts lack `skipped_event_ids`; the default keeps them loadable.
- An all-redundant batch takes the existing `not plan.new_lines` path (`already_delivered`, no commit).

---

## Acceptance Criteria

- [ ] Spec §5 criteria 1–4 hold.
- [ ] `ruff check` clean on the changed files.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_integration.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli_ledger_outbox.py -q`

---

## Test Specification

Spec §4 Unit Tests, Module 1 rows. Reuse `two_clones` / `_batch_for` for the delivery tests.

---

## Agent Instructions

Implement inside `.claude/worktrees/feat-FEAT-771-wiki-cli-fixes`; run tests with
`PYTHONPATH=packages/ai-parrot/src`.

---

## Completion Note

_(filled on completion)_
