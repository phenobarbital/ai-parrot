# TASK-4759: routes.yaml loader, merge semantics & config field

**Feature**: FEAT-755 — Inline A2UI Component Routing
**Spec**: `sdd/specs/inline-a2ui-component-routing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4757
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. Today the phrase bank is a Python constant
(`DEFAULT_OUTPUT_MODE_ROUTES`, `bots/data.py:297`) overridable only by constructing an
`IntentRouterConfig` in code. This task makes it **data**: `routes.yaml` beside the
agent's `skills/` tree, plus a per-tenant override, mirroring FEAT-707 exactly.

Merge order is `DEFAULT_OUTPUT_MODE_ROUTES` ← agent `routes.yaml` ← tenant
`routes.yaml`. Resolved in the brainstorm: a tenant override cannot live inside the
agent *definition* document (that is a single YAML file, while tenants are a
directory tree), so both levels use a file and one loader.

The loader **never raises** for a bad file — warning + skip, so one malformed tenant
file can never take an agent down.

---

## Scope

- Create `route_bank.py`: `ROUTES_FILENAME`, `RouteBankFile`, `ResolvedRouteBanks`, `agent_routes_path`, `tenant_routes_path`, `load_route_bank`, `merge_route_banks`, `resolve_route_banks`.
- Add `tenant_output_mode_routes` to `IntentRouterConfig` and update the `output_mode_routes` description to mention composite keys.
- Add `"routes"` to `RESERVED_TENANT_NAMES` so a tenant cannot be named `routes`.
- Write unit tests for load/merge/resolve, containment, and the never-raises contract.

**NOT in scope**: Calling the loader from `PandasAgent.configure` (TASK-4766), building routers from the banks (TASK-4760), and validating that a label names a real inline component (CONFIGURE's job, TASK-4760).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/routing/route_bank.py` | CREATE | routes.yaml loader + merge |
| `packages/ai-parrot/src/parrot/registry/capabilities/models.py` | MODIFY | tenant_output_mode_routes field |
| `packages/ai-parrot/src/parrot/skills/tenancy.py` | MODIFY | reserve the 'routes' tenant name |
| `packages/ai-parrot/tests/routing/test_route_bank.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED code references from the actual codebase. Use these exact
> imports, class names, and method signatures. DO NOT invent, guess, or assume any
> import, attribute, or method not listed here. Verified against `e21bc561e+ (dev @ 2026-10-27, re-verified at /sdd-task time)`.

### Verified Imports
```python
import yaml  # PyYAML — already a core dependency: packages/ai-parrot/pyproject.toml
from pydantic import BaseModel, ConfigDict, Field

from parrot.skills.tenancy import TENANTS_DIRNAME, validate_tenant_id  # verified: skills/tenancy.py:26,30
from parrot.utils.paths import secure_path  # verified: utils/paths.py
```

### Existing Signatures to Use
```python
# parrot/skills/tenancy.py:23-27
RESERVED_TENANT_NAMES: frozenset[str] = frozenset(
    {"skills", "learned", "tenants", "prompts", "queries", "kb", "documents", "flows", "_drafts", "_shared"}
)
TENANTS_DIRNAME: Final[str] = "tenants"   # :26
SKILLS_DIRNAME: Final[str] = "skills"     # :27

# parrot/skills/tenancy.py:30
def validate_tenant_id(value: str) -> str:
    """Returns value when safe and non-reserved; raises ValueError otherwise."""

# parrot/skills/tenancy.py:42 — the containment pattern to mirror
def tenant_skills_dir(agent_root: Path, tenant: str) -> Path:
    return secure_path(agent_root, TENANTS_DIRNAME, validate_tenant_id(tenant), SKILLS_DIRNAME, name="tenant id")

# parrot/skills/tenancy.py:50
def discover_tenant_dirs(agent_root: Path, logger: Optional[logging.Logger] = None) -> Dict[str, Path]: ...

# parrot/registry/capabilities/models.py:214 (line VERIFIED FRESH — spec said :216, it moved)
    output_mode_routes: dict[str, list[str]] = Field(
        default_factory=dict,
        description=("Phrase bank: OutputMode value (str) -> reference utterances. "
                     "Keys are OutputMode *values* (e.g. 'structured_chart')."),
    )
