# TASK-4406: Service + CLI — `export_shared_log` / `import_shared_log`, `ledger export-log|import-log`, audit block

**Feature**: FEAT-694 — Shared Ledger Event Log (cross-machine sync via git hooks)
**Spec**: `sdd/specs/ledger-shared-event-log.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4405
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. Async facade over TASK-4405's core: import appends then runs the
**incremental** `LedgerIndex.sync()` (never a rebuild — G3), detects claim conflicts (G6), and
`audit()` gains a `shared_log` block. Two click commands are what the git hooks (TASK-4407) call.

---

## Scope

- `LedgerService.export_shared_log`, `LedgerService.import_shared_log` (before `compact`).
- `audit()` adds the `"shared_log"` key (existing keys unchanged).
- `cli.py`: `_git_toplevel(cwd)` helper, `ledger export-log`, `ledger import-log` (before
  `@ledger.command("sync")`), and one extra `ledger audit` output line.
- Tests: `tests/knowledge/wiki/test_ledger_shared_log_service.py`,
  `tests/knowledge/wiki/test_cli_ledger_shared_log.py`.

**NOT in scope**: `rotate_shared_log`, `claim()` pre-import, `rotate-log` command (TASK-4408 —
same files, runs after this one); hooks (TASK-4407); MCP / `TOOL_REGISTRY` (spec non-goal).
`ledger_claim` in `cli.py` is NOT edited.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | export/import methods + audit block |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `export-log`, `import-log`, `_git_toplevel`, audit line |
| `tests/knowledge/wiki/test_ledger_shared_log_service.py` | CREATE | service tests |
| `tests/knowledge/wiki/test_cli_ledger_shared_log.py` | CREATE | CLI tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.shared_log import (            # created by TASK-4405
    MARKER_FILENAME, SHARED_LOG_REL_PATH, ClaimConflict, SharedLogExportReport, SharedLogImportReport,
    export_events, import_events, read_raw_events, read_shared_event_ids, shared_log_files, digest_files, is_shareable,
)
from parrot.knowledge.wiki.ledger.service import LedgerService, normalize_issue_id   # verified: cli.py:127
from parrot.knowledge.wiki.store import SQLitePragmaPolicy, WikiStoreBusy            # verified: service.py:37
from parrot.knowledge.wiki.project import find_shared_root                          # verified: project.py:1519
from parrot.knowledge.wiki import remote_cli                                        # verified: cli.py:104
from parrot.knowledge.wiki.cli import ledger, wiki                                  # verified: tests/knowledge/wiki/test_cli_ledger.py:18
```

### Existing Signatures to Use
```python
# ledger/service.py
class LedgerService:
    def __init__(self, index, store, log, shared_root: Path)                        # line 144
    @classmethod from_root(cls, root=None)                                          # line 159
    @classmethod from_dir(cls, ledger_dir: Path, *, sqlite_policy=None)             # line 189 — shared_root = ledger_dir.parent.parent (210)
    async def _sync_best_effort(self) -> None                                       # line 212 — swallows WikiStoreBusy with WARNING
    async def _all_issues(self) -> list[tuple[str, dict[str, Any]]]                 # line 219
    async def export_snapshot(self, dest: Path, *, reconcile=True) -> bool          # line 515 — asyncio.to_thread pattern (558)
    async def compact(self, older_than_days: int = 30) -> int                       # line 560
    async def audit(self) -> dict[str, Any]                                         # line 564 — return dict 583-591
# ledger/index.py
async def LedgerIndex.sync(self, conn=None) -> int                                  # line 263
# ledger/store.py
async def LedgerStore.read_cursor(self) -> tuple[int, str | None]                   # line 75
# cli.py
def _run(coro) -> Any                                                               # line 579
@ledger.command("export") … ledger_export                                           # line 3593-3610 (decorator order pattern)
@ledger.command("sync") … ledger_sync                                               # line 3613-3626 (exit 2 on WikiStoreBusy)
click.echo(f"Total events: {audit['total_events']}")                                # line 3704 (inside ledger audit)
```

