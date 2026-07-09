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

    Security Layer (server-only — requires ai-parrot-server):
        - AuthScheme: Supported authentication schemes
        - CallerIdentity: Authenticated agent identity
        - SecurityPolicy: Access control policies
        - CredentialProvider: Abstract credential storage
        - InMemoryCredentialProvider: Dev/test credential store
        - RedisCredentialProvider: Production credential store
        - JWTAuthenticator: JWT token authentication
        - MTLSAuthenticator: Mutual TLS authentication
        - A2ASecurityMiddleware: Security middleware for servers
        - SecureA2AClient: Client with automatic authentication

    Data Models:
        - AgentCard: Agent metadata and capabilities
        - AgentSkill: Skill/capability exposed by agent
        - AgentCapabilities: Agent feature flags
        - Task: A2A task with status and artifacts
        - Message: A2A message format
        - Artifact: Output produced by agent
"""
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)

# Client - Connect to remote A2A agents (consumer side — stay in core)
from .client import (
    A2AClient,
    A2AAgentConnection,
    A2ARemoteAgentTool,
    A2ARemoteSkillTool,
)

# Client Mixin - Add A2A client capabilities to agents
from .mixin import A2AClientMixin

# Data Models (stay in core)
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
    AgentConfig,
    Role,
    # v1.0.0 additions (FEAT-272)
    AgentInterface,
    AgentProvider,
    AgentExtension,
    AgentCardSignature,
    SecurityScheme,
    SecurityRequirement,
    APIKeySecurityScheme,
    HTTPAuthSecurityScheme,
    OAuth2SecurityScheme,
    OpenIdConnectSecurityScheme,
    MutualTlsSecurityScheme,
    SendMessageConfiguration,
    TaskPushNotificationConfig,
    AuthenticationInfo,
    A2AError,
    A2A_ERRORS,
    parse_task_state,
    parse_role,
    security_scheme_from_dict,
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

# Server-side exports (move to satellite in TASK-1370 — lazy via __getattr__)
# A2AServer, A2AEnabledMixin — satellite: parrot.a2a.server
# Security classes — satellite: parrot.a2a.security
_SERVER_CLASSES = {
    "A2AServer": ("parrot.a2a.server", "A2AServer"),
    "A2AEnabledMixin": ("parrot.a2a.server", "A2AEnabledMixin"),
    "AuthScheme": ("parrot.a2a.security", "AuthScheme"),
    "CallerIdentity": ("parrot.a2a.security", "CallerIdentity"),
    "SecurityPolicy": ("parrot.a2a.security", "SecurityPolicy"),
    "CredentialProvider": ("parrot.a2a.security", "CredentialProvider"),
    "InMemoryCredentialProvider": ("parrot.a2a.security", "InMemoryCredentialProvider"),
    "RedisCredentialProvider": ("parrot.a2a.security", "RedisCredentialProvider"),
    "JWTAuthenticator": ("parrot.a2a.security", "JWTAuthenticator"),
    "MTLSAuthenticator": ("parrot.a2a.security", "MTLSAuthenticator"),
    "A2ASecurityMiddleware": ("parrot.a2a.security", "A2ASecurityMiddleware"),
    "SecureA2AClient": ("parrot.a2a.security", "SecureA2AClient"),
}


def __getattr__(name: str):
    if name in _SERVER_CLASSES:
        module_path, cls_name = _SERVER_CLASSES[name]
        try:
            import importlib
            mod = importlib.import_module(module_path)
            return getattr(mod, cls_name)
        except ImportError as e:
            raise ImportError(
                f"{name!r} requires the ai-parrot-server package. "
                f"Install it with: pip install ai-parrot-server"
            ) from e
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # === Server (requires ai-parrot-server) ===
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
    "AgentConfig",
    "Role",

    # === Models — v1.0.0 additions (FEAT-272) ===
    "AgentInterface",
    "AgentProvider",
    "AgentExtension",
    "AgentCardSignature",
    "SecurityScheme",
    "SecurityRequirement",
    "APIKeySecurityScheme",
    "HTTPAuthSecurityScheme",
    "OAuth2SecurityScheme",
    "OpenIdConnectSecurityScheme",
    "MutualTlsSecurityScheme",
    "SendMessageConfiguration",
    "TaskPushNotificationConfig",
    "AuthenticationInfo",
    "A2AError",
    "A2A_ERRORS",
    "parse_task_state",
    "parse_role",
    "security_scheme_from_dict",

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

    # === Security (requires ai-parrot-server) ===
    "AuthScheme",
    "CallerIdentity",
    "SecurityPolicy",
    "CredentialProvider",
    "InMemoryCredentialProvider",
    "RedisCredentialProvider",
    "JWTAuthenticator",
    "MTLSAuthenticator",
    "A2ASecurityMiddleware",
    "SecureA2AClient",
]
