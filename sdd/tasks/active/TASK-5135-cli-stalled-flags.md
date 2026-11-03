# TASK-5135: CLI — `parrot sdd uninstall --stalled/--stale --keep`, stale lines in `status`

**Feature**: FEAT-795 — `parrot sdd uninstall --stalled` — remove stale and hand-copied SDD files
**Spec**: `sdd/specs/parrot-sdd-install-remove.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5131, TASK-5132, TASK-5133
**Assigned-to**: unassigned

---

## Context

Spec G1/G2/G4, §2 (CLI paragraph) and §3 Module 3. Exposes the installer's `remove_stale_sdd_files`
(TASK-5132) and `toolkit_stale.remove_stale_mcp_entries` (TASK-5131) as one command, and prints the new
`stale` / `stale_mcp` status keys.

---

## Scope

- `uninstall` gains `--stalled` (alias `--stale`) and repeatable `--keep GLOB`.
  - `--stalled` replaces the normal uninstall plan entirely. Hosts default to **all** `SUPPORTED_HOSTS` (not
    `claude`); `--host` narrows. It runs `remove_stale_sdd_files(...)` then `remove_stale_mcp_entries(...)` with
    the same hosts/keep/dry_run and echoes both action lists.
  - In a source checkout the file part raises `RuntimeError`: print it, still run the MCP part, then exit
    non-zero with that message (`ClickException`).
  - `--stalled --keep-edits` → `click.UsageError`; `--keep` without `--stalled` → `click.UsageError` (exit 2).
- `status` prints `stale: N` + `  stale: <path> (<reason>)` per entry, then `stale mcp: M` +
  `  stale mcp: <file>#<key> (<reason>)` per entry, before the `receipt version:` line.
- Extend `packages/ai-parrot/tests/sdd/test_sdd_cli.py`.

**NOT in scope**: the `VERBS` table (TASK-5133 already added `worktree list/remove`); installer internals; docs
(TASK-5136).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | `uninstall` options + dispatch; `status` lines |
| `packages/ai-parrot/tests/sdd/test_sdd_cli.py` | MODIFY | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# cli.py line 13 today:
from parrot.sdd.installer import SUPPORTED_HOSTS, install_sdd_integration, sdd_status, uninstall_sdd_integration
# becomes (remove_stale_sdd_files created by TASK-5132):
from parrot.sdd.installer import (
    SUPPORTED_HOSTS, install_sdd_integration, remove_stale_sdd_files, sdd_status, uninstall_sdd_integration,
)
# lazy, inside uninstall() (keeps `parrot sdd --help` import-cheap):
from parrot.mcp.toolkit_stale import remove_stale_mcp_entries   # created by TASK-5130/5131
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/cli.py
from parrot.sdd.installer import SUPPORTED_HOSTS, install_sdd_integration, sdd_status, uninstall_sdd_integration  # line 13
_dry_run_option = click.option("--dry-run", is_flag=True, ...)      # line 15
_keep_edits_option = click.option("--keep-edits", is_flag=True, ...) # line 17
_path_option / _host_option (multiple=True, click.Choice(SUPPORTED_HOSTS))   # lines 26-40
def _root(path_: Path | None) -> Path                               # line 42
def _echo_actions(actions: list[str]) -> None                       # line 50 — "warning:"/"note:" -> stderr "  ! ", "plan:" -> "  · ", else "  ✓ "
@sdd.command() @_path_option @_host_option @_keep_edits_option @_dry_run_option
def uninstall(path_: Path | None, hosts: tuple[str, ...], keep_edits: bool, dry_run: bool) -> None:   # line 137
    # body: _echo_actions(uninstall_sdd_integration(_root(path_), hosts or ("claude",), keep_edits=..., dry_run=...))
    #       except (ValueError, RuntimeError) -> click.ClickException
def status(path_: Path | None, as_json: bool) -> None               # line 150
    click.echo(f"receipt version: {report['receipt_version'] or 'none'}")   # line 171
