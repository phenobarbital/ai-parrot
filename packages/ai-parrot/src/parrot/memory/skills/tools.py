"""
SkillRegistry Tools for AI-Parrot Agents.

Provides tools that agents can use to:
- Document learned skills/patterns
- Search for relevant skills
- Read skill content
- Update existing skills
- Save learned skills as .md files for immediate /trigger activation
"""
from typing import Any, Dict, List, Optional, Type
from pathlib import Path
from pydantic import BaseModel, Field
from ...tools.abstract import AbstractTool, ToolResult
from .models import (
    SkillCategory,
    SkillDefinition,
    SkillSource,
)
from .store import SkillRegistry


class DocumentSkillArgs(BaseModel):
    """Arguments for documenting a new skill."""
    name: str = Field(..., description="Concise skill name")
    description: str = Field(..., description="What this skill does (1-2 sentences)")
    content: str = Field(..., description="Full skill documentation in Markdown")
    category: str = Field(
        default="general",
        description="Category: tool_usage, workflow, domain, error_handling, optimization, general"
    )
    tags: List[str] = Field(default_factory=list, description="Searchable tags")
    triggers: List[str] = Field(
        default_factory=list,
        description="Patterns that should trigger using this skill"
    )
    related_tools: List[str] = Field(
        default_factory=list,
        description="Tools this skill involves"
    )


