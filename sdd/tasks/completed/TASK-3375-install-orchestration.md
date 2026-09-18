# TASK-3375: Install orchestration — inventory, install, uninstall, enable/disable

**Feature**: FEAT-570 — `parrot toolkits` on-demand local-MCP toolkit installation
**Spec**: `sdd/specs/expose-local-mcp-tools.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3374, TASK-3370
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. This is the host-agnostic core of `parrot toolkits`: it joins
what *can* be installed (packaged templates) against what *is* declared
(`.parrot/mcp-toolkits.yaml`) against what each host's config actually carries,
and performs the four mutations.

It also implements design research **S6** (CONFIRM): `dist_available()` reports
whether a template's required distributions are importable **using
`importlib.util.find_spec`, never an actual import** — `inventory()` feeds
`parrot toolkits list`, and AC1 requires that listing import no toolkit class.

The mutation ordering matters and is fixed here: **preflight → seed/toggle/remove
→ reconcile hosts → sync approvals**. Uninstall inverts it, snapshotting the
managed entries *before* the YAML changes so the Claude approval cleanup knows
exactly which names it may drop (design research S3).

---

## Scope

- Create `parrot/mcp/toolkit_install.py` with `ToolkitState`, `ToolkitRow`,
  `ActionReport`, `dist_available`, `inventory`, `install_toolkits`,
  `uninstall_toolkits`, `set_toolkits_enabled`.
- Write unit tests for inventory correctness, no-import guarantees, all-or-nothing
  installs, disable-keeps-section, and approval scoping.

**NOT in scope**: the Click group and picker (TASK-3376), host flag removal
(TASK-3377/3378/3379), docs and examples (TASK-3380).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/toolkit_install.py` | CREATE | Orchestration core |
| `packages/ai-parrot/tests/mcp/test_toolkit_install.py` | CREATE | Inventory + four mutations |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_config import ToolkitSection, load_toolkits_config  # verified: toolkit_config.py:19,105
from parrot.mcp.toolkit_seed import (
    available_templates,      # verified: toolkit_seed.py:47
    load_template,            # verified: toolkit_seed.py:61
    seed_toolkit_sections,    # verified: toolkit_seed.py:154
    template_drift,           # verified: toolkit_seed.py:127
    preflight_seed,           # TASK-3369
    set_section_enabled,      # TASK-3369
    remove_section,           # TASK-3369
)
from parrot.mcp.hosts import HostEntryState, HostKind, detect_hosts, get_adapter  # TASK-3374
```

### Existing Signatures to Use
```python
# parrot/mcp/toolkit_seed.py
def available_templates() -> tuple[str, ...]: ...                 # line 47
def load_template(name: str) -> ToolkitTemplate: ...              # line 61 — raises KeyError
class ToolkitTemplate(BaseModel):                                 # line 26
    name: str; body: str; requires_llm: bool = False; summary: str = ""
    requires_dist: tuple[str, ...] = ()        # ADDED by TASK-3370
def template_drift(root: Path, name: str) -> list[str]: ...       # line 127
def seed_toolkit_sections(root: Path, names: Sequence[str]) -> SeedResult: ...  # line 154
class SeedResult(BaseModel):                                      # line 35
    created_file: bool; added: list[str]; skipped: list[str]
    unknown: list[str]; drift: dict[str, list[str]]

# TASK-3369 additions (same module)
def preflight_seed(root: Path, names: Sequence[str]) -> None: ...          # raises ValueError
def set_section_enabled(root: Path, name: str, enabled: bool) -> bool: ...
def remove_section(root: Path, name: str) -> bool: ...

# parrot/mcp/toolkit_config.py
class ToolkitSection(BaseModel):                                  # line 19
    class_path: str = Field(..., alias="class")                   # line 49
    enabled: bool = True                                          # line 50
def load_toolkits_config(root, config_path=None) -> MCPToolkitsConfig: ...  # line 105
    # after TASK-3368: returns ONLY file-declared sections