# installer (TASK-5132): remove_stale_sdd_files(root, hosts=SUPPORTED_HOSTS, *, keep=(), dry_run=False) -> list[str]
#   sdd_status(root)["stale"]: [{"path","reason","detail","symlink"}], ["stale_mcp"]: [{"host","file","key","reason","detail"}]
# toolkit_stale (TASK-5131): remove_stale_mcp_entries(root, hosts, *, keep=(), dry_run=False, gemini_config=None) -> list[str]
```
Tests: `CliRunner().invoke(cli, ["sdd", ...])` with `from parrot.cli import cli` (test_sdd_cli.py:10). The global
Gemini file MUST be redirected: `monkeypatch.setattr("parrot.knowledge.wiki.google.assets.default_mcp_config_path",
lambda: gemini_path)` — `--stalled` without `--host` scans google and could otherwise **rewrite the developer's real
`~/.gemini/config/mcp_config.json`**.

### Does NOT Exist
- ~~`--force` wiring~~ — hidden no-op since PR #1940; wire nothing to it.
- ~~`parrot sdd stale` / `parrot sdd clean` commands~~ — the feature is a flag on `uninstall` only.
- ~~a `gemini_config` CLI option~~ — tests redirect with monkeypatch; do not add an option.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_sdd_cli.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#uninstall",
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#status",
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#_echo_actions",
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#_root"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Plain `parrot sdd uninstall` (no `--stalled`) must behave exactly as before — same default host (`claude`).
- The `--host` option's help says "default: claude"; extend the `--stalled` help to say it scans all hosts unless
  `--host` narrows it (do not change the shared `_host_option`).
- Validate flag combinations before touching the filesystem.

---

## Implementation Blueprint

### Steps (in order)
1. Update the line-13 import — *why*: `remove_stale_sdd_files` is called from `uninstall`.
2. Replace the `uninstall` signature/decorators and add the `--stalled` branch — *why*: spec M3 skeleton.
3. Add the status lines — *why*: G5.
4. Add the tests — *why*: AC-1..AC-5.

### `packages/ai-parrot/src/parrot/sdd/cli.py` (MODIFY) — uninstall
```python
# occurrences: 1 (verified: grep -c 'def uninstall(path_: Path | None, hosts: tuple[str, ...], keep_edits: bool, dry_run: bool) -> None:' cli.py)
# REPLACE the decorators + function at cli.py:132-147 (`@sdd.command()` … end of `uninstall`) with:
@sdd.command()
@_path_option
@_host_option
@_keep_edits_option
@_dry_run_option
@click.option(
    "--stalled",
    "--stale",
    "stalled",
    is_flag=True,
    help="Remove only stale SDD files (hand-copied, retired or no longer shipped) and stale MCP toolkit entries for "
    "all hosts unless --host narrows it; current assets are kept.",
)
@click.option("--keep", "keep", multiple=True, metavar="GLOB", help="With --stalled: never remove paths matching GLOB (repeatable).")
def uninstall(
    path_: Path | None, hosts: tuple[str, ...], keep_edits: bool, dry_run: bool, stalled: bool, keep: tuple[str, ...]
) -> None:
    """Remove the SDD files (commands, agents, rules, templates); seeds and state are kept.

    With --stalled, remove only stale files and stale MCP entries instead.
    """
    if stalled and keep_edits:
        raise click.UsageError("--stalled cannot be combined with --keep-edits")
    if keep and not stalled:
        raise click.UsageError("--keep requires --stalled")
    root = _root(path_)
    if stalled:
        # FILL IN: selected = hosts or SUPPORTED_HOSTS; refused: str | None = None;
        #   try: _echo_actions(remove_stale_sdd_files(root, selected, keep=keep, dry_run=dry_run))
        #   except RuntimeError as exc: refused = str(exc); click.echo(f"  ! {exc}", err=True)
        #   except ValueError as exc: raise click.ClickException(str(exc)) from exc
        #   then lazy-import remove_stale_mcp_entries and _echo_actions(...) with the same arguments
        #   ((ValueError, RuntimeError, OSError) -> ClickException); finally raise click.ClickException(refused) when set.
        return
    try:
        _echo_actions(uninstall_sdd_integration(root, hosts or ("claude",), keep_edits=keep_edits, dry_run=dry_run))
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
```

### `packages/ai-parrot/src/parrot/sdd/cli.py` (MODIFY) — status
```python
# occurrences: 1 (verified: grep -c "    click.echo(f\"receipt version: {report['receipt_version'] or 'none'}\")" cli.py)
# BEFORE — insert above that line (verified: cli.py:171)
    click.echo(f"stale: {len(report['stale'])}")
    for entry in report["stale"]:
        click.echo(f"  stale: {entry['path']} ({entry['reason']})")
    click.echo(f"stale mcp: {len(report['stale_mcp'])}")
    for entry in report["stale_mcp"]:
        click.echo(f"  stale mcp: {entry['file']}#{entry['key']} ({entry['reason']})")
