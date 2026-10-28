# TASK-4860: `wikitoolkit ledger outbox prepare|status|integrate` + reject `export-log --stage`

**Feature**: FEAT-758 — Durable Ledger Outbox and Independent Integration into dev
**Spec**: `sdd/specs/ledger-outbox-integration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4859
**Assigned-to**: unassigned

---

## Context

Spec §2 "New Public Interfaces" and §3 Module 3. Workflows (TASK-4862) gate on exit codes, so the CLI is the
contract between the tested Python integrator and the three `/sdd-done` hosts. It also closes the stale-hook
hole: an old installed pre-commit hook runs `wikitoolkit ledger export-log --stage --quiet`, which would keep
staging `sdd/ledger/events.jsonl` into feature commits even after TASK-4861 changes the generator — so the
upgraded CLI must reject `--stage` **before any write**.

---

## Scope

- Add a Click sub-group `outbox` under the existing `ledger` group with three commands:
  `prepare`, `status`, `integrate` — options exactly as spec §2:
  `--repo-root PATH` (required), `--ledger-dir PATH`, `--batch-id UUID` (integrate only), `--json`.
- Source resolution: `--ledger-dir` given → that directory; else if remote mode is configured
  (`click.get_current_context().obj["remote"] is not None`) → report `unsupported` (exit 4) with **no writes**;
  else `Path(LedgerService.from_root(Path(repo_root)).log.path).parent`.
- `prepare`: `source_ref` = `git -C <repo_root> rev-parse --abbrev-ref HEAD`, `source_head` = `rev-parse HEAD`;
  `known = await LedgerIntegrator(...).remote_event_ids()`; `LedgerOutbox.prepare(..., known_ids=known)`;
  print the batch id + path, or "nothing to prepare".
- `status`: read-only — `outbox.status(known_ids=...)` + `pending()` listing; never acknowledges or pushes.
  It also reports `contaminated_paths = await integrator.check_feature_diff("HEAD")` (canonical ledger paths
  the checkout's branch changed since its merge-base with `origin/dev`) and exits **4** when that list is
  non-empty — this is the only CLI surface for spec §3 M5's "check canonical diff; report legacy contamination
  without dropping it" (the spec's §2 command list has no separate command for it). On the base branch itself
  the list is empty by construction.
- `integrate`: with `--batch-id`, that batch only; without it, every pending batch in preparation order,
  stopping at the first non-success.
- Exit codes (spec §2): `0` delivered / already_delivered / no-op / prepared; `2` pending (I/O, lock, push,
  retry exhaustion; `OutboxLockedError`); `3` invalid content or semantic conflict (`StrictLedgerReadError`,
  `status="conflict"`); `4` unsupported source/destination/legacy contamination.
- `--json` prints one JSON object (`LedgerDeliveryReport.model_dump(mode="json")` or a list of them for
  integrate; a dict for prepare/status). Human output otherwise.
- `ledger export-log --stage`: reject with a migration message and exit 4 **before** constructing the service
  or touching any file; non-staging `export-log` keeps working unchanged.
- Update `tests/knowledge/wiki/test_cli_ledger_shared_log.py`: the two `--stage` tests now assert the rejection
  (no file written, nothing staged). Create `packages/ai-parrot/tests/knowledge/wiki/test_cli_ledger_outbox.py`.

**NOT in scope**: MCP tools (spec: local-only, no MCP registry entries); hooks (TASK-4861); workflow docs
(TASK-4862); `rotate-log --stage` (unchanged — explicit maintenance command).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `ledger outbox` group + `export-log --stage` rejection |
| `tests/knowledge/wiki/test_cli_ledger_shared_log.py` | MODIFY | Rewrite the two `--stage` tests to assert rejection |
| `packages/ai-parrot/tests/knowledge/wiki/test_cli_ledger_outbox.py` | CREATE | CLI codes, JSON, remote-only mode |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already in cli.py:
from parrot.knowledge.wiki.ledger.service import LedgerService, normalize_issue_id   # cli.py:127
from parrot.knowledge.wiki.ledger.shared_log import SHARED_LOG_REL_PATH, shared_log_files  # cli.py:128
from parrot.knowledge.wiki import remote_cli   # cli.py:104
import click, json, subprocess                 # cli.py:43,29,34
# add (created by TASK-4857 / TASK-4859):
from parrot.knowledge.wiki.ledger.outbox import LedgerOutbox, OutboxLockedError, StrictLedgerReadError
from parrot.knowledge.wiki.ledger.integration import LedgerIntegrator
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
def _run(coro: Any) -> Any:  # :580 — runs a coroutine from sync Click code
@wiki.group(name="ledger")   # :3222
def ledger() -> None:        # :3223
def _git_toplevel(cwd: Path) -> Path:  # :3634
@ledger.command("export-log")          # :3647
@click.option("--repo-root", default=None, ...)
@click.option("--stage", is_flag=True, default=False, help="git add the file when it changed")
@click.option("--quiet", is_flag=True, default=False)
@remote_cli.remote_aware(proxied=False)
def ledger_export_log(repo_root: str | None, stage: bool, quiet: bool) -> None:  # :3652
@ledger.command("import-log")  # :3677 — next command; insert the outbox group ABOVE it

# packages/ai-parrot/src/parrot/knowledge/wiki/remote_cli.py:97
def remote_aware(*, proxied: bool, tool: str | None = None)
#   sets ctx.obj["remote"]; proxied=False REFUSES remote mode with a usage error,
#   proxied=True lets the body run — use proxied=True so the body can report `unsupported` (exit 4) itself.

# tests: tests/knowledge/wiki/test_cli_ledger_shared_log.py
def test_cli_export_log_stage_runs_git_add(tmp_path: Path, monkeypatch) -> None:   # :16
def test_cli_export_log_stage_reports_git_add_failure(tmp_path: Path, monkeypatch) -> None:  # :39
#   pattern: monkeypatch "parrot.knowledge.wiki.remote_cli.remote_or_none" -> (None, None, None);
#   CliRunner().invoke(ledger, [...])
```
Existing JSON-flag convention elsewhere is `@click.option("--json", "as_json", ...)` (cli.py:2117); the spec
skeleton fixes the parameter name `json_output`, so declare `@click.option("--json", "json_output", is_flag=True)`.

