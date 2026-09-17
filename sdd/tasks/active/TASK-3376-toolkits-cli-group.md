# TASK-3376: `parrot toolkits` Click group + questionary picker

**Feature**: FEAT-570 — `parrot toolkits` on-demand local-MCP toolkit installation
**Spec**: `sdd/specs/expose-local-mcp-tools.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3375
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 — the user-facing surface the whole feature exists to provide.
Six subcommands (`list`, `status`, `install`, `uninstall`, `enable`, `disable`),
each with an interactive form (a `questionary.checkbox` picker) and a
non-interactive form (explicit names, `--host`, `--yes`) so CI never blocks.

Two behaviors are load-bearing:

- **No TTY without NAMES exits 2** naming the non-interactive form. `questionary`
  on a non-interactive stdin does not block usefully, and a CI run that hangs on a
  picker is worse than one that fails with instructions.
- **Google warns before writing.** `GoogleAdapter.is_repo_scoped()` is `False`
  because its primary config is user-global; the CLI prints that writing it
  affects every project on the machine (spec §8 Q1 interim default (a)).

`questionary` is already a **core** dependency (`pyproject.toml:165`) and is
**blocking** — it must be called synchronously from the Click callback, never
inside async code. That constraint is documented at `knowledge/wiki/cli.py:4588-4590`
and the working precedent is `:4591-4606`.

---

## Scope

- Create `parrot/cli/toolkits.py` with the six subcommands and the picker.
- Register `"toolkits": "parrot.cli.toolkits"` in the `LazyGroup` command table.
- Write CLI tests via `click.testing.CliRunner` covering both forms, no-TTY, the
  Google warning, and rendering.

**NOT in scope**: removing `--toolkits` from the three host CLIs (TASK-3377/8/9),
`parrot mcp-local`'s error text, docs and examples (TASK-3380).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/toolkits.py` | CREATE | The `toolkits` Click group |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | Register the lazy subcommand |
| `packages/ai-parrot/tests/cli/test_toolkits_cli.py` | CREATE | CliRunner coverage |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import click          # verified: core dependency, packages/ai-parrot/pyproject.toml:135
import questionary    # verified: core dependency, packages/ai-parrot/pyproject.toml:165
from rich.console import Console   # verified: core dependency, pyproject.toml:131
from rich.table import Table

