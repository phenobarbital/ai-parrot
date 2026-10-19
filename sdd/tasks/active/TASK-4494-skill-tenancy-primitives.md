# TASK-4494: Tenancy primitives (`parrot/skills/tenancy.py`)

**Feature**: FEAT-707 — Per-Tenant Skills for `SkillRegistryMixin`
**Spec**: `sdd/specs/per-tenant-skills.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4493
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 — the foundation every other core task imports. It owns:
tenant-id validation (safe segment + reserved names, design-research S9),
secure tenant paths and discovery, the two per-asyncio-task ContextVars
(current tenant; request-local active skill, S5), `TenantTreeReport`, and
`SkillView` — the read-only overlay of a tenant registry over the global
registry implementing the collision matrix C1–C10 (spec §2).

---

## Scope

- Create `packages/ai-parrot/src/parrot/skills/tenancy.py` with exactly the public names in the spec M1 skeleton.
- Implement the collision matrix in `SkillView.compose()`.
- Write `packages/ai-parrot/tests/unit/test_skill_tenancy.py` (one test per matrix row + validation, paths, discovery, ContextVars).

**NOT in scope**: loading registries from disk for tenants (TASK-4499), prompt layers
(TASK-4498), any change to `SkillFileRegistry`, re-exports in `skills/__init__.py` (TASK-4499).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/skills/tenancy.py` | CREATE | validation, paths, discovery, ContextVars, `TenantTreeReport`, `SkillView` |
| `packages/ai-parrot/tests/unit/test_skill_tenancy.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.utils.paths import validate_path_segment, secure_path   # verified: utils/paths.py:33 / :52
from parrot.skills.file_registry import SkillFileRegistry            # verified: skills/file_registry.py:17
from parrot.skills.models import SkillDefinition, SkillSource        # verified: skills/models.py:60 / :53
```
Inside the package use relative imports: `from .file_registry import SkillFileRegistry`, `from .models import SkillDefinition, SkillSource`.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/utils/paths.py
SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")        # line 29
def validate_path_segment(value: str, name: str = "path segment") -> str: ...  # line 33; raises ValueError; NO reserved-name check
def secure_path(base, *segments: str, name: str = "path segment") -> Path: ...  # line 52; validates each segment, then
#   normpath containment AND symlink-resolved containment; raises ValueError("Path traversal detected: ...")

# packages/ai-parrot/src/parrot/skills/file_registry.py
class SkillFileRegistry:                                              # line 17
    def __init__(self, skills_dir: Path, learned_dir: Optional[Path] = None) -> None: ...  # line 29
    learned_dir: Path                                                 # line 35
    def get(self, trigger: str) -> Optional[SkillDefinition]: ...     # line 108
    def get_by_name(self, name: str) -> Optional[SkillDefinition]: ...  # line 119
    def list_skills(self) -> List[SkillDefinition]: ...               # line 138
    def has_trigger(self, trigger: str) -> bool: ...                  # line 142

# packages/ai-parrot/src/parrot/skills/models.py
class SkillDefinition(BaseModel):                                     # line 60
    name; description; triggers: list[str]; source: SkillSource; file_path: Path; assets_dir: Path | None
    global_only: bool = False                                         # added by TASK-4493
class SkillSource(str, Enum): AUTHORED = "authored"; LEARNED = "learned"   # line 53
```

### Does NOT Exist
- ~~`parrot.skills.tenancy`~~ — created by this task (do not look for an existing one).
- ~~`validate_path_segment(value, *, what=...)`~~ — that keyword form belongs to `knowledge/contracts/evidence.py:54`; use `utils/paths.py` with `name=`.
- ~~`SkillFileRegistry._skills` / `._triggers` as public API~~ — use only the read methods above.
- ~~`parrot.handlers.scope`~~ — server-only; never import it from core.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/skills/tenancy.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/test_skill_tenancy.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/utils/paths.py#validate_path_segment",
    "sym:packages/ai-parrot/src/parrot/utils/paths.py#secure_path",
    "sym:packages/ai-parrot/src/parrot/skills/file_registry.py#SkillFileRegistry",
    "sym:packages/ai-parrot/src/parrot/skills/models.py#SkillDefinition"
  ]
}
```

---

## Implementation Notes