class DocumentSkillTool(AbstractTool):
    """
    Tool for agents to document learned skills and patterns.
    
    Use this when you've learned something valuable that should be remembered:
    - A successful approach to a problem
    - How to use tools effectively together
    - Domain-specific knowledge discovered
    - Patterns that work well for certain tasks
    """
    
    name: str = "document_skill"
    description: str = (
        "Document a learned skill or pattern for future reference. "
        "Use when you discover an effective approach worth remembering."
    )
    args_schema: Type[BaseModel] = DocumentSkillArgs
    
    def __init__(
        self,
        registry: SkillRegistry,
        agent_id: str,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.registry = registry
        self.agent_id = agent_id
    
    async def _execute(
        self,
        name: str,
        description: str,
        content: str,
        category: str = "general",
        tags: Optional[List[str]] = None,
        triggers: Optional[List[str]] = None,
        related_tools: Optional[List[str]] = None,
        **kwargs
    ) -> ToolResult:
        try:
            skill, version = await self.registry.upload_skill(
                name=name,
                content=content,
                agent_id=self.agent_id,
                description=description,
                category=category,
                tags=tags or [],
                triggers=triggers or [],
                related_tools=related_tools or [],
                commit_message="Documented by agent",
            )
            
            return ToolResult(
                status="done",
                result=f"Skill documented: '{name}' (v{version.version_number})",
                metadata={
                    "skill_id": skill.skill_id,
                    "version": version.version_number,
                    "category": category,
                }
            )
        except Exception as e:
            return ToolResult(
                status="error",
                error=f"Failed to document skill: {str(e)}",
            )


class UpdateSkillArgs(BaseModel):
    """Arguments for updating an existing skill."""
    skill_id: str = Field(..., description="ID of skill to update")
    content: str = Field(..., description="Updated skill content in Markdown")
    commit_message: str = Field(default="", description="What changed and why")
    name: Optional[str] = Field(default=None, description="New name (optional)")
    description: Optional[str] = Field(default=None, description="New description (optional)")


class UpdateSkillTool(AbstractTool):
    """
    Tool for updating existing skills with new versions.
    
    Use when you want to improve or correct an existing skill document.
    Creates a new version while preserving history.
    """
    
    name: str = "update_skill"
    description: str = (
        "Update an existing skill with improved content. "
        "Creates a new version while preserving history."
    )
    args_schema: Type[BaseModel] = UpdateSkillArgs
    
    def __init__(
        self,
        registry: SkillRegistry,
        agent_id: str,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.registry = registry
        self.agent_id = agent_id
    
    async def _execute(
        self,
        skill_id: str,
        content: str,
        commit_message: str = "",
        name: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        try:
            # Get existing skill
            skills = await self.registry.list_skills()
            existing = next((s for s in skills if s["skill_id"] == skill_id), None)
            
            if not existing:
                return ToolResult(
                    status="error",
                    error=f"Skill not found: {skill_id}",
                )
            
            skill, version = await self.registry.upload_skill(
                name=name or existing["name"],
                content=content,
                agent_id=self.agent_id,
                description=description or existing["description"],
                category=existing["category"],
                tags=existing["tags"],
                commit_message=commit_message or "Updated by agent",
                skill_id=skill_id,
            )
            
            return ToolResult(
                status="done",
                result=f"Skill updated: '{skill.metadata.name}' → v{version.version_number}",
                metadata={
                    "skill_id": skill_id,
                    "version": version.version_number,
                }
            )
        except Exception as e:
            return ToolResult(
                status="error",
                error=f"Failed to update skill: {str(e)}",
            )


class SkillSearchArgs(BaseModel):
    """Arguments for searching skills."""
    query: str = Field(..., description="Search query")
    category: Optional[str] = Field(default=None, description="Filter by category")
    max_results: int = Field(default=5, ge=1, le=10, description="Maximum results")


class SearchSkillsTool(AbstractTool):
    """
    Tool for searching the skill registry.
    
    Use this to find relevant skills before tackling a task.
    """
    
    name: str = "search_skills"
    description: str = (
        "Search for relevant skills and patterns. "
        "Use before tackling unfamiliar tasks to leverage existing knowledge."
    )
    args_schema: Type[BaseModel] = SkillSearchArgs
    
    def __init__(
        self,
        registry: SkillRegistry,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.registry = registry
    
    async def _execute(
        self,
        query: str,
        category: Optional[str] = None,
        max_results: int = 5,
        **kwargs
    ) -> ToolResult:
        try:
            cat = SkillCategory(category) if category else None
            results = await self.registry.search_skills(
                query=query,
                category=cat,
                max_results=max_results,
            )
            
            if not results:
                return ToolResult(
                    status="done",
                    result="No relevant skills found.",
                    metadata={"skills_found": 0}
                )
            
            # Format results
            formatted = []
            for r in results:
                formatted.append({
                    "skill_id": r.skill.skill_id,
                    "name": r.skill.metadata.name,
                    "description": r.skill.metadata.description,
                    "relevance": f"{r.relevance_score:.2f}",
                    "category": r.skill.metadata.category.value,
                    "version": r.skill.current_version,
                })
            
            summary = self._format_summary(results)
            
            return ToolResult(
                status="done",
                result=summary,
                metadata={
                    "skills_found": len(results),
                    "skills": formatted,
                }
            )
        except Exception as e:
            return ToolResult(
                status="error",
                error=f"Search failed: {str(e)}",
            )
    
    def _format_summary(self, results) -> str:
        lines = ["Found relevant skills:"]
        for r in results:
            lines.append(f"\n**{r.skill.metadata.name}** (v{r.skill.current_version})")
            lines.append(f"  {r.skill.metadata.description}")
            if r.skill.metadata.triggers:
                lines.append(f"  Use when: {', '.join(r.skill.metadata.triggers[:2])}")
        return "\n".join(lines)


class ReadSkillToolArgs(BaseModel):
    """Arguments for reading a skill."""
    skill_id: str = Field(..., description="Skill ID to read")
    version: Optional[int] = Field(default=None, description="Version number (latest if None)")


class ReadSkillTool(AbstractTool):
    """
    Tool for reading skill content.
    """
    
    name: str = "read_skill"
    description: str = "Read the full content of a skill by ID."
    args_schema: Type[BaseModel] = ReadSkillToolArgs
    
    def __init__(
        self,
        registry: SkillRegistry,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.registry = registry
    
    async def _execute(
        self,
        skill_id: str,
        version: Optional[int] = None,
        **kwargs
    ) -> ToolResult:
        try:
            content = await self.registry.read_skill(skill_id, version)
            skills = await self.registry.list_skills()
            skill_info = next((s for s in skills if s["skill_id"] == skill_id), None)
            
            return ToolResult(
                status="done",
                result=content,
                metadata={
                    "skill_id": skill_id,
                    "name": skill_info["name"] if skill_info else "Unknown",
                    "version": version or (skill_info["current_version"] if skill_info else 0),
                }
            )
        except KeyError:
            return ToolResult(
                status="error",
                error=f"Skill not found: {skill_id}",
            )
        except Exception as e:
            return ToolResult(
                status="error",
                error=f"Failed to read skill: {str(e)}",
            )


class ListSkillsTool(AbstractTool):
    """
    Tool for listing all available skills.
    """
    
    name: str = "list_skills"
    description: str = "List all available skills with summary info."
    
    def __init__(
        self,
        registry: SkillRegistry,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.registry = registry
    
    async def _execute(self, **kwargs) -> ToolResult:
        try:
            skills = await self.registry.list_skills()
            
            if not skills:
                return ToolResult(
                    status="done",
                    result="No skills documented yet.",
                    metadata={"count": 0}
                )
            
            # Group by category
            by_category: Dict[str, List] = {}
            for s in skills:
                cat = s["category"]
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append(s)
            
            lines = [f"**{len(skills)} skills available:**"]
            for cat, cat_skills in by_category.items():
                lines.append(f"\n_{cat}_:")
                for s in cat_skills:
                    lines.append(f"  • {s['name']} (v{s['current_version']})")
            
            return ToolResult(
                status="done",
                result="\n".join(lines),
                metadata={
                    "count": len(skills),
                    "skills": skills,
                }
            )
        except Exception as e:
            return ToolResult(
                status="error",
                error=f"Failed to list skills: {str(e)}",
            )


class SaveLearnedSkillArgs(BaseModel):
    """Arguments for saving a learned skill as a .md file."""
    name: str = Field(..., description="Skill name (used as filename)")
    description: str = Field(..., description="Short description of what the skill does")
    content: str = Field(..., description="Skill instruction body (markdown)")
    triggers: List[str] = Field(..., description="Trigger commands, e.g. ['/resumen']")
    category: str = Field(default="general", description="Skill category")


class SaveLearnedSkillTool(AbstractTool):
    """
    Tool for saving a learned skill as a .md file for immediate /trigger activation.

    Writes a markdown file with YAML frontmatter to the learned skills directory,
    validates it, and hot-adds it to the file registry so it's immediately available.
    """

    name: str = "save_learned_skill"
    description: str = (
        "Save a new learned skill as a .md file for immediate use via /trigger. "
        "The skill will be available in the current session immediately."
    )
    args_schema: Type[BaseModel] = SaveLearnedSkillArgs

    def __init__(
        self,
        file_registry: "SkillFileRegistry",
        learned_dir: Path,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._file_registry = file_registry
        self._learned_dir = learned_dir

    async def _execute(
        self,
        name: str,
        description: str,
        content: str,
        triggers: Optional[List[str]] = None,
        category: str = "general",
        **kwargs,
    ) -> ToolResult:
        from .parsers import parse_skill_file

        triggers = triggers or []

        # Check name collision
        for existing in self._file_registry.list_skills():
            if existing.name == name:
                return ToolResult(
                    success=False,
                    status="error",
                    result=None,
                    error=f"Skill name '{name}' already exists — collision rejected",
                )

        # Check trigger collision
        for trigger in triggers:
            if self._file_registry.has_trigger(trigger):
                return ToolResult(
                    success=False,
                    status="error",
                    result=None,
                    error=f"Trigger '{trigger}' already exists — collision rejected",
                )

        # Sanitize filename
        safe_name = "".join(
            c if c.isalnum() or c in ("_", "-") else "_" for c in name
        )
        file_path = self._learned_dir / f"{safe_name}.md"

        # Build YAML frontmatter
        triggers_yaml = "\n".join(f"  - {t}" for t in triggers)
        md_content = f"""---
name: {name}
description: {description}
triggers:
{triggers_yaml}
source: learned
category: {category}
---

{content}
"""
        # Write file
        self._learned_dir.mkdir(parents=True, exist_ok=True)
        file_path.write_text(md_content)

        # Validate via parser
        try:
            skill = parse_skill_file(file_path)
        except Exception as e:
            file_path.unlink(missing_ok=True)
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=f"Skill validation failed: {str(e)}",
            )

        # Hot-add to registry
        self._file_registry.add(skill)

        return ToolResult(
            status="done",
            result=f"Learned skill '{name}' saved and available via {', '.join(triggers)}",
            metadata={
                "name": name,
                "file_path": str(file_path),
                "triggers": triggers,
            },
        )


def create_skill_tools(
    registry: SkillRegistry,
    agent_id: str,
    include_write_tools: bool = True,
    file_registry: Optional["SkillFileRegistry"] = None,
    learned_dir: Optional[Path] = None,
) -> List[AbstractTool]:
    """
    Create skill registry tools for an agent.
    
    Args:
        registry: Configured SkillRegistry
        agent_id: Agent identifier
        include_write_tools: Include document/update tools
        
    Returns:
        List of tools
    """
    tools = [
        SearchSkillsTool(registry=registry),
        ReadSkillTool(registry=registry),
        ListSkillsTool(registry=registry),
    ]
    
    if include_write_tools:
        tools.extend([
            DocumentSkillTool(registry=registry, agent_id=agent_id),
            UpdateSkillTool(registry=registry, agent_id=agent_id),
        ])

    # Add file-based learned skill tool when file registry is available
    if file_registry is not None and learned_dir is not None:
        tools.append(
            SaveLearnedSkillTool(
                file_registry=file_registry,
                learned_dir=learned_dir,
            )
        )

    return tools