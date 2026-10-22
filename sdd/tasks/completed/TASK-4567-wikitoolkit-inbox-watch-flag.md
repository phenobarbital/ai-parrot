# TASK-4567: wikitoolkit inbox --watch

**Feature**: FEAT-715 — FirefliesInsightsAgent
**Spec**: `sdd/specs/fireflies-insights-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4566
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 3**: the standalone process shape of the watcher (§8 "How the watcher
runs in production": service object **and** `wikitoolkit inbox --watch`). Also carries
**AC29**'s CLI half: without the `filesystem-transport-full` extra, `--watch` must fail
with an actionable message while the one-shot `wikitoolkit inbox` keeps working.

---

## Scope

- Add `@click.option("--watch", is_flag=True, help=...)` to the `inbox` command and a
  `watch: bool` parameter.
- Reject `--watch` together with `--limit` or `--dry-run` with `click.UsageError`
  **before** any store/runtime is built.
- When `--watch`: build the runtime exactly as today, then run
  `InboxWatcher(runtime, force=force, archive=archive).run_forever()` via `_run(...)`;
  on `WatcherUnavailable` raise `click.UsageError(str(exc))` (exit 2); on
  `KeyboardInterrupt` print the watcher's `stats` (JSON when `--json`) and exit 0.
- Import `InboxWatcher` / `WatcherUnavailable` **inside** the function, next to the
  existing lazy imports — because the CLI module must not import the watcher eagerly.

**NOT in scope**: any change to the one-shot path's behaviour or exit codes;
`InboxWatcher` itself (TASK-4566); docs (TASK-4576).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `--watch` flag on `wikitoolkit inbox` |
| `packages/ai-parrot/tests/knowledge/wiki/inbox/test_cli_inbox.py` | MODIFY | Flag wiring, incompatibilities, missing-extra error, one-shot unaffected |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.inbox.watcher import InboxWatcher, WatcherUnavailable  # created by TASK-4565/4566
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:580
def _run(coro: Any) -> Any:  # asyncio.run wrapper
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:5946  — the command (decorators directly above, last one:
#   @click.option("--json", "as_json", is_flag=True)   <- 4 occurrences in cli.py, NOT a unique anchor)
def inbox(path_, dry_run, limit, charter_opt, lightweight_model_opt, model_opt,
          archive, force, as_json) -> None: ...
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:5962 — existing lazy imports inside inbox():
#     from parrot.knowledge.wiki.inbox.processor import InboxLockBusy, InboxProcessor
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:6002 — the one-shot run:
#         report = _run(InboxProcessor(runtime).run(dry_run=dry_run, limit=limit, force=force, archive=archive))
```

### Does NOT Exist
- ~~a separate `wikitoolkit watch` command~~ — the spec decided a flag on `inbox`.
- ~~`--debounce` / `--window` CLI options~~ — the window is `InboxConfig.stability_window` (TASK-4564).

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
      "path": "packages/ai-parrot/tests/knowledge/wiki/inbox/test_cli_inbox.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#inbox",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_run"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the decorator directly above `def inbox(` — *why*: `def inbox(` is the unique anchor.
2. Add `watch: bool` to the signature — *why*: click passes every option as a kwarg.
3. Add the incompatibility check at the top of the body — *why*: fail before opening a store.
4. Branch before the one-shot run — *why*: the runtime build is shared.
5. Extend `packages/ai-parrot/tests/knowledge/wiki/inbox/test_cli_inbox.py` — *why*: AC29 and the incompatibilities.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY) — decorator
```python
# occurrences: 1 (verified: grep -cF 'def inbox(' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py)
# BEFORE — insert directly above `def inbox(` (verified: packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:5946)
@click.option("--watch", is_flag=True, help="Observe the inbox directory and ingest continuously until interrupted.")
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY) — signature
```python
# `    as_json: bool,` has 16 occurrences — anchor on this unique 3-line context
# (verified: packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:5955-5957):
#     force: bool,
#     as_json: bool,
# ) -> None:
#     """Ingest every safe document from the configured inbox directory.
# INSERT `    watch: bool,` between `    as_json: bool,` and `) -> None:`
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY) — incompatibility guard
```python
# occurrences: 1 (verified: grep -cF '    The processor, rather than the CLI, owns the whole-run write lock.' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py)
# AFTER — insert directly below the docstring's closing quotes that follow that line
    if watch and (limit is not None or dry_run):
        raise click.UsageError("--watch cannot be combined with --limit or --dry-run")
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY) — watch branch
```python
# occurrences: 1 (verified: grep -cF '        report = _run(InboxProcessor(runtime).run(dry_run=dry_run, limit=limit, force=force, archive=archive))' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py)
# BEFORE — insert directly above the `    try:` line that precedes it (verified: packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:6001-6002)
    if watch:
        from parrot.knowledge.wiki.inbox.watcher import InboxWatcher, WatcherUnavailable

        watcher = InboxWatcher(runtime, force=force, archive=archive)
        try:
            _run(watcher.run_forever())
        except WatcherUnavailable as exc:
            raise click.UsageError(str(exc)) from exc
        except KeyboardInterrupt:
            pass
        # FILL IN: emit watcher.stats — `click.echo(watcher.stats.model_dump_json())` when
        #   as_json, else one human line "Watcher: events=… runs=… documents=… lock_retries=…"
        #   — bounded by the existing one-shot output style just below.
        return
