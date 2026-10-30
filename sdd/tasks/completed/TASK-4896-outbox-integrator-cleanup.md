# TASK-4896: Outbox integrator cleanup and CLI error mapping

**Feature**: FEAT-771 — wikitoolkit CLI fixes
**Spec**: `sdd/specs/wiki-cli-fixes.spec.md`
**Discovered-from**: `issue:81330c0acb9f`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4895
**Assigned-to**: unassigned

---

## Context

Spec §1.B, §2 Module 2. `_attempt` leaks its `_ledger-outbox-<uuid>` worktree on unexpected exceptions,
`build_scratch_snapshot` leaks `outbox/scratch/<uuid>/`, and the CLI mis-maps several error cases.

---

## Scope

- `integration.py`:
  - `_attempt`: add `except Exception` after the outer `except StrictLedgerReadError` (covers everything after
    `tmp` exists): `logger.exception`, best-effort `_remove_if_clean(tmp)` (guarded), return `pending` /
    `error_code="unexpected-error"` with the kept path as `recovery_path`.
  - `integrate()`: wrap each `_attempt` call so an exception raised before `tmp` exists also becomes
    `pending` / `unexpected-error`.
  - `build_scratch_snapshot`: `try/finally` → `await asyncio.to_thread(shutil.rmtree, scratch_dir, ignore_errors=True)`.
- `outbox.py`: `class EventIdentityError(StrictLedgerReadError)`; `verify_event_identity` raises it;
  `read_strict_events` uses `isinstance(exc, EventIdentityError)`.
- `cli.py`:
  - `ledger_outbox_prepare`: trailing `except Exception` → `except IntegrationError`.
  - `ledger_outbox_status`: both `except Exception` → `except (IntegrationError, OSError)`.
  - `ledger_outbox_integrate --batch-id`: not pending but `outbox.receipt_for(id)` exists → `already_delivered`
    report, exit 0; otherwise `unknown-batch`/exit 3 as today.
- Tests per spec §4 (Module 2 rows).

**NOT in scope**: Module 1/3 behaviour.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py` | MODIFY |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/outbox.py` | MODIFY |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_integration.py` | MODIFY |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox.py` | MODIFY |
| `packages/ai-parrot/tests/knowledge/wiki/test_cli_ledger_outbox.py` | MODIFY |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
See spec §6. `IntegrationError` is defined in `integration.py:185`; cli.py imports `LedgerIntegrator`
from that module at :135 (add `IntegrationError` to that import).

### Existing Signatures
See spec §6 (`build_scratch_snapshot` :144, `integrate` :242, `_remove_if_clean` :289, `_attempt` :297 /
`tmp` :326 / outer `except StrictLedgerReadError` :543; `verify_event_identity` :98, string match :138;
cli prepare :3733/:3771, status :3791/:3801/:3811, integrate :3845/:3870). Line numbers are pre-TASK-4895.

### Does NOT Exist
`EventIdentityError` — created here. `LedgerService.close()` / `LedgerIndex.close()` do not exist.

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
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py#build_scratch_snapshot",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#ledger_outbox_integrate"
  ]
}
```

---

## Implementation Notes

- `asyncio.CancelledError` is a `BaseException`; `except Exception` must not swallow it.
- Keep the deliberately retained recovery trees (`hook-mutated-commit`, `push-failed` after commit,
  `verify-failed`) exactly as today; only unexpected exceptions are new.

---

## Acceptance Criteria

- [ ] Spec §5 criteria 5–7 hold.
- [ ] `ruff check` clean on the changed files.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_integration.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli_ledger_outbox.py -q`

---

## Test Specification

Spec §4 Unit Tests, Module 2 rows.

---

## Agent Instructions

Implement inside `.claude/worktrees/feat-FEAT-771-wiki-cli-fixes`; run tests with
`PYTHONPATH=packages/ai-parrot/src`.

---

## Completion Note

**Completed**: 2026-10-30 — verified. Implementing commit `68d2fcf89`.

- `integration.py`: `_attempt` gains `except Exception` after the outer `except StrictLedgerReadError` —
  `logger.exception`, guarded `_remove_if_clean(tmp)`, `pending`/`unexpected-error` with the kept path (if any)
  as `recovery_path`. `integrate()` wraps each `_attempt` the same way for failures before `tmp` exists.
  `build_scratch_snapshot` removes `scratch_dir` in a `finally` (`shutil.rmtree` via `asyncio.to_thread`).
  Deliberate recovery trees (`hook-mutated-commit`, post-commit `push-failed`, `verify-failed`) unchanged.
- `outbox.py`: `EventIdentityError(StrictLedgerReadError)`; `verify_event_identity` raises it and
  `read_strict_events` re-raises it by type (message text unchanged; nothing else matched on it).
- `cli.py`: imports `IntegrationError`; `prepare` catches `IntegrationError` (not `Exception`); `status` catches
  `(IntegrationError, OSError)` twice; `integrate --batch-id` of a receipted batch → `already_delivered`, exit 0,
  carrying the receipt's `skipped_event_ids`; a malformed id (`ValueError`) or no receipt keeps `unknown-batch`.
- Tests: 7 new (unexpected error leaves no worktree, scratch removed, typed identity error, receipted and unknown
  `--batch-id`, prepare remote failure exit 2, prepare programmer error propagates). Outbox suites: 51 passed.
  `ruff check` clean.