### Does NOT Exist
- ~~`wikitoolkit ledger import`~~ / ~~`ledger pull`~~ / ~~`ledger push`~~ — no such commands.
- ~~`LedgerService.import_snapshot()`~~ — not created by this feature either.
- ~~MCP tools `ledger_import` / `ledger_export`~~ — none; do not touch `TOOL_REGISTRY`.
- ~~`LedgerIndex` reducers for `insight.*`/`task.*`/`spec.*`~~ — `apply_event` ignores them (index.py:122-124).
- ~~`LedgerIndex.rebuild()` after import~~ — forbidden (wipes `spec:`/`task:` pages, G3).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_ledger_shared_log_service.py", "action": "CREATE"},
    {"path": "tests/knowledge/wiki/test_cli_ledger_shared_log.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex.sync",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py#LedgerStore.read_cursor",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#ledger"
  ]
}
```

---

## Implementation Notes

- Soft index failure: `WikiStoreBusy` on `sync()` → `index_busy=True, synced_events=0`; the
  log is already durable. CLI `import-log` exits 2 in that case (same contract as `ledger sync`).
- Claim conflict (issue:fe3480881432 — spurious-conflict fix): after sync, filter the
  `claimed` list (returned by `import_events`) to only the **last** `issue.claimed` event
  per subject in the imported batch — discard earlier claims that were superseded by a later
  `issue.unclaimed` or `issue.closed` for the same subject within the batch. Then for each
  surviving claim, look up the issue state (via `_all_issues()` or a single page read); if
  `status == "claimed"` and `claimed_by != event.payload.get("claimed_by")` →
  `ClaimConflict`. Skip the check when `index_busy`.
  Verify the payload key name against `index.py:191-200` (`_apply_issue_claimed`) before use.
- `--stage` runs `subprocess.run(["git", "-C", str(root), "add", "--", str(SHARED_LOG_REL_PATH)], check=True)`
  only when `added > 0 or created`.
- `_git_toplevel(cwd)`: `git rev-parse --show-toplevel` (subprocess, `capture_output=True`,
  `text=True`); on failure fall back to `find_shared_root(cwd)`, then `cwd`.
- Tests mirror `test_ledger_export_snapshot.py` (`LedgerService.from_dir` fixture with
  `SQLitePragmaPolicy(busy_timeout_ms=200)`) and `test_cli_ledger.py` (`CliRunner`,
  `patch("parrot.knowledge.wiki.cli.LedgerService.from_root")`).

---

## Implementation Blueprint

### Steps (in order)
1. Add imports + the two service methods before `compact` — *why*: TASK-4407's hooks and TASK-4408 call them.
2. Add the `shared_log` audit block — *why*: G6/AC10 counting.
3. Add `_git_toplevel` + the two click commands before `@ledger.command("sync")`, then the audit line.
4. Write both test files; run the Validation Commands.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    async def compact(self, older_than_days: int = 30) -> int:' service.py)
# BEFORE — insert above `    async def compact(self, older_than_days: int = 30) -> int:` (verified: ledger/service.py:560)
    async def export_shared_log(self, repo_root: Path | None = None) -> SharedLogExportReport:
        """Append this machine's shareable events to ``<repo_root>/sdd/ledger/events.jsonl``. Never touches the index."""
        return await asyncio.to_thread(export_events, self.log, repo_root or self.shared_root)

    async def import_shared_log(self, repo_root: Path | None = None, *, force: bool = False) -> SharedLogImportReport:
        """Append committed events unknown locally, sync incrementally, and report claim conflicts."""
        marker = Path(self.log.path).parent / MARKER_FILENAME
        report, claimed = await asyncio.to_thread(
            import_events, self.log, repo_root or self.shared_root, marker, force=force
        )
        if report.fast_path or report.added == 0:
            return report
        # FILL IN: try `report.synced_events = await self.index.sync()` except WikiStoreBusy →
        # logger.warning + index_busy=True, synced_events=0 (pattern service.py:212-217);
        # then, unless index_busy, build ClaimConflict list from `claimed` — bounded by G3, AC10
        return report

# occurrences: 1 (verified: grep -cF '            "broken_edges": broken_edges,' service.py)
# AFTER — insert below `            "broken_edges": broken_edges,` (verified: ledger/service.py:589)
            "shared_log": await asyncio.to_thread(self._shared_log_audit, offset),
```
Add the import block next to `service.py:29-31` and a private sync helper method
`_shared_log_audit(self, cursor_offset: int) -> dict[str, Any]` (placed after `audit`):
```python
    def _shared_log_audit(self, cursor_offset: int) -> dict[str, Any]:
        """Blocking: compare the local log with the committed logical shared log (FEAT-694)."""
        # FILL IN: files = shared_log_files(self.shared_root); committed = read_shared_event_ids(files);
        # local = shareable local ids; return {"path": str(self.shared_root / SHARED_LOG_REL_PATH),
        # "exists": bool, "local_only_events": len(local - committed),
        # "committed_unknown_events": len(committed - all_local_ids),
        # "marker": "missing" | "ok" (marker text == digest_files(files)) | "stale",
        # "claim_conflicts": <int>} — bounded by spec §3 M2 audit, AC10
        #
        # Claim conflicts (issue:fe3480881432): recompute statelessly instead of relying on
        # the transient SharedLogImportReport (which is lost when hooks redirect to /dev/null).
        # Read committed issue.claimed events from `files`, filter to only the last claim per
        # subject (discard superseded — same logic as import_shared_log), then compare each
        # surviving claim's claimed_by against `_all_issues()`. Count mismatches. This is the
        # only AC10-compliant audit path — the import report is ephemeral.
```
**Why**: `cursor_offset` is unused by the helper today; drop the parameter if ruff flags it —
the key set is what is fixed.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '@ledger.command("sync")' cli.py)
# BEFORE — insert above `@ledger.command("sync")` (verified: cli.py:3613)
def _git_toplevel(cwd: Path) -> Path:
    """Return ``git rev-parse --show-toplevel`` of ``cwd``; fall back to the shared root, then ``cwd``."""
    # FILL IN: subprocess.run([...], capture_output=True, text=True, check=False)


