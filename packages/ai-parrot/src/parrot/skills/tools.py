"""
SkillRegistry Tools for AI-Parrot Agents.

Provides tools that agents can use to:
- Document learned skills/patterns
- Search for relevant skills
- Read skill content
- Update existing skills
- Save learned skills as .md files for immediate /trigger activation

Tools are grouped into two toolkits, each initialized once with its shared
dependency:

- :class:`SkillRegistryToolkit` — DB-backed registry (search/read/list/
  document/update), sharing a :class:`~parrot.skills.store.SkillRegistry`.
- :class:`SkillFileToolkit` — file-based skills (load/read_asset/save_learned),
  sharing a :class:`~parrot.skills.file_registry.SkillFileRegistry`.
"""
import asyncio
from typing import Dict, List, Optional, Type
from pathlib import Path
from pydantic import BaseModel, Field
from ..tools.abstract import AbstractTool, ToolResult
from ..tools.toolkit import AbstractToolkit
from ..tools.decorators import tool_schema
from .models import (
    SkillCategory,
    SearchSkillArgs,
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


class UpdateSkillArgs(BaseModel):
    """Arguments for updating an existing skill."""
    skill_id: str = Field(..., description="ID of skill to update")
    content: str = Field(..., description="Updated skill content in Markdown")
    commit_message: str = Field(default="", description="What changed and why")
    name: Optional[str] = Field(default=None, description="New name (optional)")
    description: Optional[str] = Field(default=None, description="New description (optional)")


class ReadSkillToolArgs(BaseModel):
    """Arguments for reading a skill."""
    skill_id: str = Field(..., description="Skill ID to read")
    version: Optional[int] = Field(default=None, description="Version number (latest if None)")


class SkillRegistryToolkit(AbstractToolkit):
    """Unified toolkit for the DB-backed skill registry, sharing one store.

    Every public async method becomes a tool whose name equals the method name
    (no ``tool_prefix`` is applied, so ``search_skills``, ``read_skill``,
    ``list_skills``, ``document_skill`` and ``update_skill`` keep their
    historical names). The :class:`~parrot.skills.store.SkillRegistry` and the
    ``agent_id`` are injected once and shared by every tool, replacing the
    previous one-class-per-tool wiring.

    Write tools (``document_skill``, ``update_skill``) are exposed only when
    ``include_write_tools`` is ``True``.

    Args:
        registry: Configured DB-backed :class:`~parrot.skills.store.SkillRegistry`.
        agent_id: Agent identifier, recorded as the author of documented/updated
            skills.
        include_write_tools: When ``False``, ``document_skill`` and
            ``update_skill`` are not exposed.
    """

    def __init__(
        self,
        registry: SkillRegistry,
        agent_id: str,
        include_write_tools: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._registry = registry
        self._agent_id = agent_id
        # Hide write tools when the caller asked for read-only access.
        if not include_write_tools:
            self.exclude_tools = ("document_skill", "update_skill")

    @tool_schema(SearchSkillArgs)
    async def search_skills(
        self,
        query: str,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        include_deprecated: bool = False,
        max_results: int = 5,
    ) -> ToolResult:
        """Search for relevant skills and patterns. Use before tackling
        unfamiliar tasks to leverage existing knowledge.
        """
        try:
            cat = SkillCategory(category) if category else None
            results = await self._registry.search_skills(
                query=query,
                category=cat,
                tags=tags,
                include_deprecated=include_deprecated,
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
                result=None,
                error=f"Search failed: {str(e)}",
            )

    def _format_summary(self, results) -> str:
        """Render a human-readable summary of search results (internal helper)."""
        lines = ["Found relevant skills:"]
        for r in results:
            lines.append(f"\n**{r.skill.metadata.name}** (v{r.skill.current_version})")
            lines.append(f"  {r.skill.metadata.description}")
            if r.skill.metadata.triggers:
                lines.append(f"  Use when: {', '.join(r.skill.metadata.triggers[:2])}")
        return "\n".join(lines)

    @tool_schema(ReadSkillToolArgs)
    async def read_skill(
        self,
        skill_id: str,
        version: Optional[int] = None,
    ) -> ToolResult:
        """Read the full content of a skill by ID."""
        try:
            content = await self._registry.read_skill(skill_id, version)
            skills = await self._registry.list_skills()
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
                result=None,
                error=f"Skill not found: {skill_id}",
            )
        except Exception as e:
            return ToolResult(
                status="error",
                result=None,
                error=f"Failed to read skill: {str(e)}",
            )

    async def list_skills(self) -> ToolResult:
        """List all available skills with summary info."""
        try:
            skills = await self._registry.list_skills()

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
                result=None,
                error=f"Failed to list skills: {str(e)}",
            )

    @tool_schema(DocumentSkillArgs)
    async def document_skill(
        self,
        name: str,
        description: str,
        content: str,
        category: str = "general",
        tags: Optional[List[str]] = None,
        triggers: Optional[List[str]] = None,
        related_tools: Optional[List[str]] = None,
    ) -> ToolResult:
        """Document a learned skill or pattern for future reference. Use when
        you discover an effective approach worth remembering.
        """
        try:
            skill, version = await self._registry.upload_skill(
                name=name,
                content=content,
                agent_id=self._agent_id,
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
                result=None,
                error=f"Failed to document skill: {str(e)}",
            )

    @tool_schema(UpdateSkillArgs)
    async def update_skill(
        self,
        skill_id: str,
        content: str,
        commit_message: str = "",
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> ToolResult:
        """Update an existing skill with improved content. Creates a new version
        while preserving history.
        """
        try:
            # Get existing skill
            skills = await self._registry.list_skills()
            existing = next((s for s in skills if s["skill_id"] == skill_id), None)

            if not existing:
                return ToolResult(
                    status="error",
                    error=f"Skill not found: {skill_id}",
                )

            skill, version = await self._registry.upload_skill(
                name=name or existing["name"],
                content=content,
                agent_id=self._agent_id,
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
                result=None,
                error=f"Failed to update skill: {str(e)}",
            )


class SaveLearnedSkillArgs(BaseModel):
    """Arguments for saving a learned skill as a .md file."""
    name: str = Field(..., description="Skill name (used as filename)")
    description: str = Field(..., description="Short description of what the skill does")
    content: str = Field(..., description="Skill instruction body (markdown)")
    triggers: List[str] = Field(..., description="Trigger commands, e.g. ['/resumen']")
    category: str = Field(default="general", description="Skill category")


class LoadSkillArgs(BaseModel):
    """Arguments for loading a skill's full content on demand."""

    name: str = Field(..., description="Skill name as listed in <available_skills>.")


class ReadSkillAssetArgs(BaseModel):
    """Arguments for reading a bundled asset of a composite skill."""

    skill_name: str = Field(
        ...,
        description="Skill name as listed in <available_skills>.",
    )
    asset: str = Field(
        ...,
        description=(
            "Asset filename relative to the skill directory, as listed in the "
            "'assets' manifest returned by load_skill (e.g. 'template.md')."
        ),
    )


class SkillFileToolkit(AbstractToolkit):
    """Unified toolkit for file-based skills, sharing one ``SkillFileRegistry``.

    Every public async method becomes a tool whose name equals the method name
    (no ``tool_prefix`` is applied, so ``load_skill``, ``read_skill_asset`` and
    ``save_learned_skill`` keep the historical names referenced by the
    ``<available_skills>`` prompt layer). The registry is injected once and
    shared by every tool, replacing the previous one-class-per-tool wiring.

    Tiers:

    - ``load_skill`` (Tier 2): full skill body + asset manifest for composite
      skills.
    - ``read_skill_asset`` (Tier 2): sandboxed reader for a bundled asset.
    - ``save_learned_skill``: persist an LLM-authored skill for immediate use.

    Args:
        file_registry: Shared
            :class:`~parrot.skills.file_registry.SkillFileRegistry`.
        learned_dir: Directory where learned skills are written. When ``None``
            the ``save_learned_skill`` tool is not exposed.
        max_asset_bytes: Truncation ceiling for ``read_skill_asset``. Defaults
            to 64 KiB.
    """

    def __init__(
        self,
        file_registry: "SkillFileRegistry",
        learned_dir: Optional[Path] = None,
        max_asset_bytes: int = 64 * 1024,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._file_registry = file_registry
        self._learned_dir = learned_dir
        self._max_asset_bytes = max_asset_bytes
        # Only expose save_learned_skill when we have somewhere to write.
        if learned_dir is None:
            self.exclude_tools = ("save_learned_skill",)

    @tool_schema(LoadSkillArgs)
    async def load_skill(self, name: str) -> ToolResult:
        """Load the full content of a skill from the agent's skills directory.
        Use after spotting a relevant skill in <available_skills>.

        Returns ``status="done"`` with ``result=template_body``; for composite
        skills, ``metadata["assets"]`` lists the bundled asset filenames and
        ``metadata["is_composite"]`` is ``True``.
        """
        skill = self._file_registry.get_by_name(name)
        if not skill:
            return ToolResult(
                status="error", result=None, error=f"Skill not found: {name}"
            )

        assets: List[str] = []
        if skill.assets_dir:
            def _list_assets(assets_dir: Path) -> List[str]:
                return [
                    p.name
                    for p in sorted(assets_dir.iterdir())
                    if p.is_file() and p.name != "SKILL.md"
                ]

            assets = await asyncio.to_thread(_list_assets, skill.assets_dir)

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

    @tool_schema(ReadSkillAssetArgs)
    async def read_skill_asset(self, skill_name: str, asset: str) -> ToolResult:
        """Read the content of an asset bundled with a composite skill
        (template, script, example). Use after load_skill lists the skill's
        assets. Pass the skill name and the asset filename.

        Access is sandboxed to the skill's ``assets_dir``: paths that escape
        the directory (traversal) are rejected, and ``SKILL.md`` is reserved
        for ``load_skill``.
        """
        skill = self._file_registry.get_by_name(skill_name)
        if not skill:
            return ToolResult(
                status="error", result=None, error=f"Skill not found: {skill_name}"
            )
        if not skill.assets_dir:
            return ToolResult(
                status="error",
                result=None,
                error=(
                    f"Skill '{skill_name}' is a single-file skill and has no "
                    "bundled assets."
                ),
            )

        def _read(assets_dir: Path, rel: str) -> tuple[Optional[str], Optional[str]]:
            base = assets_dir.resolve()
            target = (base / rel).resolve()
            # Sandbox: the resolved target must stay within assets_dir.
            if base != target and base not in target.parents:
                return None, f"Asset path escapes the skill directory: {rel}"
            if target.name == "SKILL.md":
                return None, "Use load_skill to read the skill body (SKILL.md)."
            if not target.is_file():
                return None, f"Asset not found: {rel}"
            data = target.read_bytes()
            truncated = len(data) > self._max_asset_bytes
            text = data[: self._max_asset_bytes].decode("utf-8", errors="replace")
            if truncated:
                text += f"\n\n[... truncated at {self._max_asset_bytes} bytes ...]"
            return text, None

        content, err = await asyncio.to_thread(_read, skill.assets_dir, asset)
        if err is not None:
            return ToolResult(status="error", result=None, error=err)

        return ToolResult(
            status="done",
            result=content,
            metadata={"skill_name": skill_name, "asset": asset},
        )

    @tool_schema(SaveLearnedSkillArgs)
    async def save_learned_skill(
        self,
        name: str,
        description: str,
        content: str,
        triggers: Optional[List[str]] = None,
        category: str = "general",
    ) -> ToolResult:
        """Save a new learned skill as a .md file for immediate use via /trigger.
        The skill will be available in the current session immediately.
        """
        from .parsers import parse_skill_file

        if self._learned_dir is None:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error="No learned skills directory configured.",
            )

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
    """Create skill registry tools for an agent.

    Thin factory that instantiates the two skill toolkits and concatenates
    their generated tools.

    Args:
        registry: Configured SkillRegistry (DB-backed).
        agent_id: Agent identifier string.
        include_write_tools: If ``True``, include the ``document_skill`` /
            ``update_skill`` write tools from :class:`SkillRegistryToolkit`.
        file_registry: Optional :class:`~parrot.skills.file_registry.SkillFileRegistry`
            for file-based tools. When provided, the file-based tools from
            :class:`SkillFileToolkit` (``load_skill``, ``read_skill_asset`` and,
            when ``learned_dir`` is set, ``save_learned_skill``) are included.
        learned_dir: Path to the learned skills directory, required to expose
            the ``save_learned_skill`` tool.

    Returns:
        List of :class:`~parrot.tools.abstract.AbstractTool` instances.
    """
    tools: List[AbstractTool] = list(
        SkillRegistryToolkit(
            registry=registry,
            agent_id=agent_id,
            include_write_tools=include_write_tools,
        ).get_tools()
    )

    # Add file-based tools when file registry is available. All file-based
    # tools share the single SkillFileToolkit; save_learned_skill is exposed
    # only when a learned_dir is provided.
    if file_registry is not None:
        tools.extend(
            SkillFileToolkit(
                file_registry=file_registry,
                learned_dir=learned_dir,
            ).get_tools()
        )

    return tools