# parrot/mcp/hosts.py (TASK-3374)
class HostKind(str, Enum): CLAUDE = "claude"; CODEX = "codex"; GOOGLE = "google"
class HostEntryState(BaseModel):
    host: HostKind; config_paths: tuple[Path, ...]; config_present: bool
    repo_scoped: bool; managed: bool; foreign: bool
def get_adapter(kind: HostKind) -> HostAdapter: ...
def detect_hosts(root: Path) -> list[HostKind]: ...
# HostAdapter: config_paths / is_repo_scoped / inspect / reconcile / sync_approvals
#   reconcile(root) -> tuple[list[str], list[str]]   # (actions, warnings)
#   sync_approvals(root, removed=()) -> str | None   # Claude only
```

### Does NOT Exist
- ~~`parrot.mcp.toolkit_install`~~ — what THIS task creates.
- ~~`ToolkitSection.requires_dist`~~ — `requires_dist` is on **`ToolkitTemplate`**
  (template header metadata), not on the config section.
- ~~`SeedResult.removed`~~ / ~~`SeedResult.toggled`~~ — not fields; `remove_section`
  and `set_section_enabled` return `bool`.
- ~~`BUILTIN_TOOLKITS`~~ — deleted by TASK-3368; an empty config is now legal and
  means "nothing installed".
- ~~`wikitoolkit` as an inventory row~~ — it is owned by `parrot claude install`
  and must never appear in `inventory()` output (AC1, spec Goals).
- ~~`importlib.import_module` for availability~~ — use `importlib.util.find_spec`;
  importing would violate AC1.
- ~~a rollback mechanism for partial host failures~~ — re-running is idempotent;
  failures are collected in `ActionReport.failed_hosts`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/mcp/toolkit_install.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/mcp/test_toolkit_install.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#available_templates",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#load_template",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#seed_toolkit_sections",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#template_drift",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#SeedResult",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#load_toolkits_config",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#ToolkitSection"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Mutation order is fixed**: preflight → YAML change → host reconcile →
  approvals. Reconciling before the YAML change would write stale entries.
- **Uninstall snapshots first** (S3): capture `toolkit_server_names`-style managed
  names *before* removing sections, then pass exactly those to
  `sync_approvals(root, removed=...)`. Never pass the full managed set — that
  would de-authorize wikitoolkit or a foreign server.
- Per-host failures are collected, not raised: one unwritable config must not
  abort the others. Re-running is idempotent.
- `inventory()` must work on a repo with no config file at all (empty config).

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` — the seed/mutation layer
- `packages/ai-parrot/src/parrot/mcp/hosts.py` — the adapter layer (TASK-3374)

---

## Implementation Blueprint

### Steps (in order)
1. Define the three models — *why*: `ToolkitRow` is what the CLI renders, so its
   shape fixes what `list` can show.
2. Implement `dist_available` with `find_spec` — *why*: AC1 forbids importing a
   toolkit class, and `QuerysourceToolkit` defers its ImportError to `_open`, so
   an import-based probe would both violate AC1 and still not be reliable.
3. Implement `inventory` — *why*: every other function and the CLI read state
   through it; building it first makes the mutations testable.
4. Implement the three mutations in the fixed order — *why*: ordering is the part
   an implementer is most likely to get subtly wrong.

