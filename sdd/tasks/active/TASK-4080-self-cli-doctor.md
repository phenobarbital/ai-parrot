# TASK-4080: parrot self: CLI group (add/update/doctor/env/uninstall) + doctor checks + lazy registration

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4079
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (CLI + doctor half). TASK-4079 built the engine
(`parrot.self_.components`). This task exposes it as the lazy `parrot self` Click group —
`add | update | doctor | env | uninstall` — and implements `parrot self doctor`'s fixed
check list (spec §3 M3 skeleton, §7 "Gemini config is user-global … `self doctor` flags
baked-path collisions there"). `parrot status` is TAKEN by agentd (cli/__init__.py:134),
so every diagnostic lives under `self`.

---

## Scope

- Create `parrot/self_/cli.py`: `@click.group(name="self")` `self_group` with
  `add(component, --here)`, `update(--version)`, `doctor()`, `env()`, `uninstall(--yes)`;
  expose it under the module attribute `self` (LazyGroup's lookup convention, below).
- Create `parrot/self_/doctor.py`: `DoctorCheck` model (name, ok, detail, fix),
  `run_doctor(root: Path) -> list[DoctorCheck]`, `installed_version(venv) -> str | None`.
- Register `"self": "parrot.self_.cli"` in `cli._lazy_commands`.
- `env` prints: resolved venv + the rule that picked it (`resolve_venv`), the ai-parrot
  version inside that venv, and the managed venv's ai-parrot version.
- Doctor checks (spec §3 M3): pinned uv present + version; managed venv Python is 3.12;
  PATH contains `~/.parrot/bin`; host configs whose command paths don't exist (Claude
  `<root>/.mcp.json`, Codex `<root>/.codex/config.toml`, Google user-global
  `~/.gemini/config/mcp_config.json`) incl. the Gemini cross-repo baked-path collision;
  installed toolkits with unmet `requires_dist` / `requires_env`.
- Tests for the CLI and doctor.

**NOT in scope**: the engine (TASK-4079); fixing anything doctor reports (it only
reports + suggests a `fix`); `parrot sdd` registration (TASK-4091 adds `"sdd"` to the same
dict later — leave room, touch only the `self` line); touching `parrot status`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/self_/cli.py` | CREATE | `parrot self` Click group |
| `packages/ai-parrot/src/parrot/self_/doctor.py` | CREATE | `DoctorCheck`, `run_doctor`, `installed_version` |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | Lazy `"self"` entry |
| `packages/ai-parrot/tests/self_/test_self_cli.py` | CREATE | CLI tests (registration, env, add/uninstall wiring) |
| `packages/ai-parrot/tests/self_/test_doctor.py` | CREATE | Doctor check tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.cli import cli  # verified: packages/ai-parrot/src/parrot/cli/__init__.py:103-104
from parrot.mcp.toolkit_seed import available_templates  # verified: packages/ai-parrot/src/parrot/mcp/toolkit_seed.py:49
from parrot.mcp.toolkit_install import ToolkitState, inventory  # verified: packages/ai-parrot/src/parrot/mcp/toolkit_install.py:32,94
from parrot.knowledge.wiki.google.assets import default_mcp_config_path  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py:61
import tomllib  # stdlib (requires-python >=3.11, packages/ai-parrot/pyproject.toml:18)
# Created by dependency tasks:
from parrot.launcher import MANAGED_PYTHON, find_project_root, parrot_home, resolve_venv, script_path  # TASK-4071
from parrot.self_.components import install_component, managed_venv, uninstall_runtime, update_runtime  # TASK-4079
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/__init__.py
class LazyGroup(click.Group):                                  # line 19
    def get_command(self, ctx, cmd_name):                      # line 71
        mod = importlib.import_module(module_path)             # line 85
        attr_name = cmd_name.replace("-", "_")                 # line 99
        return getattr(mod, attr_name, None) or getattr(mod, cmd_name, None)  # line 100
#   ⇒ for "self" the module MUST expose a global named `self` (the group object).
cli._lazy_commands = {                                         # line 109
    "toolkits": "parrot.cli.toolkits",                         # line 117
    "status": "parrot.integrations.agentd.cli",                # line 134 — TAKEN, never reuse
}

# packages/ai-parrot/src/parrot/mcp/toolkit_install.py
def inventory(root: Path, hosts: Sequence[HostKind] | None = None) -> list[ToolkitRow]:  # line 94
#   NOTE: hosts=[] is falsy → _resolve_hosts falls back to detect_hosts(root) (line 76-78)
class ToolkitRow(BaseModel):  # line 38: name, state, requires_dist, dist_available (line 46-47)
#   TASK-4078 adds requires_pip / post_install / requires_env
class ToolkitState(str, Enum): NOT_INSTALLED / ENABLED / DISABLED  # line 32-35

# packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py
def default_mcp_config_path() -> Path:  # line 61 → ~/.gemini/config/mcp_config.json (USER-GLOBAL)
def wikitoolkit_mcp_entry(root) -> {"command": ..., "args": ["mcp"], "cwd": str(root.resolve())}  # line 74-80
#   ⇒ a user-global "wikitoolkit" entry whose `cwd` != current root is baked for another repo

# packages/ai-parrot/src/parrot/mcp/hosts.py
class ClaudeAdapter.config_paths(root) -> (root / ".mcp.json",)                 # line 63-64
class CodexAdapter.config_paths(root) -> (root / ".codex" / "config.toml",)     # line 125-126
class GoogleAdapter.config_paths(root) -> toolkit_config_paths(root, ...)       # line 185-188

# packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py
MCP_TABLE = "mcp_servers.wikitoolkit"   # line 19; toolkit tables `[mcp_servers.parrot-<name>]` line 84
```
- Claude `.mcp.json` shape: `{"mcpServers": {name: {"command": str, "args": [...]}}}`.
- uv-created `pyvenv.cfg` carries `version_info = 3.12.x` (verified: repo `.venv/pyvenv.cfg`).
- Pinned uv version for the bootstrap: `0.11.28` (shared brief; same value the M2 install scripts pin).

### Does NOT Exist
- ~~`parrot self`, `parrot env`, `parrot doctor` commands~~ — `"self"` is added here; never add top-level `env`/`doctor`.
- ~~reusing `parrot status`~~ — agentd owns it (cli/__init__.py:134).
- ~~`parrot.self_.cli` / `parrot.self_.doctor`~~ — created here.
- ~~a shared host-config parser in core~~ — doctor reads the three files directly (json / tomllib).
- ~~`parrot sdd` in `_lazy_commands`~~ — TASK-4091's line, not this task's.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/self_/cli.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/self_/doctor.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/cli/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/self_/test_self_cli.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/self_/test_doctor.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#LazyGroup",
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#LazyGroup.get_command",
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#cli",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#available_templates",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#inventory",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#ToolkitState",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py#default_mcp_config_path",
    "sym:packages/ai-parrot/src/parrot/mcp/hosts.py#ClaudeAdapter.config_paths",
    "sym:packages/ai-parrot/src/parrot/mcp/hosts.py#CodexAdapter.config_paths"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# packages/ai-parrot/src/parrot/cli/toolkits.py:26-28 — a lazily-registered top-level group
@click.group(name="toolkits")
def toolkits() -> None:
    """Install and manage local MCP toolkit servers."""
```

### Key Constraints
- Keep `parrot/self_/cli.py` import-cheap: import `click` at top; import `components`,
  `doctor`, `inventory`, host modules **inside** each command (precedent: cli/toolkits.py
  lazy imports at lines 57, 111, 166).
- `DoctorCheck` is a Pydantic v2 model (codebase convention "Data structures are Pydantic
  v2 models"; the brief's "dataclass" shape — fields name/ok/detail/fix — is kept).
- Doctor never mutates anything and never raises for a broken config file — an
  unreadable/unparsable config is itself a failed check.
- `requires_env`: navconfig can also supply values from `env/.env`, which `os.environ`
  does not show — the failed check's `detail` must say so.
- CLI output via `click.echo` / `click.secho` only.
- Python version check reads `pyvenv.cfg` (no subprocess); version reporting of ai-parrot
  inside a venv uses `subprocess.run([python, "-c", ...], capture_output=True, text=True)`
  — synchronous is correct in a one-shot CLI (no event loop).

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/toolkits.py` — CLI style, lazy imports
- `packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py:61-121` — Google entry shapes

---

## Implementation Blueprint

### Steps (in order)
1. Create `doctor.py` (`DoctorCheck`, `installed_version`, one private `_check_*` per spec check, `run_doctor`) — *why*: the CLI and tests both consume it.
2. Create `cli.py` with the group, five subcommands and `self = self_group` — *why*: LazyGroup resolves `getattr(mod, "self")` (cli/__init__.py:99-100).
3. Register `"self"` in `_lazy_commands` — *why*: spec §3 M3 / §6 Edit Sites.
4. Write tests — *why*: spec §4 `test_self_env_rule_report`, `test_doctor_flags_broken_host_config`.

### `packages/ai-parrot/src/parrot/self_/doctor.py` (CREATE)
```python
"""`parrot self doctor` checks (FEAT-633, spec §3 M3). Read-only diagnostics."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from parrot.launcher import MANAGED_PYTHON, parrot_home, script_path  # TASK-4071
from parrot.self_.components import managed_venv  # TASK-4079

logger = logging.getLogger(__name__)

#: Kept in sync with the pin in scripts/install/install-parrot.{sh,ps1} (--global mode).
PINNED_UV_VERSION: str = "0.11.28"


class DoctorCheck(BaseModel):
    """One diagnostic result."""

    name: str
    ok: bool
    detail: str = ""
    fix: str = ""


def installed_version(venv: Path) -> str | None:
    """ai-parrot version installed in ``venv`` (None when absent or not queryable)."""
    python = script_path(venv, "python")
    if not python.exists():
        return None
    code = "import importlib.metadata as m; print(m.version('ai-parrot'))"
    result = subprocess.run([str(python), "-c", code], capture_output=True, text=True, check=False)
    return (result.stdout.strip() or None) if result.returncode == 0 else None


def _check_uv() -> DoctorCheck:
    """Pinned uv present under ~/.parrot/bin and at PINNED_UV_VERSION."""
    bundled = parrot_home() / "bin" / ("uv.exe" if os.name == "nt" else "uv")
    # FILL IN: missing → ok=False, fix "re-run install-parrot --global"; present → `[bundled, "--version"]`
    # (capture_output) and compare the second token with PINNED_UV_VERSION — bounded by spec §3 M3 check 1
    raise NotImplementedError


def _check_python() -> DoctorCheck:
    """Managed venv's pyvenv.cfg ``version_info`` starts with MANAGED_PYTHON + '.'."""
    # FILL IN: parse managed_venv()/'pyvenv.cfg' (key = value lines); missing file → ok=False — bounded by spec §3 M3 check 2
    raise NotImplementedError


def _check_path() -> DoctorCheck:
    """PATH contains ~/.parrot/bin (resolved comparison, os.pathsep split)."""
    # FILL IN: fix text differs per OS (POSIX profile line vs Windows user PATH) — bounded by spec §5 PATH bullets
    raise NotImplementedError


def _command_problem(entry: Any, root: Path) -> str | None:
    """Return why one MCP entry's command is broken, else None.

    Absolute command → must exist; bare command → must resolve via ``shutil.which``.
    """
    # FILL IN: non-dict / missing "command" → None (not ours to judge) — bounded by "doctor never fails on foreign shapes"
    raise NotImplementedError


def _check_host_configs(root: Path) -> list[DoctorCheck]:
    """Claude .mcp.json, Codex .codex/config.toml, Google user-global mcp_config.json.

    Google also flags the cross-repo collision: a ``wikitoolkit`` / ``parrot-*`` entry whose
    ``cwd`` (or absolute ``--config`` arg) belongs to another root — fix: re-install with
    ``--portable`` (spec §7).
    """
    from parrot.knowledge.wiki.google.assets import default_mcp_config_path  # verified: google/assets.py:61

    claude = root / ".mcp.json"
    codex = root / ".codex" / "config.toml"
    google = default_mcp_config_path()
    # FILL IN: absent file → skip (no check); unparsable → ok=False; json servers under "mcpServers",
    # toml under data["mcp_servers"]; one DoctorCheck per file listing broken entries — bounded by spec §3 M3 check 4
    raise NotImplementedError


def _check_toolkits(root: Path) -> list[DoctorCheck]:
    """Installed toolkits (state != NOT_INSTALLED) with unmet requires_dist / requires_env."""
    from parrot.mcp.toolkit_install import ToolkitState, inventory  # verified: toolkit_install.py:32,94

    checks: list[DoctorCheck] = []
    for row in inventory(root):
        if row.state is ToolkitState.NOT_INSTALLED:
            continue
        # FILL IN: unmet dist → ok=False, fix f"parrot self add {row.name}"; missing env (row.requires_env,
        # TASK-4078 field) → ok=False, detail notes navconfig env/.env may still supply it — bounded by spec §3 M3 check 5
        raise NotImplementedError
    return checks


def run_doctor(root: Path) -> list[DoctorCheck]:
    """Run every check, in spec order; never raises for a broken environment."""
    checks = [_check_uv(), _check_python(), _check_path()]
    checks.extend(_check_host_configs(root))
    checks.extend(_check_toolkits(root))
    return checks
```
**Why this shape**: one function per spec check keeps each independently testable;
`run_doctor`'s signature is fixed by the spec skeleton. `_check_uv` inspects the bundled path
directly — never `bundled_uv()`, whose PATH fallback would mask a missing pinned uv.

### `packages/ai-parrot/src/parrot/self_/cli.py` (CREATE)
```python
"""`parrot self` — manage the parrot-managed runtime (~/.parrot) (FEAT-633, spec §3 M3).

Registered lazily as ``"self"`` in ``parrot.cli._lazy_commands``; LazyGroup resolves the
module attribute named ``self`` (cli/__init__.py:99-100), aliased at the bottom.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click


@click.group(name="self")
def self_group() -> None:
    """Manage the parrot-managed runtime (~/.parrot)."""


def _echo_log(log: list[str]) -> None:
    for line in log:
        click.echo(f"  {line}")


@self_group.command()
@click.argument("component")
@click.option("--here", is_flag=True, default=False, help="Install into the project venv instead of ~/.parrot/venv.")
def add(component: str, here: bool) -> None:
    """Install COMPONENT's packages (+ post-install step) into the managed venv."""
    from parrot.mcp.toolkit_seed import available_templates
    from parrot.self_.components import install_component, managed_venv

    try:
        _echo_log(install_component(component, venv=managed_venv(), here=here))
    except KeyError as exc:
        raise click.ClickException(f"unknown component {component!r}; available: {', '.join(available_templates())}") from exc
    except (FileNotFoundError, ValueError, subprocess.CalledProcessError) as exc:
        raise click.ClickException(str(exc)) from exc


@self_group.command()
@click.option("--version", "version", default=None, help="Exact ai-parrot version (default: latest).")
def update(version: str | None) -> None:
    """Upgrade ai-parrot in the managed venv."""
    # FILL IN: call update_runtime(version); map FileNotFoundError/CalledProcessError → ClickException — bounded by add's mapping
    raise NotImplementedError


@self_group.command()
def doctor() -> None:
    """Diagnose uv, Python, PATH, host configs and toolkit requirements."""
    from parrot.launcher import find_project_root  # TASK-4071
    from parrot.self_.doctor import run_doctor

    root = find_project_root(sys.argv[1:], os.environ, Path.cwd()) or Path.cwd()
    checks = run_doctor(root)
    for check in checks:
        mark, colour = ("✓", "green") if check.ok else ("✗", "red")
        click.secho(f"  {mark} {check.name}: {check.detail}", fg=colour)
        if not check.ok and check.fix:
            click.echo(f"      fix: {check.fix}")
    # FILL IN: exit code — decided: SystemExit(1) iff any check failed (CI-usable); keep unless spec says otherwise
    raise NotImplementedError


@self_group.command()
def env() -> None:
    """Print the venv the launcher resolves, the rule that picked it, and versions."""
    from parrot.launcher import resolve_venv  # TASK-4071
    from parrot.self_.components import managed_venv
    from parrot.self_.doctor import installed_version

    venv, rule = resolve_venv("parrot", argv=sys.argv[1:], env=os.environ, cwd=Path.cwd())
    click.echo(f"venv: {venv}")
    click.echo(f"rule: {rule}")
    click.echo(f"ai-parrot (resolved): {installed_version(venv) or 'not installed'}")
    click.echo(f"ai-parrot (managed):  {installed_version(managed_venv()) or 'not installed'}")


@self_group.command()
@click.option("--yes", is_flag=True, default=False, help="Skip the confirmation prompt.")
def uninstall(yes: bool) -> None:
    """Remove ~/.parrot/{bin,venv,python}; wikis, library, skills, brains and parrot.db are kept."""
    from parrot.self_.components import uninstall_runtime

    if not yes and not click.confirm("Remove the managed runtime (user data is kept)?"):
        return
    _echo_log(uninstall_runtime(yes=True))


#: LazyGroup lookup name (cli/__init__.py:99-100: getattr(mod, "self")).
self = self_group
```

### `packages/ai-parrot/src/parrot/cli/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "toolkits": "parrot.cli.toolkits",' packages/ai-parrot/src/parrot/cli/__init__.py)
# AFTER — insert below `    "toolkits": "parrot.cli.toolkits",` (verified: cli/__init__.py:117), inside
# `cli._lazy_commands = {` (verified: cli/__init__.py:109; grep -c = 1). TASK-4091 adds "sdd" separately.
    # FEAT-633 — managed-runtime lifecycle (`parrot status` is agentd's; diagnostics live here).
    "self": "parrot.self_.cli",
```

### `packages/ai-parrot/tests/self_/test_self_cli.py` (CREATE)
```python
"""`parrot self` CLI (FEAT-633, TASK-4080)."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from parrot.cli import cli


def test_self_is_registered() -> None:
    result = CliRunner().invoke(cli, ["self", "--help"])
    assert result.exit_code == 0, result.output
    for sub in ("add", "update", "doctor", "env", "uninstall"):
        assert sub in result.output


def test_self_env_rule_report(tmp_path: Path, monkeypatch) -> None:
    """Spec §4 — `self env` prints the resolved venv and the rule."""
    monkeypatch.setattr("parrot.launcher.resolve_venv", lambda *a, **k: (tmp_path / "venv", "VIRTUAL_ENV"))
    with mock.patch("parrot.self_.doctor.installed_version", return_value="1.2.3"):
        result = CliRunner().invoke(cli, ["self", "env"])
    assert result.exit_code == 0, result.output
    assert str(tmp_path / "venv") in result.output and "VIRTUAL_ENV" in result.output and "1.2.3" in result.output


def test_add_unknown_component_lists_available() -> None:
    # FILL IN: invoke ["self", "add", "nope"]; exit_code 1, "available" in output — bounded by add's KeyError mapping
    raise NotImplementedError


def test_add_passes_here_flag() -> None:
    # FILL IN: patch parrot.self_.components.install_component; invoke ["self","add","scraping","--here"];
    # assert called with here=True — bounded by spec §5 `--here`
    raise NotImplementedError


def test_uninstall_without_yes_prompts_and_aborts() -> None:
    # FILL IN: input="n\n"; uninstall_runtime not called — bounded by spec §7 data safety
    raise NotImplementedError
```

### `packages/ai-parrot/tests/self_/test_doctor.py` (CREATE)
```python
"""`parrot self doctor` checks (FEAT-633, TASK-4080)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.self_ import doctor


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """PARROT_HOME + fake HOME so the Google user-global config is a tmp file."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "parrot-home"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def test_doctor_flags_broken_host_config(isolated_home: Path, tmp_path: Path) -> None:
    """Spec §4 — a config pointing at a missing binary is reported."""
    repo = tmp_path / "repo"
    repo.mkdir()
    missing = tmp_path / "gone" / "wikitoolkit"
    (repo / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"wikitoolkit": {"command": str(missing), "args": ["mcp"]}}}), encoding="utf-8"
    )
    checks = doctor._check_host_configs(repo)
    assert any(not c.ok and str(missing) in c.detail for c in checks)


def test_gemini_cross_repo_collision(isolated_home: Path, tmp_path: Path) -> None:
    # FILL IN: ~/.gemini/config/mcp_config.json with wikitoolkit cwd=<other repo>; assert a failed check whose
    # fix mentions --portable — bounded by spec §7 Gemini bullet
    raise NotImplementedError


def test_python_check_reads_pyvenv_cfg(isolated_home: Path) -> None:
    # FILL IN: write parrot-home/venv/pyvenv.cfg with version_info = 3.11.9 → ok False; 3.12.3 → ok True — bounded by MANAGED_PYTHON
    raise NotImplementedError


def test_path_check(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: PATH with/without parrot-home/bin — bounded by spec §3 M3 check 3
    raise NotImplementedError


def test_toolkit_missing_env_and_dist(isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: seed querysource via parrot.mcp.toolkit_seed.seed_toolkit_sections(repo, ["querysource"]),
    # delenv PG_USER/PG_PWD, patch parrot.mcp.toolkit_install.dist_available → False; expect two failed
    # checks, fix "parrot self add querysource" — bounded by spec §3 M3 check 5
    raise NotImplementedError


def test_run_doctor_never_raises_on_empty_home(isolated_home: Path, tmp_path: Path) -> None:
    checks = doctor.run_doctor(tmp_path)
    assert all(isinstance(c, doctor.DoctorCheck) for c in checks)
```

### FILL IN checklist
- [ ] `doctor.py::_check_uv` — presence + version compare; bounded by spec §3 M3 check 1
- [ ] `doctor.py::_check_python` — pyvenv.cfg parse; bounded by MANAGED_PYTHON (3.12)
- [ ] `doctor.py::_check_path` — OS-specific fix text; bounded by spec §5 PATH bullets
- [ ] `doctor.py::_command_problem` / `_check_host_configs` — per-file checks + Gemini collision; bounded by spec §3 M3 check 4, §7
- [ ] `doctor.py::_check_toolkits` — dist/env checks; bounded by spec §3 M3 check 5
- [ ] `cli.py::update` / `cli.py::doctor` exit code — bounded by add's error mapping / "exit 1 iff any failed"
- [ ] tests marked FILL IN in both test files

---

## Acceptance Criteria

- [ ] `parrot self --help` lists `add`, `update`, `doctor`, `env`, `uninstall`; `parrot status` is untouched.
- [ ] `parrot self env` prints the resolved venv, the rule (`PARROT_VENV|project|VIRTUAL_ENV|managed`), and both ai-parrot versions (spec §4 `test_self_env_rule_report`).
- [ ] `parrot self doctor` reports every spec §3 M3 check; a host config pointing at a missing binary is flagged (spec §4 `test_doctor_flags_broken_host_config`); the Gemini cross-repo collision is flagged with a `--portable` fix (spec §7).
- [ ] `parrot self add <c> [--here]` delegates to `install_component`; unknown names list available templates; errors exit 1 via `ClickException`.
- [ ] `parrot self uninstall` confirms unless `--yes` and never touches user data (delegates to TASK-4079).
- [ ] `ruff check packages/ai-parrot/src/parrot/self_/ packages/ai-parrot/src/parrot/cli/__init__.py` clean.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/self_/test_self_cli.py -q`
- `pytest packages/ai-parrot/tests/self_/test_doctor.py -q`
- `pytest packages/ai-parrot/tests/cli/test_toolkits_cli.py -q`

---

## Test Specification

See the CREATE blocks for `test_self_cli.py` (registration, `test_self_env_rule_report`,
add/uninstall wiring) and `test_doctor.py` (`test_doctor_flags_broken_host_config`,
Gemini collision, Python/PATH/toolkit checks, never-raises).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/parrot-installer.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/parrot-installer.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4080 parrot-installer verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
