# TASK-4091: parrot sdd install|uninstall|status + lazy registration

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4070, TASK-4080, TASK-4090
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview piece 4 and §3 Module 6: the SDD flow becomes installable into any repository
with `parrot sdd install [--host claude|codex|google]`, deploying the packaged assets that
TASK-4090 placed under `parrot/sdd/_assets/` (listed in `_assets/manifest.json`). The installer
follows the wiki installers' discipline — never clobber foreign content, warn-and-skip on
collisions, re-runnable, uninstall removes exactly what it installed — and, per codex S9,
**reports clearly** when an installed asset references tooling unavailable on the target
machine, using the spike-S5 scanner `parrot.sdd.audit` (TASK-4070).

The command registers lazily in `parrot/cli/__init__.py::cli._lazy_commands` (spec §6 Edit
Sites, `cli/__init__.py:109`), serialized after TASK-4080 which adds `"self"` to the same dict.

---

## Scope

- Implement `parrot/sdd/installer.py`: `install_sdd_integration`, `uninstall_sdd_integration`,
  `sdd_status` with the FEAT-633 conflict rule (absent → write; byte-identical → skip;
  differs → skip + warning unless `force`; uninstall removes byte-identical files only).
- Add a managed `.gitignore` marker block ignoring `.claude/worktrees/` (own copy of the
  marker helpers — do NOT import the claude installer).
- Seed `sdd/tasks/.id_ledger.json` when absent (decided below — `reserve_ids` cannot run without it).
- After install, scan the installed files with `parrot.sdd.audit.scan_paths` +
  `missing_tools` and report unavailable tooling as warnings (codex S9).
- Implement `parrot/sdd/cli.py`: click group `sdd` with `install` / `uninstall` / `status`.
- Register `"sdd": "parrot.sdd.cli"` in `cli._lazy_commands`.
- Write `packages/ai-parrot/tests/sdd/test_installer.py` (incl. spec §4
  `test_sdd_install_into_empty_repo` and integration `test_sdd_flow_in_foreign_repo`) and
  `packages/ai-parrot/tests/sdd/test_sdd_cli.py`.

