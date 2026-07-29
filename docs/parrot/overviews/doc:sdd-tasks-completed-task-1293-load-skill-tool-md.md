---
type: Wiki Overview
title: 'TASK-1293: LoadSkillTool — Tier 2 On-Demand Skill Retrieval'
id: doc:sdd-tasks-completed-task-1293-load-skill-tool-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'This is the Tier 2 mechanism: a tool the LLM calls after spotting a relevant
  skill'
relates_to:
- concept: mod:parrot.skills
  rel: mentions
- concept: mod:parrot.skills.file_registry
  rel: mentions
- concept: mod:parrot.skills.models
  rel: mentions
- concept: mod:parrot.skills.tools
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
---

# TASK-1293: LoadSkillTool — Tier 2 On-Demand Skill Retrieval

**Feature**: FEAT-188 — Skills Directory Loader + PromptBuilder Integration
**Spec**: `sdd/specs/skill-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1290
**Assigned-to**: unassigned

---

## Context

This is the Tier 2 mechanism: a tool the LLM calls after spotting a relevant skill
in the `<available_skills>` prompt index. `LoadSkillTool` retrieves the full skill body
(`template_body`) and, for composite skills, a manifest of asset filenames.

Implements: Spec §3 Module 7 (LoadSkillTool).

---

## Scope

- Add `LoadSkillArgs` Pydantic model and `LoadSkillTool` class to `parrot/skills/tools.py`.
- `LoadSkillTool.__init__(file_registry: SkillFileRegistry)` — stores the registry reference.
- `LoadSkillTool._execute(name: str) -> ToolResult`:
  - Calls `registry.get_by_name(name)` (TASK-1290).
  - Returns `ToolResult(status="error")` if skill not found.
  - Returns `ToolResult(status="done", result=template_body, metadata={...})` on success.
  - For composite skills: includes `assets` list (filenames relative to `assets_dir`)
    and `is_composite: True` in metadata.
- Export from `parrot/skills/__init__.py`.
- Update `create_skill_tools()` to optionally include `LoadSkillTool`.
- Write unit tests.

**NOT in scope**: `LoadSkillAssetTool` (out of scope per spec), mixin wiring (TASK-1294).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/skills/tools.py` | MODIFY | Add `LoadSkillArgs`, `LoadSkillTool`; update `create_skill_tools()` |
| `parrot/skills/__init__.py` | MODIFY | Export `LoadSkillTool` |
| `tests/unit/test_load_skill_tool.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.skills.file_registry import SkillFileRegistry  # file_registry.py:16
from parrot.skills.models import SkillDefinition            # models.py:53
from parrot.tools.abstract import AbstractTool, ToolResult  # tools/abstract.py
from pydantic import BaseModel, Field
from typing import Type, Optional
```

### Existing Signatures to Use
```python
# parrot/skills/file_registry.py (after TASK-1290)
class SkillFileRegistry:
    def get_by_name(self, name: str) -> Optional[SkillDefinition]:
        # Added by TASK-1290

# parrot/skills/models.py (after TASK-1288)
class SkillDefinition(BaseModel):
    name: str
    description: str
    triggers: List[str]
    template_body: str        # THIS is the content field
    category: Optional[str]
    assets_dir: Optional[Path] = None  # added by TASK-1288

# parrot/skills/tools.py — existing tool pattern:
class SearchSkillsTool(AbstractTool):
    name: str = "search_skills"
    description: str = "..."
    args_schema: Type[BaseModel] = SkillSearchArgs
    def __init__(self, registry: SkillRegistry, **kwargs):
        super().__init__(**kwargs)
        self._registry = registry
    async def _execute(self, **kwargs) -> ToolResult:
        ...

# parrot/skills/tools.py — create_skill_tools factory (lines 507-546):
def create_skill_tools(
    registry: SkillRegistry,
    agent_id: str,
    include_write_tools: bool = True,
    file_registry: Optional["SkillFileRegistry"] = None,
    learned_dir: Optional[Path] = None,
) -> List[AbstractTool]:
```

### Does NOT Exist
- ~~`LoadSkillTool`~~ — does NOT exist. This task creates it.
- ~~`LoadSkillArgs`~~ — does NOT exist. This task creates it.
- ~~`SkillDefinition.content`~~ — field is `template_body`, NOT `content`.
- ~~`SkillDefinition.body`~~ — field is `template_body`, NOT `body`.

---

## Implementation Notes

