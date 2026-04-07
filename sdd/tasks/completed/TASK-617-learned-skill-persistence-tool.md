# TASK-617: Learned Skill Persistence Tool

**Feature**: Agent Skill System
**Spec**: `sdd/specs/agent-skill-system.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-613, TASK-614, TASK-616
**Assigned-to**: unassigned

---

## Context

> Module 5 of FEAT-088. Adapts or creates a tool (`SaveLearnedSkillTool`) that allows
> agents to write `.md` skill files to `skills/learned/` with proper YAML frontmatter,
> validate them, and hot-add to the registry for immediate availability.
> See spec Section 3, Module 5.

---

## Scope

- Create `SaveLearnedSkillTool` class in `parrot/memory/skills/tools.py` (extend existing file)
- The tool:
  - Accepts: `name`, `description`, `content` (skill body), `triggers` (list), `category`
  - Writes a `.md` file to `skills/learned/{name}.md` with YAML frontmatter
  - Validates the file via `parse_skill_file()`
  - Hot-adds the skill to `SkillFileRegistry` via `registry.add()`
  - Rejects if name collides with an existing skill
  - Returns `ToolResult` with success/failure message
- Create `SaveLearnedSkillArgs` pydantic model for the tool's args_schema
- Add the tool to `create_skill_tools()` output when file registry is available
- Adapt `SkillRegistryMixin.save_learned_skill()` (from TASK-616) to use this tool internally if needed
- Write unit tests

**NOT in scope**: Modifying existing `DocumentSkillTool` (leave it for vector-based registry)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/skills/tools.py` | MODIFY | Add SaveLearnedSkillTool, SaveLearnedSkillArgs |
| `packages/ai-parrot/src/parrot/memory/skills/__init__.py` | MODIFY | Export SaveLearnedSkillTool |
| `packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Existing tool base class:
from parrot.tools import AbstractTool, ToolResult  # verify exact import path

# Existing tools in same file:
from parrot.memory.skills.tools import DocumentSkillTool, create_skill_tools  # verified: tools.py

# From TASK-613/614:
from parrot.memory.skills.models import SkillDefinition, SkillSource  # TASK-613
from parrot.memory.skills.parsers import parse_skill_file  # TASK-613
from parrot.memory.skills.file_registry import SkillFileRegistry  # TASK-614

# Standard:
from pydantic import BaseModel, Field
from pathlib import Path
from typing import List, Optional, Type
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/skills/tools.py:39-104
class DocumentSkillTool(AbstractTool):
    name: str = "document_skill"
    description: str = "..."
    args_schema: Type[BaseModel] = DocumentSkillArgs
    def __init__(self, registry: SkillRegistry, agent_id: str, **kwargs):  # line 57
    async def _execute(self, name, description, content, category, tags, triggers, related_tools, **kwargs) -> ToolResult:  # line 67

# packages/ai-parrot/src/parrot/memory/skills/tools.py:387
def create_skill_tools(registry: SkillRegistry, agent_id: str, include_write_tools: bool = True) -> List[AbstractTool]:

# SkillFileRegistry (TASK-614):
class SkillFileRegistry:
    def add(self, skill: SkillDefinition) -> None: ...
    def has_trigger(self, trigger: str) -> bool: ...
```

### Does NOT Exist
- ~~`SaveLearnedSkillTool`~~ — does not exist yet; MUST be created in this task
- ~~`save_skill` tool~~ — existing tool is `DocumentSkillTool` (name="document_skill")
- ~~`SkillFileRegistry.save()`~~ — no save method; write file manually then call `add()`

---

## Implementation Notes

