"""
A2A (Agent-to-Agent) Protocol Implementation for AI-Parrot.

Exposes AI-Parrot agents as A2A-compliant microservices,
enabling inter-agent communication across network boundaries.

Components:
    Server Layer:
        - A2AServer: Wrap an agent as an A2A HTTP service
        - A2AEnabledMixin: Mixin to add A2A server capabilities

    Client Layer:
        - A2AClient: Connect to remote A2A agents
        - A2AClientMixin: Mixin to add A2A client capabilities
        - A2AAgentConnection: Connection state for remote agents
        - A2ARemoteAgentTool: Use remote agent as a tool
        - A2ARemoteSkillTool: Use remote skill as a tool

    Discovery Layer:
        - A2AMeshDiscovery: Centralized agent discovery service
        - A2AEndpoint: Configuration for an A2A endpoint
        - HealthCheckStrategy: How to check agent health
        - AgentStatus: Agent health status

    Routing Layer:
        - A2AProxyRouter: Rule-based request routing
        - RoutingStrategy: How to match requests to agents
        - LoadBalanceStrategy: How to balance across agents
        - RoutingRule: Individual routing rule definition

    Orchestration Layer:
        - A2AOrchestrator: Hybrid routing with LLM fallback
        - OrchestrationMode: Execution modes (rules, llm, hybrid, etc.)
        - OrchestrationResult: Result from orchestration
        - OrchestrationPlan: LLM decision plan

    Data Models:
        - AgentCard: Agent metadata and capabilities
        - AgentSkill: Skill/capability exposed by agent
        - AgentCapabilities: Agent feature flags
        - Task: A2A task with status and artifacts
        - Message: A2A message format
        - Artifact: Output produced by agent

Example Usage:
    # Expose an agent as A2A service
    from parrot.a2a import A2AServer

    a2a = A2AServer(my_agent)
    a2a.setup(app)

    # Connect to remote agents
    from parrot.a2a import A2AClient

    async with A2AClient("http://agent:8080") as client:
        task = await client.send_message("Hello!")

    # Use mesh discovery
    from parrot.a2a import A2AMeshDiscovery

    mesh = A2AMeshDiscovery.from_config("agents.yaml")
    await mesh.start()
    analysts = mesh.get_by_skill("data_analysis")

    # Use router for rule-based routing
    from parrot.a2a import A2AProxyRouter

    router = A2AProxyRouter(mesh)
    router.route_by_skill("analysis", "AnalystBot")
    result = await router.ask("Analyze this data")

    # Use orchestrator for hybrid routing
    from parrot.a2a import A2AOrchestrator

    orch = A2AOrchestrator(mesh)
    orch.set_fallback_llm(llm_client)
    result = await orch.run("Complex query requiring reasoning")
"""

# Server - Expose agents as A2A services
from .server import A2AServer, A2AEnabledMixin

# Client - Connect to remote A2A agents
from .client import (
    A2AClient,
    A2AAgentConnection,
    A2ARemoteAgentTool,
    A2ARemoteSkillTool,
)

# Client Mixin - Add A2A client capabilities to agents
from .mixin import A2AClientMixin

# Data Models
from .models import (
    AgentCard,
    AgentSkill,
    AgentCapabilities,
    Task,
    TaskState,
    TaskStatus,
    Message,
    Part,
    Artifact,
    RegisteredAgent,
)

# Mesh Discovery - Centralized agent discovery
from .mesh import (
    A2AMeshDiscovery,
    A2AEndpoint,
    HealthCheckStrategy,
    AgentStatus,
    DiscoveryStats,
)

# Router - Rule-based routing
from .router import (
    A2AProxyRouter,
    RoutingStrategy,
    LoadBalanceStrategy,
    RoutingRule,
    RoutingResult,
    ProxyStats,
)

# Orchestrator - Hybrid routing with LLM fallback
from .orchestrator import (
    A2AOrchestrator,
    OrchestrationMode,
    LLMDecisionStrategy,
    OrchestrationPlan,
    OrchestrationResult,
    AgentExecutionResult,
    OrchestratorStats,
)


__all__ = [
    # === Server ===
    "A2AServer",
    "A2AEnabledMixin",

    # === Client ===
    "A2AClient",
    "A2AClientMixin",
    "A2AAgentConnection",
    "A2ARemoteAgentTool",
    "A2ARemoteSkillTool",

    # === Models ===
    "AgentCard",
    "AgentSkill",
    "AgentCapabilities",
    "Task",
    "TaskState",
    "TaskStatus",
    "Message",
    "Part",
    "Artifact",
    "RegisteredAgent",

    # === Mesh Discovery ===
    "A2AMeshDiscovery",
    "A2AEndpoint",
    "HealthCheckStrategy",
    "AgentStatus",
    "DiscoveryStats",

    # === Router ===
    "A2AProxyRouter",
    "RoutingStrategy",
    "LoadBalanceStrategy",
    "RoutingRule",
    "RoutingResult",
    "ProxyStats",

    # === Orchestrator ===
    "A2AOrchestrator",
    "OrchestrationMode",
    "LLMDecisionStrategy",
    "OrchestrationPlan",
    "OrchestrationResult",
    "AgentExecutionResult",
    "OrchestratorStats",
]