### Does NOT Exist
- ~~`ledger outbox` group~~ — created here.
- ~~MCP tools `ledger_outbox_*`~~ — must NOT be added (spec §2).
- ~~`LedgerService.from_root(...).outbox`~~ — build `LedgerOutbox(ledger_dir)` directly.
- ~~`remote_cli.call_remote_text(..., "ledger_outbox_...")`~~ — there is no remote transport for the outbox.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_cli_ledger_shared_log.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_cli_ledger_outbox.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#ledger",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#ledger_export_log",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_run",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/remote_cli.py#remote_aware",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.from_root"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the two imports next to `cli.py:128` — *why*: commands call the outbox and integrator Python APIs.
2. Add the `--stage` rejection at the top of `ledger_export_log` — *why*: stop stale hooks before any write.
3. Insert the `outbox` group above `import-log` — *why*: spec §6 places it adjacent to `ledger_export_log`.
4. Rewrite the two root tests and create the new test file.

### `cli.py` (MODIFY) — `export-log --stage` rejection
```python
# occurrences: 1 (verified: grep -c 'def ledger_export_log(repo_root: str | None, stage: bool, quiet: bool) -> None:' cli.py)
# AFTER — replace the first two body lines below the anchor (cli.py:3652-3654):
#     """Append this machine's shareable events to the committed shared ledger log."""
#     root = Path(repo_root) if repo_root else _git_toplevel(Path.cwd())
    """Append this machine's shareable events to the committed shared ledger log (diagnostics only)."""
    if stage:
        click.echo(
            "export-log --stage is obsolete (FEAT-758): ledger events no longer travel in feature commits. "
            "Re-run `parrot claude install` to upgrade the hooks; /sdd-done delivers events with "
            "`wikitoolkit ledger outbox prepare|integrate`.",
            err=True,
        )
        raise SystemExit(4)
    root = Path(repo_root) if repo_root else _git_toplevel(Path.cwd())
```
Leave the remaining `if stage and ...` git-add branch unreachable-free: **delete** it (stage is now always
False past the guard) — keep the `--stage` option declared so old hooks reach the rejection instead of a Click
"no such option" error that some shells would hide.

