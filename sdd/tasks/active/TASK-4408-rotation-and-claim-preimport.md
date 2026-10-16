# TASK-4408: Rotation of the committed log + `claim()` pre-import

**Feature**: FEAT-694 — Shared Ledger Event Log (cross-machine sync via git hooks)
**Spec**: `sdd/specs/ledger-shared-event-log.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4406
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (G8, G9). `rotate_events` keeps the committed log bounded by moving old
terminal lines to `sdd/ledger/archive/events-<YYYY-MM>.jsonl`; `LedgerService.claim()` imports
the committed log first so concurrent claims are mostly avoided. Edits the same three files as
TASK-4405/4406, so it runs after them.

---

## Scope

- `shared_log.py`: add `rotate_events(repo_root, *, older_than_days=30, now=None)`.
- `service.py`: add `rotate_shared_log`; change `claim()` body to import first (G8).
- `cli.py`: add `ledger rotate-log` (next to `import-log`).
- Tests: `tests/knowledge/wiki/test_ledger_shared_log_rotation.py`.

**NOT in scope**: running rotation from any hook (forbidden, AC18); `/sdd-done` wiring (TASK-4409);
reducer changes for claims (spec §8 Q1: no reducer change); rotating the local log.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py` | MODIFY | `rotate_events` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | `rotate_shared_log`, `claim` pre-import |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `ledger rotate-log` |
| `tests/knowledge/wiki/test_ledger_shared_log_rotation.py` | CREATE | M5 tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.shared_log import (   # created by TASK-4405
    ARCHIVE_FILENAME_FMT, ARCHIVE_REL_DIR, ROTATION_DAYS_DEFAULT, SHARED_LOG_REL_PATH,
    TERMINAL_ISSUE_STATUSES, SharedLogRotateReport, read_raw_events,
)
from parrot.knowledge.wiki.store import WikiStoreBusy                      # verified: service.py:37
```

### Existing Signatures to Use
```python
# ledger/service.py
    async def claim(self, issue_id: str, actor: str) -> bool               # line 372-374 — `return await self.index.claim_issue(issue_id, actor)`
    async def import_shared_log(self, repo_root=None, *, force=False)      # added by TASK-4406
    async def export_shared_log(self, repo_root=None)                      # added by TASK-4406 — insert rotate_shared_log after it
# ledger/index.py
    async def _apply_issue_claimed(self, event, conn)                      # line 191 — no-op unless status == "open"
    async def _apply_issue_closed(self, event, conn)                       # line 212
# events.py — terminal kinds that set status: "issue.closed" → closed, "issue.superseded" → superseded;
#   "issue.unclaimed"/"issue.claimed"/"issue.acknowledged" re-open/keep non-terminal — verify against index.py reducers
# cli.py
@ledger.command("import-log") … ledger_import_log                          # added by TASK-4406 — insert rotate-log after it
```

### Does NOT Exist
- ~~`wikitoolkit ledger rotate-log`~~ / ~~`LedgerService.rotate_shared_log()`~~ — you add them.
- ~~`ledger compact` rotating the log~~ — `compact` (service.py:560) is index-only; do not touch it.
- ~~`claimed_at` / ts-ordered claim resolution~~ — rejected (spec §8 Q1).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_ledger_shared_log_rotation.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.claim",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex._apply_issue_claimed"
  ]
}
```

---

## Implementation Notes