```

### `packages/ai-parrot/tests/sdd/test_sdd_cli.py` (MODIFY)
```python
# AFTER — insert below test_uninstall_removes_unrecorded_assets_unless_keep_edits (verified: test_sdd_cli.py:50-59)
@pytest.fixture
def gemini(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the user-global Gemini MCP file — `--stalled` scans google by default."""
    path = tmp_path / "gemini_home" / "mcp_config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    monkeypatch.setattr("parrot.knowledge.wiki.google.assets.default_mcp_config_path", lambda: path)
    return path


# FILL IN: tests (each takes `gemini`; add `import pytest` to the imports):
#   test_cli_uninstall_stalled_all_hosts_by_default (install --host claude/codex/google, then create
#     .claude/commands/sdd-old.md, .agents/skills/sdd-old/SKILL.md, .agent/agents/sdd-worker/agent.md;
#     `uninstall --stalled` -> exit 0, all three gone, a current asset still present),
#   test_cli_uninstall_stalled_rejects_keep_edits (exit 2), test_cli_keep_requires_stalled (exit 2),
#   test_cli_stale_alias (`--stale --dry-run` == `--stalled --dry-run` output),
#   test_cli_stalled_cleans_mcp_entries (add `parrot-oldkit` to .mcp.json -> gone after --stalled; wikitoolkit kept),
#   test_cli_status_prints_stale (`status` output contains "stale: " and "stale mcp: ").
```

### FILL IN checklist
- [ ] `uninstall` `--stalled` branch; bounded by AC-1, AC-3.
- [ ] the 6 tests listed.

---

## Acceptance Criteria

- [ ] AC-1: `--stalled` without `--host` cleans stale files and MCP entries for all three hosts in one run;
      `--host` narrows.
- [ ] AC-2: `--stale` is an alias; `--stalled --keep-edits` and `--keep` alone exit 2.
- [ ] AC-3: in a source checkout the command exits non-zero with the refusal message after running the MCP part.
- [ ] AC-4: `parrot sdd status` prints the stale and stale-mcp lines; `--json` carries both keys.
- [ ] AC-5: plain `parrot sdd uninstall` output and behaviour are unchanged (existing tests pass).
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q`

---

## Test Specification

See the blueprint; rows are spec §4 "Integration Tests (`test_sdd_cli.py`, extend)" except
`test_cli_worktree_verbs_mounted` (TASK-5133 covers the mount).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug parrot-sdd-install-remove --feature-id FEAT-795`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/parrot-sdd-install-remove.json`
4. **Verify the Codebase Contract** before writing any code; fix the contract first if anything moved
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint; complete every `# FILL IN:`; never change a signature or path it fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5135 parrot-sdd-install-remove verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
