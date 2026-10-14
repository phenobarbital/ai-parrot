# TASK-4295: Reconciling `export_snapshot` + service tests

**Feature**: FEAT-671 — Reconciling Ledger Snapshot Export
**Spec**: `sdd/specs/commands-sdd-done-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:62038221413a` (ledger, `major`/`bug`, group `fixgroup:17fe5de32cd8`)

---

## Context

`LedgerService.export_snapshot()` rebuilds `sdd/ledger/issues.jsonl` only from the issues this
machine's local ledger has ever seen and overwrites `dest` with that view. Because
`events.jsonl` is machine-local, every export from a machine whose log is behind silently
drops other people's issues (`a029275b9` had to restore 118 of them; on 2026-10-14 this machine
would drop 184 of 279). Spec §1, §2 and §3 Module 1.

This task implements the reconciliation pre-pass (spec §3 M1) and the seven service-level tests
of spec §4. The CLI flag and its test are TASK-4296; the docs are TASK-4297.

---

## Scope

- Add module-level helper `_read_snapshot_rows(dest: Path) -> list[dict[str, Any]]` to
  `ledger/service.py` directly after `_write_snapshot_if_changed`.
- Change `LedgerService.export_snapshot` to `export_snapshot(self, dest: Path, *, reconcile: bool = True) -> bool`:
  carry forward every row already in `dest` whose `issue_id` is absent from `_all_issues()`;
  local rows keep the existing status filter; keep the sort + `sort_keys=True` determinism and the
  `bool` return; log carried count at INFO when > 0.
- Create `packages/ai-parrot/tests/knowledge/wiki/test_ledger_export_snapshot.py` with the fixture,
  helpers and the seven service tests named in spec §4 (NOT the CLI test).

**NOT in scope**: the `--no-reconcile` CLI flag and `test_cli_export_no_reconcile_flag`
(TASK-4296); any docs (TASK-4297); changes to compaction, claim/close, the snapshot schema, or
`_write_snapshot_if_changed`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | add `_read_snapshot_rows`; reconcile in `export_snapshot` |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_export_snapshot.py` | CREATE | seven service-level reconciliation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.index import LedgerIndex, _decode_issue_body  # verified: ledger/service.py:28
from parrot.knowledge.wiki.ledger.log import LedgerLog                  # verified: ledger/service.py:29
from parrot.knowledge.wiki.ledger.service import LedgerService          # verified: tests/knowledge/wiki/test_ledger_from_dir.py:3
from parrot.knowledge.wiki.ledger.store import LedgerStore              # verified: ledger/service.py:30
from parrot.knowledge.wiki.store import SQLitePragmaPolicy              # verified: ledger/service.py:36
```
`service.py` already imports `asyncio`, `json`, `logging`, `Path`, `Any` (lines 14-19) and defines
`logger = logging.getLogger(__name__)` (line 38) — add no new imports there.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
def _write_snapshot_if_changed(dest: Path, new_content: str) -> bool:            # line 41-48 (ends `    return True`)
def _issue_dict(issue_id: str, state: dict[str, Any]) -> dict[str, Any]:         # line 80 — 12 keys
class LedgerService:
    def __init__(self, index: LedgerIndex, store: LedgerStore, log: LedgerLog, shared_root: Path) -> None  # line 101
    async def _sync_best_effort(self) -> None                                      # line 169
    async def _all_issues(self) -> list[tuple[str, dict[str, Any]]]                # line 176 — EVERY issue page, incl. closed + compacted
    async def open_issue(self, title, body, kind="bug", severity="minor", discovered_from="", about=None, actor="agent:sdd") -> str  # line 192
    async def claim(self, issue_id: str, actor: str) -> bool                       # line 281
    async def close_issue(self, issue_id: str, reason: str, actor: str, resolved_by: str | None = None) -> bool  # line 314
    async def export_snapshot(self, dest: Path) -> bool                            # line 424-450; status filter line 445
    async def compact(self, older_than_days: int = 30) -> int                      # line 452

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py
class LedgerIndex:
    async def compact(self, older_than_days: int = 30) -> int                      # line 532 — sets "compacted": True (574); never deletes a page