### `packages/ai-parrot/src/parrot/mcp/toolkit_install.py` (CREATE)
```python
"""Host-agnostic orchestration for `parrot toolkits` (FEAT-570, spec §3 M6).

Joins packaged templates x declared config x per-host entry state, and performs
the four mutations. wikitoolkit is never included — it belongs to
`parrot claude install`.
"""
from __future__ import annotations

import importlib.util
from enum import Enum
from pathlib import Path
from typing import Sequence

from pydantic import BaseModel, Field

from parrot.mcp.hosts import HostEntryState, HostKind, detect_hosts, get_adapter
from parrot.mcp.toolkit_config import load_toolkits_config
from parrot.mcp.toolkit_seed import (
    available_templates, load_template, preflight_seed, remove_section,
    seed_toolkit_sections, set_section_enabled, template_drift,
)


class ToolkitState(str, Enum):
    NOT_INSTALLED = "not_installed"
    ENABLED = "enabled"
    DISABLED = "disabled"


class ToolkitRow(BaseModel):
    """One packaged template joined with its declared and per-host state."""

    name: str
    summary: str
    class_path: str
    state: ToolkitState
    requires_llm: bool = False
    requires_dist: tuple[str, ...] = ()
    dist_available: bool = True
    drift: list[str] = Field(default_factory=list)
    hosts: list[HostEntryState] = Field(default_factory=list)


class ActionReport(BaseModel):
    """What one mutation did, including per-host failures (never raised)."""

    actions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    failed_hosts: dict[HostKind, str] = Field(default_factory=dict)


def dist_available(requires_dist: Sequence[str]) -> bool:
    """True when every named distribution is importable, WITHOUT importing it.

    Uses `importlib.util.find_spec`, never `import_module`: `inventory()` backs
    `parrot toolkits list`, which must import no toolkit class (AC1). An empty
    `requires_dist` means core-only and is always True.
    """
    for dist in requires_dist:
        try:
            if importlib.util.find_spec(dist) is None:
                return False
        except (ImportError, ValueError):
            return False
    return True


def _resolve_hosts(root: Path, hosts: Sequence[HostKind] | None) -> list[HostKind]:
    """Explicit hosts, else every detected host (spec §8 Q1 interim default (a))."""
    return list(hosts) if hosts else detect_hosts(root)


def inventory(root: Path, hosts: Sequence[HostKind] | None = None) -> list[ToolkitRow]:
    """One row per packaged template: state, drift, dependency and per-host status.

    wikitoolkit is never a row. Imports no toolkit class.
    """
    # FILL IN: for each `available_templates()` name — load its template for
    # summary/requires_llm/requires_dist, read its `class:` from the rendered body
    # WITHOUT importing it, derive ToolkitState from `load_toolkits_config(root)`
    # (absent -> NOT_INSTALLED; present -> ENABLED/DISABLED by `section.enabled`),
    # attach `template_drift(root, name)` for declared sections only, and fold in
    # each resolved adapter's `inspect(root, names)`.
    # Bounded by AC1 (no toolkit import) and AC4 (empty config is legal).
    raise NotImplementedError


def _reconcile_all(root: Path, hosts: Sequence[HostKind], report: ActionReport) -> None:
    """Reconcile every host, collecting per-host failures instead of raising."""
    for kind in hosts:
        adapter = get_adapter(kind)
        try:
            actions, warnings = adapter.reconcile(root)
        except (OSError, ValueError) as exc:
            report.failed_hosts[kind] = str(exc)
            continue
        report.actions.extend(actions)
        report.warnings.extend(warnings)


def install_toolkits(root: Path, names: Sequence[str], hosts: Sequence[HostKind]) -> ActionReport:
    """Seed `names` and register them with each host.

    Order: preflight -> seed -> reconcile -> approvals. Preflight raises BEFORE any
    write, so an unknown name leaves the config byte-identical (AC8).

    Raises:
        ValueError: any name is unknown, or the existing config is malformed.
    """
    # FILL IN: call `preflight_seed(root, names)` FIRST; then `seed_toolkit_sections`;
    # record `SeedResult.added/skipped/drift` into the report; `_reconcile_all`;
    # then `get_adapter(CLAUDE).sync_approvals(root)` when Claude is in `hosts`.
    # Bounded by AC2, AC8.
    raise NotImplementedError


def uninstall_toolkits(root: Path, names: Sequence[str], hosts: Sequence[HostKind]) -> ActionReport:
    """Remove `names`' sections and their host entries. Removes CONFIG ONLY.

    Per spec §8 Q2 this NEVER deletes a toolkit's on-disk artifacts (scraping
    plans, db results) — operator data is not ours to delete.
    """
    # FILL IN: snapshot each host's managed entry names for `names` via
    # `adapter.inspect(root, names)` BEFORE mutating — design research S3 — then
    # `remove_section` per name, `_reconcile_all`, and finally
    # `get_adapter(CLAUDE).sync_approvals(root, removed=<snapshotted parrot-* keys>)`.
    # Passing the full managed set instead would de-authorize wikitoolkit. Bounded by AC5.
    raise NotImplementedError


def set_toolkits_enabled(
    root: Path, names: Sequence[str], enabled: bool, hosts: Sequence[HostKind]
) -> ActionReport:
    """Flip `enabled:` for `names` and reconcile; the section and its kwargs survive."""
    # FILL IN: `set_section_enabled` per name (a False return means "not installed" —
    # record it as a warning, not an error), then `_reconcile_all`, then approvals as
    # in install/uninstall depending on `enabled`. Bounded by AC2, AC10.
    raise NotImplementedError
```
**Why this shape**: `ActionReport.failed_hosts` keyed by `HostKind` (rather than
raising) is what lets `parrot toolkits install` succeed for Claude while reporting
that Codex's config was unwritable — the alternative aborts a multi-host install
halfway with no record. `_resolve_hosts` centralises the "all detected hosts"
default so resolving spec §8 Q1 later touches one function. `dist_available` takes
a sequence rather than a `ToolkitRow` so the CLI can call it directly. Do not
change these four public signatures — TASK-3376 imports them by name.