### Collision matrix (spec §2 — implement exactly)
| Case | Effective view |
|---|---|
| C1 same name | tenant skill (INFO "shadows global") |
| C2 same trigger, different names | trigger → tenant skill; `get_by_name(global)` still works; both in `list_skills()` |
| C3 same name, global `global_only` | global kept; tenant skill dropped (ERROR naming both `file_path`s) |
| C4 same trigger, global `global_only` | trigger → global; tenant skill kept by name, without that trigger (ERROR) |
| C5/C6 | tenant-only / global-only skills pass through |
| C7 | two tenants are two views — nothing to do here |
| C8 learned global skill | visible; a tenant-authored skill of the same name shadows it (C1 rule) |

`list_skills()` order: tenant skills in registry order, then globals whose name is not shadowed — deterministic.
C9/C10 are loader concerns (TASK-4499) — not handled here.

### Key Constraints
- `SkillView` is read-only: no `add()`. Hot-added learned skills go into the global registry; the
  owner calls `compose()` again afterwards.
- `learned_dir` always returns the GLOBAL registry's `learned_dir` (learned skills are global).
- ContextVars default `None`; `bind_skill_tenant` returns the `Token` so callers can reset in `finally`.
- Reserved names compared case-insensitively.

---

## Implementation Blueprint

### Steps (in order)
1. Write the validation/path/discovery block — *why*: every tenant-derived path must pass `secure_path` before touching disk (S9).
2. Write the ContextVar helpers — *why*: per-task transport for tenant and active skill (S1, S5).
3. Write `TenantTreeReport` and `SkillView` with `compose()` — *why*: isolation by construction (spec G3).
4. Write the tests — *why*: every matrix row is an acceptance criterion (AC-V2, AC-V4).

### `packages/ai-parrot/src/parrot/skills/tenancy.py` (CREATE) — block 1/3
```python
"""Per-tenant skill primitives (FEAT-707).

Tenant-id validation, secure tenant paths, per-task ContextVars and the
read-only :class:`SkillView` overlay of a tenant registry over the global one.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Final, List, Optional

from parrot.utils.paths import secure_path, validate_path_segment

from .file_registry import SkillFileRegistry
from .models import SkillDefinition

_LOGGER = logging.getLogger(__name__)

RESERVED_TENANT_NAMES: frozenset[str] = frozenset(
    {"skills", "learned", "tenants", "prompts", "queries", "kb", "documents", "flows", "_drafts", "_shared"}
)
TENANTS_DIRNAME: Final[str] = "tenants"
SKILLS_DIRNAME: Final[str] = "skills"


def validate_tenant_id(value: str) -> str:
    """Return ``value`` when it is a safe, non-reserved tenant id.

    Raises:
        ValueError: if ``value`` is not a safe single path segment or is reserved
            (case-insensitive). Never touches the filesystem.
    """
    validate_path_segment(value, name="tenant id")
    if value.lower() in RESERVED_TENANT_NAMES:
        raise ValueError(f"Reserved tenant id: {value!r}")
    return value


def tenant_skills_dir(agent_root: Path, tenant: str) -> Path:
    """Return ``agent_root/tenants/{tenant}/skills`` resolved and contained in ``agent_root``.

    Raises:
        ValueError: invalid tenant id, or the resolved path (symlinks followed) escapes ``agent_root``.
    """
    return secure_path(agent_root, TENANTS_DIRNAME, validate_tenant_id(tenant), SKILLS_DIRNAME, name="tenant id")


def discover_tenant_dirs(agent_root: Path, logger: Optional[logging.Logger] = None) -> Dict[str, Path]:
    """Map ``tenant -> skills_dir`` for every valid ``agent_root/tenants/<tenant>/skills/`` directory.

    Invalid names, escaping symlinks and entries without a ``skills/`` subdirectory are
    skipped with a WARNING. A missing ``tenants/`` directory yields ``{}``. Sorted by tenant.
    """
    log = logger or _LOGGER
    tenants_root = agent_root / TENANTS_DIRNAME
    if not tenants_root.is_dir():
        return {}
    found: Dict[str, Path] = {}
    for entry in sorted(tenants_root.iterdir()):
        # FILL IN: skip non-directories silently; try tenant_skills_dir(agent_root, entry.name)
        #          and catch ValueError → log.warning("Skipping tenant dir %s: %s", entry, exc);
        #          skip (warning) when the returned path is not a directory; else found[entry.name] = path
        #          — bounded by AC-R2 and design-research S9 (never follow an escaping symlink)
        pass
    return found
```
**Why this shape**: `secure_path` already does segment validation plus symlink-resolved containment (paths.py:52-90); adding the reserved-name check here closes the case `validate_path_segment` misses.

