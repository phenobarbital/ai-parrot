# TASK-4296: `wikitoolkit ledger export --no-reconcile` flag + CLI test

**Feature**: FEAT-671 — Reconciling Ledger Snapshot Export
**Spec**: `sdd/specs/commands-sdd-done-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4295
**Assigned-to**: unassigned
**Discovered-from**: `issue:62038221413a`

---

## Context

TASK-4295 makes `LedgerService.export_snapshot` reconcile by default and adds the keyword-only
`reconcile: bool = True`. Spec §3 Module 2 exposes the destructive opt-out on the CLI as
`--no-reconcile`, keeping the `Exported <dest> (changed|unchanged)` output that `/sdd-done`
step 9.1 greps. This task adds the flag and the eighth test of spec §4
(`test_cli_export_no_reconcile_flag`) to the module TASK-4295 creates.

---

## Scope

- Add the `--no-reconcile` click flag to `ledger_export` in `cli.py` and pass
  `reconcile=not no_reconcile` to `export_snapshot`.
- Append `test_cli_export_no_reconcile_flag` (sync test driving `CliRunner`) to
  `packages/ai-parrot/tests/knowledge/wiki/test_ledger_export_snapshot.py`.

**NOT in scope**: any change to `export_snapshot` itself (TASK-4295); docs (TASK-4297);
any other `ledger` subcommand; the `/sdd-done` script.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `--no-reconcile` option on `ledger export` |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_export_snapshot.py` | MODIFY | add imports + `test_cli_export_no_reconcile_flag` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from click.testing import CliRunner                       # verified: tests/knowledge/wiki/test_cli.py:18
from parrot.knowledge.wiki.cli import wiki                # verified: tests/knowledge/wiki/test_cli.py:56 (runner.invoke(wiki, [...]))
from parrot.knowledge.wiki.ledger.service import LedgerService  # verified: tests/knowledge/wiki/test_ledger_from_dir.py:3
```
`cli.py` already imports `click`, `Path`, `LedgerService`, `remote_cli` and defines `_run` — no new
imports there.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:3420-3431
@ledger.command("export")
@click.option("--dest", default="sdd/ledger/issues.jsonl", help="Export destination.")
@remote_cli.remote_aware(proxied=False)
def ledger_export(dest: str) -> None:
    """Export the ledger snapshot."""
    service = LedgerService.from_root()
    dest_path = Path(dest)
    changed = _run(service.export_snapshot(dest_path))
    # echoes f"Exported {dest_path} (changed)" | f"Exported {dest_path} (unchanged)"

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py (after TASK-4295)
async def export_snapshot(self, dest: Path, *, reconcile: bool = True) -> bool

# packages/ai-parrot/src/parrot/knowledge/wiki/remote_cli.py:97-124
def remote_aware(*, proxied: bool, tool: str | None = None)
#   wrapper does: _root, _effective, remote = remote_or_none(kwargs.get("path_")); remote is None → runs func
```
`parrot.knowledge.wiki.remote_cli.remote_or_none` is resolved as a module global of `remote_cli`
at call time, so `monkeypatch.setattr("parrot.knowledge.wiki.remote_cli.remote_or_none", ...)`
disables remote mode for the test.

### Does NOT Exist
- ~~`wikitoolkit ledger export --reconcile/--no-reconcile` pair~~ — only the `--no-reconcile` flag (default behaviour is reconcile).
- ~~`--force` on `ledger export`~~ — not a thing.
- ~~`ledger_export(dest, reconcile)`~~ — the click parameter is `no_reconcile: bool`.
- ~~an `async def` CLI test~~ — `CliRunner.invoke` runs `_run(...)` which owns its own event loop; the test MUST be a plain `def`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_ledger_export_snapshot.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#ledger_export",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.export_snapshot",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/remote_cli.py#remote_aware"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Output strings `Exported {dest_path} (changed)` / `(unchanged)` are a contract — `/sdd-done`
  §9.1 does `[[ "$EXPORT_OUTPUT" != *"(changed)"* ]]`. Do not add prefixes to those lines.
- The flag is `is_flag=True, default=False`; the help text must say it is destructive.
- The CLI test is synchronous (`def`, not `async def`).

### References in Codebase
- `tests/knowledge/wiki/test_cli_remote.py:53-62` — `CliRunner().invoke(wiki, ["ledger", ...])` pattern.
- `cli.py:3420-3431` — the command being extended.

---

## Implementation Blueprint

### Steps (in order)
1. Replace the `ledger_export` command with the block below — *why*: the option must sit between
   `--dest` and `remote_aware` so click passes `no_reconcile` as a keyword the wrapper forwards.
2. Add the two imports to the test module after the `SQLitePragmaPolicy` import — *why*: the
   Verified Imports list is the only source of symbols the test may use.
3. Append the CLI test after the last test in the module and complete its `FILL IN` — *why*:
   it proves both the default (reconcile) and the opt-out through the real click surface.
4. `ruff check --fix` both files; run the Validation Commands.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def ledger_export(dest: str) -> None:' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py)
# REPLACE — from `@ledger.command("export")` (cli.py:3420) through
# `        click.echo(f"Exported {dest_path} (unchanged)")` (cli.py:3431)
@ledger.command("export")
@click.option("--dest", default="sdd/ledger/issues.jsonl", help="Export destination.")
@click.option(
    "--no-reconcile",
    is_flag=True,
    default=False,
    help="Rebuild from this machine's ledger only; drops issues it has never seen (destructive).",
)
@remote_cli.remote_aware(proxied=False)
def ledger_export(dest: str, no_reconcile: bool) -> None:
    """Export the ledger snapshot."""
    service = LedgerService.from_root()
    dest_path = Path(dest)
    changed = _run(service.export_snapshot(dest_path, reconcile=not no_reconcile))
    if changed:
        click.echo(f"Exported {dest_path} (changed)")
    else:
        click.echo(f"Exported {dest_path} (unchanged)")
