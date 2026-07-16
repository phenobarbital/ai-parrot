---
type: Wiki Overview
title: 'TASK-1294: Mixin Wiring — Integrate Discovery, Prompt, and Tool into SkillRegistryMixin'
id: doc:sdd-tasks-completed-task-1294-mixin-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the final integration task for FEAT-188. It wires the `SkillsDirectoryLoader`,
relates_to:
- concept: mod:parrot.skills.file_registry
  rel: mentions
- concept: mod:parrot.skills.loader
  rel: mentions
- concept: mod:parrot.skills.prompt
  rel: mentions
- concept: mod:parrot.skills.tools
  rel: mentions
---

# TASK-1294: Mixin Wiring — Integrate Discovery, Prompt, and Tool into SkillRegistryMixin

**Feature**: FEAT-188 — Skills Directory Loader + PromptBuilder Integration
**Spec**: `sdd/specs/skill-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1291, TASK-1292, TASK-1293
**Assigned-to**: unassigned

---

## Context

This is the final integration task for FEAT-188. It wires the `SkillsDirectoryLoader`,
`render_skills_prompt_layer()`, and `LoadSkillTool` into the existing `SkillRegistryMixin`
so that agents automatically discover skills, inject them into the system prompt, and
expose the `load_skill` tool — all during `configure()`.

Implements: Spec §3 Module 8 (Mixin Wiring).

---

## Scope

- Add new configuration flags to `SkillRegistryMixin`:
  - `skill_paths: list[Path] = []` — filesystem paths to scan for skills
  - `inject_skills_into_prompt: bool = True` — whether to add the `<available_skills>` layer
  - `skill_prompt_max_entries: int | None = None` — truncation limit (None = all)
- Extend `_configure_skill_file_registry()` to:
  1. After existing `load()`, run `SkillsDirectoryLoader(self.skill_paths).load_into(registry)`.
  2. If `inject_skills_into_prompt` and `self._prompt_builder is not None`:
     call `render_skills_prompt_layer(registry, max_skills=...)` and
     `self._prompt_builder.add(layer)`.
  3. Register `LoadSkillTool(file_registry=registry)` via the existing dual-mode pattern.
- Write integration tests.

**NOT in scope**: Hot-reload, IntentRouter integration, `LoadSkillAssetTool`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/skills/mixin.py` | MODIFY | Add config flags, extend `_configure_skill_file_registry()` |
| `tests/integration/test_skill_registry_mixin.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.skills.loader import SkillsDirectoryLoader        # TASK-1291
from parrot.skills.prompt import render_skills_prompt_layer    # TASK-1292
from parrot.skills.tools import LoadSkillTool                  # TASK-1293
from parrot.skills.file_registry import SkillFileRegistry      # file_registry.py:16
from pathlib import Path
from typing import List, Optional
import inspect
```

### Existing Signatures to Use
```python
# parrot/skills/mixin.py — class attributes (lines 38-49):
class SkillRegistryMixin:
    enable_skill_registry: bool = True
    skill_registry_expose_tools: bool = True
    skill_registry_inject_context: bool = True
    skill_registry_auto_extract: bool = False
    skill_registry_max_context_skills: int = 3
    skill_registry_max_context_tokens: int = 1500
    _skill_registry: Optional[SkillRegistry] = None
    _skill_file_registry: Optional["SkillFileRegistry"] = None
    _active_skill: Optional[SkillDefinition] = None

# parrot/skills/mixin.py — file registry configure (lines 110-155):
async def _configure_skill_file_registry(self) -> None:
    # Imports SkillFileRegistry and create_skill_trigger_middleware
    # Creates SkillFileRegistry(skills_dir, learned_dir)
    # Calls registry.load()
    # Registers trigger middleware in self._prompt_pipeline
    # self._skill_file_registry = registry

# parrot/skills/mixin.py — tool registration pattern (lines 250-257):
tool_manager = getattr(self, 'tool_manager', None)
if tool_manager and hasattr(tool_manager, 'register_tool'):
    result = tool_manager.register_tool(tool)
    if inspect.isawaitable(result):
        await result
elif hasattr(self, '_tools'):
    self._tools = getattr(self, '_tools', []) + tools

# Bot base class pattern for prompt builder access:
# self._prompt_builder (inherited from AbstractBot/Agent, NOT from mixin)
if self._prompt_builder is not None:
    self._prompt_builder.add(layer)

# parrot/skills/loader.py (TASK-1291):
class SkillsDirectoryLoader:
    def __init__(self, paths: list[Path], logger: Logger | None = None): ...
    async def load_into(self, registry: SkillFileRegistry) -> int: ...

# parrot/skills/prompt.py (TASK-1292):
def render_skills_prompt_layer(
    registry: SkillFileRegistry,
    max_skills: int | None = None,
    priority: int = 45,
) -> PromptLayer: ...

# parrot/skills/tools.py (TASK-1293):
class LoadSkillTool(AbstractTool):
    def __init__(self, file_registry: SkillFileRegistry, **kwargs): ...
```

### Does NOT Exist
- ~~`SkillRegistryMixin.skill_paths`~~ — does NOT exist yet. This task adds it.
- ~~`SkillRegistryMixin.inject_skills_into_prompt`~~ — does NOT exist. This task adds it.
- ~~`SkillRegistryMixin.skill_prompt_max_entries`~~ — does NOT exist. This task adds it.
- ~~`SkillRegistryMixin._prompt_builder`~~ — mixin does NOT define this. It is accessed
  via `self._prompt_builder` (inherited from the bot base class). Always guard with
  `if self._prompt_builder is not None:`.
