"""
AI-Parrot Skills Module (top-level namespace).

Git-like versioned skill/knowledge registry that enables agents to:
- Document learned skills and patterns
- Version control with unified diffs
- Search and discover relevant skills
- Auto-extract skills from conversations

Usage:
    from parrot.skills import (
        SkillRegistry,
        SkillRegistryMixin,
        create_skill_tools,
    )

    # Option 1: Use mixin
    class MyAgent(SkillRegistryMixin, AbstractBot):
        enable_skill_registry = True

    # Option 2: Use registry directly
    registry = SkillRegistry(namespace="my_org/my_agent")
    await registry.configure()

    skill, version = await registry.upload_skill(
        name="Database Query Pattern",
        content="# How to query efficiently...",
        agent_id="my_agent",
    )
"""

from .models import (
    Skill,
    SkillVersion,
    SkillMetadata,
    SkillCategory,
    SkillStatus,
    ContentType,
    SkillSource,
    SkillDefinition,
    SkillSearchResult,
    UploadSkillArgs,
    SearchSkillArgs,
    ReadSkillArgs,
    ExtractedSkill,
)

from .parsers import parse_skill_file, parse_skill_directory
from .file_registry import SkillFileRegistry
from .loader import SkillsDirectoryLoader
from .prompt import render_skills_prompt_layer
from .middleware import create_skill_trigger_middleware

from .store import (
    SkillRegistry,
    create_skill_registry,
    compute_unified_diff,
    apply_unified_diff,
)

from .tools import (
    SkillRegistryToolkit,
    SkillFileToolkit,
    create_skill_tools,
)

from .mixin import (
    SkillRegistryMixin,
    SkillRegistryHooks,
)

__all__ = [
    # Models
    "Skill",
    "SkillVersion",
    "SkillMetadata",
    "SkillCategory",
    "SkillStatus",
    "ContentType",
    "SkillSource",
    "SkillDefinition",
    "SkillSearchResult",
    "UploadSkillArgs",
    "SearchSkillArgs",
    "ReadSkillArgs",
    "ExtractedSkill",
    # Parsers
    "parse_skill_file",
    "parse_skill_directory",
    # File Registry
    "SkillFileRegistry",
    # Loader
    "SkillsDirectoryLoader",
    # Prompt layer factory
    "render_skills_prompt_layer",
    # Middleware
    "create_skill_trigger_middleware",
    # Store
    "SkillRegistry",
    "create_skill_registry",
    "compute_unified_diff",
    "apply_unified_diff",
    # Tools
    "SkillRegistryToolkit",
    "SkillFileToolkit",
    "create_skill_tools",
    # Mixin
    "SkillRegistryMixin",
    "SkillRegistryHooks",
]
