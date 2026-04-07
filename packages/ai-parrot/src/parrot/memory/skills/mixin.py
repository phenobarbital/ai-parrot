"""
SkillRegistryMixin for AbstractBot integration.

Provides automatic skill management integration:
- Skill tools exposed to agent
- Context injection of relevant skills
- Auto-extraction of skills from conversations
- File-based skill registry with eager loading
- Skill trigger middleware for /trigger patterns
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from .models import SkillCategory, SkillDefinition, SkillSource, Skill
from .store import SkillRegistry, create_skill_registry
from .tools import create_skill_tools

if TYPE_CHECKING:
    from .file_registry import SkillFileRegistry


class SkillRegistryMixin:
    """
    Mixin to add skill registry capabilities to AbstractBot.
    
    Features:
    - Auto-configure skill registry
    - Expose skill tools to agent
    - Inject relevant skills into context
    - Auto-extract skills from conversations
    
    Usage:
        class MyAgent(SkillRegistryMixin, AbstractBot):
            enable_skill_registry = True
    """
    
    # Configuration
    enable_skill_registry: bool = True
    skill_registry_expose_tools: bool = True
    skill_registry_inject_context: bool = True
    skill_registry_auto_extract: bool = False  # Expensive, opt-in
    skill_registry_max_context_skills: int = 3
    skill_registry_max_context_tokens: int = 1500
    
    # Runtime
    _skill_registry: Optional[SkillRegistry] = None
    _skill_file_registry: Optional["SkillFileRegistry"] = None
    _active_skill: Optional[SkillDefinition] = None

    async def _configure_skill_registry(self) -> None:
        """Configure skill registry during agent configure()."""
        if not self.enable_skill_registry:
            return
        
        if self._skill_registry is not None:
            return
        
        agent_id = getattr(self, 'name', None) or getattr(self, 'agent_id', 'default')
        org_id = getattr(self, 'org_id', 'default')
        namespace = f"{org_id}/{agent_id}"
        
        # Determine persistence path
        persistence_path = None
        agents_dir = getattr(self, '_agents_dir', None)
        if agents_dir:
            persistence_path = agents_dir / agent_id / "skills"
        
        self._skill_registry = create_skill_registry(
            namespace=namespace,
            persistence_path=persistence_path,
            extraction_llm=getattr(self, '_llm', None),
        )
        
        await self._skill_registry.configure()
        
        # Add tools
        if self.skill_registry_expose_tools:
            await self._add_skill_tools()
        
        # Configure file-based skill registry
        await self._configure_skill_file_registry()

        if hasattr(self, 'logger'):
            self.logger.info(f"SkillRegistry configured: {namespace}")

    async def _configure_skill_file_registry(self) -> None:
        """Configure file-based skill registry and trigger middleware.

        Resolves ``AGENTS_DIR/{agent_id}/skills/`` and loads all .md skill files.
        Registers SkillTriggerMiddleware in the bot's prompt pipeline.
        """
        from .file_registry import SkillFileRegistry
        from .middleware import create_skill_trigger_middleware

        if self._skill_file_registry is not None:
            return

        agent_id = getattr(self, 'name', None) or getattr(self, 'agent_id', 'default')
        agents_dir = getattr(self, '_agents_dir', None)
        if not agents_dir:
            return

        skills_dir = agents_dir / agent_id / "skills"
        learned_dir = skills_dir / "learned"

        # Create directories if they don't exist
        skills_dir.mkdir(parents=True, exist_ok=True)
        learned_dir.mkdir(parents=True, exist_ok=True)

        self._skill_file_registry = SkillFileRegistry(
            skills_dir=skills_dir,
            learned_dir=learned_dir,
        )
        await self._skill_file_registry.load()

        # Register trigger middleware in prompt pipeline
        prompt_pipeline = getattr(self, '_prompt_pipeline', None)
        if prompt_pipeline is not None:
            mw = create_skill_trigger_middleware(
                registry=self._skill_file_registry,
                bot=self,
            )
            prompt_pipeline.add(mw)

        logger = getattr(self, 'logger', logging.getLogger(__name__))
        n_skills = len(self._skill_file_registry.list_skills())
        logger.info(
            "SkillFileRegistry loaded: %d skills from %s",
            n_skills,
            skills_dir,
        )

    async def save_learned_skill(
        self,
        name: str,
        content: str,
        description: str,
        triggers: List[str],
        category: str = "general",
    ) -> Optional[SkillDefinition]:
        """Save a learned skill as a .md file and hot-add to the registry.

        Writes a markdown file with YAML frontmatter to the learned skills
        directory and makes it immediately available in the current session.

        Args:
            name: Skill name (used as filename).
            description: Short description of the skill.
            content: Skill instruction body (markdown).
            triggers: Trigger commands, e.g. ['/resumen'].
            category: Skill category.

        Returns:
            The created SkillDefinition, or None if the save failed.
        """
        if not self._skill_file_registry:
            return None

        from .parsers import parse_skill_file

        logger = getattr(self, 'logger', logging.getLogger(__name__))

        # Check name collision
        for existing in self._skill_file_registry.list_skills():
            if existing.name == name:
                logger.error("Skill name '%s' already exists — cannot save", name)
                return None

        # Resolve learned directory
        learned_dir = self._skill_file_registry.learned_dir
        learned_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize filename
        safe_name = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in name)
        file_path = learned_dir / f"{safe_name}.md"

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
        file_path.write_text(md_content)

        # Validate via parser
        try:
            skill = parse_skill_file(file_path)
        except Exception as exc:
            logger.error("Failed to validate learned skill '%s': %s", name, exc)
            file_path.unlink(missing_ok=True)
            return None

        # Hot-add to registry
        self._skill_file_registry.add(skill)
        logger.info("Learned skill '%s' saved and hot-added", name)
        return skill

    async def _add_skill_tools(self) -> None:
        """Add skill tools to agent."""
        if not self._skill_registry:
            return
        
        agent_id = getattr(self, 'name', 'agent')
        tools = create_skill_tools(
            registry=self._skill_registry,
            agent_id=agent_id,
            include_write_tools=True,
        )
        
        tool_manager = getattr(self, 'tool_manager', None)
        if tool_manager and hasattr(tool_manager, 'register_tool'):
            for tool in tools:
                await tool_manager.register_tool(tool)
        elif hasattr(self, '_tools'):
            self._tools = getattr(self, '_tools', []) + tools
    
    async def get_skill_context(
        self,
        query: str,
        max_skills: Optional[int] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Get relevant skills for context injection.
        
        Returns formatted Markdown for system prompt.
        """
        if not self._skill_registry or not self.skill_registry_inject_context:
            return ""
        
        return await self._skill_registry.get_relevant_skills(
            query=query,
            max_skills=max_skills or self.skill_registry_max_context_skills,
            max_tokens=max_tokens or self.skill_registry_max_context_tokens,
        )
    
    async def document_skill(
        self,
        name: str,
        content: str,
        description: str = "",
        category: str = "general",
        tags: Optional[List[str]] = None,
        triggers: Optional[List[str]] = None,
    ) -> Optional[Skill]:
        """
        Programmatically document a skill.
        
        Returns created Skill or None.
        """
        if not self._skill_registry:
            return None
        
        agent_id = getattr(self, 'name', 'agent')
        skill, _ = await self._skill_registry.upload_skill(
            name=name,
            content=content,
            agent_id=agent_id,
            description=description,
            category=category,
            tags=tags or [],
            triggers=triggers or [],
        )
        return skill
    
    async def extract_skills_from_conversation(
        self,
        conversation: str,
        context: Optional[str] = None,
    ) -> Optional[Skill]:
        """
        Use LLM to extract skills from conversation.
        
        Should be called selectively (expensive).
        """
        if not self._skill_registry or not self.skill_registry_auto_extract:
            return None
        
        agent_id = getattr(self, 'name', 'agent')
        result = await self._skill_registry.extract_skill_from_conversation(
            conversation=conversation,
            agent_id=agent_id,
            context=context,
        )
        
        return result[0] if result else None
    
    async def search_skills(
        self,
        query: str,
        category: Optional[str] = None,
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """Search for relevant skills."""
        if not self._skill_registry:
            return []
        
        cat = SkillCategory(category) if category else None
        results = await self._skill_registry.search_skills(
            query=query,
            category=cat,
            max_results=max_results,
        )
        
        return [
            {
                "skill_id": r.skill.skill_id,
                "name": r.skill.metadata.name,
                "description": r.skill.metadata.description,
                "content": r.content,
                "relevance": r.relevance_score,
            }
            for r in results
        ]
    
    async def _cleanup_skill_registry(self) -> None:
        """Cleanup skill registry."""
        if self._skill_registry:
            await self._skill_registry.cleanup()
            self._skill_registry = None


class SkillRegistryHooks:
    """Hook functions for skill registry integration."""
    
    @staticmethod
    async def pre_ask_hook(
        agent: SkillRegistryMixin,
        query: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Get relevant skills before ask()."""
        context = await agent.get_skill_context(query)
        return {"skill_context": context}
    
    @staticmethod
    async def post_ask_hook(
        agent: SkillRegistryMixin,
        query: str,
        response: Any,
        **kwargs
    ) -> None:
        """Optionally extract skills after ask()."""
        if not agent.skill_registry_auto_extract:
            return
        
        conversation = f"User: {query}\nAssistant: {response}"
        await agent.extract_skills_from_conversation(conversation)