### `tenancy.py` — block 2/3 (append)
```python
_skill_tenant: ContextVar[Optional[str]] = ContextVar("parrot_skill_tenant", default=None)
_active_skill: ContextVar[Optional[SkillDefinition]] = ContextVar("parrot_active_skill", default=None)


def current_skill_tenant() -> Optional[str]:
    """Tenant bound to the current asyncio task, or ``None``."""
    return _skill_tenant.get()


def bind_skill_tenant(tenant: Optional[str]) -> Token:
    """Bind ``tenant`` for the current task; reset the returned token in ``finally``."""
    return _skill_tenant.set(tenant)


def reset_skill_tenant(token: Token) -> None:
    """Undo :func:`bind_skill_tenant`."""
    _skill_tenant.reset(token)


def current_active_skill() -> Optional[SkillDefinition]:
    """The ``/trigger``-activated skill for the current task, or ``None`` (request-local, S5)."""
    return _active_skill.get()


def set_active_skill(skill: Optional[SkillDefinition]) -> None:
    """Request-local replacement for ``bot._active_skill = skill``."""
    _active_skill.set(skill)


@dataclass(frozen=True)
class TenantTreeReport:
    """Configure-time audit of one tenant tree (one INFO log line per tenant)."""

    tenant: str
    skills_dir: Path
    loaded: int
    shadowing: tuple[str, ...] = ()
    shadowed_triggers: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()
```

### `tenancy.py` — block 3/3 (append)
```python
class SkillView:
    """Read-only overlay of a tenant registry over the global registry (spec §2 collision matrix)."""

    def __init__(
        self,
        global_registry: SkillFileRegistry,
        tenant_registry: Optional[SkillFileRegistry] = None,
        *,
        tenant: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._global = global_registry
        self._tenant_registry = tenant_registry
        self.tenant = tenant
        self.logger = logger or _LOGGER
        self.report: Optional[TenantTreeReport] = None
        self._by_name: Dict[str, SkillDefinition] = {}
        self._by_trigger: Dict[str, SkillDefinition] = {}
        self._ordered: List[SkillDefinition] = []
        self.compose()

    @property
    def learned_dir(self) -> Path:
        """Always the global registry's learned dir — learned skills are global."""
        return self._global.learned_dir

    def compose(self) -> "SkillView":
        """Recompute the effective indexes (C1–C8) from both registries; returns ``self``."""
        globals_ = self._global.list_skills()
        if self._tenant_registry is None:
            # FILL IN: global view — index globals by name and by every trigger, _ordered = globals_,
            #          report stays None — bounded by AC-B1 (identical to the global registry)
            return self
        # FILL IN: tenant view —
        #   1. locked_names / locked_triggers from globals with global_only (C3/C4)
        #   2. walk tenant skills: drop name collisions with a locked name (ERROR naming both file_path,
        #      record in `dropped`); strip triggers that are locked (ERROR); record shadowing (C1) and
        #      shadowed triggers (C2)
        #   3. _ordered = kept tenant skills, then globals whose name is not shadowed
        #   4. _by_name: tenant names win; _by_trigger: tenant triggers win except locked ones
        #   5. self.report = TenantTreeReport(tenant=self.tenant, skills_dir=<tenant registry skills_dir>,
        #      loaded=len(kept), shadowing=..., shadowed_triggers=..., dropped=...)
        #   — bounded by spec §2 collision matrix, AC-V2, AC-V4
        return self

    def get(self, trigger: str) -> Optional[SkillDefinition]:
        """Skill for ``trigger`` in this view."""
        return self._by_trigger.get(trigger)

    def get_by_name(self, name: str) -> Optional[SkillDefinition]:
        """Skill named ``name`` in this view."""
        return self._by_name.get(name)

    def list_skills(self) -> List[SkillDefinition]:
        """Effective skills: tenant first, then un-shadowed globals."""
        return list(self._ordered)

    def has_trigger(self, trigger: str) -> bool:
        """True when ``trigger`` resolves in this view."""
        return trigger in self._by_trigger
```
**Why this shape**: the interface mirrors `SkillFileRegistry`'s read API so toolkits/middleware accept either (spec M5); C2 keeps the shadowed global reachable by name, which is why `_by_name` and `_by_trigger` are separate indexes. `skills_dir` of the tenant registry is the `SkillFileRegistry.skills_dir` attribute (set in its `__init__`, file_registry.py:29-35).

