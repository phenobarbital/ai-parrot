---
type: Wiki Summary
title: parrot.a2a.security
id: mod:parrot.a2a.security
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: A2A Security - Authentication and authorization for agent-to-agent communication.
relates_to:
- concept: class:parrot.a2a.security.A2ASecurityMiddleware
  rel: defines
- concept: class:parrot.a2a.security.AuthScheme
  rel: defines
- concept: class:parrot.a2a.security.CallerIdentity
  rel: defines
- concept: class:parrot.a2a.security.CredentialProvider
  rel: defines
- concept: class:parrot.a2a.security.InMemoryCredentialProvider
  rel: defines
- concept: class:parrot.a2a.security.JWTAuthenticator
  rel: defines
- concept: class:parrot.a2a.security.MTLSAuthenticator
  rel: defines
- concept: class:parrot.a2a.security.RedisCredentialProvider
  rel: defines
- concept: class:parrot.a2a.security.SecureA2AClient
  rel: defines
- concept: class:parrot.a2a.security.SecurityPolicy
  rel: defines
- concept: func:parrot.a2a.security.generate_api_key
  rel: defines
- concept: func:parrot.a2a.security.generate_hmac_secret
  rel: defines
- concept: func:parrot.a2a.security.get_request_identity
  rel: defines
- concept: func:parrot.a2a.security.hash_password
  rel: defines
- concept: func:parrot.a2a.security.require_permission
  rel: defines
- concept: func:parrot.a2a.security.require_role
  rel: defines
- concept: func:parrot.a2a.security.verify_password
  rel: defines
- concept: mod:parrot.a2a.client
  rel: references
---

# `parrot.a2a.security`

A2A Security - Authentication and authorization for agent-to-agent communication.

This module provides comprehensive security for A2A networks including:
- Multiple authentication schemes (JWT, mTLS, API Key, HMAC)
- Pluggable credential providers (in-memory, Redis, database, Vault)
- Security middleware for A2AServer
- Secure client wrapper for A2AClient
- Request signing and verification

Security Architecture:
    ┌─────────────────────────────────────────────────────────────────┐
    │                      A2A Security Layer                          │
    │                                                                  │
    │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
    │  │ Authenticator │  │  Authorizer  │  │ Credential Provider  │   │
    │  │              │  │              │  │                      │   │
    │  │ - JWT        │  │ - Policies   │  │ - InMemory           │   │
    │  │ - mTLS       │  │ - Permissions│  │ - Redis              │   │
    │  │ - API Key    │  │ - Rate Limit │  │ - Database           │   │
    │  │ - HMAC       │  │              │  │ - Vault              │   │
    │  └──────────────┘  └──────────────┘  └──────────────────────┘   │
    │                           │                                      │
    │                           ▼                                      │
    │  ┌─────────────────────────────────────────────────────────┐    │
    │  │              A2ASecurityMiddleware                       │    │
    │  │  (Integrates with A2AServer for request validation)      │    │
    │  └─────────────────────────────────────────────────────────┘    │
    └─────────────────────────────────────────────────────────────────┘

Example:
    # Server-side security
    from parrot.a2a.security import (
        A2ASecurityMiddleware,
        JWTAuthenticator,
        InMemoryCredentialProvider,
    )

    # Create credential provider
    credentials = InMemoryCredentialProvider()
    await credentials.register_agent(
        agent_name="DataBot",
        permissions=["skill:*"],
        api_key="secret-key-123"
    )

    # Create authenticator
    jwt_auth = JWTAuthenticator(
        secret_key="your-secret",
        issuer="a2a-network"
    )

    # Apply middleware
    middleware = A2ASecurityMiddleware(
        authenticator=jwt_auth,
        credential_provider=credentials,
    )
    a2a_server.add_security(middleware)

    # Client-side authentication
    from parrot.a2a.security import SecureA2AClient

    client = SecureA2AClient(
        "http://remote-agent:8080",
        auth_scheme=AuthScheme.BEARER,
        token=jwt_auth.create_token(agent_name="MyAgent")
    )

## Classes

- **`AuthScheme(str, Enum)`** — Supported authentication schemes for A2A communication.
- **`CallerIdentity(BaseModel)`** — Represents the authenticated identity of a calling agent.
- **`SecurityPolicy(BaseModel)`** — Security policy for an agent, endpoint, or skill.
- **`CredentialProvider(ABC)`** — Abstract base for credential storage and retrieval.
- **`InMemoryCredentialProvider(CredentialProvider)`** — In-memory credential provider for development and testing.
- **`RedisCredentialProvider(CredentialProvider)`** — Redis-based credential provider for distributed systems.
- **`JWTAuthenticator`** — JWT-based authentication for A2A communication.
- **`MTLSAuthenticator`** — Mutual TLS (mTLS) authentication for A2A communication.
- **`A2ASecurityMiddleware`** — Security middleware for A2AServer.
- **`SecureA2AClient`** — Wrapper for A2AClient with automatic authentication.

## Functions

- `def generate_api_key(prefix: str='a2a') -> str` — Generate a secure API key.
- `def generate_hmac_secret() -> str` — Generate a secure HMAC secret.
- `def hash_password(password: str) -> str` — Hash a password for storage.
- `def verify_password(password: str, hashed: str) -> bool` — Verify a password against a hash.
- `def get_request_identity(request: web.Request) -> Optional[CallerIdentity]` — Get the authenticated identity from a request.
- `def require_permission(permission: str)` — Decorator to require a specific permission.
- `def require_role(role: str)` — Decorator to require a specific role.