**NOT in scope**:
- Producing / syncing `_assets/` or `manifest.json` (TASK-4090).
- Moving helpers / rewriting markdown (TASK-4085..4089).
- `parrot/sdd/__init__.py`, `parrot/sdd/audit.py`, `packages/ai-parrot/tests/sdd/__init__.py` (TASK-4070).
- Registering the `sdd-worker-format.sh` hook in the target's `.claude/settings.json` — v1 copies
  the script only and prints a one-line wiring note (JSON-merge of settings is not a spec'd target).
- Committing anything in the target repo (the installer never runs `git add/commit/push`).
- A hash manifest / install receipt (spec non-goal: "no manifest/symlink machinery").

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/installer.py` | CREATE | install / uninstall / status over `_assets/manifest.json`; gitignore block; ledger seed; S9 audit |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | CREATE | click group `sdd`: `install` / `uninstall` / `status` |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | `"sdd": "parrot.sdd.cli"` in `cli._lazy_commands` |
| `packages/ai-parrot/tests/sdd/test_installer.py` | CREATE | Installer unit tests + `test_sdd_flow_in_foreign_repo` integration |
| `packages/ai-parrot/tests/sdd/test_sdd_cli.py` | CREATE | CliRunner tests for the group and lazy registration |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
import click                                   # core dependency: packages/ai-parrot/pyproject.toml:139 ("click>=8.1.7")
from importlib import resources                # stdlib; precedent: tests/flows/dev_loop/test_subagent_parity.py:15
from importlib.resources.abc import Traversable   # stdlib (Python >= 3.11; core requires-python >=3.11)
from parrot.cli import cli                     # packages/ai-parrot/src/parrot/cli/__init__.py:104 (LazyGroup instance)
# Created by dependency tasks (do NOT exist on dev yet — verify exact names before use):
from parrot.sdd.audit import AssumptionFinding, missing_tools, scan_paths   # TASK-4070
from parrot.sdd.scripts.id_ledger import LEDGER_PATH, bootstrap_ledger, save_ledger  # TASK-4085 (moved from
                                               # scripts/sdd/id_ledger.py:28,145,69 — same names)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/__init__.py
class LazyGroup(click.Group):                                 # line 19
    def get_command(self, ctx, cmd_name):                     # line 71 — imports _lazy_commands[cmd_name]
        attr_name = cmd_name.replace("-", "_")                # line 99
        return getattr(mod, attr_name, None) or getattr(mod, cmd_name, None)  # line 100
#   => parrot/sdd/cli.py MUST expose a module attribute named `sdd` (the click group)
@click.group(cls=LazyGroup)
def cli(): ...                                                # line 104
cli._lazy_commands = {                                        # line 109 (24 entries; TASK-4080 adds "self")
    "devloop": "parrot.cli.devloop",                          # line 125 — insertion anchor, grep -c == 1

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py — PATTERN ONLY (copy, never import)
def _upsert_marker_block(text: str, block: str, begin: str, end: str) -> str:   # line 50
def _remove_marker_block(text: str, begin: str, end: str) -> str:               # line 71
def _install_gitignore(root: Path) -> str:                                      # line 943 (non-marker variant)

# scripts/sdd/id_ledger.py (moves verbatim to parrot.sdd.scripts.id_ledger in TASK-4085)
LEDGER_PATH = Path("sdd/tasks/.id_ledger.json")                                 # line 28
def save_ledger(path: Path, ledger: IdLedger) -> None:                          # line 69 — does NOT mkdir parents
def bootstrap_ledger(index_dir: Path = Path("sdd/tasks/index"),
                     specs_dir: Path = Path("sdd/specs")) -> IdLedger:          # line 145 — missing dirs → ids start at 1
# scripts/sdd/reserve_ids.py
def _read_ledger_at(root: Path, base_sha: str) -> IdLedger:                     # line 259 — reads the ledger via
#   `git show <base_sha>:sdd/tasks/.id_ledger.json` and raises IdReservationError (line 54) when absent
#   => the ledger MUST exist AND be committed+pushed on the base branch before any reservation.

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py
path_option = click.option("--path", "path_", default=None, help="Repo root (default: auto-detect).")  # line 33 (style precedent)
```

### Does NOT Exist
- ~~`parrot.sdd.installer`, `parrot.sdd.cli`, a `sdd` entry in `_lazy_commands`~~ — new here.
- ~~`parrot sdd` / `parrot env` / `parrot doctor`~~ — and **`parrot status` is TAKEN** (agentd); the
  status verb lives under the group: `parrot sdd status`.
- ~~an `sdd` console script, `packages/ai-parrot-sdd/`, `parrot_sdd`~~ — rejected design (spec §6).
- ~~a public marker helper to import~~ — `_upsert_marker_block` is private to the claude installer;
  copy it (spec §6 Integration Points: "same discipline (own copy)").
- ~~ledger auto-creation inside `reserve_ids`~~ — it raises; seeding is the installer's job.
- ~~exec-bit preservation from wheel package data~~ — not guaranteed; chmod `.sh` targets on install.

---

## Complexity Contract

> **MANDATORY.** Declares the measurable targets and contract symbols used for
> deterministic complexity routing (FEAT-561) before any coder is dispatched.
> This is a declaration, not a hand-authored score — the evaluator computes
> classification from measured evidence, never from this section's prose.

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/installer.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/cli.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/cli/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_installer.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/sdd/test_sdd_cli.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#LazyGroup",
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#LazyGroup.get_command",
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#cli",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_upsert_marker_block",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_remove_marker_block",
    "sym:scripts/sdd/id_ledger.py#save_ledger",
    "sym:scripts/sdd/id_ledger.py#bootstrap_ledger",
    "sym:scripts/sdd/reserve_ids.py#_read_ledger_at"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`knowledge/wiki/claude_code/installer.py` — each step returns a human-readable action string;
the public function returns the list; `uninstall` is the exact inverse; marker blocks key on the
BEGIN marker.

### Key Constraints
- **Spec signature delta (from the FEAT-633 brief, supersedes spec §3 M6 skeleton)**:
  `install_sdd_integration(root, hosts=("claude",), *, force=False)` and
  `uninstall_sdd_integration(root, hosts=("claude",))`.
- An asset belongs to the install iff `set(entry["hosts"]) & set(hosts)`; shared assets
  (templates, `sdd/WORKFLOW.md`) therefore install for any host. On uninstall, a shared asset is
  removed only if **no remaining installed host** still needs it — v1 has no receipt, so
  "remaining" = hosts NOT passed to uninstall whose host-specific assets are still present
  byte-identical (FILL IN bounded by this rule).
- Read assets via `importlib.resources.files("parrot.sdd") / "_assets"` — never a repo path
  (installed runtime must not depend on a monorepo checkout, codex S8).
- `force=True` overwrites a differing file; it never touches a file that is not a manifest target.
- Uninstall never removes a modified file, never removes `sdd/tasks/.id_ledger.json` (state, not
  an asset), and prunes only directories it leaves empty.
- Hosts are validated against `SUPPORTED_HOSTS`; unknown → `ValueError` (CLI: `click.Choice`).
- Library code logs via `logger = logging.getLogger(__name__)`; only `cli.py` writes output (`click.echo`).

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py:50-90` — marker helpers to copy.
- `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py:33-53,180-200` — CLI shape (`--path`, `✓` action lines).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Confirm `parrot.sdd.audit`, `parrot.sdd.scripts.id_ledger` and
   `resources.files("parrot.sdd") / "_assets" / "manifest.json"` exist — *why*: all three come from dependency tasks.
2. Write `installer.py` (manifest loader → per-asset decision → gitignore → ledger → audit) — *why*: the CLI is a thin shell over it.
3. Write `cli.py` exposing the group as attribute `sdd` — *why*: `LazyGroup.get_command` resolves `getattr(mod, "sdd")` (cli/__init__.py:99-100).
4. Add the `_lazy_commands` entry — *why*: lazy import keeps `parrot --help` cheap.
5. Write both test files; run the Validation Commands.

### `packages/ai-parrot/src/parrot/sdd/installer.py` (CREATE)
```python
"""Deploy the packaged SDD flow (``parrot/sdd/_assets/``) into a repository (FEAT-633 M6).

Conflict rule (no hash manifest — spec non-goal): absent → write; byte-identical → skip;
differs → skip with a warning unless ``force``. ``uninstall`` removes byte-identical files only.
"""

from __future__ import annotations

import json
import logging
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Sequence

from parrot.sdd.audit import missing_tools, scan_paths  # TASK-4070

logger = logging.getLogger(__name__)

SUPPORTED_HOSTS: tuple[str, ...] = ("claude", "codex", "google")
MANIFEST_SCHEMA_VERSION = 1
GITIGNORE_BEGIN = "# >>> parrot sdd (managed) >>>"
GITIGNORE_END = "# <<< parrot sdd (managed) <<<"
GITIGNORE_BLOCK = f"{GITIGNORE_BEGIN}\n# SDD feature worktrees (python -m parrot.sdd.scripts.ensure_worktree)\n.claude/worktrees/\n{GITIGNORE_END}"
HOOK_WIRING_NOTE = (
    "note: .claude/hooks/sdd-worker-format.sh is installed but not registered — add it to "
    ".claude/settings.json (SubagentStop/Stop) if you want post-run formatting"
)


def _assets_root() -> Traversable:
    """Packaged asset tree (works from a wheel; never a repo checkout path)."""
    return resources.files("parrot.sdd") / "_assets"


def load_manifest() -> list[dict[str, Any]]:
    """Return the manifest's ``assets`` list.

    Raises:
        RuntimeError: manifest missing or ``schema_version`` unsupported.
    """
    path = _assets_root() / "manifest.json"
    if not path.is_file():
        raise RuntimeError("parrot/sdd/_assets/manifest.json is missing — broken ai-parrot install")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise RuntimeError(f"unsupported SDD asset manifest schema_version {data.get('schema_version')!r}")
    return list(data["assets"])


def _validate_hosts(hosts: Sequence[str]) -> tuple[str, ...]:
    """Normalise ``hosts`` (dedupe, keep order) and reject unknown names with ``ValueError``."""
    unknown = sorted(set(hosts) - set(SUPPORTED_HOSTS))
    if unknown or not hosts:
        raise ValueError(f"unknown/empty SDD host(s) {unknown or list(hosts)}; choose from {SUPPORTED_HOSTS}")
    return tuple(dict.fromkeys(hosts))


def _selected(entries: list[dict[str, Any]], hosts: Sequence[str]) -> list[dict[str, Any]]:
    """Assets whose ``hosts`` intersect ``hosts``."""
    wanted = set(hosts)
    return [e for e in entries if wanted & set(e["hosts"])]


def _upsert_marker_block(text: str, block: str, begin: str, end: str) -> str:
    """Own copy of claude_code/installer.py:50 (keys on BEGIN; repairs a missing END)."""
    # FILL IN: copy the body of knowledge/wiki/claude_code/installer.py::_upsert_marker_block verbatim — bounded by spec §6 "own copy"
    raise NotImplementedError


def _remove_marker_block(text: str, begin: str, end: str) -> str:
    """Own copy of claude_code/installer.py:71."""
    # FILL IN: copy the body of knowledge/wiki/claude_code/installer.py::_remove_marker_block verbatim
    raise NotImplementedError


def _install_asset(root: Path, entry: dict[str, Any], *, force: bool) -> str:
    """Apply the conflict rule to one manifest entry; return the action line ('warning: …' when skipped)."""
    payload = (_assets_root() / entry["source"]).read_bytes()
    target = root / entry["target"]
    if target.exists() and target.read_bytes() == payload:
        return f"{entry['target']} — up to date"
    if target.exists() and not force:
        logger.warning("sdd install: %s differs from the packaged copy; skipped", entry["target"])
        return f"warning: {entry['target']} differs from the packaged copy — skipped (use --force)"
    existed = target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    if target.suffix == ".sh":
        target.chmod(0o755)  # wheels do not reliably preserve the exec bit
    return f"{entry['target']} — {'overwritten (--force)' if existed else 'installed'}"


def _install_gitignore(root: Path) -> str:
    """Upsert the managed ``.claude/worktrees/`` block into ``<root>/.gitignore``."""
    path = root / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = _upsert_marker_block(text, GITIGNORE_BLOCK, GITIGNORE_BEGIN, GITIGNORE_END)
    if updated == text:
        return ".gitignore — .claude/worktrees/ block up to date"
    path.write_text(updated, encoding="utf-8")
    return ".gitignore — managed .claude/worktrees/ block written"


def _seed_id_ledger(root: Path) -> str | None:
    """Create ``sdd/tasks/.id_ledger.json`` iff absent (reserve_ids reads it from git and raises when missing)."""
    from parrot.sdd.scripts.id_ledger import LEDGER_PATH, bootstrap_ledger, save_ledger  # TASK-4085

    path = root / LEDGER_PATH
    if path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    save_ledger(path, bootstrap_ledger(root / "sdd/tasks/index", root / "sdd/specs"))
    return (
        f"{LEDGER_PATH} — seeded; warning: commit and push it to your base branch before "
        "`python -m parrot.sdd.scripts.reserve_ids` (it reads the ledger from git)"
    )


def _audit(root: Path, installed: list[Path]) -> list[str]:
    """codex S9: warn about tooling the installed assets need but this machine lacks."""
    findings = scan_paths(installed)
    # FILL IN: map missing_tools(...) result to one 'warning: <tool> not found (needed by <path>:<line>)'
    #          line per tool — bounded by TASK-4070's missing_tools signature; never fail the install
    raise NotImplementedError


def install_sdd_integration(root: Path, hosts: Sequence[str] = ("claude",), *, force: bool = False) -> list[str]:
    """Deploy packaged SDD assets for ``hosts`` into ``root``; never overwrites foreign content.

    Args:
        root: Target repository root (need not be a Python project).
        hosts: Any of ``SUPPORTED_HOSTS``; shared assets (templates, WORKFLOW.md) install for every host.
        force: Overwrite manifest targets whose bytes differ from the packaged copy.

    Returns:
        Human-readable action log; skipped conflicts and audit findings start with ``warning:``.

    Raises:
        ValueError: unknown host.
        RuntimeError: packaged manifest missing/unsupported.
    """
    selected = _selected(load_manifest(), _validate_hosts(hosts))
    actions = [_install_asset(root, entry, force=force) for entry in selected]
    actions.append(_install_gitignore(root))
    seeded = _seed_id_ledger(root)
    if seeded:
        actions.append(seeded)
    if "claude" in hosts:
        actions.append(HOOK_WIRING_NOTE)
    actions.extend(_audit(root, [root / e["target"] for e in selected if (root / e["target"]).is_file()]))
    return actions


def uninstall_sdd_integration(root: Path, hosts: Sequence[str] = ("claude",)) -> list[str]:
    """Remove byte-identical SDD assets for ``hosts`` (modified files are kept and reported).

    The ``.gitignore`` block is removed only when no supported host keeps installed assets;
    ``sdd/tasks/.id_ledger.json`` is never removed (it is state, not an asset).
    """
    # FILL IN: per selected entry — identical → unlink + prune now-empty parents up to root;
    #          differs → 'warning: … modified — kept'; absent → skip. Shared assets: keep while another
    #          host's identical assets remain (Key Constraints). Drop the .gitignore block via
    #          _remove_marker_block when nothing remains — bounded by the FEAT-633 conflict rule
    raise NotImplementedError


def sdd_status(root: Path) -> dict[str, Any]:
    """Per-host install state: ``{"hosts": {h: {"installed": [...], "modified": [...], "missing": [...]}},
    "gitignore": bool, "id_ledger": bool}`` (targets are repo-relative strings)."""
    # FILL IN: classify every manifest entry per host it belongs to (identical/differs/absent) — bounded by
    #          the dict shape in this docstring (test_installer asserts it)
    raise NotImplementedError
```
**Why this shape**: the manifest (TASK-4090) is the only source of what to install; the
conflict rule and marker block follow the brief verbatim. The ledger seed is required because
`reserve_ids._read_ledger_at` (reserve_ids.py:259) raises `IdReservationError` when the ledger is
absent from the base commit — a fresh repo could otherwise never run `/sdd-spec`. Seeding only
when absent and never removing it keeps installs idempotent and uninstall state-safe.

### `packages/ai-parrot/src/parrot/sdd/cli.py` (CREATE)
```python
"""``parrot sdd`` — install the SDD flow (commands, agents, rules, templates) into a repository."""

from __future__ import annotations

import json
from pathlib import Path

import click

from parrot.sdd.installer import SUPPORTED_HOSTS, install_sdd_integration, sdd_status, uninstall_sdd_integration

_path_option = click.option(
    "--path", "path_", type=click.Path(file_okay=False, path_type=Path), default=None,
    help="Target repository root (default: current directory).",
)
_host_option = click.option(
    "--host", "hosts", type=click.Choice(SUPPORTED_HOSTS), multiple=True,
    help="Assistant host(s) to install for; repeatable (default: claude).",
)


def _root(path_: Path | None) -> Path:
    """Resolve ``--path`` (default cwd) or abort when it is not a directory."""
    root = (path_ or Path.cwd()).resolve()
    if not root.is_dir():
        raise click.ClickException(f"Not a directory: {root}")
    return root


def _echo_actions(actions: list[str]) -> None:
    for action in actions:
        if action.startswith(("warning:", "note:")):
            click.echo(f"  ! {action}", err=True)
        else:
            click.echo(f"  ✓ {action}")


@click.group(name="sdd")
def sdd() -> None:
    """Spec-Driven Development flow: install / uninstall / status."""


@sdd.command()
@_path_option
@_host_option
@click.option("--force", is_flag=True, help="Overwrite SDD files that differ from the packaged copy.")
def install(path_: Path | None, hosts: tuple[str, ...], force: bool) -> None:
    """Deploy the packaged SDD assets into the repository."""
    try:
        _echo_actions(install_sdd_integration(_root(path_), hosts or ("claude",), force=force))
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc


@sdd.command()
@_path_option
@_host_option
def uninstall(path_: Path | None, hosts: tuple[str, ...]) -> None:
    """Remove SDD files that are still byte-identical to the packaged copy."""
    try:
        _echo_actions(uninstall_sdd_integration(_root(path_), hosts or ("claude",)))
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc


@sdd.command()
@_path_option
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def status(path_: Path | None, as_json: bool) -> None:
    """Show which SDD assets are installed, modified or missing per host."""
    report = sdd_status(_root(path_))
    if as_json:
        click.echo(json.dumps(report, indent=2))
        return
    # FILL IN: one summary line per host (installed/modified/missing counts) + gitignore/ledger flags
    raise NotImplementedError
```
**Why this shape**: the attribute is named `sdd` because `LazyGroup.get_command` resolves
`getattr(mod, cmd_name.replace("-", "_"))` (cli/__init__.py:99-100); `--host` is a repeatable
`click.Choice` defaulting to `claude` (brief); `--path` defaults to cwd (brief) — deliberately NOT
the wiki's `find_project_root`, so a fresh non-git dir works and `parrot.knowledge.wiki` is never imported.

### `packages/ai-parrot/src/parrot/cli/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "devloop": "parrot.cli.devloop",' packages/ai-parrot/src/parrot/cli/__init__.py)
# AFTER — insert below `    "devloop": "parrot.cli.devloop",` (verified: packages/ai-parrot/src/parrot/cli/__init__.py:125)
    # FEAT-633 — SDD flow installer (parrot sdd install|uninstall|status).
    "sdd": "parrot.sdd.cli",
```
**Why**: inside `cli._lazy_commands = {` (cli/__init__.py:109, grep -c == 1). The `devloop` anchor
is used instead of the dict opener so this edit cannot collide with TASK-4080's `"self"` insertion;
if TASK-4080 moved the `devloop` line, re-run the grep and STOP if the count is not 1.

### `packages/ai-parrot/tests/sdd/test_installer.py` (CREATE)
```python
"""Tests for parrot.sdd.installer (FEAT-633 M6; spec §4 test_sdd_install_into_empty_repo,
integration test_sdd_flow_in_foreign_repo)."""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

from parrot.sdd.installer import (
    GITIGNORE_BEGIN,
    install_sdd_integration,
    load_manifest,
    sdd_status,
    uninstall_sdd_integration,
)


@pytest.fixture
def empty_repo(tmp_path: Path) -> Path:
    """A fresh, non-Python git repository."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("# foreign repo\n")
    return tmp_path


def _claude_targets() -> list[str]:
    return [e["target"] for e in load_manifest() if "claude" in e["hosts"]]


def test_sdd_install_into_empty_repo(empty_repo: Path) -> None:
    """Deploy + uninstall round-trip, marker-block safe (spec §4)."""
    install_sdd_integration(empty_repo)
    assert all((empty_repo / t).is_file() for t in _claude_targets())
    assert GITIGNORE_BEGIN in (empty_repo / ".gitignore").read_text()
    assert (empty_repo / "sdd/tasks/.id_ledger.json").is_file()
    uninstall_sdd_integration(empty_repo)
    assert not any((empty_repo / t).exists() for t in _claude_targets())
    assert GITIGNORE_BEGIN not in (empty_repo / ".gitignore").read_text()
    assert (empty_repo / "README.md").read_text() == "# foreign repo\n"
    assert (empty_repo / "sdd/tasks/.id_ledger.json").is_file()  # state is never removed


def test_reinstall_is_idempotent(empty_repo: Path) -> None:
    install_sdd_integration(empty_repo)
    actions = install_sdd_integration(empty_repo)
    assert not any("installed" in a or "overwritten" in a for a in actions)


def test_modified_file_skipped_unless_force_and_kept_on_uninstall(empty_repo: Path) -> None:
    install_sdd_integration(empty_repo)
    target = empty_repo / _claude_targets()[0]
    target.write_text("user edit\n")
    assert any(a.startswith("warning:") for a in install_sdd_integration(empty_repo))
    assert target.read_text() == "user edit\n"
    uninstall_sdd_integration(empty_repo)
    assert target.read_text() == "user edit\n"
    install_sdd_integration(empty_repo, force=True)
    assert target.read_text() != "user edit\n"


def test_existing_gitignore_content_preserved(empty_repo: Path) -> None:
    (empty_repo / ".gitignore").write_text("node_modules/\n")
    install_sdd_integration(empty_repo)
    assert (empty_repo / ".gitignore").read_text().startswith("node_modules/\n")


def test_unknown_host_rejected(empty_repo: Path) -> None:
    with pytest.raises(ValueError):
        install_sdd_integration(empty_repo, hosts=("vim",))


def test_status_shape(empty_repo: Path) -> None:
    install_sdd_integration(empty_repo, hosts=("codex",))
    report = sdd_status(empty_repo)
    assert set(report) >= {"hosts", "gitignore", "id_ledger"}
    assert report["hosts"]["codex"]["missing"] == []
    # FILL IN: assert claude-only targets are reported missing for "claude" — bounded by sdd_status docstring


@pytest.mark.parametrize("hosts", [("claude",), ("codex",), ("google",)])
def test_sdd_flow_in_foreign_repo(empty_repo: Path, hosts: tuple[str, ...]) -> None:
    """Integration: installed markdown references only parrot.sdd.scripts modules that import (spec §4)."""
    install_sdd_integration(empty_repo, hosts=hosts)
    installed = [empty_repo / e["target"] for e in load_manifest() if set(hosts) & set(e["hosts"])]
    texts = [p.read_text(encoding="utf-8") for p in installed if p.suffix in {".md", ".toml"}]
    # FILL IN: (1) every `parrot\.sdd\.scripts\.([a-z_]+)` name resolves via importlib.util.find_spec;
    #          (2) no `python -m scripts.sdd.<moved>` / `scripts/sdd/<moved>.(py|sh)` remains — bounded by spec §5
    #          ("every helper referenced by installed markdown resolves as python -m parrot.sdd.scripts.<name>")
    raise NotImplementedError
```
**Why**: maps 1:1 onto spec §4 (`test_sdd_install_into_empty_repo`, `test_sdd_flow_in_foreign_repo`)
and the brief's conflict rule.

### `packages/ai-parrot/tests/sdd/test_sdd_cli.py` (CREATE)
```python
"""CLI tests for ``parrot sdd`` (FEAT-633 M6)."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from parrot.cli import cli
from parrot.sdd.cli import sdd


def test_lazy_registration() -> None:
    assert cli._lazy_commands["sdd"] == "parrot.sdd.cli"
    assert cli.get_command(None, "sdd") is sdd


def test_install_status_uninstall_roundtrip(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["sdd", "install", "--path", str(tmp_path), "--host", "claude", "--host", "codex"])
    assert result.exit_code == 0, result.output
    status = runner.invoke(cli, ["sdd", "status", "--path", str(tmp_path), "--json"])
    report = json.loads(status.output)
    assert report["hosts"]["claude"]["missing"] == [] and report["hosts"]["codex"]["missing"] == []
    result = runner.invoke(cli, ["sdd", "uninstall", "--path", str(tmp_path), "--host", "claude", "--host", "codex"])
    assert result.exit_code == 0, result.output


def test_unknown_host_is_a_usage_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(cli, ["sdd", "install", "--path", str(tmp_path), "--host", "vim"])
    assert result.exit_code == 2


def test_force_flag_overwrites(tmp_path: Path) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["sdd", "install", "--path", str(tmp_path)])
    # FILL IN: edit one installed .claude/commands file, re-run without/with --force and assert skip/overwrite
```

### FILL IN checklist
- [ ] `installer.py::_upsert_marker_block` / `_remove_marker_block` — verbatim copies of claude_code/installer.py:50/:71.
- [ ] `installer.py::_audit` — S9 warnings from `scan_paths` + `missing_tools`; bounded by TASK-4070 API; never raises.
- [ ] `installer.py::uninstall_sdd_integration` — identical-only removal, shared-asset retention, gitignore block removal.
- [ ] `installer.py::sdd_status` — dict shape in the docstring.
- [ ] `cli.py::status` — human summary.
- [ ] `test_installer.py::test_status_shape`, `test_sdd_flow_in_foreign_repo`; `test_sdd_cli.py::test_force_flag_overwrites`.

---

## Acceptance Criteria

- [ ] `parrot sdd install` into an empty non-Python git repo deploys every manifest asset for the
      requested host(s), writes the `.gitignore` marker block and seeds `sdd/tasks/.id_ledger.json`
      (spec §5: "`parrot sdd install` deploys the flow into an empty non-Python repo").
- [ ] Every helper referenced by installed markdown resolves as `python -m parrot.sdd.scripts.<name>`
      (`test_sdd_flow_in_foreign_repo`, all three hosts).
- [ ] Conflict rule: absent → write; identical → skip; differs → skip + `warning:` unless `--force`;
      uninstall removes byte-identical files only and never the ledger.
- [ ] Unavailable tooling referenced by installed assets is reported as warnings, never as a failure (codex S9).
- [ ] `parrot sdd --help` lists `install`, `uninstall`, `status`; `--host` accepts only
      `claude|codex|google`; `parrot status` (agentd) is unchanged.
- [ ] `parrot.sdd.installer` does not import `parrot.knowledge.wiki.*`.
- [ ] `ruff check` passes on all five files; all tests below pass.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/sdd/test_installer.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass.

```python
# packages/ai-parrot/tests/sdd/test_installer.py — see the CREATE block:
#   test_sdd_install_into_empty_repo (spec §4), test_reinstall_is_idempotent,
#   test_modified_file_skipped_unless_force_and_kept_on_uninstall, test_existing_gitignore_content_preserved,
#   test_unknown_host_rejected, test_status_shape, test_sdd_flow_in_foreign_repo[claude|codex|google] (spec §4 integration)
# packages/ai-parrot/tests/sdd/test_sdd_cli.py — see the CREATE block:
#   test_lazy_registration, test_install_status_uninstall_roundtrip,
#   test_unknown_host_is_a_usage_error, test_force_flag_overwrites
```

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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4091 parrot-installer verified`
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
