# TASK-2467: CLI `sync` command group (push/pull, --env, --dry-run, --all)

**Feature**: FEAT-461 — wikitoolkit Environment Support (env-aware config + memory sync)
**Spec**: `sdd/specs/wikitoolkit-env-support.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2463, TASK-2466
**Assigned-to**: unassigned

---

## Context

Spec §2 (New Public Interfaces, CLI block) + §3 Module 5 (CLI half). Exposes
the TASK-2466 engine as `wikitoolkit sync push|pull` with per-category
summaries. Runs after TASK-2463 because both edit `cli.py` (sequential,
per-spec worktree).

---

## Scope

- Add a `sync` click group to `wikitoolkit` (`cli.py`) with two commands:
  - `sync push [--env dev] [--dry-run]`
  - `sync pull [--env dev] [--dry-run] [--all]` (`--all` → `include_own=True`)
- Both resolve the repo via the existing `_resolve_project` pattern and call
  `sync_push` / `sync_pull` (async — wrap with the same `asyncio.run(...)`
  convention other CLI commands use).
- Determine `local_identity` and pass it explicitly: `f"human:{getpass.getuser()}"`
  (document in `--help`; a future flag can override — do NOT add one now).
- Print the per-category summary from `SyncReport`:
  `created / updated / skipped-older / skipped-own` (+ `DRY RUN` marker),
  via `click.echo`.
- Exit non-zero with a clean message on unreachable remote (catch the
  engine's typed error; no traceback spew).
- CLI tests in `tests/knowledge/wiki/test_cli_sync.py` (CliRunner; engine
  mocked/monkeypatched — the engine's own logic is tested in TASK-2466).

**NOT in scope**: engine logic (TASK-2466); status header (TASK-2463);
docs (TASK-2468).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | add `sync` group with `push` / `pull` commands |
| `tests/knowledge/wiki/test_cli_sync.py` | CREATE | CliRunner tests with mocked engine |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import click                    # cli.py is click-based throughout
from parrot.knowledge.wiki.sync import sync_push, sync_pull, SyncReport  # TASK-2466
# _resolve_project helper: cli.py:321 (returns (root, config))
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
def _resolve_project(path: str | None) -> tuple[Path, WikiProjectConfig]  # line 321
# Existing command style: @cli.command()/@group, click.option, click.echo,
# errors via click.ClickException (see _resolve_project body, lines 323-339)
# Async commands wrap coroutines with asyncio.run(...) — grep an existing
# command (e.g. the note command at cli.py:2570) for the exact convention.

# From TASK-2466:
async def sync_push(root, *, target_env="dev", dry_run=False, local_identity=None) -> SyncReport
async def sync_pull(root, *, target_env="dev", include_own=False, dry_run=False, local_identity=None) -> SyncReport
class SyncReport(BaseModel):  # direction, env, created, updated,
                              # skipped_older, skipped_own, dry_run
```

### Does NOT Exist
- ~~`wikitoolkit sync` group~~ — created by THIS task.
- ~~`--identity` / `--author` flag~~ — explicitly deferred; do not add.
- ~~a bidirectional `sync` (no subcommand)~~ — rejected in brainstorm;
  push/pull only.

---

## Implementation Notes

### Key Constraints
- `click.ClickException` for user-facing failures (consistent with
  `_resolve_project`); remote-unreachable message must name host/env.
- Summary format (one line per counter, stable order):
  `pushed: created=N updated=N skipped-older=N` /
  `pulled: created=N updated=N skipped-older=N skipped-own=N`.
- `--dry-run` output identical shape, prefixed `DRY RUN — nothing applied`.

### References in Codebase
- `cli.py:2570` (`note` command) — command + asyncio wrapping convention.
- `tests/knowledge/wiki/test_cli.py` — CliRunner conventions.

---

## Acceptance Criteria