```
Test fixture pattern: `tests/knowledge/wiki/test_ledger_list_issues.py:16-24`. pytest runs
`asyncio_mode = auto` (`packages/ai-parrot/pyproject.toml:1043`): bare `async def` tests.

### Does NOT Exist
- ~~`LedgerService.reconcile()`~~ / ~~`merge_snapshot()`~~ — the pre-pass lives inside `export_snapshot`.
- ~~`export_snapshot(dest, merge=True)`~~ — the keyword is `reconcile`, keyword-only.
- ~~`wikitoolkit ledger delete`~~ / ~~`issue.deleted` event~~ — issues cannot be deleted.
- ~~`LedgerService.from_root` in tests~~ — tests build the service directly (fixture below).
- ~~`snapshot row key "compacted"`~~ — `_issue_dict` never emits it; carried rows never carry it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_ledger_export_snapshot.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#_write_snapshot_if_changed",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#_issue_dict",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService._all_issues",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.export_snapshot",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex.compact"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `known` MUST be built from the full `issues` list (closed and compacted included), **not** from
  the status-filtered `rows` — otherwise a locally compacted issue would look "unknown" and be
  resurrected from `dest`.
- Read `dest` **before** `_write_snapshot_if_changed` runs (it is the writer).
- Keep `rows.sort(key=lambda row: row["issue_id"])` and `json.dumps(row, sort_keys=True)` —
  FEAT-566 determinism contract. Carried rows go through the same serialisation.
- Blocking I/O via `asyncio.to_thread`, same as the existing write. `logger`, never `print`.
- 120 columns, Google docstrings, `ruff check` clean.

### References in Codebase
- `ledger/service.py:41-48` — `_write_snapshot_if_changed`, the pattern for the blocking helper.
- `ledger/service.py:424-450` — current `export_snapshot` (the method being replaced).
- `tests/knowledge/wiki/test_ledger_list_issues.py` — fixture + `_seed` style.

---

## Implementation Blueprint

### Steps (in order)
1. Insert `_read_snapshot_rows` right after `_write_snapshot_if_changed` — *why*: keeps the two
   blocking halves of the export together and ahead of `LedgerService`.
2. Replace `export_snapshot` (lines 424-450) with the block below — *why*: the signature is fixed
   by spec §2 "New Public Interfaces"; the reconciliation branch sits between the local row build
   and the sort so carried rows share the deterministic ordering.
3. Create the test module from the CREATE block, then complete every `FILL IN` body — *why*:
   the seven tests are the acceptance contract of spec §4; names are not renegotiable.
4. Run `ruff check --fix` on both files, then the Validation Commands.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` (MODIFY — helper)
```python
# occurrences: 1 (verified: grep -c 'def _write_snapshot_if_changed(dest: Path, new_content: str) -> bool:' packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py)
# AFTER — insert below the END of `_write_snapshot_if_changed` (its last line is `    return True`,
# service.py:48; keep two blank lines before and after the new function)
def _read_snapshot_rows(dest: Path) -> list[dict[str, Any]]:
    """Blocking half of the reconciliation pre-pass — run via ``asyncio.to_thread``.

    Returns the JSON rows already in ``dest`` (``[]`` when the file is missing). A line that
    is not a JSON object carrying a string ``issue_id`` is logged at WARNING with its 1-based
    line number and skipped — it is not a valid issue row and cannot be reconciled.
    """
    if not dest.exists():
        return []
    rows: list[dict[str, Any]] = []
    skipped: list[int] = []
    with dest.open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                skipped.append(lineno)
                continue
            if not isinstance(row, dict) or not isinstance(row.get("issue_id"), str):
                skipped.append(lineno)
                continue
            rows.append(row)
    if skipped:
        logger.warning("Ledger snapshot %s: skipped %d malformed line(s) at %s", dest, len(skipped), skipped)
    return rows
```
**Why**: a corrupt line is neither a local issue nor a carry-forward candidate; skipping it with
a WARNING that names the line is the only honest option (spec §3 M1, test
`test_export_skips_malformed_snapshot_lines`). Blank lines are tolerated silently because the
file's own format ends with `\n`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` (MODIFY — method)
```python
# occurrences: 1 (verified: grep -c '    async def export_snapshot(self, dest: Path) -> bool:' packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py)
# REPLACE — from the anchor `    async def export_snapshot(self, dest: Path) -> bool:` (service.py:424)
# through `        return await asyncio.to_thread(_write_snapshot_if_changed, dest, new_content)` (service.py:450)
    async def export_snapshot(self, dest: Path, *, reconcile: bool = True) -> bool:
        """Write ``sdd/ledger/issues.jsonl`` deterministically, reconciling against ``dest``.

        One JSON object per issue with status ``open``, ``claimed``, or closed/superseded but
        not yet compacted — keys sorted, rows sorted by ``issue_id``, no volatile fields, so
        regenerating from the same ledger state and the same ``dest`` is byte-identical.
        Insights are excluded.

        Local state is authoritative for every issue this ledger has recorded. With
        ``reconcile=True`` (default) every row already in ``dest`` whose ``issue_id`` is
        unknown to this ledger is carried forward unchanged, so an export from a machine whose
        event log is behind never drops another machine's issues (FEAT-671).
        ``reconcile=False`` rebuilds the snapshot from the local view only — destructive,
        explicit opt-in.

        Args:
            dest: Destination path (created, with parents, if missing).
            reconcile: Carry forward rows for issues unknown to this ledger.

        Returns:
            ``True`` if the written content differs from what was already on disk (or the
            file did not exist yet).
        """
        await self._sync_best_effort()
        issues = await self._all_issues()

        rows = [
            _issue_dict(issue_id, state)
            for issue_id, state in issues
            if state.get("status") in ("open", "claimed") or not state.get("compacted", False)
        ]
        if reconcile:
            known = {issue_id for issue_id, _ in issues}
            existing = await asyncio.to_thread(_read_snapshot_rows, dest)
            carried = [row for row in existing if row["issue_id"] not in known]
            if carried:
                logger.info(
                    "Ledger snapshot %s: carried forward %d issue(s) unknown to this ledger", dest, len(carried)
                )
            rows.extend(carried)
        rows.sort(key=lambda row: row["issue_id"])
        new_content = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)

        return await asyncio.to_thread(_write_snapshot_if_changed, dest, new_content)
```
**Why this shape**: `known` comes from the unfiltered `issues` so a locally compacted issue stays
*known* and is therefore neither exported nor carried forward — it disappears exactly when its
owning machine exports (spec §2 Overview). The local status filter, sort and `sort_keys=True`
are untouched: they are FEAT-566's determinism contract. Nothing here must change signatures.

