---
type: Wiki Overview
title: 'TASK-1287: Namespace Promotion — Move parrot.memory.skills to parrot.skills'
id: doc:sdd-tasks-completed-task-1287-namespace-promotion-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the foundational task for FEAT-188. All subsequent tasks depend on
  the new
relates_to:
- concept: mod:parrot.memory
  rel: mentions
- concept: mod:parrot.memory.skills
  rel: mentions
- concept: mod:parrot.memory.skills.store
  rel: mentions
- concept: mod:parrot.skills
  rel: mentions
- concept: mod:parrot.skills.store
  rel: mentions
---

# TASK-1287: Namespace Promotion — Move parrot.memory.skills to parrot.skills

**Feature**: FEAT-188 — Skills Directory Loader + PromptBuilder Integration
**Spec**: `sdd/specs/skill-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for FEAT-188. All subsequent tasks depend on the new
`parrot.skills` namespace. The spec decided on a full module promotion with deprecation
re-exports in the old `parrot.memory.skills` path. This task makes no functional changes
— it is a pure move + re-export operation.

Implements: Spec §3 Module 1 (Namespace Promotion).

---

## Scope

- Copy all 8 `.py` files from `parrot/memory/skills/` to a new `parrot/skills/` package.
- Update all internal imports within the moved files to use `parrot.skills` paths
  (e.g., `from .models import ...` stays relative; absolute cross-module imports like
  `from parrot.memory.skills.store import ...` in `unified/mixin.py` must update).
- Rewrite `parrot/memory/skills/__init__.py` as a deprecation re-export shim that:
  - Imports everything from `parrot.skills`
  - Issues `DeprecationWarning` on module attribute access (use `__getattr__`)
  - Preserves the same `__all__` list for backward compatibility
- Update the one known external importer:
  `parrot/memory/unified/mixin.py:262` — change `from parrot.memory.skills.store import SkillRegistry`
  to `from parrot.skills.store import SkillRegistry`
- Create unit test verifying the deprecation shim works and warns.

**NOT in scope**: Adding any new functionality (new methods, fields, classes). That is
handled by TASK-1288 through TASK-1294.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/skills/__init__.py` | CREATE | New package init, mirrors old `__all__` exports |
| `parrot/skills/models.py` | CREATE | Moved from `parrot/memory/skills/models.py` |
| `parrot/skills/parsers.py` | CREATE | Moved from `parrot/memory/skills/parsers.py` |
| `parrot/skills/file_registry.py` | CREATE | Moved from `parrot/memory/skills/file_registry.py` |
| `parrot/skills/store.py` | CREATE | Moved from `parrot/memory/skills/store.py` |
| `parrot/skills/tools.py` | CREATE | Moved from `parrot/memory/skills/tools.py` |
| `parrot/skills/mixin.py` | CREATE | Moved from `parrot/memory/skills/mixin.py` |
| `parrot/skills/middleware.py` | CREATE | Moved from `parrot/memory/skills/middleware.py` |
| `parrot/memory/skills/__init__.py` | MODIFY | Rewrite as deprecation re-export shim |
| `parrot/memory/unified/mixin.py` | MODIFY | Update import at line 262 |
| `tests/unit/test_skills_deprecation.py` | CREATE | Verify re-export + DeprecationWarning |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Current exports from parrot/memory/skills/__init__.py (lines 32-111):
from parrot.memory.skills import (
    Skill, SkillVersion, SkillMetadata, SkillCategory, SkillStatus,
    ContentType, SkillSource, SkillDefinition, SkillSearchResult,
    UploadSkillArgs, SearchSkillArgs, ReadSkillArgs, ExtractedSkill,
    parse_skill_file,
    SkillFileRegistry,
    create_skill_trigger_middleware,
    SkillRegistry, create_skill_registry, compute_unified_diff, apply_unified_diff,
    DocumentSkillTool, UpdateSkillTool, SearchSkillsTool, ReadSkillTool,
    ListSkillsTool, SaveLearnedSkillTool, create_skill_tools,
    SkillRegistryMixin, SkillRegistryHooks,
)
```

### Existing Signatures to Use
```python
# parrot/memory/skills/__init__.py — __all__ list (lines 74-111):
__all__ = [
    "Skill", "SkillVersion", "SkillMetadata", "SkillCategory", "SkillStatus",
    "ContentType", "SkillSource", "SkillDefinition", "SkillSearchResult",
    "UploadSkillArgs", "SearchSkillArgs", "ReadSkillArgs", "ExtractedSkill",
    "parse_skill_file",
    "SkillFileRegistry",
    "create_skill_trigger_middleware",
    "SkillRegistry", "create_skill_registry",
    "compute_unified_diff", "apply_unified_diff",
    "DocumentSkillTool", "UpdateSkillTool", "SearchSkillsTool",
    "ReadSkillTool", "ListSkillsTool", "SaveLearnedSkillTool",
    "create_skill_tools",
    "SkillRegistryMixin", "SkillRegistryHooks",
]
```

```python
# parrot/memory/unified/mixin.py:262 — the one external import to update:
from parrot.memory.skills.store import SkillRegistry  # type: ignore[import]
```

### Internal Imports Within Skills Module
The moved files use relative imports (e.g., `from .models import ...`). These do NOT
need updating — they are relative to the package and work regardless of package path.
Only update absolute imports if any exist.

### Does NOT Exist
- ~~`parrot/skills/`~~ — does NOT exist yet. Must be created as a new package.
- ~~`parrot.memory.__init__.py` re-exports skills~~ — `parrot.memory.__init__.py` does NOT re-export the skills subpackage. No changes needed there.

---

## Implementation Notes

### Pattern to Follow — Deprecation Shim
```python
# parrot/memory/skills/__init__.py — rewrite as shim
import warnings
import importlib

