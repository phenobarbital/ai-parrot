# TASK-1757: Wire LeadIQ package exports and TOOL_REGISTRY entry

**Feature**: FEAT-304 — LeadIQ Toolkit for ai-parrot-tools
**Spec**: `sdd/specs/leadiqtool.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1756
**Assigned-to**: unassigned

---

## Context

Implements Spec §3 Module 2. Makes `LeadIQToolkit` importable as a package and
discoverable via the lazy `TOOL_REGISTRY`.

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/leadiq/__init__.py`
  exporting `LeadIQToolkit` and `LeadIQSearchInput`, with `__all__`.
- Add a manual entry to `TOOL_REGISTRY` in
  `packages/ai-parrot-tools/src/parrot_tools/__init__.py`:
  `"leadiq": "parrot_tools.leadiq.tool.LeadIQToolkit"`.

**NOT in scope**: toolkit implementation (TASK-1756); tests (TASK-1758).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/leadiq/__init__.py` | CREATE | Export `LeadIQToolkit`, `LeadIQSearchInput` |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | Add `"leadiq"` `TOOL_REGISTRY` entry |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-13.

### Verified Imports
```python
# leadiq/__init__.py
from .tool import LeadIQToolkit, LeadIQSearchInput   # provided by TASK-1756
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/__init__.py:12-25
TOOL_REGISTRY: dict[str, str] = {
    "company_info": "parrot_tools.company_info.tool.CompanyInfoToolkit",
    "bloomberg": "parrot_tools.bloomberg.BloombergTool",
    # ...
}
# Follow the existing "company_info" module pattern:
# packages/ai-parrot-tools/src/parrot_tools/company_info/__init__.py:1-6
#   from .tool import CompanyInfoToolkit, CompanyInfo
#   __all__ = ["CompanyInfoToolkit", "CompanyInfo"]
```

### Does NOT Exist
- ~~a `"leadiq"` key already in `TOOL_REGISTRY`~~ — must be added by this task.
- ~~auto-generation makes the entry for you~~ — `scripts/generate_tool_registry.py`
  only *preserves* manual entries (line 258-262); add it by hand.

---

## Implementation Notes

### Key Constraints
- Keep the `TOOL_REGISTRY` dict formatting consistent with neighbours.
- Do not reorder or touch other registry entries.
- Place the new entry near the other company/data toolkits for readability.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/company_info/__init__.py` — export pattern
- `scripts/generate_tool_registry.py:258-262` — manual-entry preservation

---

## Acceptance Criteria

- [ ] `leadiq/__init__.py` exports `LeadIQToolkit` and `LeadIQSearchInput` via `__all__`.
- [ ] `TOOL_REGISTRY["leadiq"] == "parrot_tools.leadiq.tool.LeadIQToolkit"`.
- [ ] `from parrot_tools.leadiq import LeadIQToolkit` succeeds.
- [ ] `import parrot_tools` (loading `TOOL_REGISTRY`) raises no error.
- [ ] No other registry entries changed (`git diff` shows only the added line).
- [ ] `ruff check` clean.

---

## Test Specification

```python
def test_registry_entry_resolves():
    import importlib
    from parrot_tools import TOOL_REGISTRY
    assert TOOL_REGISTRY["leadiq"] == "parrot_tools.leadiq.tool.LeadIQToolkit"
    mod_path, _, cls = TOOL_REGISTRY["leadiq"].rpartition(".")
    assert getattr(importlib.import_module(mod_path), cls) is not None
```

---

## Agent Instructions

Standard flow: verify TASK-1756 is completed → implement → run `ruff` → move to
`sdd/tasks/completed/` → update `sdd/tasks/index/leadiqtool.json` → fill note.

---

## Completion Note

**Completed by**: sdd-worker (Claude, Sonnet 5)
**Date**: 2026-07-13
**Notes**: Created `packages/ai-parrot-tools/src/parrot_tools/leadiq/__init__.py`
exporting `LeadIQToolkit` and `LeadIQSearchInput` via `__all__` (mirrors
`company_info/__init__.py`). Added a single manual `TOOL_REGISTRY` entry
`"leadiq": "parrot_tools.leadiq.tool.LeadIQToolkit"` next to `"company_info"`
in `parrot_tools/__init__.py`; `git diff` on that file shows only the one
added line, no other entries touched or reordered. Verified: `ruff check`
clean on both files (pre-existing F401 warnings on `parrot_tools/__init__.py`
line 10 predate this change — confirmed via `git stash` — out of scope,
left untouched); manual smoke test confirms `TOOL_REGISTRY["leadiq"]`
resolves via `importlib` and `from parrot_tools.leadiq import LeadIQToolkit,
LeadIQSearchInput` succeeds.
**Deviations from spec**: none.
