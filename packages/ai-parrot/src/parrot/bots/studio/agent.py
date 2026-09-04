"""AgentStudioAgent — the AgentStudio meta-agent (FEAT-467 TASK-2521).

Lets users build agents, skills, and knowledge-base files through natural
language conversation. Absorbs the ``AgentFactory`` YAML-agent flow (its
``create_yaml_agent`` tool reuses ``parrot.bots.factory.tools.finalize.
finalize_agent_registration`` directly) and ships three authored composite
skills (``agent-builder``, ``skill-writer``, ``kb-writer``) alongside its
HITL-gated tools.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from parrot.bots.agent import Agent
from parrot.conf import STUDIO_AGENT_MODEL
from parrot.skills.mixin import SkillRegistryMixin

from .tools import build_studio_tools

#: Composite skills shipped with the package — agent-builder, skill-writer,
#: kb-writer (each ``<skill>/SKILL.md`` + assets — SkillRegistryMixin's
#: directory discovery, FEAT-188).
_SKILLS_DIR = Path(__file__).parent / "skills"

_SYSTEM_PROMPT = """\
You are AgentStudio, an assistant that helps users build AI agents, \
skills, and knowledge-base files for the ai-parrot framework through \
natural language conversation.

You can:
- Scaffold a new Python agent as a DRAFT (save_agent_draft) — drafts are
  never live code; a human must explicitly activate one via the Studio
  drafts endpoint before it becomes a real, running agent.
- Create a simple, non-code-generated agent from an existing base class
  (create_yaml_agent) — this writes a lossless YAML definition and
  registers it immediately.
- Write or update an existing agent's identity, knowledge-base, or skill
  files (write_identity_file / write_kb_file / write_skill_file).
- Publish a new skill to the shared, org-wide skills catalog
  (publish_skill_to_catalog).
- Look up available agent base classes, tools, and already-registered
  agents (list_agent_base_classes / list_available_tools /
  list_existing_agents) before proposing a design.

Every writing tool asks for explicit human confirmation before it runs —
always explain exactly what you are about to write and where before
calling one. Follow the agent-builder, skill-writer, and kb-writer skills
for the conventions each artifact type must follow.
"""


class AgentStudioAgent(SkillRegistryMixin, Agent):
    """Meta-agent for AgentStudio (spec §3 Module 13).

    Attributes:
        skill_paths: The package's bundled ``skills/`` directory —
            discovered by :class:`~parrot.skills.mixin.SkillRegistryMixin`
            at ``configure()`` time (FEAT-188).
    """

    skill_paths: ClassVar[list[Path]] = [_SKILLS_DIR]

    def __init__(
        self,
        name: str = "agent_studio",
        api_key: str | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Build the AgentStudio meta-agent.

        Args:
            name: Bot instance name.
            api_key: Optional Anthropic API key override — the caller
                (``StudioAssistantHandler``) resolves the session's BYOK
                key (TASK-2516) BEFORE construction and passes it here;
                ``None`` falls back to the server's configured
                ``ANTHROPIC_API_KEY`` (``AnthropicClient``'s own default).
            model: Optional model id override. Falls back to
                ``parrot.conf.STUDIO_AGENT_MODEL``.
            system_prompt: Optional system prompt override. Falls back to
                this module's default AgentStudio prompt.
            **kwargs: Forwarded to :class:`~parrot.bots.agent.Agent`. An
                explicit ``llm=`` kwarg (instance/class/string) takes
                precedence over the ``api_key``/``model`` construction
                path below.
        """
        llm = kwargs.pop("llm", None)
        if llm is None:
            # FEAT-523 (TASK-2846): lazy import — core must not import a
            # provider module at module scope (AC-3).
            from parrot.clients.anthropic import AnthropicClient
            resolved_model = model or STUDIO_AGENT_MODEL
            llm = AnthropicClient(api_key=api_key, model=resolved_model)
        super().__init__(
            name=name,
            llm=llm,
            system_prompt=system_prompt or _SYSTEM_PROMPT,
            **kwargs,
        )

    def agent_tools(self) -> list:
        """Return the AgentStudio-specific tool set (FEAT-467 TASK-2521)."""
        return [*super().agent_tools(), *build_studio_tools()]
