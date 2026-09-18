# TASK-3374: `HostAdapter` contract + `detect_hosts`

**Feature**: FEAT-570 — `parrot toolkits` on-demand local-MCP toolkit installation
**Spec**: `sdd/specs/expose-local-mcp-tools.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3371, TASK-3372, TASK-3373
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1, driven by design research **S2** (CONFIRM, `risk: high`).

The three MCP hosts are **not** symmetric, and code that assumes they are will not
work:

| | Claude Code | Codex | Google Antigravity |
|---|---|---|---|
| Config | `<root>/.mcp.json` (JSON) | `<root>/.codex/config.toml` (TOML) | `~/.gemini/config/mcp_config.json` **+** `<root>/.agents/plugins/parrot/mcp_config.json` |
| Scope | repo | repo | **user-global** + repo |
| Ownership test | `_is_managed_toolkit_entry` | **none** — marker block + `_existing_table_names` | `_is_managed_toolkit_entry` |
| Approvals | `.claude/settings.local.json` | n/a | n/a |

This task puts one protocol over all three so `toolkit_install.py` (TASK-3375) and
the CLI (TASK-3376) never import a private per-host helper.

It also implements spec §8 Q1's **interim default (a)**: `detect_hosts` includes
Google when its user-global config exists, and the adapter reports
`is_repo_scoped() is False` so the CLI can warn that writing it affects every
project on the machine.

---

## Scope

- Create `parrot/mcp/hosts.py` with `HostKind`, `HostEntryState`, the
  `HostAdapter` protocol, three concrete adapters, `get_adapter` and `detect_hosts`.
- Each adapter wraps only the **public toolkit-only** functions from TASK-3371/2/3.
- Write tests for detection, scope reporting and per-host inspection.

**NOT in scope**: inventory/install/uninstall orchestration (TASK-3375), the CLI
(TASK-3376), resolving spec §8 Q1.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/hosts.py` | CREATE | `HostKind`, `HostEntryState`, `HostAdapter`, three adapters, `detect_hosts` |
| `packages/ai-parrot/tests/mcp/test_hosts.py` | CREATE | Detection, scope, inspection |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_config import ToolkitSection, load_toolkits_config  # verified: toolkit_config.py:19,105

# Created by this feature's earlier tasks — verify they exist before importing:
from parrot.knowledge.wiki.claude_code.installer import (   # TASK-3371
    reconcile_toolkit_entries as claude_reconcile,
    toolkit_server_names,
    _install_mcp_approval,        # verified: claude_code/installer.py:340
    _uninstall_mcp_approval,      # verified: claude_code/installer.py:371
    _is_managed_toolkit_entry as claude_is_managed,   # verified: claude_code/installer.py:420
)
from parrot.knowledge.wiki.codex.installer import (        # TASK-3372
    reconcile_toolkit_tables,
    _existing_table_names,        # verified: codex/installer.py:100
)
from parrot.knowledge.wiki.google.installer import (       # TASK-3373
    reconcile_toolkit_entries as google_reconcile,
    toolkit_config_paths,
    _is_managed_toolkit_entry as google_is_managed,        # verified: google/installer.py:73
)
from parrot.knowledge.wiki.google import assets as google_assets   # verified: google/assets.py
```

### Existing Signatures to Use
```python
# Created by TASK-3371 (packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
def reconcile_toolkit_entries(root: Path) -> tuple[list[str], list[str]]: ...
def toolkit_server_names(root: Path) -> list[str]: ...   # NEVER returns "wikitoolkit"
def _install_mcp_approval(root: Path) -> str: ...                       # line 340
def _uninstall_mcp_approval(root: Path, removed_toolkit_names: Sequence[str] = ()) -> str | None: ...  # line 371

# Created by TASK-3372 (codex/installer.py)
def reconcile_toolkit_tables(root: Path) -> tuple[list[str], list[str]]: ...