- ~~`self._prompt_pipeline`~~ — used for middleware (line 141), NOT for PromptLayer.
  Do NOT confuse `_prompt_pipeline` (middleware) with `_prompt_builder` (layers).

---

## Implementation Notes

### Pattern to Follow — Extended _configure_skill_file_registry()
```python
async def _configure_skill_file_registry(self) -> None:
    # ... existing code (import, create registry, load, register middleware) ...

    # --- NEW: Directory discovery ---
    if self.skill_paths:
        from .loader import SkillsDirectoryLoader
        loader = SkillsDirectoryLoader(self.skill_paths, logger=self.logger)
        loaded = await loader.load_into(self._skill_file_registry)
        self.logger.info(
            "Loaded %d skills from %s", loaded,
            [str(p) for p in self.skill_paths]
        )

    # --- NEW: Prompt layer injection ---
    if self.inject_skills_into_prompt and self._skill_file_registry.list_skills():
        prompt_builder = getattr(self, '_prompt_builder', None)
        if prompt_builder is not None:
            from .prompt import render_skills_prompt_layer
            layer = render_skills_prompt_layer(
                self._skill_file_registry,
                max_skills=self.skill_prompt_max_entries,
            )
            prompt_builder.add(layer)

    # --- NEW: LoadSkillTool registration ---
    if self.skill_paths:  # only register if directory discovery is enabled
        from .tools import LoadSkillTool
        load_tool = LoadSkillTool(file_registry=self._skill_file_registry)
        tool_manager = getattr(self, 'tool_manager', None)
        if tool_manager and hasattr(tool_manager, 'register_tool'):
            result = tool_manager.register_tool(load_tool)
            if inspect.isawaitable(result):
                await result
        elif hasattr(self, '_tools'):
            if isinstance(self._tools, list):
                self._tools.append(load_tool)
            else:
                self._tools = list(self._tools) + [load_tool]
```

### Key Constraints
- Insert new code AFTER the existing `_configure_skill_file_registry()` logic, not before.
- Guard prompt builder access with `getattr(self, '_prompt_builder', None)`.
- Guard tool registration with the dual-mode pattern (already used in `_add_skill_tools`).
- Use lazy imports (`from .loader import ...`) inside the method to avoid circular imports.
- When `skill_paths` is empty (default), NONE of the new code runs — zero impact on existing behavior.
- Log at INFO level when skills are loaded (consistent with existing logging in mixin).

### References in Codebase
- `parrot/skills/mixin.py` — full mixin class, especially `_configure_skill_file_registry()` (lines 110-155) and `_add_skill_tools()` (lines 230-257)
- `parrot/bots/agent.py:1161-1163` — prompt builder access pattern

---

## Acceptance Criteria

- [ ] `skill_paths=[]` (default) → no loader, no prompt layer, no LoadSkillTool — zero behavioral change
- [ ] `skill_paths=[Path("...")]` → loader runs, skills discovered, prompt layer injected, LoadSkillTool registered
- [ ] `inject_skills_into_prompt=False` → skills discovered but NO prompt layer
- [ ] `skill_prompt_max_entries=5` → prompt layer truncated to 5 skills
- [ ] `LoadSkillTool` is registered via dual-mode pattern
- [ ] Existing `SkillFileRegistry`, trigger middleware, and DB-backed tools unaffected
- [ ] All existing tests pass (no regressions)
- [ ] No linting errors: `ruff check parrot/skills/mixin.py`
- [ ] Integration test: full flow from discovery to tool retrieval

---

## Test Specification

```python
# tests/integration/test_skill_registry_mixin.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.fixture
def skill_dir(tmp_path):
    (tmp_path / "test-skill.md").write_text(
        "---\nname: test-skill\ndescription: A test\n"
        "triggers: []\n---\nTest body."
    )
    return tmp_path


class MockBot:
    """Minimal mock for testing SkillRegistryMixin in isolation."""
    _prompt_builder = None
    _tools = []
    _prompt_pipeline = None
    logger = MagicMock()
    name = "test-bot"

    # Mixin config
    enable_skill_registry = True
    skill_registry_expose_tools = False
    skill_paths = []
    inject_skills_into_prompt = True
    skill_prompt_max_entries = None


@pytest.mark.asyncio
async def test_no_skill_paths_no_change():
    """Default config (empty skill_paths) doesn't add anything."""
    bot = MockBot()
    bot.skill_paths = []
    # Should not raise, should not add tools or layers


@pytest.mark.asyncio
async def test_skill_paths_discovers_skills(skill_dir):
    """Non-empty skill_paths triggers discovery and tool registration."""
    # This test verifies the integration flow
    # Full implementation depends on the MockBot fixture matching the mixin interface


@pytest.mark.asyncio
async def test_inject_skills_false_no_prompt_layer(skill_dir):
    """inject_skills_into_prompt=False skips prompt layer but still registers tool."""
    pass  # Implementation depends on MockBot setup
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/skill-registry.spec.md`
2. **Check dependencies** — verify TASK-1291, TASK-1292, TASK-1293 are all completed
3. **Read `parrot/skills/mixin.py`** thoroughly — understand the existing `_configure_skill_file_registry()` flow before modifying
4. **Verify** all component signatures (SkillsDirectoryLoader, render_skills_prompt_layer, LoadSkillTool)
5. **Implement** the mixin extensions carefully, preserving existing behavior
6. **Test** with both empty and non-empty `skill_paths`
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-25
**Notes**: Added skill_paths, inject_skills_into_prompt, skill_prompt_max_entries to SkillRegistryMixin. Extended _configure_skill_file_registry() with directory discovery, prompt layer injection, and LoadSkillTool dual-mode registration. 6 integration tests pass. 51 total tests pass.

**Deviations from spec**: none | describe if any
