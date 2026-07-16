---
type: Wiki Summary
title: parrot.a2a
id: mod:parrot.a2a
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: A2A (Agent-to-Agent) Protocol Implementation for AI-Parrot.
relates_to:
- concept: mod:parrot
  rel: references
- concept: mod:parrot.models
  rel: references
---

# `parrot.a2a`

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