### `packages/ai-parrot/tests/knowledge/wiki/test_ledger_export_snapshot.py` (CREATE)
```python
"""FEAT-671: ``LedgerService.export_snapshot`` reconciles against the committed snapshot."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.store import SQLitePragmaPolicy

ROW_KEYS = (
    "about", "acknowledged", "claimed_by", "closed_by", "closed_reason", "discovered_from",
    "issue_id", "kind", "resolved_by", "severity", "status", "title",
)


@pytest.fixture
def service(tmp_path: Path) -> LedgerService:
    """A LedgerService over an isolated temporary ledger root."""
    ledger_dir = tmp_path / ".parrot" / "ledger"
    ledger_dir.mkdir(parents=True)
    store = LedgerStore(
        ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0)
    )
    log = LedgerLog(str(ledger_dir / "events.jsonl"))
    return LedgerService(LedgerIndex(store, log), store, log, tmp_path)


def _foreign_row(issue_id: str, status: str = "open") -> dict[str, Any]:
    """A canonical 12-key snapshot row for an issue this ledger never recorded."""
    row: dict[str, Any] = dict.fromkeys(ROW_KEYS)
    row.update(about=[], acknowledged=False, discovered_from="spec:FEAT-000", issue_id=issue_id)
    row.update(kind="bug", severity="minor", status=status, title=f"foreign {issue_id}")
    return row


def _write_rows(dest: Path, rows: list[dict[str, Any]]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _read_rows(dest: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in dest.read_text(encoding="utf-8").splitlines() if line]


async def test_export_carries_forward_rows_unknown_to_local_ledger(service: LedgerService, tmp_path: Path) -> None:
    # FILL IN: seed dest with _foreign_row("issue:aaa") + _foreign_row("issue:zzz", "closed"); open one
    # local issue; assert export returns True, 3 rows sorted by issue_id, foreign rows == seed — bounded by AC-1
    raise NotImplementedError


async def test_export_local_state_wins_for_known_issue(service: LedgerService, tmp_path: Path) -> None:
    # FILL IN: open + close a local issue; seed dest with that issue_id as status "open"; assert the single
    # exported row for it is "closed" with closed_reason, no duplicate issue_id — bounded by AC-2
    raise NotImplementedError


async def test_export_drops_locally_compacted_issue(service: LedgerService, tmp_path: Path) -> None:
    # FILL IN: open + close a local issue, `await service.compact(older_than_days=0)`; seed dest with it as
    # "closed"; assert it is absent from the export — bounded by AC-3
    raise NotImplementedError


async def test_export_no_reconcile_rebuilds_from_local_only(service: LedgerService, tmp_path: Path) -> None:
    # FILL IN: same seed as the first test, `reconcile=False`; assert only the local row remains — bounded by AC-4
    raise NotImplementedError


async def test_export_deterministic_and_idempotent(service: LedgerService, tmp_path: Path) -> None:
    # FILL IN: seed + export; second export returns False and bytes are unchanged — bounded by AC-5
    raise NotImplementedError


async def test_export_missing_dest_creates_file(service: LedgerService, tmp_path: Path) -> None:
    # FILL IN: dest under a missing parent dir; assert True, file exists, local rows only — bounded by AC-6
    raise NotImplementedError


async def test_export_skips_malformed_snapshot_lines(
    service: LedgerService, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # FILL IN: dest = valid foreign row, "not json\n", '{"title": "no id"}\n', valid foreign row; with
    # caplog.at_level(logging.WARNING): export; assert both valid rows carried, warning names lines 2 and 3 — AC-7
    raise NotImplementedError
```
**Why this shape**: `_foreign_row` produces exactly the 12 keys `_issue_dict` emits so byte-equality
of carried rows is meaningful (AC-1). Tests are bare `async def` because the suite runs in
`asyncio_mode = auto`. `compact(older_than_days=0)` folds the closed page deterministically
because `updated_at` is an isoformat with microseconds set at close time (spec §7).