```
**Why**: spec §3 M2 fixes the flag name and the unchanged echo contract; `reconcile=not no_reconcile`
keeps the service default (`True`) when the flag is absent.

### `packages/ai-parrot/tests/knowledge/wiki/test_ledger_export_snapshot.py` (MODIFY — imports)
```python
# occurrences: 1 (verified at TASK-4295 blueprint; re-run: grep -c 'from parrot.knowledge.wiki.store import SQLitePragmaPolicy' packages/ai-parrot/tests/knowledge/wiki/test_ledger_export_snapshot.py)
# AFTER — insert below `from parrot.knowledge.wiki.store import SQLitePragmaPolicy`
from click.testing import CliRunner  # noqa: E402 — keep ruff happy if it wants the import grouped; else move it above
from parrot.knowledge.wiki.cli import wiki
```
**Why**: `ruff` may ask to move `CliRunner` into the third-party group above `parrot.*`; do so if
it does — the symbol set, not the order, is fixed.

### `packages/ai-parrot/tests/knowledge/wiki/test_ledger_export_snapshot.py` (MODIFY — test)
```python
# occurrences: 1 (verified at TASK-4295 blueprint; re-run: grep -c 'async def test_export_skips_malformed_snapshot_lines' packages/ai-parrot/tests/knowledge/wiki/test_ledger_export_snapshot.py)
# AFTER — append at END OF FILE (below the body of `test_export_skips_malformed_snapshot_lines`)
def test_cli_export_no_reconcile_flag(
    service: LedgerService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ledger export` keeps unknown rows by default and drops them with --no-reconcile."""
    monkeypatch.setattr("parrot.knowledge.wiki.remote_cli.remote_or_none", lambda path_=None: (None, None, None))
    monkeypatch.setattr(LedgerService, "from_root", classmethod(lambda cls, root=None: service))
    dest = tmp_path / "snap" / "issues.jsonl"
    _write_rows(dest, [_foreign_row("issue:aaa")])
    runner = CliRunner()
    # FILL IN: result = runner.invoke(wiki, ["ledger", "export", "--dest", str(dest)]); assert exit_code 0,
    # "(changed)" in result.output, "issue:aaa" still in _read_rows(dest); then invoke again with
    # "--no-reconcile" and assert "issue:aaa" is gone and "(changed)" in result.output — bounded by AC-1/AC-2
    raise NotImplementedError
```
**Why**: patching `from_root` routes the real click command at the isolated fixture ledger; patching
`remote_or_none` keeps `remote_aware` on the local path regardless of the developer's config. The
test is sync because `_run` drives its own event loop.

### FILL IN checklist
- [ ] `test_ledger_export_snapshot.py::test_cli_export_no_reconcile_flag` — two invocations, default keeps / flag drops; bounded by AC-1, AC-2

---

## Acceptance Criteria

- [ ] AC-1 `wikitoolkit ledger export --dest <p>` (no flag) carries forward the foreign row and prints `Exported <p> (changed)` on first run.
- [ ] AC-2 `wikitoolkit ledger export --dest <p> --no-reconcile` drops the foreign row and prints `(changed)`.
- [ ] `wikitoolkit ledger export --help` lists `--no-reconcile` with the destructive wording.
- [ ] Output lines keep the literal `Exported <dest> (changed)` / `(unchanged)` format.
- [ ] `ruff check` clean on both files; `test_cli_remote.py` still passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_export_snapshot.py::test_cli_export_no_reconcile_flag -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_export_snapshot.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli_remote.py -q`

---

## Test Specification

See the MODIFY (test) block above. One sync test, two `CliRunner` invocations against the same
`dest`, assertions on `result.exit_code`, `result.output` and `_read_rows(dest)`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug commands-sdd-done-fixes --feature-id FEAT-671`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — `TASK-4295` must be `"done"` in `sdd/tasks/index/commands-sdd-done-fixes.json`
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
   `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4296 commands-sdd-done-fixes verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Opus 5.5 (`/sdd-fix issue:62038221413a`, FEAT-671 worktree)
**Date**: 2026-10-14
**Notes**: Added the `--no-reconcile` flag to `ledger export` (`reconcile=not no_reconcile`), echo
format unchanged. `test_cli_export_no_reconcile_flag` is a sync test patching
`remote_cli.remote_or_none` and `LedgerService.from_root`; 14/14 green with `test_cli_remote.py`.
Manual check on the real ledger (worktree code, `PYTHONPATH=packages/ai-parrot/src`): committed
snapshot 279 rows → reconciling export 286 rows, 0 dropped / 7 added; `--no-reconcile` → 102 rows
(184 dropped), i.e. the old behaviour is now opt-in only.

**Deviations from spec**: the CLI test asserts `(unchanged)` on the first (reconciling) run instead
of the task's AC-1 `(changed)`: with no local issues the carried-forward row reproduces the file
byte-for-byte, which is the stronger guarantee; the `--no-reconcile` run asserts `(changed)` as
specified.
