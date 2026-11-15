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
from parrot.conf import STUDIO_AGENT_LLM, STUDIO_AGENT_MODEL
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


#: Model used when ``STUDIO_AGENT_MODEL`` is unset, per provider key. A provider
#: missing here uses its client class's own default model.
_PROVIDER_DEFAULT_MODELS: dict[str, str] = {"anthropic": "claude-opus-5"}


def studio_agent_provider() -> str:
    """Return the configured Studio Assistant provider key (``STUDIO_AGENT_LLM``), normalised.

    This is the single source of the provider name: the agent builds its client
    from it and the HTTP handler resolves BYOK keys / key-source choice with it.

    Returns:
        The lower-cased provider key (``"anthropic"`` by default).
    """
    return str(STUDIO_AGENT_LLM or "anthropic").strip().lower()


def _resolve_studio_client_class(provider: str) -> type:
    """Resolve ``provider`` through the client registry (lazy; no provider module at import time).

    Raises:
        ValueError: If ``provider`` is not a registered client provider.
    """
    from parrot.clients.factory import SUPPORTED_CLIENTS

    if provider not in SUPPORTED_CLIENTS:
        raise ValueError(
            f"Unknown STUDIO_AGENT_LLM provider '{provider}'. "
            f"Supported: {sorted(SUPPORTED_CLIENTS)}"
        )
    client_class = SUPPORTED_CLIENTS[provider]
    if callable(client_class) and not isinstance(client_class, type):
        client_class = client_class()
    return client_class


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
        declarative_only: bool = False,
        **kwargs: Any,
    ) -> None:
        """Build the AgentStudio meta-agent.

        Args:
            name: Bot instance name.
            api_key: Optional API key override for the configured provider
                (``STUDIO_AGENT_LLM``) — the caller (``StudioAssistantHandler``)
                resolves the session's BYOK key (TASK-2516) BEFORE construction
                and passes it here; ``None`` falls back to the provider
                client's own server-key default (e.g. ``ANTHROPIC_API_KEY``,
                ``GOOGLE_API_KEY``).
            model: Optional model id override. Falls back to
                ``parrot.conf.STUDIO_AGENT_MODEL`` and, when that is unset, to
                the configured provider's own default model.
            system_prompt: Optional system prompt override. Falls back to
                this module's default AgentStudio prompt.
            declarative_only: Tenant partitions (FEAT-621 X11): offer
                ``save_agent_bundle`` instead of ``save_agent_draft``.
            **kwargs: Forwarded to :class:`~parrot.bots.agent.Agent`. An
                explicit ``llm=`` kwarg (instance/class/string) takes
                precedence over the ``api_key``/``model`` construction
                path below.

        Raises:
            ValueError: ``STUDIO_AGENT_LLM`` names an unknown provider (and no
                explicit ``llm=`` was given).
        """
        self._declarative_only = declarative_only
        llm = kwargs.pop("llm", None)
        if llm is None:
            # FEAT-523 (TASK-2846): resolved lazily through the client
            # registry — core must not import a provider module at module
            # scope (AC-3).
            provider = studio_agent_provider()
            client_class = _resolve_studio_client_class(provider)
            resolved_model = (
                model
                or STUDIO_AGENT_MODEL
                or _PROVIDER_DEFAULT_MODELS.get(provider)
                or getattr(client_class, "_default_model", None)
                or getattr(client_class, "default_model", None)
            )
            # Build through the factory so provider-specific wiring
            # (``PROVIDER_BACKEND``: bedrock / anthropic-aws) is applied.
            # ``api_key`` is only forwarded when set: an explicit ``None``
            # would disable the client's own navconfig key fallback.
            from parrot.clients.factory import LLMFactory

            create_kwargs: dict[str, Any] = {}
            if api_key is not None:
                create_kwargs["api_key"] = api_key
            spec = f"{provider}:{resolved_model}" if resolved_model else provider
            llm = LLMFactory.create(spec, **create_kwargs)
        super().__init__(
            name=name,
            llm=llm,
            system_prompt=system_prompt or _SYSTEM_PROMPT,
            **kwargs,
        )

    def agent_tools(self) -> list:
        """Return the AgentStudio-specific tool set (FEAT-467 TASK-2521)."""
        return [*super().agent_tools(), *build_studio_tools(declarative_only=self._declarative_only)]