### Pattern to Follow
```python
class SaveLearnedSkillArgs(BaseModel):
    name: str = Field(..., description="Skill name (used as filename)")
    description: str = Field(..., description="Short description of what the skill does")
    content: str = Field(..., description="Skill instruction body (markdown)")
    triggers: List[str] = Field(..., description="Trigger commands, e.g. ['/resumen']")
    category: str = Field(default="general", description="Skill category")


class SaveLearnedSkillTool(AbstractTool):
    name: str = "save_learned_skill"
    description: str = "Save a new learned skill as a .md file for immediate use via /trigger"
    args_schema: Type[BaseModel] = SaveLearnedSkillArgs

    def __init__(self, file_registry: SkillFileRegistry, learned_dir: Path, **kwargs):
        super().__init__(**kwargs)
        self._file_registry = file_registry
        self._learned_dir = learned_dir

    async def _execute(self, name, description, content, triggers, category="general", **kwargs) -> ToolResult:
        # 1. Check name collision
        # 2. Write .md file with YAML frontmatter to learned_dir/{name}.md
        # 3. Parse via parse_skill_file() to validate
        # 4. Hot-add via file_registry.add()
        # 5. Return success/failure ToolResult
        ...
```

### YAML Frontmatter Format
```yaml
---
name: {name}
description: {description}
triggers:
  - {trigger1}
  - {trigger2}
source: learned
category: {category}
---

{content}
```

### Key Constraints
- Must validate the written file via `parse_skill_file()` — catches token limit violations
- Name collision → reject with error, do NOT overwrite
- File written to `skills/learned/{name}.md` — sanitize `name` for filesystem safety
- Hot-add to registry so skill is immediately available without restart

---

## Acceptance Criteria

- [ ] `SaveLearnedSkillTool` writes `.md` file with valid YAML frontmatter
- [ ] File written to `skills/learned/{name}.md`
- [ ] Written file validates via `parse_skill_file()`
- [ ] Skill hot-added to `SkillFileRegistry` after save
- [ ] Name collision rejected with error message
- [ ] Token limit enforced (content exceeding 1000 tokens rejected)
- [ ] Tool included in `create_skill_tools()` when file registry available
- [ ] Exported from `parrot/memory/skills/__init__.py`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py
import pytest
from pathlib import Path
from parrot.memory.skills.tools import SaveLearnedSkillTool
from parrot.memory.skills.file_registry import SkillFileRegistry
from parrot.memory.skills.models import SkillDefinition


@pytest.fixture
def skills_dir(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "learned").mkdir()
    return d


@pytest.fixture
async def registry(skills_dir):
    reg = SkillFileRegistry(skills_dir)
    await reg.load()
    return reg


@pytest.fixture
def tool(registry, skills_dir):
    return SaveLearnedSkillTool(
        file_registry=registry,
        learned_dir=skills_dir / "learned",
    )


class TestSaveLearnedSkillTool:
    @pytest.mark.asyncio
    async def test_writes_md_file(self, tool, skills_dir):
        result = await tool._execute(
            name="extraer_datos",
            description="Extrae datos de texto",
            content="Instrucciones para extraer datos...",
            triggers=["/extraer"],
        )
        assert result.success  # or check result content
        assert (skills_dir / "learned" / "extraer_datos.md").exists()

    @pytest.mark.asyncio
    async def test_hot_adds_to_registry(self, tool, registry):
        await tool._execute(
            name="nuevo",
            description="Test skill",
            content="Do something",
            triggers=["/nuevo"],
        )
        assert registry.get("/nuevo") is not None

    @pytest.mark.asyncio
    async def test_name_collision(self, tool, registry):
        # Add first
        await tool._execute(
            name="duplicado",
            description="First",
            content="Body",
            triggers=["/dup1"],
        )
        # Try duplicate
        result = await tool._execute(
            name="duplicado",
            description="Second",
            content="Body",
            triggers=["/dup2"],
        )
        # Should be rejected
        assert "collision" in str(result).lower() or "exists" in str(result).lower()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agent-skill-system.spec.md` for full context
2. **Check dependencies** — verify TASK-613, TASK-614, TASK-616 are in `tasks/completed/`
3. **Verify the Codebase Contract** — read `tools.py` to understand existing tool patterns
4. **Verify `AbstractTool` and `ToolResult` imports** — grep for exact import path
5. **Update status** in `tasks/.index.json` → `"in-progress"`
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `tasks/completed/TASK-617-learned-skill-persistence-tool.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