### `packages/ai-parrot/tests/unit/test_skill_tenancy.py` (CREATE)
```python
"""FEAT-707 — tenancy primitives (TASK-4494)."""
import asyncio
from pathlib import Path

import pytest

from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.tenancy import (
    RESERVED_TENANT_NAMES, SkillView, bind_skill_tenant, current_active_skill, current_skill_tenant,
    discover_tenant_dirs, reset_skill_tenant, set_active_skill, tenant_skills_dir, validate_tenant_id,
)


def _skill(dir_: Path, name: str, triggers: list[str], *, global_only: bool = False) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    extra = "global_only: true\n" if global_only else ""
    trig = "".join(f"  - {t}\n" for t in triggers)
    (dir_ / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {name} skill\ntriggers:\n{trig}{extra}---\n\n{name} body for {dir_.name}\n"
    )


async def _registry(skills_dir: Path) -> SkillFileRegistry:
    reg = SkillFileRegistry(skills_dir=skills_dir, learned_dir=skills_dir / "learned")
    await reg.load()
    return reg


@pytest.mark.parametrize("value", ["pokemon", "acme-01", "Tenant.A"])
def test_validate_tenant_id_accepts_safe_segment(value: str) -> None:
    assert validate_tenant_id(value) == value


@pytest.mark.parametrize("value", ["..", "a/b", "", "skills", "Learned", "TENANTS", "_shared"])
def test_validate_tenant_id_rejects(value: str) -> None:
    with pytest.raises(ValueError):
        validate_tenant_id(value)

# FILL IN tests (one each):
#  test_tenant_skills_dir_secure_path_escape  — symlink tenants/evil -> outside dir raises ValueError
#  test_discover_tenant_dirs_sorted_and_filtered — files, invalid names, reserved names, dirs w/o skills/, symlink escape skipped
#  test_skill_view_c1_shadow_by_name … test_skill_view_c8_learned_global (C1–C6, C8)
#  test_skill_view_global_view_equals_registry
#  test_skill_view_learned_dir_is_global
#  test_list_skills_order_deterministic
#  test_contextvars_default_none_and_reset
#  test_contextvars_isolated_between_tasks (asyncio.gather of two tasks binding different tenants)
#  — bounded by spec §2 collision matrix, AC-R2, AC-V2, AC-V4
```

### FILL IN checklist
- [ ] `discover_tenant_dirs` loop body — bounded by AC-R2, S9
- [ ] `SkillView.compose` global and tenant branches — bounded by §2 matrix, AC-V2, AC-V4
- [ ] all listed tests

---

## Acceptance Criteria

- [ ] Public names match the spec M1 skeleton exactly.
- [ ] AC-R2: invalid / reserved ids raise `ValueError` before any filesystem access.
- [ ] Collision rows C1–C6 and C8 behave as specified; `global_only` rows C3/C4 log ERROR naming both files.
- [ ] ContextVars default `None`, reset restores the previous value, isolated across concurrent tasks.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_skill_tenancy.py -q`
- `pytest packages/ai-parrot/tests/unit/test_skill_file_registry.py -q`

---

## Test Specification

See the CREATE test block; every FILL IN test name is required.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug per-tenant-skills --feature-id FEAT-707`).
2. **Read the spec** §2 (Overview, Collision matrix) and §3 Module 1.
3. **Check dependencies**: TASK-4493 must be `done` in `sdd/tasks/index/per-tenant-skills.json`.
4. **Verify the Codebase Contract** before writing code.
5. **Update status** → `"in-progress"`; commit only the index file.
6. **Implement** from the blueprint; never change a fixed signature or path.
7. **Validate** with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit code** — only the listed files.
9. **Close** with `scripts/sdd/close_task.sh TASK-4494 per-tenant-skills verified`.
10. **Fill in the Completion Note** and commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
