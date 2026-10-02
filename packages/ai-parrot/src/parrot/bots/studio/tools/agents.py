"""YAML-agent factory tool (absorbs AgentFactory) and its database-mode path."""

from __future__ import annotations

from typing import Any

from parrot.tools import tool

from ._context import _refusing, _require_app, _require_author, _require_user_id, _studio_partition_and_services


@tool(
    name="create_yaml_agent",
    requires_confirmation=True,
    confirm_template="Register agent {name!s} (class {bot_class!s}) via a " "persisted YAML definition?",
    description=(
        "Create a simple (non-code-generated) agent by writing a lossless "
        "YAML definition under AGENTS_DIR/agents/<category>/ and "
        "registering it into the live AgentRegistry. Reuses the SAME "
        "finalize_agent_registration() the AgentFactory flow uses — never "
        "writes a live .py module."
    ),
)
async def create_yaml_agent(
    name: str,
    bot_class: str = "BasicBot",
    llm: str | None = None,
    description: str | None = None,
    category: str = "general",
) -> dict:
    """Create + register a YAML-defined agent (absorbs AgentFactory's
    finalize step — TASK-2521).

    Args:
        name: Agent slug.
        bot_class: Base class name (e.g. ``"BasicBot"``, ``"Agent"``).
        llm: Optional ``"provider:model"`` string.
        description: Optional human-readable description.
        category: YAML category sub-directory.

    Returns:
        The ``finalize_agent_registration`` result dict
        (``yaml_path``, ``registered``, ``agent_name``, ...).
    """
    # AgentDefinition IS BotConfig (a deliberate alias — see
    # bots/factory/contracts.py); resolving bot_class through the live
    # BotManager mirrors the EXACT construction TASK-2512's
    # `POST /astudio/agents` create flow uses, so YAML-agent creation
    # behaves identically whether it comes from the REST endpoint or
    # this tool.
    from parrot.bots.factory.tools.finalize import finalize_agent_registration
    from parrot.clients.factory import LLMFactory
    from parrot.models.basic import ModelConfig
    from parrot.registry.registry import BotConfig

    _require_author()
    app = _require_app()
    # Adversarial-review fix: stamp the real session user as owner (the
    # HTTP create path does the same server-side `created_by` stamping) —
    # without it, agents built via the assistant were unowned, which
    # fail-closed ownership checks then treat as "nobody may modify".
    user_id = _require_user_id()
    if (ps := await _studio_partition_and_services(app)) is not None:
        if isinstance(ps, dict):
            return ps
        return await _refusing(_db_create_agent(app, ps, user_id, name, bot_class, llm, description, category))
    manager = app.get("bot_manager")
    if manager is None:
        raise RuntimeError("BotManager unavailable — cannot resolve bot_class.")
    resolved_class = manager.get_bot_class(bot_class)
    if resolved_class is None:
        raise ValueError(f"Unknown bot_class '{bot_class}'.")

    config_dict = {"description": description} if description else {}
    config_dict["created_by"] = user_id
    model_config = None
    if llm:
        provider, model = LLMFactory.parse_llm_string(llm)
        model_config = ModelConfig(provider=provider, model=model or "")

    definition = BotConfig(
        name=name,
        class_name=resolved_class.__name__,
        module=resolved_class.__module__,
        origin="factory",
        config=config_dict,
        model=model_config,
    )
    return await finalize_agent_registration(definition, category=category)


async def _db_create_agent(app: Any, ps: tuple, user_id: str, name: str, bot_class: str, llm: str | None,
                           description: str | None, category: str) -> dict:
    """``StudioAgentService.create``; the non-tenant partition keeps the live ``get_bot_class`` resolution."""
    from parrot.handlers.studio.storage.models import StudioAgentDefinition

    part, services = ps
    manager = app.get("bot_manager")
    if part.tenant is None and manager is not None and manager.get_bot_class(bot_class) is None:
        raise ValueError(f"Unknown bot_class '{bot_class}'.")
    definition = StudioAgentDefinition(bot_class=bot_class, llm=llm, description=description, category=category)
    rec = await services.agents.create(part, name=name, owner=user_id, definition=definition)
    return {"agent_name": rec.name, "agent_id": str(rec.agent_id), "version": rec.version, "tenant": rec.tenant,
            "source": "studio", "persisted": True, "registered": False, "yaml_path": None}