### `packages/ai-parrot/tests/mcp/test_toolkit_install.py` (CREATE)
```python
"""Install orchestration (FEAT-570, TASK-3375)."""
from __future__ import annotations

import sys
import pytest

from parrot.mcp.hosts import HostKind
from parrot.mcp.toolkit_install import (
    ToolkitState, dist_available, install_toolkits, inventory,
    set_toolkits_enabled, uninstall_toolkits,
)


def test_dist_available_missing_distribution():
    assert dist_available(["definitely_not_installed_xyz"]) is False


def test_dist_available_core_only_is_true():
    assert dist_available([]) is True


def test_inventory_on_empty_repo_lists_templates_as_not_installed(tmp_path):
    rows = inventory(tmp_path, hosts=[])
    assert rows and all(r.state is ToolkitState.NOT_INSTALLED for r in rows)


def test_inventory_never_includes_wikitoolkit(tmp_path):
    assert "wikitoolkit" not in {r.name for r in inventory(tmp_path, hosts=[])}


def test_inventory_imports_no_toolkit_class(tmp_path):
    """AC1 — listing must stay side-effect free."""
    before = set(sys.modules)
    inventory(tmp_path, hosts=[])
    new = set(sys.modules) - before
    assert not [m for m in new if m.startswith(("parrot_tools", "parrot.tools"))]


def test_install_unknown_name_is_atomic(tmp_path):
    """AC8 — nothing seeded, nothing written."""
    with pytest.raises(ValueError):
        install_toolkits(tmp_path, ["memory", "not-a-template"], hosts=[])
    assert not (tmp_path / ".parrot" / "mcp-toolkits.yaml").exists()


def test_disable_keeps_section_and_kwargs(tmp_path):
    # FILL IN: install `memory`, disable it, assert state is DISABLED and the
    # section plus its kwargs are still in the YAML; bounded by AC2, AC10.


def test_uninstall_drops_only_its_own_approvals(tmp_path):
    # FILL IN: with a Claude config carrying wikitoolkit + parrot-memory, uninstall
    # `memory` and assert `wikitoolkit` remains in enabledMcpjsonServers;
    # bounded by AC5 and design research S3.
```
**Why**: `test_inventory_imports_no_toolkit_class` is the only assertion that
actually enforces AC1 — every other check would pass a lazy import.
`test_install_unknown_name_is_atomic` asserts the file does not exist at all,
which is stronger than comparing contents and catches an accidental `mkdir`.

### FILL IN checklist
- [ ] `toolkit_install.py::inventory` — join templates × config × host state, no imports; bounded by AC1, AC4
- [ ] `toolkit_install.py::install_toolkits` — preflight → seed → reconcile → approvals; bounded by AC2, AC8
- [ ] `toolkit_install.py::uninstall_toolkits` — snapshot before mutate, scoped approval cleanup; bounded by AC5
- [ ] `toolkit_install.py::set_toolkits_enabled` — toggle, absent = warning not error; bounded by AC2, AC10
- [ ] `test_toolkit_install.py` — the two FILL IN cases; bounded by AC2, AC5, AC10

---

## Acceptance Criteria

