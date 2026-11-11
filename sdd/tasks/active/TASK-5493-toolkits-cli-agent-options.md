# TASK-5493: CLI — `parrot toolkits install --agent` and `list --agents`

**Feature**: FEAT-877 — Agent as a local stdio MCP server
**Spec**: `sdd/specs/agent-local-mcp.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5491
**Assigned-to**: unassigned

---

## Context

The user-facing entry point of FEAT-877 (spec G5): `parrot toolkits install --agent finance`
and `parrot toolkits list --agents`. This task implements spec §3 **Module 6** in
`parrot/cli/toolkits.py`, wiring the two functions TASK-5491 added. The interactive picker
stays template-only (spec Non-Goals); `uninstall`/`enable`/`disable` need no change.

---

## Scope

- `install` gains `--agent NAME` (`"agents"`, `multiple=True`). With agents and no NAMES the
  picker is NOT opened. NAMES (templates) keep their current path and run first; then, when
  agents were given: user-global warnings (once), confirmation
  `Install agents <a, b> into [<hosts>]?` (skipped with `--yes`), `install_agent_toolkits`,
  `ValueError` → `click.ClickException`, `_render(report)`. The
  `ℹ Start a new session for the MCP servers to appear.` hint prints once at the end.
- `list` gains `--agents`: prints `  ℹ discovering agents imports every agent module under AGENTS_DIR`,
  then appends `agent_inventory(root, hosts)` rows to the same table.
- Create `packages/ai-parrot/tests/mcp/test_toolkits_cli_agent.py`.

**NOT in scope**: changing `_resolve_names` / the picker; `uninstall`/`enable`/`disable`;
the `status` command.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/toolkits.py` | MODIFY | `install --agent`, `list --agents` |
| `packages/ai-parrot/tests/mcp/test_toolkits_cli_agent.py` | CREATE | CLI tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/dev` at `41df674d50` (2026-11-11).

### Verified Imports
```python
import click                                                         # verified: cli/toolkits.py
from click.testing import CliRunner                                  # verified: test_toolkit_matrix.py:23
from parrot.cli.toolkits import toolkits                             # verified: cli/toolkits.py:40-41 (`@click.group(name="toolkits")`)
from parrot.mcp.toolkit_install import ActionReport, ToolkitRow, ToolkitState   # verified: toolkit_install.py:55,38,32
# lazy inside the commands (existing pattern, patched at call time):
from parrot.mcp.toolkit_install import install_agent_toolkits, agent_inventory  # created by TASK-5491
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/toolkits.py
host_option = click.option("--host", "hosts_", multiple=True, type=click.Choice(["claude", "codex", "google"]), ...)  # line 18
yes_option = click.option("--yes", is_flag=True, default=False, help="Skip the confirmation prompt.")              # line 25
def _resolve_hosts(root: Path, hosts_: tuple[str, ...])               # line 45
def _resolve_names(root: Path, names: tuple[str, ...], hosts) -> list[str]   # line 52 (picker when names empty)
def _root(path_: Path | None = None, *, write: bool) -> Path          # line 90
def _warn_user_global(root: Path, hosts) -> list[str]                 # line 101
def _render(report) -> None                                           # line 118 (SystemExit(1) when every host failed)
@toolkits.command("list")                                             # line 130
@host_option
def list_(hosts_: tuple[str, ...]) -> None:                           # line 132
    #   from parrot.mcp.toolkit_install import inventory              (line 137)
    #   root = _root(write=False); hosts = _resolve_hosts(root, hosts_); rows = inventory(root, hosts)   (lines 139-141)
    #   table columns Name/State/Summary/Hosts/Deps/Drift; loop `for row in rows:` builds cells; Console(width=200).print(table)