# Created by TASK-3373 (google/installer.py)
def reconcile_toolkit_entries(root: Path, mcp_path: Optional[Path] = None) -> tuple[list[str], list[str]]: ...
def toolkit_config_paths(root: Path, mcp_path: Optional[Path] = None) -> tuple[Path, ...]: ...
    # index 0 = USER-GLOBAL ~/.gemini/config/mcp_config.json; index 1 = repo plugin file

# Pre-existing, verified
# google/assets.py:59  def default_mcp_config_path() -> Path   (user-global)
# google/assets.py:19  PLUGIN_DIR = Path(".agents/plugins/parrot")
# claude_code/installer.py:440  managed shape test: args[:2] == ["mcp-local", name]
# Host config locations: <root>/.mcp.json ; <root>/.codex/config.toml
# Entry key format across hosts: f"parrot-{name}"
```

### Does NOT Exist
- ~~`codex.installer._is_managed_toolkit_entry`~~ — **does not exist**; Codex
  ownership is structural (marker block + `_existing_table_names`). The
  `CodexAdapter.inspect` must use that, not a per-entry shape check.
- ~~`claude_code/assets.py::toolkit_mcp_entries`~~ — lives only in `google/assets.py:81`.
- ~~`parrot.mcp.hosts`~~ — what THIS task creates.
- ~~a repo-relative Google config~~ — index 0 of `toolkit_config_paths` is user-global.
- ~~`HostKind.GEMINI`~~ — the member is `GOOGLE` (the CLI accepts `google`).
- ~~`ToolkitSection.host`~~ — sections are host-agnostic; there is no per-host field.
- ~~an approvals concept for Codex or Google~~ — only Claude Code has
  `.claude/settings.local.json` approvals.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/mcp/hosts.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/mcp/test_hosts.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_install_mcp_approval",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_uninstall_mcp_approval",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_is_managed_toolkit_entry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#_existing_table_names",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#_is_managed_toolkit_entry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py#default_mcp_config_path",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#load_toolkits_config"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Import no toolkit class.** Adapters read config files only — `inventory()`
  (TASK-3375) must stay side-effect free (AC1).
- Keep the per-host installer imports **function-local** (the wiki modules avoid
  top-level `parrot.mcp` imports and vice versa; a top-level import here risks a
  cycle).
- `sync_approvals` is Claude-only; Codex and Google return `None`.
- `detect_hosts` must not create any file — detection is existence checks only.

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/toolkit_config.py` — the config model layer
- `packages/ai-parrot/src/parrot/knowledge/wiki/*/installer.py` — the three hosts

---

## Implementation Blueprint

### Steps (in order)
1. Define `HostKind` and `HostEntryState` — *why*: the CLI renders per-host state
   in `list`/`status`, and it needs `repo_scoped` to warn about Google.
2. Define the `HostAdapter` Protocol — *why*: it is the contract S2 asked for; the
   three concrete classes then cannot diverge in signature.
3. Implement the three adapters over the public toolkit-only functions — *why*:
   importing private helpers is exactly what S2 said would not work across hosts.
4. Implement `get_adapter` and `detect_hosts` — *why*: the CLI's "all detected
   hosts" default (spec §8 Q1 interim (a)) lives here, not in the CLI.

