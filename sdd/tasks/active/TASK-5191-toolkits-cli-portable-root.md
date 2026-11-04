# TASK-5191: Toolkit CLI portability flags and explicit checkout targets

**Feature**: FEAT-804 — Installer portability gaps — one root, one portable rule
**Spec**: `sdd/specs/installer-portability-gaps.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5189
**Assigned-to**: unassigned

## Context

Implement the approved revision 0.4 of FEAT-804. This task owns the following bounded deliverable;
the dependency graph separates disjoint host implementations and serializes overlapping test writers.
Source references and literal edit anchors were verified at `62aaa17228` on 2026-11-05.

## Scope

- Implement spec M3/M4 toolkits CLI changes: replace seven cwd usages, add tri-state flags to install/enable and --path to all four write verbs.
- Resolve root before selection, confirmation, warnings or writes; pass that root to user-global warnings.
- Keep existing host detection, selection, confirmations and distribution hints.

**NOT in scope**: worktree-root relocation (FEAT-802), wiki discovery redesign, non-Python worktree
provisioning, dependency additions, or edits outside the declared files. This is an implementation
task artifact; generation of this artifact makes no runtime changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/toolkits.py` | MODIFY | The promised escape hatch must be accepted by Click and reach the root resolver. |
| `packages/ai-parrot/tests/cli/test_toolkits_cli.py` | MODIFY | Test the public flags and the side-effect ordering. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Existing imports below resolve in the referenced source/test modules; `click`, `pytest` and
`pydantic` are already declared in the workspace pyproject files. Stdlib imports require no new
dependency. Imports explicitly marked with a task ID are future dependency contracts, not claims
that those symbols exist at planning HEAD. Preserve existing imports not shown in the blueprint.

```python
from pathlib import Path
import click
import pytest
from click.testing import CliRunner
from parrot.cli import cli
from parrot.launcher import LinkedWorktreeError, install_root, require_primary_checkout  # TASK-5184
from parrot.mcp.toolkit_install import install_toolkits, set_toolkits_enabled  # TASK-5189
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/cli/toolkits.py:88
def _warn_user_global(hosts) -> list[str]:

# packages/ai-parrot/src/parrot/cli/toolkits.py:180
def install(names: tuple[str, ...], hosts_: tuple[str, ...], yes: bool) -> None:

# packages/ai-parrot/src/parrot/cli/toolkits.py:216
def uninstall(names: tuple[str, ...], hosts_: tuple[str, ...], yes: bool) -> None:

# packages/ai-parrot/src/parrot/cli/toolkits.py:245
def enable(names: tuple[str, ...], hosts_: tuple[str, ...], yes: bool) -> None:

# packages/ai-parrot/src/parrot/cli/toolkits.py:267
def disable(names: tuple[str, ...], hosts_: tuple[str, ...], yes: bool) -> None:

# packages/ai-parrot/src/parrot/cli/toolkits.py:160
def status(hosts_: tuple[str, ...]) -> None:
```

### Does NOT Exist

- Toolkit write callbacks do not currently accept --path or a portable tri-state.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/cli/toolkits.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/cli/test_toolkits_cli.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/toolkits.py#_warn_user_global",
    "sym:packages/ai-parrot/src/parrot/cli/toolkits.py#install",
    "sym:packages/ai-parrot/src/parrot/cli/toolkits.py#uninstall",
    "sym:packages/ai-parrot/src/parrot/cli/toolkits.py#enable",
    "sym:packages/ai-parrot/src/parrot/cli/toolkits.py#disable",
    "sym:packages/ai-parrot/src/parrot/cli/toolkits.py#status"
  ]
}
```

## Implementation Notes

TASK-5189 adds portable keywords to install_toolkits/set_toolkits_enabled; inherited TASK-5184 provides install_root/refusal.

Use the approved stdlib-only launcher/decision structures from the spec. Keep public signatures
and existing ownership checks; use black (120 columns) and ruff for Python edits. New test functions
must have type hints and explanatory docstrings, matching production conventions. Keep HOME/PATH,
Google user-global config, credential probes and Git fixtures isolated under tmp_path. Never run
installers against the developer checkout/home as a test. Store test logs in artifacts/logs/.

## Implementation Blueprint

The blocks below are scoped edit plans, not wholesale replacements of existing files. CREATE
blocks are whole-file starting points; fill their bounded bodies before committing. Preserve
surrounding implementation and imports. No FILL IN or unfinished body may remain in implemented code.

### Steps (in order)

1. Revalidate listed anchors and prerequisite signatures — because dependencies or FEAT-802 may move adjacent code.
2. Apply the declared per-file edits in the order below — because caller and callee contracts must remain coherent.
3. Implement every bounded test case in Acceptance Criteria — because wiring-only spies do not verify emitted artifacts.
4. Run the Validation Commands and scoped lint — because the final state must preserve existing regression coverage.

### `packages/ai-parrot/src/parrot/cli/toolkits.py` (MODIFY)

Anchor `    root = Path.cwd()` — occurrences: 6; verified `packages/ai-parrot/src/parrot/cli/toolkits.py:126,164,184,224,249,271`.

Disambiguating current context for each occurrence:

```python
    from parrot.mcp.toolkit_install import inventory

    root = Path.cwd()
    hosts = _resolve_hosts(root, hosts_)
    rows = inventory(root, hosts)
```

```python
    from parrot.mcp.hosts import HostKind, get_adapter

    root = Path.cwd()
    hosts = [HostKind(h) for h in hosts_] if hosts_ else list(HostKind)