@toolkits.command()                                                   # line 189
@click.argument("names", nargs=-1) / @host_option / @yes_option / --path / --portable/--no-portable   (lines 190-198)
def install(names, hosts_, yes, path_, portable) -> None:             # lines 199-230 (full body quoted in the blueprint)
```

### Does NOT Exist
- ~~`parrot toolkits install --agent`~~ / ~~`list --agents`~~ — created by this task.
- ~~an agent picker~~ — agents are installed only with the explicit `--agent` option.
- ~~`parrot toolkits uninstall --agent`~~ — uninstall works by section name (`agent-<slug>`); no new option.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/cli/toolkits.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/mcp/test_toolkits_cli_agent.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/toolkits.py#install",
    "sym:packages/ai-parrot/src/parrot/cli/toolkits.py#list_",
    "sym:packages/ai-parrot/src/parrot/cli/toolkits.py#_render",
    "sym:packages/ai-parrot/src/parrot/cli/toolkits.py#_root",
    "sym:packages/ai-parrot/src/parrot/cli/toolkits.py#_warn_user_global"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Keep the lazy-import pattern (`from parrot.mcp.toolkit_install import ...` inside the
  command): tests patch `parrot.mcp.toolkit_install.<fn>` and the command must pick the patch up.
- `list` without `--agents` must not import `parrot.mcp.agent_toolkit` or run discovery.
- Click passes options as keyword arguments, so the new parameter can be appended last.

---

## Implementation Blueprint

### Steps (in order)
1. Add `--agents` to `list` and append agent rows — *why*: G5 `list --agents`.
2. Replace `install` with the version below — *why*: agents and templates in one call, templates first.
3. Write the tests; run the Validation Commands.

### `packages/ai-parrot/src/parrot/cli/toolkits.py` (MODIFY) — `list`
```python
# occurrences: 1 (verified: grep -c '@toolkits.command("list")' cli/toolkits.py → line 130)
# REPLACE lines 130-141 (decorators, signature, docstring, imports, root/hosts/rows) — the line
#   `    rows = inventory(root, hosts)` occurs 2 times (lines 74, 141), so replace the whole quoted span:
@toolkits.command("list")
@host_option
@click.option("--agents", "agents_", is_flag=True, default=False, help="Also list agents declared for local MCP exposure.")
def list_(hosts_: tuple[str, ...], agents_: bool = False) -> None:
    """Show every available toolkit with its state, hosts, drift and dependencies."""
    from rich.console import Console
    from rich.table import Table

    from parrot.mcp.toolkit_install import inventory

    root = _root(write=False)
    hosts = _resolve_hosts(root, hosts_)
    rows = inventory(root, hosts)
    if agents_:
        from parrot.mcp.toolkit_install import agent_inventory  # lazy: discovery imports agent modules

        click.echo("  ℹ discovering agents imports every agent module under AGENTS_DIR")
        rows = [*rows, *agent_inventory(root, hosts)]
# (the table-building code that follows — `table = Table()` … the trailing missing-distribution hints — is unchanged)
```

### `toolkits.py` (MODIFY) — `install`
```python
# occurrences: 1 (verified: grep -c 'def install(' cli/toolkits.py → line 199)
# REPLACE the decorator `@click.option("--portable/--no-portable", ...)` block end (line 198 `)`) through the end of
#   `install` (line 230) — i.e. add the --agent option after --portable and rewrite the body:
@click.option("--agent", "agents", multiple=True, help="Registered agent to expose (repeatable); see `list --agents`.")
def install(
    names: tuple[str, ...],
    hosts_: tuple[str, ...],
    yes: bool,
    path_: Path | None,
    portable: bool | None,
    agents: tuple[str, ...] = (),
) -> None:
    """Seed selected toolkits — and, with --agent, registered agents — at the resolved target."""
    root = _root(path_, write=True)
    from parrot.mcp.toolkit_install import install_agent_toolkits, install_toolkits

    hosts = _resolve_hosts(root, hosts_)
    selected = _resolve_names(root, names, hosts) if (names or not agents) else []
    if not selected and not agents:
        click.echo("Nothing selected.")
        return
    for warning in _warn_user_global(root, hosts):
        click.secho(f"  ⚠ {warning}", fg="yellow")
    if selected:
        # FILL IN: the existing template flow unchanged — confirm `Install {names} into [...]?` (skip with --yes;
        #   declining returns), install_toolkits(root, selected, hosts, portable=portable) with ValueError →
        #   click.ClickException, _render(report), then the missing-distribution hints loop (lines 221-230 today)
        ...
    if agents:
        # FILL IN: confirm f"Install agents {', '.join(agents)} into {[h.value for h in hosts]}?" (skip with --yes;
        #   declining returns); install_agent_toolkits(root, list(agents), hosts, portable=portable) with
        #   ValueError → click.ClickException; _render(report)
        ...
    click.echo("  ℹ Start a new session for the MCP servers to appear.")