```

### Does NOT Exist
- ~~`IntentRouterConfig.tenant_output_mode_routes`~~ — this task ADDS it; FEAT-224 fields end at `discrepancy_margin`.
- ~~`IntentRouterConfig.route_bank_path`~~ — not added; the agent root is passed to `resolve_route_banks` by the caller (TASK-4766).
- ~~`parrot.skills.tenancy.tenant_routes_dir`~~ — does not exist; this task adds `tenant_routes_path` in `route_bank.py`, NOT in `tenancy.py`.
- ~~`"routes"` in `RESERVED_TENANT_NAMES`~~ — absent today; this task adds it.
- ~~a `routes.yaml` convention anywhere in the tree~~ — grep over `packages/*/src` returns 0 hits.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/registry/routing/route_bank.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/registry/capabilities/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/skills/tenancy.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/routing/test_route_bank.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/skills/tenancy.py#validate_tenant_id",
    "sym:packages/ai-parrot/src/parrot/skills/tenancy.py#RESERVED_TENANT_NAMES",
    "sym:packages/ai-parrot/src/parrot/utils/paths.py#secure_path",
    "sym:packages/ai-parrot/src/parrot/registry/capabilities/models.py#IntentRouterConfig",
    "sym:packages/ai-parrot/src/parrot/registry/routing/route_labels.py#parse_route_label"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Never raises for a bad file.** `load_route_bank` returns `None` for a missing file and logs `logger.warning` + returns `None` for unparseable YAML or a schema violation. A broken tenant file must not break the agent.
- `RouteBankFile` uses `extra="forbid"` so a typo'd key is a visible validation error (caught and warned), not silently ignored.
- Path containment is **mandatory**: `tenant_routes_path` goes through `secure_path(..., name="tenant id")` + `validate_tenant_id`, exactly like `tenant_skills_dir` (`tenancy.py:42`). A tenant id that escapes the agent root raises `ValueError`.
- `merge_route_banks` does NOT validate keys — label validation is CONFIGURE's job (TASK-4760), which can warn with the agent's logger. Merge is pure dict work.
- Merge semantics per key: `replace=False` (default) **extends** the base list preserving order and dropping duplicates; `replace=True` **substitutes** it.
- `yaml.safe_load` only — never `yaml.load`.
- `resolve_route_banks(agent_root=None, ...)` returns the defaults unchanged (the no-agent-dir case).

### References in Codebase
- `parrot/skills/tenancy.py:42-48` — `tenant_skills_dir`, the containment pattern to mirror exactly.
- `parrot/skills/tenancy.py:50-60` — `discover_tenant_dirs`, the per-tenant discovery + warn-and-skip pattern.
- `parrot/registry/capabilities/models.py:208-238` — the FEAT-224 output-router field block this extends.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Business-logic branches, edge
> cases and test bodies are `FILL IN` stubs by design. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Create `route_bank.py` with the two models and five functions — *why*: the spec fixes these names; TASK-4766 imports `resolve_route_banks` by name.
2. Mirror `tenant_skills_dir`'s containment exactly — *why*: a tenant id is untrusted input and must not escape the agent root.
3. Add `tenant_output_mode_routes` to `IntentRouterConfig` — *why*: TASK-4760 builds one router per tenant from this mapping.
4. Add `"routes"` to `RESERVED_TENANT_NAMES` — *why*: otherwise a tenant literally named `routes` would collide with the agent-level file name.
5. Write `test_route_bank.py` — *why*: AC-1..AC-6.

### `packages/ai-parrot/src/parrot/registry/routing/route_bank.py` (CREATE)
```python
"""``routes.yaml`` phrase-bank loading and merging (FEAT-755).

Layout mirrors the FEAT-707 per-tenant skills tree::

    <agent_root>/routes.yaml                      # agent-level bank
    <agent_root>/tenants/<tenant>/routes.yaml     # per-tenant override

Merge order is defaults <- agent <- tenant. Nothing here raises for a bad file:
a malformed bank is warned about and skipped.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final, Mapping, Optional, Sequence

import yaml
from pydantic import BaseModel, ConfigDict, Field

from parrot.skills.tenancy import TENANTS_DIRNAME, validate_tenant_id  # verified: skills/tenancy.py:26,30
from parrot.utils.paths import secure_path  # verified: utils/paths.py

logger = logging.getLogger(__name__)

ROUTES_FILENAME: Final[str] = "routes.yaml"


class RouteBankFile(BaseModel):
    """Schema of one ``routes.yaml``."""

    model_config = ConfigDict(extra="forbid")

    routes: dict[str, list[str]] = Field(default_factory=dict)
    replace: bool = False
    # FILL IN: optional threshold/margin overrides — bounded by AC-5
    #          (names must match what resolve_route_banks surfaces)


class ResolvedRouteBanks(BaseModel):
    """Merged global bank, per-tenant banks, and optional threshold/margin overrides."""

    routes: dict[str, list[str]] = Field(default_factory=dict)
    tenant_routes: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    # FILL IN: threshold/margin Optional[float] fields — bounded by AC-5


def agent_routes_path(agent_root: Path) -> Path:
    """Return ``agent_root/routes.yaml``."""
    return agent_root / ROUTES_FILENAME


def tenant_routes_path(agent_root: Path, tenant: str) -> Path:
    """Return the contained ``agent_root/tenants/<tenant>/routes.yaml``.

    Raises:
        ValueError: If the tenant id is invalid/reserved or the path escapes ``agent_root``.
    """
    return secure_path(agent_root, TENANTS_DIRNAME, validate_tenant_id(tenant), ROUTES_FILENAME, name="tenant id")


def load_route_bank(path: Path) -> Optional[RouteBankFile]:
    """Load and validate one ``routes.yaml``.

    Returns ``None`` for a missing file, and ``None`` + a logged warning for
    unparseable YAML or a schema violation. Never raises.
    """
    # FILL IN: exists check -> yaml.safe_load -> RouteBankFile.model_validate,
    #          catching (yaml.YAMLError, ValidationError, OSError) -> warn + None
    #          — bounded by AC-3 (never raises)


def merge_route_banks(base: Mapping[str, Sequence[str]], *overlays: RouteBankFile) -> dict[str, list[str]]:
    """Left-to-right merge of ``base`` with each overlay.

    Per key: ``replace=False`` extends (order preserved, duplicates dropped);
    ``replace=True`` substitutes. Keys are NOT validated here — that is CONFIGURE's job.
    """
    # FILL IN: copy base to list[str] values, then apply each overlay per its `replace`
    #          — bounded by AC-2


def resolve_route_banks(agent_root: Optional[Path], *, defaults: Mapping[str, Sequence[str]],
                        tenant_based: bool) -> ResolvedRouteBanks:
    """Resolve defaults <- agent file <- (per discovered tenant) tenant file.

    ``agent_root=None`` returns ``defaults`` only. ``tenant_based=False`` skips the
    tenant tree entirely.
    """
    # FILL IN: agent bank, then per-tenant banks for each discovered tenant dir;
    #          a tenant whose file is missing/invalid inherits the merged global bank
    #          — bounded by AC-4
```
**Why this shape**: the spec fixes these names (§3 M3) and TASK-4766 imports `resolve_route_banks` verbatim. `merge_route_banks` stays key-agnostic so the same function serves agent and tenant levels, and so label validation happens exactly once, where there is a logger with agent context.

### `packages/ai-parrot/src/parrot/registry/capabilities/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    output_mode_routes: dict\[str, list\[str\]\] = Field(' packages/ai-parrot/src/parrot/registry/capabilities/models.py)
# NOTE: the spec's Edit Sites table says :216 — it moved to :214 on dev. Verified fresh.
# AFTER — insert directly below the closing `)` of the `output_mode_routes` Field(...)
# (verified: packages/ai-parrot/src/parrot/registry/capabilities/models.py:214)
    tenant_output_mode_routes: dict[str, dict[str, list[str]]] = Field(
        default_factory=dict,
        description=(
            "FEAT-755: per-tenant phrase banks, tenant id -> (label -> utterances). "
            "Built by route_bank.resolve_route_banks(); each entry becomes its own "
            "EmbeddingIntentRouter sharing the global router's encoder."
        ),
    )
# ALSO: update the `output_mode_routes` description in place to read
#   "Phrase bank: OutputMode value (str) or 'a2ui:<Component>' -> reference utterances."
```
**Why**: the config object is what `configure_output_router` receives, so the per-tenant banks must travel on it rather than being re-read from disk at CONFIGURE.

### `packages/ai-parrot/src/parrot/skills/tenancy.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'RESERVED_TENANT_NAMES: frozenset\[str\] = frozenset(' packages/ai-parrot/src/parrot/skills/tenancy.py)
# MODIFY — add "routes" to the existing frozenset literal (verified: skills/tenancy.py:23)
RESERVED_TENANT_NAMES: frozenset[str] = frozenset(
    {"skills", "learned", "tenants", "prompts", "queries", "kb", "documents",
      "flows", "routes", "_drafts", "_shared"}
)
```
**Why**: `routes` now names an agent-level file; without reserving it, a tenant directory called `routes` would be ambiguous with the bank file. One word, same guarantee FEAT-707 already makes for `skills`.

### `packages/ai-parrot/tests/routing/test_route_bank.py` (CREATE)
```python
"""Unit tests for the routes.yaml loader (FEAT-755 TASK-4759)."""
from __future__ import annotations

import pytest

from parrot.registry.routing.route_bank import (
    ROUTES_FILENAME, RouteBankFile, agent_routes_path, load_route_bank,
    merge_route_banks, resolve_route_banks, tenant_routes_path,
)


@pytest.fixture
def agent_root_with_banks(tmp_path):
    """<root>/routes.yaml + <root>/tenants/acme/routes.yaml + a reserved dir to ignore."""
    # FILL IN: build the tree from the spec's Test Data / Fixtures block — bounded by AC-4
    ...


class TestLoad:
    # FILL IN: missing file -> None; valid file -> RouteBankFile; bad YAML -> None + warning;
    #          extra key -> None + warning (extra="forbid") — bounded by AC-1/AC-3
    ...


class TestMerge:
    # FILL IN: extend preserves base order and dedups; replace=True substitutes per key
    #          — bounded by AC-2
    ...


class TestResolve:
    # FILL IN: agent_root=None -> defaults only; tenant tree discovered and merged;
    #          reserved/invalid tenant dir skipped; tenant_based=False skips tenants
    #          — bounded by AC-4
    ...


class TestContainment:
    # FILL IN: tenant_routes_path rejects "../escape" and a reserved name with ValueError
    #          — bounded by AC-6
    ...
```
**Why**: the never-raises contract and path containment are the two properties the rest of the feature trusts blindly, so they are pinned here rather than at the mixin.

### FILL IN checklist
- [ ] `route_bank.py::RouteBankFile` / `ResolvedRouteBanks` — the threshold/margin override fields; bounded by AC-5
- [ ] `route_bank.py::load_route_bank` — safe_load + validate, catching every error; bounded by AC-1/AC-3
- [ ] `route_bank.py::merge_route_banks` — extend-vs-replace semantics; bounded by AC-2
- [ ] `route_bank.py::resolve_route_banks` — agent + per-tenant resolution; bounded by AC-4
- [ ] `test_route_bank.py` — the fixture and five test classes; bounded by AC-1..AC-6

---

## Acceptance Criteria

- [ ] **AC-1**: `load_route_bank` returns `None` for a missing file; a valid file validates into `RouteBankFile`.
- [ ] **AC-2**: `merge_route_banks` extends by default (base order preserved, duplicates dropped) and substitutes per key when `replace=True`.
- [ ] **AC-3**: unparseable YAML and a schema violation (`extra="forbid"`) each log a warning and return `None` — `load_route_bank` never raises.
- [ ] **AC-4**: `resolve_route_banks` applies defaults ← agent ← tenant; `agent_root=None` returns defaults; `tenant_based=False` skips the tenant tree; a reserved/invalid tenant dir is skipped.
- [ ] **AC-5**: threshold/margin overrides declared in a bank file surface on `ResolvedRouteBanks`.
- [ ] **AC-6**: `tenant_routes_path` raises `ValueError` for a traversing (`../`) or reserved tenant id; `"routes"` is now reserved.
- [ ] `ruff check` clean on all four files.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/routing/test_route_bank.py -q`
- `pytest packages/ai-parrot/tests/unit/test_skill_tenancy.py -q`

---

## Test Specification

Create `packages/ai-parrot/tests/routing/test_route_bank.py` per the blueprint.

Use the spec's `agent_root_with_banks` fixture shape (§4 Test Data / Fixtures):
`<root>/routes.yaml` + `<root>/tenants/acme/routes.yaml` + a reserved `tenants/skills/`
directory that must be ignored.

`packages/ai-parrot/tests/unit/test_skill_tenancy.py` must still pass with `"routes"` added to
`RESERVED_TENANT_NAMES` — check whether it asserts the frozenset's exact contents and
update that assertion if so.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug inline-a2ui-component-routing --feature-id FEAT-755`)
2. **Read the spec** at `sdd/specs/inline-a2ui-component-routing.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/inline-a2ui-component-routing.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/inline-a2ui-component-routing.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <ID> inline-a2ui-component-routing verified`
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
