---
type: Wiki Overview
title: 6. Cross-cutting concerns and reference deployment
id: doc:docs-architecture-06-cross-cutting-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: The diagram below traces a single user message from any channel down to
---

# 6. Cross-cutting concerns and reference deployment

> Part of the [Exposure, Interoperability & Hardening](README.md) set.
> Previous: [Hardening](05-hardening.md) · Next: [AgentCrew](07-agentcrew.md)

## 6.1 End-to-end request path

The diagram below traces a single user message from any channel down to
the external vendor and back, naming every layer it crosses.

```mermaid
sequenceDiagram
    autonumber
    actor U as User / Channel
    participant TX as Transport<br/>(HTTP · WS · MCP · A2A)
    participant MW as aiohttp middleware<br/>navigator-auth · PBAC Guardian · A2ASecurityMiddleware
    participant Bot as Bot / Agent / Crew<br/>(post_login)
    participant AI as PromptInjectionDetector<br/>+ SecurityEventLogger
    participant TM as ToolManager + Resolver<br/>(@requires_permission)
    participant Tool as Tool / Toolkit
    participant Safe as QueryValidator<br/>SandboxTool (gVisor)
    participant Ext as External system<br/>Jira · Odoo · AWS · …
    participant Audit as security_events<br/>+ Guardian log

    U->>TX: request (TLS / mTLS, credentials)
    TX->>MW: authenticated request<br/>(API key · JWT · OAuth · Bearer)
    MW->>MW: PBAC evaluate (resource, action, subject, condition)
    alt deny
        MW-->>U: 403 Forbidden
        MW->>Audit: log denial
    else allow
        MW->>Bot: dispatch
        Bot->>AI: scan(input)
        AI->>Audit: log threat event
        alt strict + CRITICAL
            AI-->>U: rejected (sanitized response)
        else clean / sanitized
            AI-->>Bot: sanitized text
            Bot->>TM: call tool(args, _permission_context, _resolver)
            TM->>TM: filter_tools (Layer 1)
            TM->>Tool: execute(args)
            Tool->>TM: can_execute(perm) (Layer 2)
            alt perm denied
                TM-->>Bot: ToolResult(status=forbidden)
                TM->>Audit: log denial
            else allowed
                Tool->>Safe: validate query / sandbox code
                Safe->>Ext: call vendor API
                Ext-->>Safe: response
                Safe-->>Tool: validated output
                Tool-->>Bot: ToolResult(success)
            end
            Bot-->>U: response (text · stream · audio · form)
        end
    end
```

## 6.2 Deployment topologies

- **All-in-one HTTP service** — single aiohttp app exposing
  `/api/v1/chat`, `/api/v1/agents/chat`, `/.well-known/agent.json`, the
  voice WebSocket, and an MCP HTTP/SSE endpoint. Good fit for internal
  copilots.
- **MCP-only sidecar** — `MCPServer(transport="stdio"|"sse")` packaged
  as a vendor connector (Atlassian-MCP, Odoo-MCP, AWS-MCP). PBAC and
  prompt-injection are still active because they live on the toolkit /
  agent layer.
- **A2A mesh** — multiple agents registered through `A2AMeshDiscovery`
  with `JWTAuthenticator` and an orchestrator routing through
  `A2AProxyRouter`.
- **Voice-first agent** — VoiceChatHandler WebSocket fronting a
  `MCPClient` toolset with Gemini Live native audio.

```mermaid
graph TB
    subgraph T1["Topology 1 — All-in-one"]
        AIO["aiohttp app<br/>/api/v1/chat<br/>/api/v1/agents/chat<br/>/.well-known/agent.json<br/>/ws · /mcp"]
    end

    subgraph T2["Topology 2 — MCP sidecar"]
        Side["MCPServer<br/>(stdio · sse)"]
        Tk2["Toolkit (Jira · Odoo · AWS)"]
        Side --> Tk2
    end

    subgraph T3["Topology 3 — A2A mesh"]
        Orch["A2AOrchestratorAgent"]
        A1["Agent 1"]
        A2["Agent 2"]
        A3["Agent 3"]
        Mesh["A2AMeshDiscovery + JWT"]
        Orch --> Mesh
        Mesh --> A1
        Mesh --> A2
        Mesh --> A3
    end

    subgraph T4["Topology 4 — Voice-first"]
        WS["VoiceChatHandler /ws"]
        Live["Gemini Live"]
        MCP["MCP client toolset"]
        WS --> Live
        WS --> MCP
    end
```

## 6.3 Open work

- Prompt-injection detector currently regex-only; a classifier-based
  second stage is the natural next step.
- Vault / Secrets-Manager backend for `CredentialResolver`.
- Durable task store for `A2AServer._tasks` (today in-memory).
- Rate limiting on MCP transports (today only on A2A).
- Prompt registry on the MCP `prompts/list` dispatcher (currently a
  stub).

## 6.4 Pointers for reviewers

| Concern                 | Read first                                                     |
|-------------------------|---------------------------------------------------------------|
| Add a new MCP transport | `parrot/mcp/transports/base.py` + an existing transport file. |
| Add a new auth backend  | `parrot/auth/credentials.py` and `parrot/mcp/oauth.py`.       |
| Expose a crew over A2A  | `parrot/a2a/server.py` and `bots/orchestration/a2a_orchestrator.py`. |
| Add a vendor toolkit    | `parrot_tools/abstract.py` + `parrot_tools/toolkit.py` + an existing toolkit (e.g. `jiratoolkit.py`). |
| Tighten policies        | `policies/*.yaml` and `parrot/auth/pbac.py`.                  |
| Harden a tool           | `@requires_permission` in `parrot/auth/decorators.py`, plus PBAC YAML. |