```
**Why**: one call may install templates and agents; the hint prints once so the output
stays the same for the template-only path.

### `packages/ai-parrot/tests/mcp/test_toolkits_cli_agent.py` (CREATE)
```python
"""FEAT-877 Module 6 — `parrot toolkits install --agent` / `list --agents`."""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.cli.toolkits import toolkits
from parrot.mcp.toolkit_install import ActionReport, ToolkitRow, ToolkitState


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the CLI at tmp_path with no detected hosts."""
    monkeypatch.setattr("parrot.cli.toolkits._root", lambda path_=None, *, write: tmp_path)
    monkeypatch.setattr("parrot.cli.toolkits._resolve_hosts", lambda root, hosts_: [])
    return tmp_path


def test_cli_install_agent(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []

    def fake_install(root_, agents, hosts, *, portable=None):
        calls.append((root_, agents))
        return ActionReport(actions=["finance — seeded as agent-finance (tools: forecast)"])

    monkeypatch.setattr("parrot.mcp.toolkit_install.install_agent_toolkits", fake_install)
    result = CliRunner().invoke(toolkits, ["install", "--agent", "finance", "--yes"])
    assert result.exit_code == 0, result.output
    assert calls == [(root, ["finance"])]
    assert "seeded as agent-finance" in result.output
    # FILL IN: without --yes and answering "n" → install not called; with NAMES and --agent → templates first
    #   (patch install_toolkits too and record the order); the picker (_resolve_names) is never called for agents only


def test_cli_install_agent_error_exit(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: fake install raises ValueError("Unknown agent 'nope'") → exit_code 1 and the message in output
    ...


def test_cli_list_agents(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: patch parrot.mcp.toolkit_install.inventory → [] and agent_inventory → [ToolkitRow(name="agent-finance",
    #   summary="agent finance: forecast", class_path="parrot.mcp.agent_toolkit.AgentToolkit", state=ToolkitState.ENABLED)];
    #   `list --agents` output contains "agent-finance" and the discovery notice; plain `list` never calls agent_inventory
    ...
```

### FILL IN checklist
- [ ] template branch of `install` — unchanged behaviour.
- [ ] agent branch of `install` — spec §3 M6 message and flow.
- [ ] every `...` test body.

---

## Acceptance Criteria

- [ ] `parrot toolkits install --agent X [--yes]` calls `install_agent_toolkits` and renders its report; errors exit 1 with the message (G5).
- [ ] `--agent` alone never opens the picker; NAMES + `--agent` installs templates first.
- [ ] `parrot toolkits list --agents` appends agent rows; plain `list` runs no agent discovery.
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/mcp/test_toolkits_cli_agent.py -q`

---

## Test Specification

See the CREATE block above: spec §4 Module 6 rows `test_cli_install_agent`,
`test_cli_install_agent_error_exit`, `test_cli_list_agents`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug agent-local-mcp --feature-id FEAT-877`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/agent-local-mcp.json`
4. **Verify the Codebase Contract** before writing code; if anything changed, update the contract first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:` marker
7. **Verify** the acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5493 agent-local-mcp verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