### `cli.py` (MODIFY) — `outbox` group
```python
# occurrences: 1 (verified: grep -c '@ledger.command("import-log")' cli.py)
# BEFORE — insert above `@ledger.command("import-log")` (cli.py:3677)
_OUTBOX_EXIT = {"delivered": 0, "already_delivered": 0, "pending": 2, "conflict": 3, "unsupported": 4}


@ledger.group("outbox")
def ledger_outbox() -> None:
    """Local-only durable delivery of ledger events to origin/dev (FEAT-758)."""


def _outbox_source(repo_root: str, ledger_dir: str | None) -> Path | None:
    """Resolve the local journal directory, or ``None`` when only a remote ledger is configured."""
    if ledger_dir:
        return Path(ledger_dir).resolve()
    if click.get_current_context().obj.get("remote") is not None:
        return None
    return Path(LedgerService.from_root(Path(repo_root)).log.path).parent


def _unsupported(json_output: bool, reason: str) -> None:
    # FILL IN: emit {"status": "unsupported", "error_code": reason} (JSON or text) and raise SystemExit(4)
    raise NotImplementedError


@ledger_outbox.command("prepare")
@click.option("--repo-root", required=True)
@click.option("--ledger-dir", default=None)
@click.option("--json", "json_output", is_flag=True, default=False)
@remote_cli.remote_aware(proxied=True)
def ledger_outbox_prepare(repo_root: str, ledger_dir: str | None, json_output: bool) -> None:
    """Resolve local source, capture a batch, and report its durable location."""
    # FILL IN: source None -> _unsupported("remote-only-ledger"); source_ref/head via subprocess git rev-parse;
    #   known = _run(LedgerIntegrator(Path(repo_root), outbox).remote_event_ids()); batch =
    #   _run(outbox.prepare(...)); OutboxLockedError -> exit 2; StrictLedgerReadError -> exit 3; print result.


@ledger_outbox.command("status")
@click.option("--repo-root", required=True)
@click.option("--ledger-dir", default=None)
@click.option("--json", "json_output", is_flag=True, default=False)
@remote_cli.remote_aware(proxied=True)
def ledger_outbox_status(repo_root: str, ledger_dir: str | None, json_output: bool) -> None:
    """Show sealed/unsealed pending delivery without side effects beyond read-only Git queries."""
    # FILL IN: read-only; a failed fetch still reports local counts with "remote_fresh": false.
    #   Include "contaminated_paths" from LedgerIntegrator.check_feature_diff("HEAD"); non-empty -> exit 4
    #   after printing (never edit or restore those paths).


@ledger_outbox.command("integrate")
@click.option("--repo-root", required=True)
@click.option("--ledger-dir", default=None)
@click.option("--batch-id", default=None)
@click.option("--json", "json_output", is_flag=True, default=False)
@remote_cli.remote_aware(proxied=True)
def ledger_outbox_integrate(repo_root: str, ledger_dir: str | None, batch_id: str | None, json_output: bool) -> None:
    """Deliver pending batches and map typed outcomes to documented exit codes."""
    # FILL IN: pending() (filter by batch_id; unknown id -> exit 3 "unknown-batch"); integrate each in order,
    #   stop at first report whose _OUTBOX_EXIT != 0; print each report (recovery_path + retry command
    #   `wikitoolkit ledger outbox integrate --repo-root <root> --batch-id <id>`); exit with that code.
```