from parrot.mcp.hosts import HostKind, detect_hosts, get_adapter            # TASK-3374
from parrot.mcp.toolkit_install import (                                    # TASK-3375
    ActionReport, ToolkitRow, ToolkitState,
    install_toolkits, inventory, set_toolkits_enabled, uninstall_toolkits,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/__init__.py
class LazyGroup(click.Group):                       # line 15
    def get_command(self, ctx, cmd_name): ...       # imports self._lazy_commands[cmd_name]
        # `attr_name = cmd_name.replace("-", "_")`
        # `return getattr(mod, attr_name, None) or getattr(mod, cmd_name, None)`
        #   -> the module MUST expose a Click object named exactly `toolkits`
cli._lazy_commands = {                              # line 110
    "setup": "parrot.setup.cli",
    ...
    "mcp-local": "parrot.mcp.local_cli",            # the registration pattern to copy
    ...
}
cli._lazy_extras = {...}                            # line 135 — install hints, optional

# packages/ai-parrot/src/parrot/mcp/toolkit_install.py (TASK-3375)
class ToolkitState(str, Enum): NOT_INSTALLED; ENABLED; DISABLED
class ToolkitRow(BaseModel):
    name; summary; class_path; state; requires_llm; requires_dist
    dist_available: bool; drift: list[str]; hosts: list[HostEntryState]
class ActionReport(BaseModel):
    actions: list[str]; warnings: list[str]; failed_hosts: dict[HostKind, str]
def inventory(root: Path, hosts: Sequence[HostKind] | None = None) -> list[ToolkitRow]: ...
def install_toolkits(root, names, hosts) -> ActionReport: ...     # raises ValueError on unknown name
def uninstall_toolkits(root, names, hosts) -> ActionReport: ...
def set_toolkits_enabled(root, names, enabled, hosts) -> ActionReport: ...

# packages/ai-parrot/src/parrot/mcp/hosts.py (TASK-3374)
class HostKind(str, Enum): CLAUDE = "claude"; CODEX = "codex"; GOOGLE = "google"
def detect_hosts(root: Path) -> list[HostKind]: ...
def get_adapter(kind: HostKind) -> HostAdapter: ...   # .is_repo_scoped() / .config_paths(root)

# questionary precedent (blocking, sync, never inside async):
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:4588-4590  (the constraint comment)
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:4591       `import questionary`
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:4602       `questionary.select(...).ask()`
```

### Does NOT Exist
- ~~`parrot.cli.toolkits`~~ — what THIS task creates.
- ~~a `parrot toolkits` entry in `_lazy_commands`~~ — added by this task.
- ~~`questionary.checkbox(...).ask_async()`~~ — do not use; the call site is sync.
- ~~`parrot mcp toolkits`~~ — the `parrot mcp` group is owned by **ai-parrot-server**
  (`parrot.mcp.cli`), so core cannot attach a subcommand to it. This is a
  **top-level** command, exactly like `mcp-local` (precedent: `local_cli.py:1-9`).
- ~~`ToolkitRow.installed`~~ — the field is `state: ToolkitState`.
- ~~`ActionReport.errors`~~ — the field is `failed_hosts: dict[HostKind, str]`.
- ~~`rich.print_table`~~ — use `rich.table.Table` with a `Console`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/cli/toolkits.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/cli/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/cli/test_toolkits_cli.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#LazyGroup",
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#cli",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#inventory",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#install_toolkits",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#uninstall_toolkits",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#set_toolkits_enabled",
    "sym:packages/ai-parrot/src/parrot/mcp/hosts.py#detect_hosts"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The module must expose a Click object named exactly **`toolkits`** — `LazyGroup`
  resolves `getattr(mod, "toolkits")`.
- Heavy imports (`toolkit_install`, `rich`, `questionary`) belong **inside** the
  callbacks, not at module top level, so `parrot --help` stays fast. Precedent:
  `local_cli.py`'s deferred `create_toolkit_mcp_server` import.
- Project root is `Path.cwd()`, matching `mcp-local` (`local_cli.py:104`).
- Exit codes: `2` for a no-TTY interactive invocation, `1` for a `ValueError`
  from the orchestration layer, `0` otherwise (even with `failed_hosts`, which is
  reported as warnings — **unless** every requested host failed).

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/local_cli.py` — a top-level lazy command with
  deferred heavy imports
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:4588-4606` — questionary usage

---

## Implementation Blueprint

### Steps (in order)
1. Write the group and the shared `--host` / `--yes` options — *why*: five of six
   subcommands share them, so defining them once avoids drift.
2. Write `_resolve_names` (the picker) and `_warn_user_global` — *why*: both are
   shared by install/uninstall/enable/disable and hold the two load-bearing
   behaviors (no-TTY exit, Google warning).
3. Write `list` and `status` — *why*: read-only, so they can be tested before any
   mutation path works.
4. Write the four mutating subcommands as thin wrappers — *why*: all logic lives
   in `toolkit_install`; the CLI only resolves arguments and renders.
5. Register in `_lazy_commands` — *why*: without it `parrot toolkits` does not exist.

### `packages/ai-parrot/src/parrot/cli/toolkits.py` (CREATE)
```python
"""`parrot toolkits` — install and manage local MCP toolkit servers (FEAT-570).

Top-level lazy Click group. The `parrot mcp` group is owned by ai-parrot-server,
so core attaches a sibling top-level command instead (precedent: `mcp-local`).

wikitoolkit is deliberately invisible here — it stays owned by `parrot claude install`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import click

host_option = click.option(
    "--host", "hosts_", multiple=True,
    type=click.Choice(["claude", "codex", "google"]),
    help="Target host (repeatable). Default: every detected host.",
)
yes_option = click.option("--yes", is_flag=True, default=False, help="Skip the confirmation prompt.")


@click.group(name="toolkits")
def toolkits() -> None:
    """Install and manage local MCP toolkit servers."""


def _resolve_hosts(root: Path, hosts_: tuple[str, ...]):
    """Explicit `--host` values, else every detected host."""
    from parrot.mcp.hosts import HostKind, detect_hosts

    return [HostKind(h) for h in hosts_] if hosts_ else detect_hosts(root)


def _resolve_names(root: Path, names: tuple[str, ...], hosts) -> list[str]:
    """Return NAMES, or open the checkbox picker when none were given.

    questionary is BLOCKING and is called synchronously here, never inside async
    code (constraint documented at knowledge/wiki/cli.py:4588-4590).

    Exits 2 with the non-interactive form when stdin is not a TTY — a CI run must
    fail with instructions rather than hang on a picker.
    """
    if names:
        return list(names)
    if not sys.stdin.isatty():
        raise click.ClickException(
            "No toolkit names given and stdin is not a TTY. "
            "Use the non-interactive form: parrot toolkits install <name>... [--host ...] --yes"
        )
    import questionary

    from parrot.mcp.toolkit_install import ToolkitState, inventory

    rows = inventory(root, hosts)
    # FILL IN: build questionary.Choice entries — title "<name> — <summary>",
    # `checked=row.state is not ToolkitState.NOT_INSTALLED`, and mark rows whose
    # `dist_available` is False so the operator sees the missing distribution.
    # Return [] when the picker is cancelled (ask() returns None). Bounded by AC2.
    raise NotImplementedError


def _warn_user_global(hosts) -> list[str]:
    """Warn for any host whose primary config is user-global (Google).

    Spec §8 Q1 interim default (a): Antigravity's `~/.gemini/config/mcp_config.json`
    is shared by every project on the machine, so the blast radius is surfaced
    before the write rather than discovered afterwards.
    """
    from parrot.mcp.hosts import get_adapter

    return [
        f"{kind.value}: writes {get_adapter(kind).config_paths(Path.cwd())[0]} — "
        f"USER-GLOBAL, affects every project on this machine"
        for kind in hosts
        if not get_adapter(kind).is_repo_scoped()
    ]


def _render(report) -> None:
    """Print actions, warnings and per-host failures; exit 1 if every host failed."""
    # FILL IN: echo each action with "  ✓ ", each warning with "  ⚠ ", each
    # failed host with "  ✗ <host>: <error>"; raise SystemExit(1) only when
    # `report.failed_hosts` covers every host that was requested. Bounded by AC2.
    raise NotImplementedError


@toolkits.command("list")
@host_option
def list_(hosts_: tuple[str, ...]) -> None:
    """Show every available toolkit with its state, hosts, drift and dependencies."""
    # FILL IN: rich.table.Table with columns Name / State / Summary / Hosts /
    # Deps / Drift; one row per `inventory(...)` entry. Bounded by AC1.
    raise NotImplementedError


@toolkits.command()
@host_option
def status(hosts_: tuple[str, ...]) -> None:
    """Show each host's resolved config paths, scope and health."""
    # FILL IN: per host — kind, every `config_paths(root)` entry, whether each
    # exists, and "repo" vs "USER-GLOBAL" from `is_repo_scoped()`. Bounded by AC2.
    raise NotImplementedError


@toolkits.command()
@click.argument("names", nargs=-1)
@host_option
@yes_option
def install(names: tuple[str, ...], hosts_: tuple[str, ...], yes: bool) -> None:
    """Seed NAMES into .parrot/mcp-toolkits.yaml and register them with each host."""
    from parrot.mcp.toolkit_install import install_toolkits

    root = Path.cwd()
    hosts = _resolve_hosts(root, hosts_)
    selected = _resolve_names(root, names, hosts)
    if not selected:
        click.echo("Nothing selected.")
        return
    for warning in _warn_user_global(hosts):
        click.secho(f"  ⚠ {warning}", fg="yellow")
    if not yes and not click.confirm(f"Install {', '.join(selected)} into {[h.value for h in hosts]}?"):
        return
    try:
        report = install_toolkits(root, selected, hosts)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    _render(report)
    click.echo("  ℹ Start a new session for the MCP servers to appear.")
```
**Why this shape**: `install` is written out in full as the reference; `uninstall`,
`enable` and `disable` mirror it exactly, differing only in the orchestration
function they call and their confirmation text. Every heavy import is inside a
callback so `parrot --help` does not pay for `rich`, `questionary` or the MCP
stack. `_resolve_names` raising `ClickException` (rather than `sys.exit`) keeps
the message consistent with the rest of the CLI. The `ValueError → ClickException`
mapping is what turns TASK-3375's all-or-nothing preflight into a clean exit 1
with the unknown name named.

```python
# FILL IN: `uninstall`, `enable` and `disable` — same argument shape as `install`.
#   uninstall -> uninstall_toolkits(root, selected, hosts); confirmation text must
#     state that CONFIG ONLY is removed (spec §8 Q2: operator data is never deleted)
#   enable    -> set_toolkits_enabled(root, selected, True, hosts)
#   disable   -> set_toolkits_enabled(root, selected, False, hosts)
# Bounded by AC2.
```

### `packages/ai-parrot/src/parrot/cli/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '"mcp-local": "parrot.mcp.local_cli",' packages/ai-parrot/src/parrot/cli/__init__.py)
# AFTER — insert below `    "mcp-local": "parrot.mcp.local_cli",` (verified: cli/__init__.py:118)
    "toolkits": "parrot.cli.toolkits",