- **Predicate** (spec §2 (4)): line rotatable iff `ts < cutoff` and (kind not `issue.*`, or the
  subject's final status after replaying the *current file's own* `issue.*` events is in
  `TERMINAL_ISSUE_STATUSES` and the terminal event's `ts < cutoff`). Every event of a
  non-terminal issue stays. Unparseable lines stay (counted in `kept`).
- Determinism: same `(bytes, now)` → byte-identical output; archive file per month of the
  event's own `ts` (`events-YYYY-MM.jsonl`), appended in file order; current file rewritten
  atomically (`tmp` + `os.replace`) with kept lines in original order. Raw lines verbatim.
- Parse `ts` with `datetime.fromisoformat`; treat naive as UTC.
- `claim()`: `try: await self.import_shared_log() except WikiStoreBusy: pass except Exception:
  logger.warning(...)`; skip the import entirely when `not (self.shared_root / SHARED_LOG_REL_PATH).exists()`
  (from_dir/MCP services). Then the unchanged `claim_issue` call. (`import_shared_log` already
  turns busy into `index_busy=True`; the except is belt-and-braces.)
- CLI `rotate-log --stage`: `git -C root add -- sdd/ledger/events.jsonl <each touched archive>`
  only when `moved > 0`. `--now` parsed via `datetime.fromisoformat`.

---

## Implementation Blueprint

### Steps (in order)
1. `rotate_events` in `shared_log.py` (append at end of module).
2. `rotate_shared_log` + `claim` change in `service.py`.
3. `rotate-log` command in `cli.py`.
4. Tests; Validation Commands.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py` (MODIFY)
```python
# APPEND at end of module (file created by TASK-4405; add `from datetime import timedelta, timezone` to imports)
def rotate_events(
    repo_root: Path, *, older_than_days: int = ROTATION_DAYS_DEFAULT, now: datetime | None = None
) -> SharedLogRotateReport:
    """Move old terminal lines of the committed log into monthly archive files (deterministic)."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=older_than_days)
    current = repo_root / SHARED_LOG_REL_PATH
    # FILL IN: read raw lines (keep unparseable in place); replay issue.* per subject → final status +
    # terminal ts; partition lines; append moved lines per month to ARCHIVE_REL_DIR/ARCHIVE_FILENAME_FMT
    # (sorted month order for determinism of archives_touched); rewrite current atomically only when
    # moved > 0 — bounded by AC16, spec §7 "must never move an event of a non-terminal issue"
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '        return await self.index.claim_issue(issue_id, actor)' service.py)
# REPLACE the body of `claim` (service.py:372-374) with:
    async def claim(self, issue_id: str, actor: str) -> bool:
        """Import the committed shared log first (FEAT-694 G8), then :meth:`LedgerIndex.claim_issue`."""
        if (self.shared_root / SHARED_LOG_REL_PATH).exists():
            try:
                await self.import_shared_log()
            except WikiStoreBusy:
                pass
            except Exception:  # noqa: BLE001 — a broken checkout must never block a claim (AC15)
                logger.warning("Shared ledger log import before claim failed; claiming anyway.", exc_info=True)
        return await self.index.claim_issue(issue_id, actor)

# AFTER `import_shared_log` (added by TASK-4406):
    async def rotate_shared_log(
        self, repo_root: Path | None = None, *, older_than_days: int = 30, now: datetime | None = None
    ) -> SharedLogRotateReport:
        """Rotate the committed log (``/sdd-done`` 9.1 only). Never touches the local log or index."""
        return await asyncio.to_thread(
            rotate_events, repo_root or self.shared_root, older_than_days=older_than_days, now=now
        )
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)
```python
# AFTER the `ledger_import_log` function (added by TASK-4406), before `@ledger.command("sync")`
@ledger.command("rotate-log")
@click.option("--repo-root", default=None)
@click.option("--older-than-days", default=30, show_default=True, type=click.IntRange(min=1))
@click.option("--now", default=None, help="ISO-8601 UTC override of 'now' (tests / reproducible runs)")
@click.option("--stage", is_flag=True, default=False, help="git add current + touched archives when anything moved")
@click.option("--quiet", is_flag=True, default=False)
@remote_cli.remote_aware(proxied=False)
def ledger_rotate_log(repo_root: str | None, older_than_days: int, now: str | None, stage: bool, quiet: bool) -> None:
    """Move terminal events older than N days from sdd/ledger/events.jsonl to sdd/ledger/archive/."""
    # FILL IN: "Rotated N events into K archive file(s)" / "(nothing to rotate)"; exit 0
```

### `tests/knowledge/wiki/test_ledger_shared_log_rotation.py` (CREATE)
```python
"""FEAT-694 M5 — committed-log rotation and claim pre-import."""
# FILL IN: test_rotate_moves_only_terminal_and_old, test_rotate_is_deterministic_and_idempotent,
# test_rotate_keeps_unparseable_lines, test_marker_invalidated_by_rotation, test_claim_imports_first
# (incl. unreadable checkout → WARNING, claim proceeds), test_cli_rotate_log_stage_adds_archive (git init)
```

### FILL IN checklist
- [ ] `rotate_events` predicate + determinism; AC16
- [ ] `rotate-log` command output/stage
- [ ] six tests

---

## Acceptance Criteria

- [ ] AC15, AC16, AC17 (rotation side).
- [ ] Existing `test_cli_ledger.py` claim tests still pass.
- [ ] `ruff check` clean on touched files.

## Validation Commands

- `pytest tests/knowledge/wiki/test_ledger_shared_log_rotation.py -q`
- `pytest tests/knowledge/wiki/test_cli_ledger.py -q`

---

## Test Specification

Spec §4 rows tagged M5 (use `now=` / `--now` fixed values).

---

## Agent Instructions

Standard SDD flow (`sdd/templates/task.md` § Agent Instructions); feature worktree
`feat-FEAT-694-ledger-shared-event-log`; `PYTHONPATH=packages/ai-parrot/src`; close with
`scripts/sdd/close_task.sh TASK-4408 ledger-shared-event-log verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
