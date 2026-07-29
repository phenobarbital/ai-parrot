"""Agent lifecycle events.

FEAT-176 — Lifecycle Events System.

Covers: agent initialization, configuration, tool-manager readiness,
and status changes.
"""
from dataclasses import dataclass
from typing import Optional

from navigator_eventbus.lifecycle.base import LifecycleEvent


@dataclass(frozen=True)
class AgentInitializedEvent(LifecycleEvent):
    """Emitted at the end of AbstractBot.__init__.

    Attributes:
        agent_name: Name of the initialized agent.
        agent_class: Fully-qualified class name of the concrete bot.
    """

    agent_name: str = ""
    agent_class: str = ""


@dataclass(frozen=True)
class AgentConfiguredEvent(LifecycleEvent):
    """Emitted at the end of AbstractBot.configure().

    Attributes:
        agent_name: Name of the configured agent.
        llm_provider: String identifying the LLM provider (e.g., ``"anthropic"``).
        llm_model: Model name/identifier used by the configured LLM.
        has_vector_store: True if a vector store is wired to the agent.
    """

    agent_name: str = ""
    llm_provider: str = ""
    llm_model: str = ""
    has_vector_store: bool = False


@dataclass(frozen=True)
class ToolManagerReadyEvent(LifecycleEvent):
    """Emitted after the ToolManager is fully populated.

    Attributes:
        agent_name: Name of the agent whose ToolManager is ready.
        tool_count: Number of tools registered.
        tool_names: Immutable tuple of registered tool names.
    """

    agent_name: str = ""
    tool_count: int = 0
    tool_names: tuple = ()


@dataclass(frozen=True)
class AgentStatusChangedEvent(LifecycleEvent):
    """Emitted when the agent's status property changes.

    old_status / new_status hold the AgentStatus enum member name
    (uppercase string, e.g., ``"IDLE"``, ``"WORKING"``, ``"COMPLETED"``,
    ``"FAILED"``).

    Attributes:
        agent_name: Name of the agent whose status changed.
        old_status: Previous status as uppercase enum name.
        new_status: New status as uppercase enum name.
    """

    agent_name: str = ""
    old_status: str = ""
    new_status: str = ""
