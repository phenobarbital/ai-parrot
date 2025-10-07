from ..conf import AGENTS_DIR
from .registry import AgentRegistry, BotMetadata


# Global default registry
agent_registry = AgentRegistry(
    agents_dir=AGENTS_DIR
)

register_agent = agent_registry.register_bot_decorator  # type: ignore

__all__ = [
    "agent_registry",
    "BotMetadata",
    "register_agent",
    "AgentRegistry"
]