### `tests/knowledge/wiki/test_cli_ledger_shared_log.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_cli_export_log_stage_runs_git_add(tmp_path: Path, monkeypatch) -> None:')
# REPLACE the bodies of test_cli_export_log_stage_runs_git_add (:16) and
# test_cli_export_log_stage_reports_git_add_failure (:39) with ONE test:
def test_cli_export_log_stage_is_rejected_without_writes(tmp_path: Path, monkeypatch) -> None:
    """An old hook's `export-log --stage` exits 4 before any write or staging (FEAT-758)."""
    # FILL IN: git init tmp_path; patch LedgerService.from_root with a Mock that fails the test if called;
    #   invoke ["export-log", "--repo-root", str(tmp_path), "--stage", "--quiet"]; exit_code == 4;
    #   sdd/ledger/events.jsonl does not exist; `git diff --cached --name-only` is empty.
```

### `packages/ai-parrot/tests/knowledge/wiki/test_cli_ledger_outbox.py` (CREATE)
```python
"""FEAT-758 M3 — `wikitoolkit ledger outbox` exit codes and source resolution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import ledger
from parrot.knowledge.wiki.ledger.outbox import LedgerDeliveryReport


@pytest.fixture(autouse=True)
def _local_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("parrot.knowledge.wiki.remote_cli.remote_or_none", lambda path_=None: (None, None, None))


@pytest.mark.parametrize("status,code", [("delivered", 0), ("already_delivered", 0), ("pending", 2),
                                         ("conflict", 3), ("unsupported", 4)])
def test_integrate_maps_status_to_exit_code(tmp_path: Path, status: str, code: int) -> None: ...  # FILL IN
def test_integrate_json_is_structured(tmp_path: Path) -> None: ...  # FILL IN
def test_remote_only_mode_is_unsupported_without_writes(tmp_path: Path, monkeypatch) -> None: ...  # FILL IN: remote_or_none returns a sentinel remote; no outbox/ dir created
def test_prepare_lock_busy_exits_2(tmp_path: Path) -> None: ...  # FILL IN
def test_status_never_acknowledges(tmp_path: Path) -> None: ...  # FILL IN: no receipts/ files after status
def test_status_reports_contamination_exit_4(tmp_path: Path) -> None: ...  # FILL IN: patch check_feature_diff -> ["sdd/ledger/events.jsonl"]
```

### FILL IN checklist
- [ ] `_unsupported`, three command bodies — bounded by spec §2 exit-code table
- [ ] `export-log` guard placed before ANY service/file access (AC "old --stage commands cannot reintroduce tracked events")
- [ ] Root test rewrite + 6 new tests (replace each `...`)

---

## Acceptance Criteria

- [ ] Stable JSON and exit codes 0/2/3/4 as documented
- [ ] Remote-only configuration → `unsupported`, no silent local fallback, no writes
- [ ] `export-log --stage` produces no canonical writes or index changes; plain `export-log` unchanged
- [ ] No MCP registry entry added
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli_ledger_outbox.py -q`
- `pytest tests/knowledge/wiki/test_cli_ledger_shared_log.py -q`

---

## Test Specification

See the test blueprints above.

---

## Agent Instructions

1. Work in the feature worktree; TASK-4859 must be `done`.
2. Read spec §2 "New Public Interfaces" and §3 Module 3.
3. Re-verify the `cli.py` anchors (`grep -n`) — the file is large and busy; line numbers may drift.
4. Implement, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`, commit only the three files.
5. Close with `scripts/sdd/close_task.sh TASK-4860 ledger-outbox-integration verified`.

---

## Completion Note

*(Agent fills this in when done)*