### FILL IN checklist
- [ ] `test_ledger_export_snapshot.py::test_export_carries_forward_rows_unknown_to_local_ledger` — bounded by AC-1
- [ ] `::test_export_local_state_wins_for_known_issue` — bounded by AC-2
- [ ] `::test_export_drops_locally_compacted_issue` — bounded by AC-3
- [ ] `::test_export_no_reconcile_rebuilds_from_local_only` — bounded by AC-4
- [ ] `::test_export_deterministic_and_idempotent` — bounded by AC-5
- [ ] `::test_export_missing_dest_creates_file` — bounded by AC-6
- [ ] `::test_export_skips_malformed_snapshot_lines` — bounded by AC-7

---

## Acceptance Criteria

- [ ] AC-1 Rows in `dest` for issues unknown to the local ledger are carried forward byte-identical (after canonical re-serialisation) and sorted with the local rows.
- [ ] AC-2 For an `issue_id` known locally, the exported row reflects local state (a local close beats a stale `open` in `dest`); no duplicate `issue_id` in the output.
- [ ] AC-3 A locally closed-and-compacted issue is absent from the export even if `dest` still lists it.
- [ ] AC-4 `reconcile=False` reproduces today's behaviour (local view only).
- [ ] AC-5 Two consecutive exports with no state change: second returns `False`, bytes identical.
- [ ] AC-6 Missing `dest` (and parents) is created; returns `True`.
- [ ] AC-7 Malformed lines in `dest` are skipped with one WARNING naming their line numbers; valid rows around them are still carried.
- [ ] `export_snapshot(dest)` positional callers are unaffected (keyword-only `reconcile`, default `True`).
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py packages/ai-parrot/tests/knowledge/wiki/test_ledger_export_snapshot.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_export_snapshot.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_from_dir.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_list_issues.py -q`

---

## Test Specification

See the CREATE block above — the seven test functions and their `FILL IN` bodies are the scaffold.
Each test seeds `dest` with `_write_rows`, drives the service through `open_issue` / `close_issue` /
`compact`, calls `await service.export_snapshot(dest)` (or `reconcile=False`) and inspects
`_read_rows(dest)` plus the returned `bool`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug commands-sdd-done-fixes --feature-id FEAT-671`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/commands-sdd-done-fixes.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src` (the shared `.venv` points at the main checkout)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4295 commands-sdd-done-fixes verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Opus 5.5 (`/sdd-fix issue:62038221413a`, FEAT-671 worktree)
**Date**: 2026-10-14
**Notes**: Added module-level `_read_snapshot_rows()` and the keyword-only `reconcile: bool = True`
parameter on `LedgerService.export_snapshot()`. Rows already in `dest` whose `issue_id` is absent
from `_all_issues()` are carried forward unchanged; local state wins for known ids; a locally
closed-and-compacted issue still disappears. Carried count logged at INFO, malformed snapshot lines
skipped with one WARNING naming their line numbers. Seven tests in
`tests/knowledge/wiki/test_ledger_export_snapshot.py`; 12/12 green together with
`test_ledger_from_dir.py` + `test_ledger_list_issues.py` (`PYTHONPATH=packages/ai-parrot/src`).
Environment note: the worktree needed the main checkout's git-ignored compiled Cython `.so`
files copied in before `parrot.utils.types` could import.

**Deviations from spec**: none