### Pattern to Follow
```python
class LoadSkillArgs(BaseModel):
    name: str = Field(..., description="Skill name as listed in <available_skills>.")


class LoadSkillTool(AbstractTool):
    name: str = "load_skill"
    description: str = (
        "Load the full content of a skill from the agent's skills directory. "
        "Use after spotting a relevant skill in <available_skills>."
    )
    args_schema: Type[BaseModel] = LoadSkillArgs

    def __init__(self, file_registry: SkillFileRegistry, **kwargs):
        super().__init__(**kwargs)
        self._file_registry = file_registry

    async def _execute(self, name: str, **kwargs) -> ToolResult:
        skill = self._file_registry.get_by_name(name)
        if not skill:
            return ToolResult(status="error", error=f"Skill not found: {name}")

        assets: list[str] = []
        if skill.assets_dir:
            for p in skill.assets_dir.rglob("*"):
                if p.is_file() and p.name != "SKILL.md":
                    assets.append(str(p.relative_to(skill.assets_dir)))

        return ToolResult(
            status="done",
            result=skill.template_body,
            metadata={
                "skill_name": name,
                "category": skill.category,
                "assets": assets,
                "is_composite": skill.assets_dir is not None,
            },
        )
```

### Key Constraints
- `LoadSkillTool` takes `file_registry: SkillFileRegistry` (not `SkillRegistry` — the DB-backed one).
  This is distinct from `SearchSkillsTool` which uses the DB-backed `SkillRegistry`.
- Follow the existing tool naming convention: `name = "load_skill"`.
- `_execute` uses keyword args matching `LoadSkillArgs` fields.
- `rglob("*")` for asset discovery — skip `SKILL.md` itself.
- Update `create_skill_tools()` to accept and optionally include `LoadSkillTool` when
  `file_registry` is provided.

---

## Acceptance Criteria

- [ ] `load_skill(name="known")` returns `ToolResult(status="done")` with `template_body` as result
- [ ] `load_skill(name="unknown")` returns `ToolResult(status="error")`
- [ ] Composite skill → `metadata.assets` lists filenames, `metadata.is_composite` is `True`
- [ ] Single-file skill → `metadata.assets` is `[]`, `metadata.is_composite` is `False`
- [ ] `metadata.skill_name` and `metadata.category` are populated
- [ ] Exported: `from parrot.skills import LoadSkillTool`
- [ ] `create_skill_tools()` includes `LoadSkillTool` when `file_registry` provided
- [ ] No linting errors: `ruff check parrot/skills/tools.py`

---

## Test Specification

```python
# tests/unit/test_load_skill_tool.py
import pytest
from pathlib import Path
from parrot.skills.tools import LoadSkillTool
from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.models import SkillDefinition, SkillSource


@pytest.fixture
def registry_with_skills(tmp_path):
    registry = SkillFileRegistry(skills_dir=tmp_path)
    # Single-file skill
    registry.add(SkillDefinition(
        name="summarize", description="Summarize text",
        triggers=["/resumen"], source=SkillSource.AUTHORED,
        template_body="Summarize the input text concisely.",
        token_count=8, file_path=tmp_path / "summarize.md",
    ))
    # Composite skill with assets
    composite_dir = tmp_path / "extract-pdf"
    composite_dir.mkdir()
    (composite_dir / "script.py").write_text("# script")
    (composite_dir / "SKILL.md").write_text("placeholder")
    registry.add(SkillDefinition(
        name="extract-pdf", description="Extract tables",
        triggers=[], source=SkillSource.AUTHORED,
        template_body="Use camelot to extract tables.",
        token_count=7, file_path=composite_dir / "SKILL.md",
        assets_dir=composite_dir,
    ))
    return registry


@pytest.mark.asyncio
async def test_load_skill_found(registry_with_skills):
    tool = LoadSkillTool(file_registry=registry_with_skills)
    result = await tool._execute(name="summarize")
    assert result.status == "done"
    assert "Summarize the input text" in result.result


@pytest.mark.asyncio
async def test_load_skill_not_found(registry_with_skills):
    tool = LoadSkillTool(file_registry=registry_with_skills)
    result = await tool._execute(name="nonexistent")
    assert result.status == "error"


@pytest.mark.asyncio
async def test_load_skill_composite_manifest(registry_with_skills):
    tool = LoadSkillTool(file_registry=registry_with_skills)
    result = await tool._execute(name="extract-pdf")
    assert result.status == "done"
    assert result.metadata["is_composite"] is True
    assert "script.py" in result.metadata["assets"]


@pytest.mark.asyncio
async def test_load_skill_single_file_no_assets(registry_with_skills):
    tool = LoadSkillTool(file_registry=registry_with_skills)
    result = await tool._execute(name="summarize")
    assert result.metadata["is_composite"] is False
    assert result.metadata["assets"] == []
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/skill-registry.spec.md`
2. **Check dependencies** — verify TASK-1290 is completed
3. **Verify** `AbstractTool`, `ToolResult` signatures and `get_by_name()` method
4. **Implement** `LoadSkillTool` following the existing tool patterns in `tools.py`
5. **Update** `create_skill_tools()` to include `LoadSkillTool`
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-25
**Notes**: Added LoadSkillArgs and LoadSkillTool to tools.py. Updated create_skill_tools() to include LoadSkillTool when file_registry is provided. Exported from __init__.py. 6 tests pass.

**Deviations from spec**: none | describe if any