```

```python
    from parrot.mcp.toolkit_install import install_toolkits

    root = Path.cwd()
    hosts = _resolve_hosts(root, hosts_)
    selected = _resolve_names(root, names, hosts)
```

```python
    from parrot.mcp.toolkit_install import uninstall_toolkits

    root = Path.cwd()
    hosts = _resolve_hosts(root, hosts_)
    selected = _resolve_names(root, names, hosts)
```

```python
    from parrot.mcp.toolkit_install import set_toolkits_enabled

    root = Path.cwd()
    hosts = _resolve_hosts(root, hosts_)
    selected = _resolve_names(root, names, hosts)
```

```python
    from parrot.mcp.toolkit_install import set_toolkits_enabled

    root = Path.cwd()
    hosts = _resolve_hosts(root, hosts_)
    selected = _resolve_names(root, names, hosts)
```

Anchor `        f"{kind.value}: writes {get_adapter(kind).config_paths(Path.cwd())[0]} — "` — occurrences: 1; verified `packages/ai-parrot/src/parrot/cli/toolkits.py:98`.

```python
from parrot.launcher import LinkedWorktreeError, install_root, require_primary_checkout

def _root(path_: Path | None = None, *, write: bool) -> Path:
    """Resolve target checkout and refuse only implicit linked-worktree mutations."""
    try:
        resolved = install_root(Path.cwd(), explicit=path_)
        if write:
            require_primary_checkout(resolved)
    except LinkedWorktreeError as exc:
        raise click.ClickException(str(exc)) from exc
    return resolved.root

# Add to install/uninstall/enable/disable:
# @click.option("--path", "path_", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
# Add to install/enable:
# @click.option("--portable/--no-portable", default=None,
#               help="Bare launcher commands or baked paths; default keeps form then follows the launcher.")
def install(names: tuple[str, ...], hosts_: tuple[str, ...], yes: bool,
            path_: Path | None, portable: bool | None) -> None:
    """Seed selected toolkits at the resolved target using the selected command form."""
    # FILL IN: preserve body with root/portable forwarding below.

def enable(names: tuple[str, ...], hosts_: tuple[str, ...], yes: bool,
           path_: Path | None, portable: bool | None) -> None:
    """Enable selected toolkits at the resolved target using the selected form."""
    # FILL IN: preserve body with root/portable forwarding below.

def uninstall(names: tuple[str, ...], hosts_: tuple[str, ...], yes: bool, path_: Path | None) -> None:
    """Remove selected toolkit configuration from the resolved target."""
    # FILL IN: preserve body; resolve _root(path_, write=True) first.

def disable(names: tuple[str, ...], hosts_: tuple[str, ...], yes: bool, path_: Path | None) -> None:
    """Disable selected toolkits without deleting their retained configuration."""
    # FILL IN: preserve body; resolve _root(path_, write=True) first.
# FILL IN: resolve root first; _warn_user_global accepts root and uses config_paths(root).
# install_toolkits(..., portable=portable); set_toolkits_enabled(..., portable=portable) for enable.
# uninstall/disable retain default service forms. list/status use _root(write=False).
```

**Why**: The promised escape hatch must be accepted by Click and reach the root resolver.

### `packages/ai-parrot/tests/cli/test_toolkits_cli.py` (MODIFY)

Anchor `def test_list_on_empty_repo` — occurrences: 1; verified `packages/ai-parrot/tests/cli/test_toolkits_cli.py:19`.

```python
def test_toolkits_cli_worktree_path_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """All write verbs reject implicit worktrees before prompting and accept validated --path."""
    # FILL IN: parameterize four verbs; capture prompts/services, invalid paths and unchanged snapshots.
def test_toolkits_cli_portable_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Install/enable pass None, True and False exactly to their services."""
    # FILL IN: real Click invocations with --yes; preserve existing empty-repo list coverage.
```

**Why**: Test the public flags and the side-effect ordering.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/cli/toolkits.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/tests/cli/test_toolkits_cli.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.

## Acceptance Criteria

- [ ] AC6: install/enable forward None/True/False, including --no-portable, without coercion.
- [ ] AC7: install/uninstall/enable/disable refuse implicit worktrees and accept validated --path; list/status never refuse.
- [ ] Subdirectory commands operate on repository configs; non-git list still works; warnings name the actual target paths.

## Validation Commands

- `pytest packages/ai-parrot/tests/cli/test_toolkits_cli.py -q`

Run with the activated project environment and `PYTHONPATH=packages/ai-parrot/src`.
These commands are this task's relevant tests; the index carries the cached spec-wide contract.

## Test Specification

Use the cases and assertions in Acceptance Criteria and each test-file blueprint. Assert outputs,
exit statuses and before/after file snapshots as appropriate. Tests for malformed config and
worktree refusal must prove no unintended write; avoid network services and real user config.

## Agent Instructions

1. Use `$sdd-start TASK-5191` in the feature workflow; implementation belongs in its provisioned worktree.
2. Read the spec and verify dependencies are done in `sdd/tasks/index/installer-portability-gaps.json`.
3. Verify this contract before editing; refresh stale anchors explicitly rather than inventing interfaces.
4. Implement only declared files, complete every blueprint gap, run validation and scoped lint.
5. Commit only the implementation scope. Finalize through `scripts.sdd.finalize_task` with real
   TaskCompletionEvidence and exact implementation HEAD per docs/sdd/CODEX.md; never hand-edit
   the Completion Note or move this task to completed manually. Commit the resulting SDD state.

## Completion Note

Pending. The finalizer records verified implementation evidence when this task is complete.