### `packages/ai-parrot/src/parrot/mcp/hosts.py` (CREATE)
```python
"""One adapter contract over three asymmetric MCP hosts (FEAT-570, spec §3 M1).

Claude Code, Codex and Google Antigravity differ in config format, ownership
detection and — critically — scope: Google's primary config is USER-GLOBAL.
`parrot toolkits` talks to this protocol, never to a host's private helpers.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional, Protocol, Sequence

from pydantic import BaseModel


class HostKind(str, Enum):
    """The MCP hosts `parrot toolkits` can register a toolkit with."""

    CLAUDE = "claude"
    CODEX = "codex"
    GOOGLE = "google"


class HostEntryState(BaseModel):
    """One toolkit's entry state in one host."""

    host: HostKind
    config_paths: tuple[Path, ...]
    config_present: bool
    repo_scoped: bool
    managed: bool
    foreign: bool


class HostAdapter(Protocol):
    """One MCP host's toolkit-entry surface. Implementations NEVER touch wikitoolkit."""

    kind: HostKind

    def config_paths(self, root: Path) -> tuple[Path, ...]:
        """Config files this host reads, most significant first."""

    def is_repo_scoped(self) -> bool:
        """False when the primary config is user-global (Google only)."""

    def inspect(self, root: Path, names: Sequence[str]) -> dict[str, HostEntryState]:
        """Per-toolkit entry state. Reads config files only; imports no toolkit."""

    def reconcile(self, root: Path) -> tuple[list[str], list[str]]:
        """Rewrite ONLY this host's `parrot-<name>` entries. Returns (actions, warnings)."""

    def sync_approvals(self, root: Path, removed: Sequence[str] = ()) -> Optional[str]:
        """Claude Code only; returns None elsewhere."""


class ClaudeAdapter:
    """Claude Code — repo `.mcp.json`, per-entry managed-shape ownership, approvals."""

    kind = HostKind.CLAUDE

    def config_paths(self, root: Path) -> tuple[Path, ...]:
        return (root / ".mcp.json",)

    def is_repo_scoped(self) -> bool:
        return True

    def inspect(self, root: Path, names: Sequence[str]) -> dict[str, HostEntryState]:
        # FILL IN: read .mcp.json's "mcpServers"; for each name, `managed` is
        # `_is_managed_toolkit_entry(servers.get(f"parrot-{name}"), root, name)` and
        # `foreign` is "key present but not managed" — bounded by AC1 (no toolkit import).
        raise NotImplementedError

    def reconcile(self, root: Path) -> tuple[list[str], list[str]]:
        from parrot.knowledge.wiki.claude_code.installer import reconcile_toolkit_entries

        return reconcile_toolkit_entries(root)

    def sync_approvals(self, root: Path, removed: Sequence[str] = ()) -> Optional[str]:
        from parrot.knowledge.wiki.claude_code.installer import (
            _install_mcp_approval,
            _uninstall_mcp_approval,
        )

        if removed:
            return _uninstall_mcp_approval(root, removed)
        return _install_mcp_approval(root)


class CodexAdapter:
    """Codex — repo `.codex/config.toml`, STRUCTURAL ownership (managed marker block)."""

    kind = HostKind.CODEX

    def config_paths(self, root: Path) -> tuple[Path, ...]:
        return (root / ".codex" / "config.toml",)

    def is_repo_scoped(self) -> bool:
        return True

    def inspect(self, root: Path, names: Sequence[str]) -> dict[str, HostEntryState]:
        # FILL IN: Codex has NO per-entry shape check. `managed` means the table
        # `mcp_servers.parrot-<name>` appears INSIDE the managed marker block;
        # `foreign` means `_existing_table_names` finds it OUTSIDE the block.
        # Bounded by AC1 and the structural-ownership rule (design research S2).
        raise NotImplementedError

    def reconcile(self, root: Path) -> tuple[list[str], list[str]]:
        from parrot.knowledge.wiki.codex.installer import reconcile_toolkit_tables

        return reconcile_toolkit_tables(root)

    def sync_approvals(self, root: Path, removed: Sequence[str] = ()) -> Optional[str]:
        return None


class GoogleAdapter:
    """Antigravity — USER-GLOBAL `~/.gemini/config/mcp_config.json` + repo plugin file."""

    kind = HostKind.GOOGLE

    def __init__(self, mcp_path: Optional[Path] = None) -> None:
        """Accepts an override so tests never touch the real home directory."""
        self._mcp_path = mcp_path

    def config_paths(self, root: Path) -> tuple[Path, ...]:
        from parrot.knowledge.wiki.google.installer import toolkit_config_paths

        return toolkit_config_paths(root, self._mcp_path)

    def is_repo_scoped(self) -> bool:
        return False

    def inspect(self, root: Path, names: Sequence[str]) -> dict[str, HostEntryState]:
        # FILL IN: same per-entry check as Claude but via
        # `google.installer._is_managed_toolkit_entry`, over the PRIMARY config path;
        # set repo_scoped=False on every returned state — bounded by AC1.
        raise NotImplementedError

    def reconcile(self, root: Path) -> tuple[list[str], list[str]]:
        from parrot.knowledge.wiki.google.installer import reconcile_toolkit_entries

        return reconcile_toolkit_entries(root, self._mcp_path)

    def sync_approvals(self, root: Path, removed: Sequence[str] = ()) -> Optional[str]:
        return None


def get_adapter(kind: HostKind) -> HostAdapter:
    """Return the adapter for `kind`."""
    return {HostKind.CLAUDE: ClaudeAdapter(), HostKind.CODEX: CodexAdapter(),
            HostKind.GOOGLE: GoogleAdapter()}[kind]


def detect_hosts(root: Path) -> list[HostKind]:
    """Hosts whose config already exists — the default target set for `parrot toolkits`.

    Spec §8 Q1 interim default (a): Google IS auto-detected when its user-global
    config exists, and callers warn that writing it affects every project on the
    machine (see `HostAdapter.is_repo_scoped`). Creates nothing.
    """
    # FILL IN: for each HostKind, include it when ANY of its `config_paths(root)`
    # exists. Never create a file or directory here — bounded by AC2.
    raise NotImplementedError
```
**Why this shape**: the Protocol is structural, so the three classes need no base
class and no registration — `get_adapter` is a plain dict. Every installer import
is **function-local** on purpose: `parrot.mcp` and `parrot.knowledge.wiki` import
each other's pieces lazily today, and a module-level import here would risk a
cycle. `GoogleAdapter.__init__` takes `mcp_path` so tests can redirect the
user-global file — without it, a test would write into the developer's real
`~/.gemini`. `is_repo_scoped()` exists purely so the CLI can print the blast-radius
warning; do not remove it when Q1 resolves — resolving Q1 changes `detect_hosts`,
not the protocol.

