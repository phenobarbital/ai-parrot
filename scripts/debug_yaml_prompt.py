"""Dump the constructed system prompt for a YAML-defined agent.

Usage:
    source .venv/bin/activate
    python scripts/debug_yaml_prompt.py [AgentName] [agents_dir]

Defaults:
    AgentName   = Carajito
    agents_dir  = agents/agents

Useful for validating PromptBuilder.from_system_prompt() — compare the
output against the bot's raw YAML ``system_prompt`` to confirm the
default stack (security/knowledge/user_session/tools/output/behavior)
wraps the identity layer correctly without colliding with IDENTITY_LAYER.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from parrot.registry import agent_registry


SEP = "=" * 78


async def dump(agent_name: str, agents_dir: Path) -> int:
    if not agents_dir.exists():
        print(f"ERROR: agents dir not found: {agents_dir}", file=sys.stderr)
        return 2

    n = agent_registry.load_agent_definitions(agents_dir)
    print(f"Loaded {n} agent definition(s) from {agents_dir}")

    metadata = agent_registry.get_metadata(agent_name)
    if metadata is None:
        registered = sorted(agent_registry._registered_agents.keys())
        print(
            f"ERROR: agent '{agent_name}' not registered.\n"
            f"Available: {registered}",
            file=sys.stderr,
        )
        return 1

    bot = await metadata.get_instance()

    if bot._prompt_builder and not bot._prompt_builder.is_configured:
        await bot._configure_prompt_builder()

    print(f"\n{SEP}\nAgent: {bot.name}  ({type(bot).__name__})\n{SEP}")

    raw = getattr(bot, "_system_prompt_base", "") or ""
    print("\n--- Raw YAML system_prompt ---")
    print(raw if raw else "(empty)")

    if bot._prompt_builder is None:
        print("\nPromptBuilder: NOT active — bot is on the legacy template path.")
        print("\n--- system_prompt_template (legacy) ---")
        print(bot.system_prompt_template)
        return 0

    print(f"\nPromptBuilder: active. Layers = {bot._prompt_builder.layer_names}")

    result = await bot.create_system_prompt(
        user_context="(debug user_context placeholder)",
        conversation_context="",
        vector_context="",
        kb_context="",
    )
    prompt = (
        result
        if isinstance(result, str)
        else "\n".join(getattr(seg, "text", str(seg)) for seg in result)
    )

    print(f"\n--- Final constructed system prompt ({len(prompt)} chars) ---")
    print(prompt)
    print(f"\n{SEP}\nEND\n{SEP}")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    agent_name = sys.argv[1] if len(sys.argv) > 1 else "Carajito"
    agents_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("agents/agents")
    return asyncio.run(dump(agent_name, agents_dir))


if __name__ == "__main__":
    sys.exit(main())