- [ ] `wikitoolkit sync push --dry-run` and `sync pull --all --env dev` parse
  and dispatch with the right kwargs (CliRunner tests, engine mocked).
- [ ] Summary lines render all counters; dry-run marker present.
- [ ] Unreachable remote → exit code ≠ 0, clean message, no traceback.
- [ ] `wikitoolkit sync --help` documents env default (`dev`) and the author
  filter default.
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_cli_sync.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`

---

## Test Specification

```python
# tests/knowledge/wiki/test_cli_sync.py

class TestSyncCli:
    def test_push_dispatches_with_env_and_dry_run(self, monkeypatch): ...
    def test_pull_all_maps_to_include_own(self, monkeypatch): ...
    def test_summary_rendering(self, monkeypatch): ...
    def test_unreachable_remote_clean_exit(self, monkeypatch): ...
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/wikitoolkit-env-support.spec.md` (§2 CLI block, §3 Module 5).
2. **Check dependencies** — TASK-2463 and TASK-2466 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code.
4. **Update status** in `sdd/tasks/index/wikitoolkit-env-support.json` → `"in-progress"`.
5. **Implement**, then verify all acceptance criteria.
6. **Move this file** to `sdd/tasks/completed/`.
7. **Update index** → `"done"` and fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude, Sonnet)
**Date**: 2026-08-27
**Notes**: Added `@wiki.group(name="sync")` with `push`/`pull` subcommands
(placed right after the `ground` command, before the Supervised Ingestion
section) — matches the `ns` group's structure exactly. Both subcommands
resolve the repo via `_resolve_project(path_)` (root only; the config
half is unused since `sync_push`/`sync_pull` re-resolve local/remote
configs internally) and wrap the coroutine with the existing `_run()`
helper, matching the `note` command's convention. `local_identity` is
always `default_local_identity()` from `wiki/sync.py` (TASK-2466's own
`f"human:{getpass.getuser()}"` — reused rather than reimplemented or
routed through the unrelated, more general `_authoring_identity()`
helper, since the task explicitly specifies this exact formula and no
override flag). `--all` on `pull` maps to `include_own=True`. Both
`sync_push`/`sync_pull` are imported LAZILY inside each command function
(matching this file's established convention for less-common subcommands,
e.g. the `ground` command's graphindex imports) — also means
`monkeypatch.setattr("parrot.knowledge.wiki.sync.sync_push", ...)` in
tests is picked up correctly, since the `from ... import` re-resolves the
attribute at call time. `SyncError` → `click.ClickException` (clean exit,
no traceback) at both call sites. Summary lines match the Key Constraints
format exactly: `pushed: created=N updated=N skipped-older=N` /
`pulled: created=N updated=N skipped-older=N skipped-own=N`, with a
`DRY RUN — nothing applied` line first when `report.dry_run`.

6 tests in `tests/knowledge/wiki/test_cli_sync.py`, all passing — engine
fully mocked via `monkeypatch.setattr` on `parrot.knowledge.wiki.sync.
sync_push`/`sync_pull` (engine's own logic already covered by
TASK-2466's `test_sync.py`). Covers: push dispatch with `--env`/
`--dry-run` and the identity string shape, `--all` → `include_own=True`,
default (`--all` absent) → `include_own=False` with default `--env dev`,
full summary-line rendering (all 4 counters), clean non-zero exit with no
traceback on a mocked `SyncError`, and `--help` documenting both the
`dev` env default and the `--all`/`human:` author-filter default.

Full `tests/knowledge/wiki/` suite: 1123 passed, 1 pre-existing unrelated
failure (`test_claude_code.py`, confirmed via `git stash` baseline). No
recurrence of the intermittent `test_sources.py` timing flake noted in
TASK-2466's completion note. `ruff check cli.py`: same 3 pre-existing
findings as the TASK-2463/2464/2465/2466 baseline (verified — none
introduced by this task); `test_cli_sync.py`: clean.

**Deviations from spec**: none.
