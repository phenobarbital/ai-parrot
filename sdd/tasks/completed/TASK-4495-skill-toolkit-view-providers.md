# TASK-4495: View/registry providers on the skill toolkits

**Feature**: FEAT-707 — Per-Tenant Skills for `SkillRegistryMixin`
**Spec**: `sdd/specs/per-tenant-skills.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (toolkit part) and design-research S6. Both skill toolkits
capture one registry at construction, so a per-request tenant view can never
reach them. This task adds keyword-only provider callables that are called on
every tool invocation; with no provider the behaviour is byte-identical to
today (AC-B1). The mixin wires the providers in TASK-4503 / TASK-4504.

---

## Scope

- `SkillFileToolkit.__init__(..., *, view_provider=None)` + private `_view()`; `list_skill_commands`,
  `load_skill`, `read_skill_asset` read through `_view()`.
- `save_learned_skill` keeps writing to and hot-adding into `self._file_registry` (the GLOBAL registry);
  its name/trigger collision checks run against the global registry only (spec §2 C8, brainstorm edge case).
- `SkillRegistryToolkit.__init__(..., *, registry_provider=None)` + private `_registry_for()`; every
  `self._registry.<call>` (search, read, list, upload in document_skill and update_skill) goes through it.
- `create_skill_tools(..., *, view_provider=None, registry_provider=None)` forwards them.
- Write `packages/ai-parrot/tests/unit/test_skill_tenant_toolkits.py`.

**NOT in scope**: the mixin wiring (TASK-4503/4504), the trigger middleware (TASK-4501), `SkillView` (TASK-4494).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/skills/tools.py` | MODIFY | providers on both toolkits + factory |
| `packages/ai-parrot/tests/unit/test_skill_tenant_toolkits.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# tools.py existing imports (lines 20-31): asyncio; Dict, List, Optional, Type (typing); Path; BaseModel, Field;
#   AbstractTool, ToolResult (..tools.abstract); AbstractToolkit (..tools.toolkit); tool_schema (..tools.decorators);
#   .models (...); .store.SkillRegistry
from typing import Any, Callable   # add to the existing typing import line (tools.py:21)
from parrot.skills.tools import SkillFileToolkit, SkillRegistryToolkit, create_skill_tools  # verified: tools.py:371 / :69 / :635
from parrot.skills.file_registry import SkillFileRegistry   # verified: file_registry.py:17
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/skills/tools.py
class SkillRegistryToolkit(AbstractToolkit):                                            # line 69
    def __init__(self, registry: SkillRegistry, agent_id: str, include_write_tools: bool = True, **kwargs) -> None:  # line 90
        self._registry = registry                                                        # line 98
    # self._registry.search_skills (118), .read_skill (180), .list_skills (181, 209, 304), .upload_skill (262, 313)
class SkillFileToolkit(AbstractToolkit):                                                # line 371
    def __init__(self, file_registry: "SkillFileRegistry", learned_dir: Optional[Path] = None,
                 max_asset_bytes: int = 64 * 1024, **kwargs) -> None:                    # line 398
        self._file_registry = file_registry                                              # line 406
        self._learned_dir = learned_dir                                                  # line 407
    async def list_skill_commands(self) -> ToolResult: ...   # line 413; self._file_registry.list_skills() at 419
    async def load_skill(self, name: str) -> ToolResult: ... # line 454; get_by_name at 462
    async def read_skill_asset(self, skill_name: str, asset: str) -> ToolResult: ...  # line 491; get_by_name at 500
    async def save_learned_skill(self, name, description, content, triggers=None, category="general") -> ToolResult: ...  # line 543
    #   collision checks: self._file_registry.list_skills() (~567), self._file_registry.has_trigger(t) (~578); hot-add self._file_registry.add(skill) (~622)
def create_skill_tools(registry: SkillRegistry, agent_id: str, include_write_tools: bool = True,
                       file_registry: Optional["SkillFileRegistry"] = None,
                       learned_dir: Optional[Path] = None) -> List[AbstractTool]: ...    # line 635
```