@ledger.command("export-log")
@click.option("--repo-root", default=None, help="Checkout whose sdd/ledger/ is written; default: git toplevel of cwd")
@click.option("--stage", is_flag=True, default=False, help="git add the file when it changed")
@click.option("--quiet", is_flag=True, default=False)
@remote_cli.remote_aware(proxied=False)
def ledger_export_log(repo_root: str | None, stage: bool, quiet: bool) -> None:
    """Append this machine's shareable ledger events to the committed sdd/ledger/events.jsonl."""
    # FILL IN: root = Path(repo_root) if repo_root else _git_toplevel(Path.cwd());
    # report = _run(LedgerService.from_root().export_shared_log(root)); OSError → click.ClickException;
    # echo "Exported <dest> (+N events)" or "Exported <dest> (unchanged)" unless quiet; --stage per Notes


@ledger.command("import-log")
@click.option("--repo-root", default=None)
@click.option("--force", is_flag=True, default=False, help="Ignore the marker fast path")
@click.option("--quiet", is_flag=True, default=False)
@remote_cli.remote_aware(proxied=False)
def ledger_import_log(repo_root: str | None, force: bool, quiet: bool) -> None:
    """Append committed ledger events unknown to this machine and sync the index."""
    # FILL IN: "(up to date)" on fast path / added==0, else "Imported +N events (M known)";
    # one "⚠️ claim conflict on <issue>: local <a> vs committed <b> (<event_id>)" line per conflict
    # (always printed, even with --quiet); SystemExit(2) when index_busy — bounded by spec §3 M2

# occurrences: 1 (verified: grep -cF "    click.echo(f\"Total events: {audit['total_events']}\")" cli.py)
# AFTER — insert below `    click.echo(f"Total events: {audit['total_events']}")` (verified: cli.py:3704)
    shared = audit.get("shared_log")
    if shared:
        # FILL IN: "Shared log: <path> (+K archives) · local-only events: N · committed-unknown events: M · marker: <state>"
        # Also (issue:fe3480881432): "  claim conflicts: N" when claim_conflicts > 0 (AC10)
        pass
```

### Test files (CREATE)
```python
# tests/knowledge/wiki/test_ledger_shared_log_service.py
"""FEAT-694 M2 — LedgerService shared-log import/export."""
# FILL IN: fixture `two_ledgers` per spec §4; tests test_import_keeps_cursor_valid (spy
# `LedgerIndex._rebuild_locked_with_cursor` never called), test_import_detects_claim_conflict,
# test_import_index_busy_is_soft (patch index.sync to raise WikiStoreBusy), test_audit_reports_shared_log_block

# tests/knowledge/wiki/test_cli_ledger_shared_log.py
"""FEAT-694 M2 — `wikitoolkit ledger export-log|import-log`."""
# FILL IN: test_cli_export_log_stage_runs_git_add (real `git init` in tmp_path; `--repo-root`),
# test_cli_import_log_outputs_and_exit_codes (patched from_root; "(up to date)", "Imported +", conflict line, exit 2)
```

### FILL IN checklist
- [ ] `import_shared_log` sync + conflicts; G3/AC3/AC10
- [ ] `_shared_log_audit` keys exactly per spec
- [ ] `_git_toplevel`, `export-log`, `import-log`, audit line
- [ ] six test functions listed above

---

## Acceptance Criteria

- [ ] AC1/AC2 via CLI; AC3 (no rebuild, cursor valid); AC10 (conflict surfaced, local winner kept).
- [ ] `import-log` exits 2 on busy index, 0 otherwise.
- [ ] Existing `test_cli_ledger.py` and `test_ledger_service.py` still pass.
- [ ] `ruff check` clean on touched files.

## Validation Commands

- `pytest tests/knowledge/wiki/test_ledger_shared_log_service.py -q`
- `pytest tests/knowledge/wiki/test_cli_ledger_shared_log.py -q`
- `pytest tests/knowledge/wiki/test_cli_ledger.py -q`
- `pytest tests/knowledge/wiki/test_ledger_service.py -q`

---

## Test Specification

Spec §4 rows tagged M2.

---

## Agent Instructions

Standard SDD flow (`sdd/templates/task.md` § Agent Instructions); feature worktree
`feat-FEAT-694-ledger-shared-event-log`; `PYTHONPATH=packages/ai-parrot/src`; close with
`scripts/sdd/close_task.sh TASK-4406 ledger-shared-event-log verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