### `packages/ai-parrot/tests/mcp/test_hosts.py` (CREATE)
```python
"""HostAdapter contract over three asymmetric hosts (FEAT-570, TASK-3374)."""
from __future__ import annotations

import pytest

from parrot.mcp.hosts import HostKind, detect_hosts, get_adapter


def test_detect_hosts_empty_repo(tmp_path):
    """A bare directory has no host configs, so nothing is detected."""
    assert detect_hosts(tmp_path) == []


def test_detect_hosts_finds_claude_and_codex(tmp_path):
    (tmp_path / ".mcp.json").write_text('{"mcpServers": {}}', encoding="utf-8")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text("", encoding="utf-8")
    found = detect_hosts(tmp_path)
    assert HostKind.CLAUDE in found and HostKind.CODEX in found


def test_only_google_is_user_scoped():
    assert get_adapter(HostKind.CLAUDE).is_repo_scoped() is True
    assert get_adapter(HostKind.CODEX).is_repo_scoped() is True
    assert get_adapter(HostKind.GOOGLE).is_repo_scoped() is False


def test_detect_hosts_creates_nothing(tmp_path):
    detect_hosts(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_inspect_imports_no_toolkit(tmp_path, monkeypatch):
    """AC1 — inspection reads config files, never imports a toolkit class."""
    # FILL IN: snapshot sys.modules, call inspect() on each adapter, assert no new
    # `parrot_tools.*` or `parrot.tools.*` module appeared; bounded by AC1.
```
**Why**: `test_detect_hosts_creates_nothing` pins the "detection creates nothing"
rule that would otherwise be easy to break with a `mkdir(parents=True)`. The
`sys.modules` case is the only way to actually prove AC1 rather than assume it.

### FILL IN checklist
- [ ] `hosts.py::ClaudeAdapter.inspect` — per-entry managed/foreign from `.mcp.json`; bounded by AC1
- [ ] `hosts.py::CodexAdapter.inspect` — structural ownership via marker block + `_existing_table_names`; bounded by AC1, S2
- [ ] `hosts.py::GoogleAdapter.inspect` — per-entry check on the primary path, `repo_scoped=False`; bounded by AC1
- [ ] `hosts.py::detect_hosts` — existence checks only, creates nothing; bounded by AC2
- [ ] `test_hosts.py::test_inspect_imports_no_toolkit` — `sys.modules` assertion; bounded by AC1