```
**Why**: `WatcherUnavailable` is raised from `start()` inside `run_forever()`, so it
surfaces through `_run`. `UsageError` gives exit code 2 with the extra's name (AC29).

### FILL IN checklist
- [ ] stats output (JSON vs human line).
- [ ] `packages/ai-parrot/tests/knowledge/wiki/inbox/test_cli_inbox.py` cases below.

---

## Acceptance Criteria

- [ ] `--watch --limit 1` and `--watch --dry-run` exit 2 before any store is opened.
- [ ] `--watch` constructs `InboxWatcher` with the CLI's `force` / `archive` values.
- [ ] With `watchdog` absent, `--watch` exits 2 naming `filesystem-transport-full` (AC29).
- [ ] With `watchdog` absent, the one-shot `wikitoolkit inbox` still succeeds (AC29).
- [ ] Existing `packages/ai-parrot/tests/knowledge/wiki/inbox/test_cli_inbox.py` tests still pass unchanged.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/knowledge/wiki/inbox/test_cli_inbox.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/inbox/test_cli_inbox.py  (append) — reuse the module's existing monkeypatch helpers
#   (_resolve_project / _open_store / _open_sources / _resolve_charter_path /
#    load_charter / _build_ingest_runtime are already stubbed there, see lines 41-46)
def test_watch_rejects_limit_and_dry_run(...): ...
def test_watch_runs_watcher_with_cli_flags(...):      # monkeypatch InboxWatcher with a fake recording kwargs
    ...
def test_watch_without_watchdog_is_usage_error(...):  # fake run_forever raises WatcherUnavailable
    ...
def test_one_shot_works_without_watchdog(..., monkeypatch):
    monkeypatch.setitem(sys.modules, "watchdog", None)
    ...
```
> FILL IN: bodies — follow `test_cli_inbox_options_and_exit_codes` (CliRunner +
> the stubs at lines 41-60). Patch `parrot.knowledge.wiki.inbox.watcher.InboxWatcher`,
> because the CLI imports it lazily from that module.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug fireflies-insights-agent --feature-id FEAT-715`).
2. **Read the spec** `sdd/specs/fireflies-insights-agent.spec.md` — §3 (the module this task implements) and §6.
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/fireflies-insights-agent.json`.
4. **Verify the Codebase Contract** before writing code. Anchors were verified at
   `f6a4dbfca`; re-run every `grep -c` in the blueprint and use the fresh count.
   A count of `0` means the anchor moved — stop and report, never invent one.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`)
   and commit only that index file.
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
   marker; never change a signature, class name or path the blueprint fixes.
7. **Run** the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
   (plus `packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src`
   when the task imports them) — the shared venv is installed against the main
   checkout. Then `ruff check --fix` on every file you touched.
8. **Commit** only the files this task lists (never `git add .` / `-A`):
   `feat(fireflies-insights-agent): TASK-4567 — <title>`.
9. **Close** with `scripts/sdd/close_task.sh TASK-4567 fireflies-insights-agent verified` — never move
   the file by hand.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

**Completed by**: sdd-worker; coder seat gpt-5.6-terra (codex, attempt 1, 240.9s)
**Date**: 2026-10-22
**Notes**: Added CLI support for wikitoolkit inbox --watch. 101 passed merge-tier validation.

**Deviations from spec**: none