```
**Why**: `LazyGroup.get_command` resolves `getattr(mod, "toolkits")`, which is why
the group object in the new module must carry exactly that name. Placing it beside
`mcp-local` keeps the two MCP-facing commands together.

### `packages/ai-parrot/tests/cli/test_toolkits_cli.py` (CREATE)
```python
"""`parrot toolkits` CLI (FEAT-570, TASK-3376)."""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from parrot.cli import cli


def test_toolkits_is_registered():
    result = CliRunner().invoke(cli, ["toolkits", "--help"])
    assert result.exit_code == 0
    for sub in ("list", "status", "install", "uninstall", "enable", "disable"):
        assert sub in result.output


def test_list_on_empty_repo(tmp_path):
    with CliRunner().isolated_filesystem(temp_dir=tmp_path):
        result = CliRunner().invoke(cli, ["toolkits", "list"])
        assert result.exit_code == 0
        assert "querysource" in result.output
        assert "wikitoolkit" not in result.output


def test_install_without_names_no_tty_exits_nonzero(tmp_path, monkeypatch):
    """AC2 — CI must fail with instructions, never hang on a picker."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with CliRunner().isolated_filesystem(temp_dir=tmp_path):
        result = CliRunner().invoke(cli, ["toolkits", "install"])
        assert result.exit_code != 0
        assert "non-interactive" in result.output.lower()


def test_install_unknown_name_reports_cleanly(tmp_path):
    # FILL IN: assert exit 1 and that the unknown name appears in the output;
    # bounded by AC2, AC8.


def test_google_host_warns_user_global(tmp_path):
    # FILL IN: invoke `install memory --host google --yes` and assert the output
    # names the user-global path and "every project"; bounded by spec §8 Q1.
```
**Why**: `test_list_on_empty_repo` asserts both halves of the contract at once —
templates are listed even with nothing installed, and wikitoolkit never leaks in.
The no-TTY case is the one that protects CI from a hang, so it asserts on the
message, not just the exit code.

### FILL IN checklist
- [ ] `toolkits.py::_resolve_names` — picker construction, pre-checked installed rows, cancel → `[]`; bounded by AC2
- [ ] `toolkits.py::_render` — actions/warnings/failures, exit 1 only if all hosts failed; bounded by AC2
- [ ] `toolkits.py::list_` — rich table; bounded by AC1
- [ ] `toolkits.py::status` — per-host paths, existence and scope; bounded by AC2
- [ ] `toolkits.py` — `uninstall`, `enable`, `disable` mirroring `install`; bounded by AC2, §8 Q2
- [ ] `test_toolkits_cli.py` — the two FILL IN cases; bounded by AC2, AC8

---

## Acceptance Criteria

- [ ] `parrot toolkits --help` lists all six subcommands
- [ ] `parrot toolkits list` renders every packaged template and never `wikitoolkit`
- [ ] `parrot toolkits install` with no NAMES and no TTY exits non-zero naming the
      non-interactive form
- [ ] `--host` accepts `claude`, `codex`, `google` and is repeatable; omitting it
      targets every detected host
- [ ] Installing into `google` prints a user-global blast-radius warning
- [ ] An unknown name exits 1 with the name in the message and writes nothing
- [ ] `parrot --help` does not import `rich`, `questionary` or `toolkit_install`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/cli/toolkits.py`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/cli/test_toolkits_cli.py -q`

---

## Test Specification

See the CREATE block above. Add a case asserting `parrot toolkits status` on a
repo with only `.mcp.json` reports Claude as present and the other two as absent.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 7, §7 Patterns, §8 Q1 and Q2).
2. **Check dependencies** — TASK-3375 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm `_lazy_commands` is still at
   `cli/__init__.py:110` and that `questionary` is still a core dependency.
4. **Update status** in `sdd/tasks/index/expose-local-mcp-tools.json` → `"in-progress"`.
5. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3376-toolkits-cli-group.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