---

## Acceptance Criteria

- [ ] `from parrot.mcp.hosts import HostKind, HostAdapter, get_adapter, detect_hosts` works
- [ ] `get_adapter(k).reconcile(root)` returns `(actions, warnings)` for all three
- [ ] Only `HostKind.GOOGLE` reports `is_repo_scoped() is False`
- [ ] `GoogleAdapter(mcp_path=...)` redirects the user-global path (no real `$HOME` writes)
- [ ] `detect_hosts` creates no files or directories
- [ ] `inspect()` imports no `parrot.tools.*` / `parrot_tools.*` module (asserted)
- [ ] `sync_approvals` returns `None` for Codex and Google
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/mcp/hosts.py`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/mcp/test_hosts.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py -q`
- `pytest tests/knowledge/wiki/test_google_installer_toolkit_entries.py -q`

---

## Test Specification

See the CREATE block above — `packages/ai-parrot/tests/mcp/test_hosts.py` is the
full scaffold. Add a case asserting `get_adapter(HostKind.GOOGLE).config_paths()`
returns two paths while the other two return one.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 1, §8 Q1, design research S2 and S8).
2. **Check dependencies** — TASK-3371, TASK-3372 and TASK-3373 must all be in
   `sdd/tasks/completed/`. Confirm their three public functions actually exist
   before importing them.
3. **Verify the Codebase Contract** — especially that Codex still has **no**
   `_is_managed_toolkit_entry`.
4. **Update status** in `sdd/tasks/index/expose-local-mcp-tools.json` → `"in-progress"`.
5. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3374-host-adapter-contract.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (native `sonnet` seat, attempt_uid `852ca5a869454f47bda54dc49bd81d2c`)
**Date**: 2026-09-18
**Notes**: Created `packages/ai-parrot/src/parrot/mcp/hosts.py` (HostKind,
HostEntryState, the `HostAdapter` Protocol, `ClaudeAdapter`/`CodexAdapter`/
`GoogleAdapter`, `get_adapter`, `detect_hosts`) and
`packages/ai-parrot/tests/mcp/test_hosts.py`. Per-host installer imports are
function-local, keeping `parrot.mcp` decoupled from `parrot.knowledge.wiki` at
import time (AC1, verified by `test_inspect_imports_no_toolkit` snapshotting
`sys.modules`). `CodexAdapter.inspect` classifies entries structurally via the
MCP_BEGIN/MCP_END marker block (codex has no `_is_managed_toolkit_entry`).
`GoogleAdapter` always reports `repo_scoped=False` (reads the primary/user-global
config). Validation: `pytest packages/ai-parrot/tests/mcp/test_hosts.py -q` → 6
passed. Feature-wide merge-tier batch (`packages/ai-parrot/tests/{mcp,knowledge/wiki,
flows/dev_loop/sdd_coder,test_coding_agents.py}`, after copying the two Cython
extensions this bare worktree lacked into `.gitignore`d paths to unblock the
`parrot.bots` import chain): 409 passed, 12 failed — this task's diff touches
ONLY 2 new CREATE files with zero MODIFY targets, so none of the 12 pre-date it;
they trace to missing external services (arango/vault) and matplotlib version
skew, except `test_examples_mcp_wiring::test_explicit_selection_may_name_builtins`
which may be a regression from TASK-3368's `BUILTIN_TOOLKITS` deletion — flagged
for the feature-level code review / ledger, not fixed here (out of this task's
file scope). `ruff check` clean. Review recorded: `coder-review:258b6a05fbe1d6d5c5c51e5a`.

**Deviations from spec**: The blueprint's `detect_hosts` tests did not
monkeypatch `Path.home()`; this machine's real `$HOME` has a stray
`~/.gemini/config/mcp_config.json`, which made the literal empty-list assertion
flaky. Added the same `Path.home()` monkeypatch already used elsewhere in the
file to the three `detect_hosts` tests for hermeticity — no production code
changed, consistent with the blueprint's own "never touch the real home
directory" rationale.