_NEW_MODULE = "parrot.skills"

def __getattr__(name):
    new_mod = importlib.import_module(_NEW_MODULE)
    if hasattr(new_mod, name):
        warnings.warn(
            f"Importing '{name}' from 'parrot.memory.skills' is deprecated. "
            f"Use 'parrot.skills' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return getattr(new_mod, name)
    raise AttributeError(f"module 'parrot.memory.skills' has no attribute '{name}'")

# Preserve __all__ for star imports
from parrot.skills import __all__  # noqa: F401
```

### Key Constraints
- All 8 `.py` files must be copied (not just moved) initially to avoid breaking
  any transient imports during testing.
- The old `parrot/memory/skills/` directory retains `__init__.py` (the shim) but
  the other files can be removed after the shim is confirmed working. The shim
  delegates all attribute access to `parrot.skills`.
- Keep old `.py` files temporarily (remove in a later cleanup task or version) to
  avoid breaking any imports the grep didn't catch.
- Run `ruff check` and `pytest` after the move to ensure nothing breaks.

### References in Codebase
- `parrot/memory/skills/__init__.py` — current exports (lines 32-111)
- `parrot/memory/unified/mixin.py:262` — only external importer

---

## Acceptance Criteria

- [ ] `parrot/skills/` package exists with all 8 moved files
- [ ] `from parrot.skills import SkillFileRegistry` works
- [ ] `from parrot.skills import SkillDefinition` works
- [ ] `from parrot.skills import SkillRegistryMixin` works
- [ ] All 31 names in `__all__` importable from `parrot.skills`
- [ ] `from parrot.memory.skills import SkillFileRegistry` still works but issues `DeprecationWarning`
- [ ] `parrot/memory/unified/mixin.py` uses `parrot.skills.store` import
- [ ] No linting errors: `ruff check parrot/skills/`
- [ ] All existing tests pass (no regressions)

---

## Test Specification

```python
# tests/unit/test_skills_deprecation.py
import pytest
import warnings


class TestSkillsNamespacePromotion:
    def test_new_import_works(self):
        from parrot.skills import SkillFileRegistry
        assert SkillFileRegistry is not None

    def test_new_import_all_names(self):
        import parrot.skills
        for name in parrot.skills.__all__:
            assert hasattr(parrot.skills, name), f"Missing export: {name}"

    def test_old_import_warns(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from parrot.memory.skills import SkillFileRegistry  # noqa: F811
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) > 0

    def test_old_and_new_resolve_same(self):
        from parrot.skills import SkillDefinition as New
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from parrot.memory.skills import SkillDefinition as Old
        assert New is Old
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/skill-registry.spec.md` for full context
2. **Check dependencies** — this task has none; it can start immediately
3. **Verify the Codebase Contract** — confirm the files and imports listed above still match
4. **Update status** in `sdd/tasks/index/skill-registry.json` → `"in-progress"`
5. **Implement** the move, internal import updates, deprecation shim, and tests
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1287-namespace-promotion.md`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-25
**Notes**: All 8 .py files moved to parrot/skills/. The ...tools.abstract import in tools.py corrected to ..tools.abstract. Updated parrot/memory/skills/__init__.py as deprecation shim. Updated parrot/memory/unified/mixin.py. Modified parse_skill_file to allow empty triggers: [] (only raise when key absent). All 5 tests pass.

**Deviations from spec**: Allowed empty triggers list in parsers.py — needed for composite skills without triggers.