- [ ] `inventory()` returns one row per packaged template, never `wikitoolkit`
- [ ] `inventory()` works on a repo with no `.parrot/mcp-toolkits.yaml`
- [ ] `inventory()` imports no `parrot.tools.*` / `parrot_tools.*` module (asserted)
- [ ] `dist_available` uses `find_spec` and never raises on a missing distribution
- [ ] `install_toolkits` with an unknown name raises `ValueError` and writes nothing
- [ ] `uninstall_toolkits` removes config only — no operator data directories deleted
- [ ] Claude approval cleanup receives only the toolkit names actually removed
- [ ] `set_toolkits_enabled(..., False)` keeps the section and its kwargs
- [ ] A per-host failure lands in `ActionReport.failed_hosts` without aborting others
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/mcp/toolkit_install.py`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/mcp/test_toolkit_install.py -q`
- `pytest tests/mcp/test_toolkit_seed.py -q`

---

## Test Specification

See the CREATE block above. Add a case asserting that `install_toolkits` on a
repo with **no** host configs still seeds the YAML (hosts resolve to an empty
list) — that is the `--host`-less path on a fresh checkout.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§2 Data Models, §3 Module 6, §8 Q1 and Q2).
2. **Check dependencies** — TASK-3374 and TASK-3370 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm `preflight_seed`,
   `set_section_enabled`, `remove_section` (TASK-3369), `ToolkitTemplate.requires_dist`
   (TASK-3370) and `parrot.mcp.hosts` (TASK-3374) all exist as documented.
4. **Update status** in `sdd/tasks/index/expose-local-mcp-tools.json` → `"in-progress"`.
5. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3375-install-orchestration.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (native `sonnet` seat, attempt_uid `eb8d3f54496c432c8cb798efeac087e5`)
**Date**: 2026-09-18
**Notes**: Created `packages/ai-parrot/src/parrot/mcp/toolkit_install.py`
(`ToolkitState`, `ToolkitRow`, `ActionReport`, `dist_available`, `_resolve_hosts`,
`_class_path_for_template`, `inventory`, `_reconcile_all`, `install_toolkits`,
`uninstall_toolkits`, `set_toolkits_enabled`) and
`packages/ai-parrot/tests/mcp/test_toolkit_install.py`. Mutation order is
preflight → seed/toggle/remove → reconcile → approvals, matching the
blueprint. `uninstall_toolkits`/`set_toolkits_enabled(enabled=False)` snapshot
each host's managed entry names via `adapter.inspect()` BEFORE mutating
(design research S3), so approval cleanup targets exactly the removed
`parrot-<name>` keys.

**Blocked, then unblocked, mid-attempt**: the native coder implemented this
task correctly on its first pass, but its own 9th test —
`test_uninstall_drops_only_its_own_approvals`, mandated by this task's own
blueprint to verify AC5/S3 — failed due to a confirmed, out-of-scope defect
in already-merged TASK-3374 code (`hosts.py::ClaudeAdapter.sync_approvals`
delegated toolkit-only removal to `_uninstall_mcp_approval`, which always
ALSO strips `"wikitoolkit"` — correct for the FULL `parrot claude uninstall`
path it was written for, wrong here). The coder correctly stopped without
committing rather than deliver code that silently violates AC5, and reported
the root cause with a reproduction. The orchestrator verified the report
against the actual code, fixed TASK-3374's `hosts.py` (see
`fix(expose-local-mcp-tools): TASK-3374 review fixes`, commit `27e541609`,
which adds a toolkit-only `uninstall_toolkit_approvals` sibling to
`claude_code/installer.py` that never touches `"wikitoolkit"`), then
committed the coder's already-correct `toolkit_install.py` +
`test_toolkit_install.py` verbatim after re-verifying: all 9 tests pass
(including the previously-failing one), plus `test_hosts.py` (6 passed),
`ruff check` clean, `black` formatted. Feedback on the TASK-3374 defect
recorded: `coder-feedback:8321f2734cd04e07d580eb71`. Review recorded:
`coder-review:3a856f218778852b62bf6682`.

**Deviations from spec**: none in this task's own two files.
