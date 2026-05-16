"""Finalize step — write the YAML and reload the registry.

This is the only tool that mutates the registry on disk. It is invoked at the
very end of the factory flow, **after** the user has approved the
``AgentDefinition`` at the pre-finalize HITL checkpoint.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from parrot.bots.factory.contracts import AgentDefinition
from parrot.registry import agent_registry
from parrot.registry.registry import BotConfig
from parrot.tools.decorators import tool


async def write_agent_yaml(
    definition: AgentDefinition,
    category: str = "general",
) -> Path:
    """Persist an ``AgentDefinition`` as a YAML file under ``agents/<category>/``.

    Delegates to ``AgentRegistry.create_agent_definition`` so the on-disk
    layout matches what the registry's YAML loader expects.
    """
    if not isinstance(definition, BotConfig):
        definition = BotConfig(**definition.model_dump())
    return agent_registry.create_agent_definition(definition, category=category)


async def finalize_agent_registration(
    definition: AgentDefinition,
    category: str = "general",
) -> Dict[str, Any]:
    """Write the YAML, reload the registry, and return the registration result.

    Returns a dict with the YAML path and whether the registry picked up the
    new definition (the registry skips ``enabled=False`` configs silently).
    """
    yaml_path = await write_agent_yaml(definition, category=category)

    # Reload only the directory we just wrote to — avoids redundant rescans.
    loaded = agent_registry.load_agent_definitions(yaml_path.parent)

    is_registered = definition.name in agent_registry._registered_agents
    return {
        "yaml_path": str(yaml_path),
        "registered": is_registered,
        "definitions_loaded_in_directory": loaded,
        "agent_name": definition.name,
    }


# --- LLM-facing wrapper ------------------------------------------------------


@tool(name="finalize_agent_registration",
      description="Persist the AgentDefinition to YAML and reload the "
                  "AgentRegistry so the new agent is immediately available. "
                  "ONLY call this after the user has approved the definition "
                  "at the pre-finalize checkpoint.")
async def _finalize_agent_registration_tool(
    definition: Dict[str, Any],
    category: str = "general",
) -> Dict[str, Any]:
    config = BotConfig(**definition)
    return await finalize_agent_registration(config, category=category)