### Does NOT Exist
- ~~`SkillFileToolkit(view_provider=...)`~~ / ~~`SkillRegistryToolkit(registry_provider=...)`~~ — added here.
- ~~`AbstractToolkit` treating `_view` / `_registry_for` as tools~~ — underscore-prefixed methods are not exposed by `_generate_tools()`; keep the leading underscore.
- ~~A method named `_registry` on `SkillRegistryToolkit`~~ — `self._registry` is already the attribute; the helper MUST be named `_registry_for` to avoid shadowing it (the spec skeleton's `_registry()` name is adjusted here for that reason).
- ~~Editing `parrot.memory.skills.tools`~~ — deprecated shim.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/skills/tools.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_skill_tenant_toolkits.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/skills/tools.py#SkillFileToolkit",
    "sym:packages/ai-parrot/src/parrot/skills/tools.py#SkillRegistryToolkit",
    "sym:packages/ai-parrot/src/parrot/skills/tools.py#create_skill_tools",
    "sym:packages/ai-parrot/src/parrot/skills/file_registry.py#SkillFileRegistry"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Providers are keyword-only and default `None` (AC-B2).
- Call the provider on EVERY invocation — never cache its result (the tenant changes per request).
- A provider returning `None` falls back to the constructor's registry.
- `save_learned_skill` stays global (AC-L1); it must not call `_view()` for writes.

---

## Implementation Blueprint

### Steps (in order)
1. Extend the typing import with `Any, Callable` — *why*: provider type hints.
2. Add `view_provider` to `SkillFileToolkit.__init__` and the `_view()` helper; route the three read tools through it — *why*: per-request tenant view (S6).
3. Add `registry_provider` + `_registry_for()` to `SkillRegistryToolkit`; replace every `self._registry.` call site with `self._registry_for().` — *why*: tenant-side search/read/write (AC-S2/S3).
4. Forward both from `create_skill_tools` — *why*: single factory used by the mixin.
5. Tests.

### `packages/ai-parrot/src/parrot/skills/tools.py` (MODIFY) — SkillRegistryToolkit
```python
# occurrences: 1 (verified: grep -c 'class SkillRegistryToolkit(AbstractToolkit):' packages/ai-parrot/src/parrot/skills/tools.py)
# REPLACE the __init__ signature at tools.py:90 and add the helper right after __init__:
    def __init__(
        self,
        registry: SkillRegistry,
        agent_id: str,
        include_write_tools: bool = True,
        *,
        registry_provider: Optional[Callable[[], Optional[SkillRegistry]]] = None,
        **kwargs,
    ) -> None:
        # (existing body unchanged) + :
        self._registry_provider = registry_provider

    def _registry_for(self) -> SkillRegistry:
        """Registry for the current request: provider result, else the constructor registry."""
        if self._registry_provider is not None:
            current = self._registry_provider()
            if current is not None:
                return current
        return self._registry
# THEN: every `self._registry.` at tools.py:118, 180, 181, 209, 262, 304, 313 → `self._registry_for().`
# FILL IN: in methods calling it twice (read_skill: 180-181), call `_registry_for()` once into a local
#          so both calls hit the same registry — bounded by AC-S2 (no mixed-namespace answers)
```
**Why**: `_registry_for` (not `_registry`) because `_registry` is an existing attribute name.

### `tools.py` (MODIFY) — SkillFileToolkit
```python
# occurrences: 1 (verified: grep -c 'class SkillFileToolkit(AbstractToolkit):' packages/ai-parrot/src/parrot/skills/tools.py)
# REPLACE the __init__ signature at tools.py:398:
    def __init__(
        self,
        file_registry: "SkillFileRegistry",
        learned_dir: Optional[Path] = None,
        max_asset_bytes: int = 64 * 1024,
        *,
        view_provider: Optional[Callable[[], Any]] = None,
        **kwargs,
    ) -> None:
        # (existing body unchanged) + :
        self._view_provider = view_provider

    def _view(self) -> Any:
        """Current skill view (``SkillView`` or ``SkillFileRegistry``); never cached."""
        if self._view_provider is not None:
            current = self._view_provider()
            if current is not None:
                return current
        return self._file_registry
# THEN: tools.py:419 `self._file_registry.list_skills()` → `self._view().list_skills()`
#       tools.py:462 and :500 `self._file_registry.get_by_name(...)` → `self._view().get_by_name(...)`
#       save_learned_skill: leave every `self._file_registry` use as is (global writes)
# FILL IN: update the class docstring Args with `view_provider` — bounded by Google docstring rule
```

### `tools.py` (MODIFY) — factory
```python
# occurrences: 1 (verified: grep -c 'def create_skill_tools(' packages/ai-parrot/src/parrot/skills/tools.py)
def create_skill_tools(
    registry: SkillRegistry,
    agent_id: str,
    include_write_tools: bool = True,
    file_registry: Optional["SkillFileRegistry"] = None,
    learned_dir: Optional[Path] = None,
    *,
    view_provider: Optional[Callable[[], Any]] = None,
    registry_provider: Optional[Callable[[], Optional[SkillRegistry]]] = None,
) -> List[AbstractTool]:
    # body: pass registry_provider=registry_provider to SkillRegistryToolkit(...)
    #       and view_provider=view_provider to SkillFileToolkit(...); document both in Args
```

### `packages/ai-parrot/tests/unit/test_skill_tenant_toolkits.py` (CREATE)
```python
"""FEAT-707 — toolkit providers (TASK-4495)."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.tools import SkillFileToolkit, SkillRegistryToolkit, create_skill_tools

# FILL IN tests:
#  test_file_toolkit_without_provider_unchanged — list/load read the constructor registry
#  test_file_toolkit_uses_view_provider — provider called on each invocation (count calls), result used
#  test_file_toolkit_provider_none_falls_back
#  test_read_skill_asset_uses_view — composite skill only in the provider's registry is readable
#  test_save_learned_skill_writes_global — hot-add lands in the constructor registry even with a provider
#  test_registry_toolkit_uses_registry_provider — AsyncMock registries; search/list/document/update hit the provided one
#  test_create_skill_tools_forwards_providers
# — bounded by AC-B1, AC-L1, AC-S2, AC-S3
```

### FILL IN checklist
- [ ] `read_skill` single-registry local — AC-S2
- [ ] docstrings for new params
- [ ] all listed tests

---

## Acceptance Criteria

- [ ] With no providers, all pre-existing toolkit tests pass unmodified (AC-0, AC-B1).
- [ ] Providers are consulted on every call and override the constructor registry.
- [ ] `save_learned_skill` always writes/hot-adds to the global registry (AC-L1).
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_skill_tenant_toolkits.py -q`
- `pytest tests/unit/test_load_skill_tool.py -q`
- `pytest tests/unit/test_list_skill_commands_tool.py -q`
- `pytest tests/unit/test_read_skill_asset_tool.py -q`
- `pytest tests/unit/test_skill_registry_toolkit.py -q`
- `pytest packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py -q`

---

## Test Specification

See the CREATE block.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug per-tenant-skills --feature-id FEAT-707`).
2. **Read the spec** §3 Module 5 and §9 S6.
3. **Check dependencies**: none.
4. **Verify the Codebase Contract** (re-grep each `self._registry.` / `self._file_registry.` line — numbers may shift).
5. **Update status** → `"in-progress"`; commit only the index file.
6. **Implement** from the blueprint.
7. **Validate** with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit code** — only the listed files.
9. **Close** with `scripts/sdd/close_task.sh TASK-4495 per-tenant-skills verified`.
10. **Fill in the Completion Note** and commit the SDD state.

---

## Completion Note


- Task: TASK-4495
- Feature: per-tenant-skills
- Implementation SHA: 7f7dce775f15331f7475087cf52a8aa44e482375
- Closed at (UTC): 2026-10-19T21:21:27+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-luna · Backend: codex · Model: gpt-5.6-luna · Attempts: 1 · Duration: 87s · Tokens: n/a |
