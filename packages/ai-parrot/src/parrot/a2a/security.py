"""
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
"""
from __future__ import annotations
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
)
import base64
import contextlib
import hashlib
import hmac
import json
import secrets
import ssl
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import wraps
from aiohttp import web
import aiohttp
from navconfig.logging import logging
if TYPE_CHECKING:
    from .server import A2AServer
    from .client import A2AClient


# ─────────────────────────────────────────────────────────────────────────────
# Core Security Models
# ─────────────────────────────────────────────────────────────────────────────

class AuthScheme(str, Enum):
    """Supported authentication schemes for A2A communication."""

    NONE = "none"              # No authentication (development only!)
    API_KEY = "apiKey"         # Simple API key in header
    BEARER = "bearer"          # Bearer token (typically JWT)
    BASIC = "basic"            # Basic auth (username:password)
    MTLS = "mutualTLS"         # Mutual TLS with client certificates
    HMAC = "hmac"              # HMAC request signing
    OAUTH2 = "oauth2"          # OAuth 2.0 tokens


@dataclass
class CallerIdentity:
    """
    Represents the authenticated identity of a calling agent.

    This is the result of successful authentication and contains
    all information needed for authorization decisions.

    Attributes:
        agent_name: Unique name/identifier of the agent
        agent_url: Optional URL of the calling agent
        permissions: List of permission strings
        metadata: Additional identity metadata
        auth_scheme: Authentication scheme used
        certificate_fingerprint: For mTLS, the cert fingerprint
        issued_at: When the identity was established
        expires_at: When the identity expires
        scopes: OAuth2-style scopes
        roles: Role-based access control roles
    """
    agent_name: str
    agent_url: Optional[str] = None
    permissions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    auth_scheme: Optional[AuthScheme] = None
    certificate_fingerprint: Optional[str] = None
    issued_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    scopes: List[str] = field(default_factory=list)
    roles: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.issued_at is None:
            self.issued_at = datetime.now(timezone.utc)

    def has_permission(self, permission: str) -> bool:
        """
        Check if caller has a specific permission.

        Supports wildcard (*) for full access.

        Args:
            permission: Permission string to check

        Returns:
            True if permission is granted
        """
        if "*" in self.permissions:
            return True
        if permission in self.permissions:
            return True
        # Check prefix wildcards (e.g., "skill:*" matches "skill:analyze")
        for perm in self.permissions:
            if perm.endswith(":*"):
                prefix = perm[:-1]  # "skill:"
                if permission.startswith(prefix):
                    return True
        return False

    def can_invoke_skill(self, skill_id: str) -> bool:
        """Check if caller can invoke a specific skill."""
        return (
            self.has_permission("*") or self.has_permission(f"skill:{skill_id}")
            or self.has_permission("skill:*")
        )

    def has_role(self, role: str) -> bool:
        """Check if caller has a specific role."""
        return role in self.roles or "admin" in self.roles

    def has_scope(self, scope: str) -> bool:
        """Check if caller has a specific OAuth2 scope."""
        return scope in self.scopes or "*" in self.scopes

    def is_expired(self) -> bool:
        """Check if identity has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "agent_name": self.agent_name,
            "agent_url": self.agent_url,
            "permissions": self.permissions,
            "metadata": self.metadata,
            "auth_scheme": self.auth_scheme.value if self.auth_scheme else None,
            "certificate_fingerprint": self.certificate_fingerprint,
            "issued_at": self.issued_at.isoformat() if self.issued_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "scopes": self.scopes,
            "roles": self.roles,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CallerIdentity":
        """Create from dictionary."""
        auth_scheme = None
        if data.get("auth_scheme"):
            auth_scheme = AuthScheme(data["auth_scheme"])

        issued_at = None
        if data.get("issued_at"):
            issued_at = datetime.fromisoformat(data["issued_at"])

        expires_at = None
        if data.get("expires_at"):
            expires_at = datetime.fromisoformat(data["expires_at"])

        return cls(
            agent_name=data["agent_name"],
            agent_url=data.get("agent_url"),
            permissions=data.get("permissions", []),
            metadata=data.get("metadata", {}),
            auth_scheme=auth_scheme,
            certificate_fingerprint=data.get("certificate_fingerprint"),
            issued_at=issued_at,
            expires_at=expires_at,
            scopes=data.get("scopes", []),
            roles=data.get("roles", []),
        )


@dataclass
class SecurityPolicy:
    """
    Security policy for an agent, endpoint, or skill.

    Defines authentication requirements and access control rules.

    Attributes:
        require_auth: Whether authentication is required
        allowed_schemes: Which auth schemes are accepted
        allowed_agents: Specific agents allowed (None = any authenticated)
        denied_agents: Specific agents denied (blacklist)
        required_permissions: Permissions required to access
        required_roles: Roles required to access
        required_scopes: OAuth2 scopes required
        rate_limit: Requests per minute limit
        rate_limit_burst: Burst allowance for rate limiting
        ip_whitelist: Allowed IP addresses/ranges
        ip_blacklist: Denied IP addresses/ranges
        require_https: Require HTTPS connections
        require_mtls: Require mutual TLS
    """
    require_auth: bool = True
    allowed_schemes: List[AuthScheme] = field(
        default_factory=lambda: [AuthScheme.BEARER, AuthScheme.API_KEY]
    )
    allowed_agents: Optional[List[str]] = None
    denied_agents: Optional[List[str]] = None
    required_permissions: List[str] = field(default_factory=list)
    required_roles: List[str] = field(default_factory=list)
    required_scopes: List[str] = field(default_factory=list)
    rate_limit: Optional[int] = None
    rate_limit_burst: int = 10
    ip_whitelist: Optional[List[str]] = None
    ip_blacklist: Optional[List[str]] = None
    require_https: bool = False
    require_mtls: bool = False

    def allows_scheme(self, scheme: AuthScheme) -> bool:
        """Check if authentication scheme is allowed."""
        return scheme in self.allowed_schemes

    def is_agent_allowed(self, agent_name: str) -> bool:
        """Check if a specific agent is allowed."""
        # Check blacklist first
        if self.denied_agents and agent_name in self.denied_agents:
            return False
        # If whitelist exists, agent must be in it
        if self.allowed_agents is not None:
            return agent_name in self.allowed_agents
        return True

    def check_permissions(self, identity: CallerIdentity) -> bool:
        """Check if identity has all required permissions."""
        return all(
            identity.has_permission(perm) for perm in self.required_permissions
        )

    def check_roles(self, identity: CallerIdentity) -> bool:
        """Check if identity has all required roles."""
        return all(identity.has_role(role) for role in self.required_roles)

    def check_scopes(self, identity: CallerIdentity) -> bool:
        """Check if identity has all required scopes."""
        return all(
            identity.has_scope(scope) for scope in self.required_scopes
        )


# ─────────────────────────────────────────────────────────────────────────────
# Credential Provider Interface
# ─────────────────────────────────────────────────────────────────────────────
class CredentialProvider(ABC):
    """
    Abstract base for credential storage and retrieval.

    Implementations can use different backends:
    - InMemoryCredentialProvider: For development/testing
    - RedisCredentialProvider: For distributed production systems
    - DatabaseCredentialProvider: For SQL-based storage
    - VaultCredentialProvider: For HashiCorp Vault integration

    The provider is responsible for:
    - Storing and retrieving API keys
    - Validating bearer tokens
    - Managing agent certificates for mTLS
    - Storing agent metadata and permissions
    """

    @abstractmethod
    async def get_api_key(self, key_id: str) -> Optional[Dict[str, Any]]:
        """
        Get API key details by key ID or the key itself.

        Args:
            key_id: The API key or key identifier

        Returns:
            Dict with key details including 'identity' (CallerIdentity),
            or None if not found
        """
        pass

    @abstractmethod
    async def get_agent_by_token(self, token: str) -> Optional[CallerIdentity]:
        """
        Validate a bearer token and return the caller identity.

        This may involve JWT validation, token lookup, or external
        validation service calls.

        Args:
            token: The bearer token

        Returns:
            CallerIdentity if valid, None otherwise
        """
        pass

    @abstractmethod
    async def get_agent_by_certificate(
        self, fingerprint: str
    ) -> Optional[CallerIdentity]:
        """
        Get agent identity by certificate fingerprint.

        Used for mTLS authentication where the client presents
        a certificate.

        Args:
            fingerprint: SHA-256 fingerprint of the certificate

        Returns:
            CallerIdentity if certificate is registered, None otherwise
        """
        pass

    @abstractmethod
    async def register_agent(
        self,
        agent_name: str,
        *,
        permissions: Optional[List[str]] = None,
        roles: Optional[List[str]] = None,
        scopes: Optional[List[str]] = None,
        api_key: Optional[str] = None,
        certificate_fingerprint: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Register a new agent with credentials.

        Args:
            agent_name: Unique agent name
            permissions: List of permissions
            roles: List of roles
            scopes: List of OAuth2 scopes
            api_key: API key (generated if not provided)
            certificate_fingerprint: mTLS certificate fingerprint
            metadata: Additional metadata

        Returns:
            Registration details including generated credentials
        """
        pass

    @abstractmethod
    async def revoke_agent(self, agent_name: str) -> bool:
        """
        Revoke all credentials for an agent.

        Args:
            agent_name: Agent to revoke

        Returns:
            True if revoked, False if not found
        """
        pass

    async def validate_basic_auth(
        self, username: str, password: str
    ) -> Optional[CallerIdentity]:
        """
        Validate basic authentication credentials.

        Default implementation returns None. Override if needed.

        Args:
            username: Username
            password: Password

        Returns:
            CallerIdentity if valid, None otherwise
        """
        return None

    async def validate_hmac(
        self,
        signature: str,
        payload: bytes,
        timestamp: str,
    ) -> Optional[CallerIdentity]:
        """
        Validate HMAC signature.

        Default implementation returns None. Override if needed.

        Args:
            signature: The HMAC signature
            payload: The signed payload
            timestamp: Request timestamp

        Returns:
            CallerIdentity if valid, None otherwise
        """
        return None


# ─────────────────────────────────────────────────────────────────────────────
# In-Memory Credential Provider
# ─────────────────────────────────────────────────────────────────────────────

class InMemoryCredentialProvider(CredentialProvider):
    """
    In-memory credential provider for development and testing.

    NOT suitable for production - credentials are lost on restart.

    Example:
        provider = InMemoryCredentialProvider()

        # Register an agent
        result = await provider.register_agent(
            "DataBot",
            permissions=["skill:analyze", "skill:query"],
            roles=["analyst"],
        )
        api_key = result["api_key"]

        # Validate later
        identity = await provider.get_agent_by_token(token)
    """

    def __init__(self):
        # agent_name -> registration data
        self._agents: Dict[str, Dict[str, Any]] = {}
        # api_key -> agent_name
        self._api_keys: Dict[str, str] = {}
        # token -> CallerIdentity
        self._tokens: Dict[str, CallerIdentity] = {}
        # certificate_fingerprint -> agent_name
        self._certificates: Dict[str, str] = {}
        # agent_name -> hmac_secret
        self._hmac_secrets: Dict[str, str] = {}

        self.logger = logging.getLogger("A2A.Security.InMemory")

    async def get_api_key(self, key_id: str) -> Optional[Dict[str, Any]]:
        """Get API key details."""
        agent_name = self._api_keys.get(key_id)
        if not agent_name:
            return None

        if agent_data := self._agents.get(agent_name):
            return {
                "agent_name": agent_name,
                "identity": CallerIdentity(
                    agent_name=agent_name,
                    permissions=agent_data.get("permissions", []),
                    roles=agent_data.get("roles", []),
                    scopes=agent_data.get("scopes", []),
                    metadata=agent_data.get("metadata", {}),
                    auth_scheme=AuthScheme.API_KEY,
                ),
            }
        return None

    async def get_agent_by_token(self, token: str) -> Optional[CallerIdentity]:
        """Get identity by bearer token."""
        identity = self._tokens.get(token)
        if identity and identity.is_expired():
            del self._tokens[token]
            return None
        return identity

    async def get_agent_by_certificate(
        self, fingerprint: str
    ) -> Optional[CallerIdentity]:
        """Get identity by certificate fingerprint."""
        agent_name = self._certificates.get(fingerprint)
        if not agent_name:
            return None

        if agent_data := self._agents.get(agent_name):
            return CallerIdentity(
                agent_name=agent_name,
                permissions=agent_data.get("permissions", []),
                roles=agent_data.get("roles", []),
                scopes=agent_data.get("scopes", []),
                metadata=agent_data.get("metadata", {}),
                auth_scheme=AuthScheme.MTLS,
                certificate_fingerprint=fingerprint,
            )
        return None

    async def register_agent(
        self,
        agent_name: str,
        *,
        permissions: Optional[List[str]] = None,
        roles: Optional[List[str]] = None,
        scopes: Optional[List[str]] = None,
        api_key: Optional[str] = None,
        certificate_fingerprint: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Register a new agent."""
        # Generate API key if not provided
        if api_key is None:
            api_key = f"a2a_{secrets.token_urlsafe(32)}"

        # Generate HMAC secret
        hmac_secret = secrets.token_urlsafe(32)

        # Store agent data
        self._agents[agent_name] = {
            "permissions": permissions or [],
            "roles": roles or [],
            "scopes": scopes or [],
            "metadata": metadata or {},
            "api_key": api_key,
            "hmac_secret": hmac_secret,
            "certificate_fingerprint": certificate_fingerprint,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }

        # Index by API key
        self._api_keys[api_key] = agent_name

        # Index by certificate if provided
        if certificate_fingerprint:
            self._certificates[certificate_fingerprint] = agent_name

        # Store HMAC secret
        self._hmac_secrets[agent_name] = hmac_secret

        self.logger.info(f"Registered agent: {agent_name}")

        return {
            "agent_name": agent_name,
            "api_key": api_key,
            "hmac_secret": hmac_secret,
        }

    async def revoke_agent(self, agent_name: str) -> bool:
        """Revoke all credentials for an agent."""
        if agent_name not in self._agents:
            return False

        agent_data = self._agents[agent_name]

        # Remove API key index
        api_key = agent_data.get("api_key")
        if api_key and api_key in self._api_keys:
            del self._api_keys[api_key]

        # Remove certificate index
        cert_fp = agent_data.get("certificate_fingerprint")
        if cert_fp and cert_fp in self._certificates:
            del self._certificates[cert_fp]

        # Remove HMAC secret
        if agent_name in self._hmac_secrets:
            del self._hmac_secrets[agent_name]

        # Remove tokens
        tokens_to_remove = [
            token for token, identity in self._tokens.items()
            if identity.agent_name == agent_name
        ]
        for token in tokens_to_remove:
            del self._tokens[token]

        # Remove agent
        del self._agents[agent_name]

        self.logger.info(f"Revoked agent: {agent_name}")
        return True

    async def store_token(
        self,
        token: str,
        identity: CallerIdentity,
    ) -> None:
        """Store a token for later validation."""
        self._tokens[token] = identity

    async def validate_hmac(
        self,
        signature: str,
        payload: bytes,
        timestamp: str,
        agent_name: Optional[str] = None,
    ) -> Optional[CallerIdentity]:
        """Validate HMAC signature."""
        # Try to find the agent by checking all secrets
        for name, secret in self._hmac_secrets.items():
            if agent_name and name != agent_name:
                continue

            # Compute expected signature
            message = timestamp.encode() + payload
            expected = hmac.new(
                secret.encode(),
                message,
                hashlib.sha256
            ).hexdigest()

            if hmac.compare_digest(signature, expected):
                if agent_data := self._agents.get(name):
                    return CallerIdentity(
                        agent_name=name,
                        permissions=agent_data.get("permissions", []),
                        roles=agent_data.get("roles", []),
                        scopes=agent_data.get("scopes", []),
                        metadata=agent_data.get("metadata", {}),
                        auth_scheme=AuthScheme.HMAC,
                    )

        return None

    def get_hmac_secret(self, agent_name: str) -> Optional[str]:
        """Get HMAC secret for an agent (for client-side signing)."""
        return self._hmac_secrets.get(agent_name)


# ─────────────────────────────────────────────────────────────────────────────
# Redis Credential Provider
# ─────────────────────────────────────────────────────────────────────────────

class RedisCredentialProvider(CredentialProvider):
    """
    Redis-based credential provider for distributed systems.

    Provides persistent, distributed credential storage with
    automatic expiration support.

    Example:
        import redis.asyncio as redis

        redis_client = redis.Redis(host='localhost', port=6379)
        provider = RedisCredentialProvider(redis_client)

        await provider.register_agent("DataBot", permissions=["skill:*"])
    """

    def __init__(
        self,
        redis_client: Any,  # redis.asyncio.Redis
        *,
        key_prefix: str = "a2a:auth:",
        token_ttl: int = 3600,  # 1 hour
    ):
        """
        Initialize Redis credential provider.

        Args:
            redis_client: Async Redis client instance
            key_prefix: Prefix for Redis keys
            token_ttl: Default token TTL in seconds
        """
        self._redis = redis_client
        self._prefix = key_prefix
        self._token_ttl = token_ttl
        self.logger = logging.getLogger("A2A.Security.Redis")

    def _key(self, *parts: str) -> str:
        """Build Redis key with prefix."""
        return self._prefix + ":".join(parts)

    async def get_api_key(self, key_id: str) -> Optional[Dict[str, Any]]:
        """Get API key details from Redis."""
        # Look up agent name by API key
        agent_name = await self._redis.get(self._key("apikey", key_id))
        if not agent_name:
            return None

        agent_name = agent_name.decode() if isinstance(agent_name, bytes) else agent_name

        # Get agent data
        data = await self._redis.hgetall(self._key("agent", agent_name))
        if not data:
            return None

        # Decode bytes
        data = {
            k.decode() if isinstance(k, bytes) else k:
            v.decode() if isinstance(v, bytes) else v
            for k, v in data.items()
        }

        return {
            "agent_name": agent_name,
            "identity": CallerIdentity(
                agent_name=agent_name,
                permissions=json.loads(data.get("permissions", "[]")),
                roles=json.loads(data.get("roles", "[]")),
                scopes=json.loads(data.get("scopes", "[]")),
                metadata=json.loads(data.get("metadata", "{}")),
                auth_scheme=AuthScheme.API_KEY,
            ),
        }

    async def get_agent_by_token(self, token: str) -> Optional[CallerIdentity]:
        """Get identity by bearer token from Redis."""
        data = await self._redis.get(self._key("token", token))
        if not data:
            return None

        data = data.decode() if isinstance(data, bytes) else data
        return CallerIdentity.from_dict(json.loads(data))

    async def get_agent_by_certificate(
        self, fingerprint: str
    ) -> Optional[CallerIdentity]:
        """Get identity by certificate fingerprint from Redis."""
        agent_name = await self._redis.get(self._key("cert", fingerprint))
        if not agent_name:
            return None

        agent_name = agent_name.decode() if isinstance(agent_name, bytes) else agent_name

        # Get agent data
        data = await self._redis.hgetall(self._key("agent", agent_name))
        if not data:
            return None

        data = {
            k.decode() if isinstance(k, bytes) else k:
            v.decode() if isinstance(v, bytes) else v
            for k, v in data.items()
        }

        return CallerIdentity(
            agent_name=agent_name,
            permissions=json.loads(data.get("permissions", "[]")),
            roles=json.loads(data.get("roles", "[]")),
            scopes=json.loads(data.get("scopes", "[]")),
            metadata=json.loads(data.get("metadata", "{}")),
            auth_scheme=AuthScheme.MTLS,
            certificate_fingerprint=fingerprint,
        )

    async def register_agent(
        self,
        agent_name: str,
        *,
        permissions: Optional[List[str]] = None,
        roles: Optional[List[str]] = None,
        scopes: Optional[List[str]] = None,
        api_key: Optional[str] = None,
        certificate_fingerprint: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Register agent in Redis."""
        if api_key is None:
            api_key = f"a2a_{secrets.token_urlsafe(32)}"

        hmac_secret = secrets.token_urlsafe(32)

        # Store agent data
        agent_data = {
            "permissions": json.dumps(permissions or []),
            "roles": json.dumps(roles or []),
            "scopes": json.dumps(scopes or []),
            "metadata": json.dumps(metadata or {}),
            "api_key": api_key,
            "hmac_secret": hmac_secret,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }

        if certificate_fingerprint:
            agent_data["certificate_fingerprint"] = certificate_fingerprint

        await self._redis.hset(self._key("agent", agent_name), mapping=agent_data)

        # Index by API key
        await self._redis.set(self._key("apikey", api_key), agent_name)

        # Index by certificate
        if certificate_fingerprint:
            await self._redis.set(
                self._key("cert", certificate_fingerprint),
                agent_name
            )

        self.logger.info(f"Registered agent in Redis: {agent_name}")

        return {
            "agent_name": agent_name,
            "api_key": api_key,
            "hmac_secret": hmac_secret,
        }

    async def revoke_agent(self, agent_name: str) -> bool:
        """Revoke agent from Redis."""
        # Get agent data first
        data = await self._redis.hgetall(self._key("agent", agent_name))
        if not data:
            return False

        data = {
            k.decode() if isinstance(k, bytes) else k:
            v.decode() if isinstance(v, bytes) else v
            for k, v in data.items()
        }

        # Remove API key index
        if api_key := data.get("api_key"):
            await self._redis.delete(self._key("apikey", api_key))

        # Remove certificate index
        if cert_fp := data.get("certificate_fingerprint"):
            await self._redis.delete(self._key("cert", cert_fp))

        # Remove agent
        await self._redis.delete(self._key("agent", agent_name))

        self.logger.info(f"Revoked agent from Redis: {agent_name}")
        return True

    async def store_token(
        self,
        token: str,
        identity: CallerIdentity,
        ttl: Optional[int] = None,
    ) -> None:
        """Store token in Redis with TTL."""
        await self._redis.set(
            self._key("token", token),
            json.dumps(identity.to_dict()),
            ex=ttl or self._token_ttl,
        )


# ─────────────────────────────────────────────────────────────────────────────
# JWT Authenticator
# ─────────────────────────────────────────────────────────────────────────────

class JWTAuthenticator:
    """
    JWT-based authentication for A2A communication.

    Supports both symmetric (HS256) and asymmetric (RS256) algorithms.

    Example:
        # Symmetric (shared secret)
        auth = JWTAuthenticator(
            secret_key="your-secret-key",
            algorithm="HS256",
            issuer="a2a-network",
        )

        # Create token for an agent
        token = auth.create_token(
            agent_name="DataBot",
            permissions=["skill:*"],
            expires_in=3600,  # 1 hour
        )

        # Validate token
        identity = await auth.validate_token(token)

        # Asymmetric (RSA key pair)
        auth = JWTAuthenticator(
            private_key=private_key_pem,
            public_key=public_key_pem,
            algorithm="RS256",
        )
    """

    def __init__(
        self,
        *,
        secret_key: Optional[str] = None,
        private_key: Optional[str] = None,
        public_key: Optional[str] = None,
        algorithm: str = "HS256",
        issuer: str = "a2a",
        audience: Optional[str] = None,
        default_expiry: int = 3600,  # 1 hour
        clock_skew: int = 60,  # 60 seconds tolerance
    ):
        """
        Initialize JWT authenticator.

        For HS256: Provide secret_key
        For RS256: Provide private_key (for signing) and/or public_key (for validation)

        Args:
            secret_key: Shared secret for HS256
            private_key: PEM-encoded private key for RS256
            public_key: PEM-encoded public key for RS256
            algorithm: JWT algorithm (HS256, RS256)
            issuer: Token issuer claim
            audience: Token audience claim
            default_expiry: Default token expiry in seconds
            clock_skew: Allowed clock skew in seconds
        """
        self._algorithm = algorithm
        self._issuer = issuer
        self._audience = audience
        self._default_expiry = default_expiry
        self._clock_skew = clock_skew

        if algorithm == "HS256":
            if not secret_key:
                raise ValueError("secret_key required for HS256")
            self._sign_key = secret_key
            self._verify_key = secret_key
        elif algorithm == "RS256":
            self._sign_key = private_key
            self._verify_key = public_key or private_key
            if not self._verify_key:
                raise ValueError("public_key or private_key required for RS256")
        else:
            raise ValueError(f"Unsupported algorithm: {algorithm}")

        self.logger = logging.getLogger("A2A.Security.JWT")

        # Try to import PyJWT
        try:
            import jwt
            self._jwt = jwt
        except ImportError:
            raise ImportError(
                "PyJWT is required for JWT authentication. "
                "Install with: pip install PyJWT"
            )

    def create_token(
        self,
        agent_name: str,
        *,
        agent_url: Optional[str] = None,
        permissions: Optional[List[str]] = None,
        roles: Optional[List[str]] = None,
        scopes: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        expires_in: Optional[int] = None,
    ) -> str:
        """
        Create a JWT token for an agent.

        Args:
            agent_name: Agent identifier
            agent_url: Optional agent URL
            permissions: List of permissions
            roles: List of roles
            scopes: OAuth2-style scopes
            metadata: Additional claims
            expires_in: Token lifetime in seconds

        Returns:
            Signed JWT token
        """
        if not self._sign_key:
            raise ValueError("No signing key configured")

        now = datetime.now(timezone.utc)
        expiry = now + timedelta(seconds=expires_in or self._default_expiry)

        payload = {
            # Standard claims
            "iss": self._issuer,
            "sub": agent_name,
            "iat": int(now.timestamp()),
            "exp": int(expiry.timestamp()),
            "jti": str(uuid.uuid4()),

            # A2A-specific claims
            "agent_name": agent_name,
            "permissions": permissions or [],
            "roles": roles or [],
            "scopes": scopes or [],
        }

        if self._audience:
            payload["aud"] = self._audience

        if agent_url:
            payload["agent_url"] = agent_url

        if metadata:
            payload["metadata"] = metadata

        token = self._jwt.encode(
            payload,
            self._sign_key,
            algorithm=self._algorithm,
        )

        self.logger.debug(f"Created JWT for agent: {agent_name}")
        return token

    async def validate_token(self, token: str) -> Optional[CallerIdentity]:
        """
        Validate a JWT token and return the caller identity.

        Args:
            token: JWT token to validate

        Returns:
            CallerIdentity if valid, None if invalid
        """
        try:
            options = {
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "require": ["exp", "iat", "sub"],
            }

            kwargs = {
                "algorithms": [self._algorithm],
                "issuer": self._issuer,
                "options": options,
                "leeway": self._clock_skew,
            }

            if self._audience:
                kwargs["audience"] = self._audience

            payload = self._jwt.decode(
                token,
                self._verify_key,
                **kwargs,
            )

            return CallerIdentity(
                agent_name=payload.get("agent_name") or payload["sub"],
                agent_url=payload.get("agent_url"),
                permissions=payload.get("permissions", []),
                roles=payload.get("roles", []),
                scopes=payload.get("scopes", []),
                metadata=payload.get("metadata", {}),
                auth_scheme=AuthScheme.BEARER,
                issued_at=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
                expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
            )

        except self._jwt.ExpiredSignatureError:
            self.logger.warning("JWT token expired")
            return None
        except self._jwt.InvalidTokenError as e:
            self.logger.warning(f"Invalid JWT token: {e}")
            return None

    def decode_without_verification(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Decode JWT without verifying signature.

        Useful for debugging or extracting claims before validation.
        WARNING: Do not trust the contents for authorization!

        Args:
            token: JWT token

        Returns:
            Decoded payload or None if invalid format
        """
        try:
            return self._jwt.decode(
                token,
                options={"verify_signature": False}
            )
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# mTLS Authenticator
# ─────────────────────────────────────────────────────────────────────────────
class MTLSAuthenticator:
    """
    Mutual TLS (mTLS) authentication for A2A communication.

    Validates client certificates and extracts identity information.

    Example:
        auth = MTLSAuthenticator(
            ca_cert_path="/path/to/ca.crt",
            credential_provider=provider,
        )

        # Create SSL context for server
        ssl_context = auth.create_server_ssl_context(
            cert_path="/path/to/server.crt",
            key_path="/path/to/server.key",
        )

        # Validate client certificate from request
        identity = await auth.validate_certificate(request)
    """

    def __init__(
        self,
        *,
        ca_cert_path: Optional[str] = None,
        ca_cert_data: Optional[str] = None,
        credential_provider: Optional[CredentialProvider] = None,
        require_client_cert: bool = True,
        verify_hostname: bool = True,
    ):
        """
        Initialize mTLS authenticator.

        Args:
            ca_cert_path: Path to CA certificate file
            ca_cert_data: PEM-encoded CA certificate data
            credential_provider: Provider for certificate-to-identity lookup
            require_client_cert: Whether to require client certificates
            verify_hostname: Whether to verify client certificate hostname
        """
        self._ca_cert_path = ca_cert_path
        self._ca_cert_data = ca_cert_data
        self._credential_provider = credential_provider
        self._require_client_cert = require_client_cert
        self._verify_hostname = verify_hostname

        self.logger = logging.getLogger("A2A.Security.mTLS")

    def create_server_ssl_context(
        self,
        cert_path: str,
        key_path: str,
        *,
        key_password: Optional[str] = None,
    ) -> ssl.SSLContext:
        """
        Create SSL context for server with mTLS support.

        Args:
            cert_path: Path to server certificate
            key_path: Path to server private key
            key_password: Password for encrypted key

        Returns:
            Configured SSL context
        """
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)

        # Load server certificate and key
        context.load_cert_chain(cert_path, key_path, password=key_password)

        # Load CA for client verification
        if self._ca_cert_path:
            context.load_verify_locations(self._ca_cert_path)
        elif self._ca_cert_data:
            context.load_verify_locations(cadata=self._ca_cert_data)

        # Require client certificate
        if self._require_client_cert:
            context.verify_mode = ssl.CERT_REQUIRED
        else:
            context.verify_mode = ssl.CERT_OPTIONAL

        # Security settings
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.set_ciphers('ECDHE+AESGCM:DHE+AESGCM:ECDHE+CHACHA20')

        return context

    def create_client_ssl_context(
        self,
        cert_path: str,
        key_path: str,
        *,
        key_password: Optional[str] = None,
    ) -> ssl.SSLContext:
        """
        Create SSL context for client with mTLS support.

        Args:
            cert_path: Path to client certificate
            key_path: Path to client private key
            key_password: Password for encrypted key

        Returns:
            Configured SSL context
        """
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

        # Load client certificate and key
        context.load_cert_chain(cert_path, key_path, password=key_password)

        # Load CA for server verification
        if self._ca_cert_path:
            context.load_verify_locations(self._ca_cert_path)
        elif self._ca_cert_data:
            context.load_verify_locations(cadata=self._ca_cert_data)
        else:
            context.load_default_certs()

        # Security settings
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = self._verify_hostname
        context.verify_mode = ssl.CERT_REQUIRED

        return context

    @staticmethod
    def get_certificate_fingerprint(cert_der: bytes) -> str:
        """
        Calculate SHA-256 fingerprint of a certificate.

        Args:
            cert_der: DER-encoded certificate bytes

        Returns:
            Hex-encoded SHA-256 fingerprint
        """
        return hashlib.sha256(cert_der).hexdigest()

    async def validate_certificate(
        self,
        request: web.Request,
    ) -> Optional[CallerIdentity]:
        """
        Validate client certificate from an aiohttp request.

        Args:
            request: aiohttp web request

        Returns:
            CallerIdentity if valid, None otherwise
        """
        # Get SSL object from transport
        transport = request.transport
        if not transport:
            self.logger.debug("No transport available")
            return None

        ssl_object = transport.get_extra_info('ssl_object')
        if not ssl_object:
            self.logger.debug("No SSL object (not HTTPS?)")
            return None

        # Get peer certificate
        peer_cert = ssl_object.getpeercert(binary_form=True)
        if not peer_cert:
            if self._require_client_cert:
                self.logger.warning("No client certificate provided")
            return None

        # Calculate fingerprint
        fingerprint = self.get_certificate_fingerprint(peer_cert)

        # Look up identity by fingerprint
        if self._credential_provider:
            identity = await self._credential_provider.get_agent_by_certificate(
                fingerprint
            )
            if identity:
                self.logger.debug(f"mTLS auth success: {identity.agent_name}")
                return identity

        # If no provider, create minimal identity from cert
        if cert_info := ssl_object.getpeercert():
            # Extract common name from subject
            subject = dict(x[0] for x in cert_info.get('subject', ()))
            cn = subject.get('commonName', 'unknown')

            return CallerIdentity(
                agent_name=cn,
                auth_scheme=AuthScheme.MTLS,
                certificate_fingerprint=fingerprint,
            )

        return None


# ─────────────────────────────────────────────────────────────────────────────
# Security Middleware
# ─────────────────────────────────────────────────────────────────────────────

class A2ASecurityMiddleware:
    """
    Security middleware for A2AServer.

    Handles authentication and authorization for incoming A2A requests.

    Example:
        middleware = A2ASecurityMiddleware(
            jwt_authenticator=jwt_auth,
            credential_provider=provider,
            default_policy=SecurityPolicy(require_auth=True),
        )

        # Add to A2AServer
        a2a_server.add_security(middleware)

        # Or use directly as aiohttp middleware
        app.middlewares.append(middleware.middleware)
    """

    # Header names
    AUTH_HEADER = "Authorization"
    API_KEY_HEADER = "X-API-Key"
    AGENT_NAME_HEADER = "X-Agent-Name"
    HMAC_SIGNATURE_HEADER = "X-A2A-Signature"
    HMAC_TIMESTAMP_HEADER = "X-A2A-Timestamp"

    def __init__(
        self,
        *,
        jwt_authenticator: Optional[JWTAuthenticator] = None,
        mtls_authenticator: Optional[MTLSAuthenticator] = None,
        credential_provider: Optional[CredentialProvider] = None,
        default_policy: Optional[SecurityPolicy] = None,
        skip_paths: Optional[List[str]] = None,
        rate_limiter: Optional[Any] = None,  # Optional rate limiter
    ):
        """
        Initialize security middleware.

        Args:
            jwt_authenticator: JWT authenticator for bearer tokens
            mtls_authenticator: mTLS authenticator
            credential_provider: Credential provider for API keys
            default_policy: Default security policy
            skip_paths: Paths to skip authentication (e.g., health checks)
            rate_limiter: Optional rate limiter implementation
        """
        self._jwt = jwt_authenticator
        self._mtls = mtls_authenticator
        self._provider = credential_provider
        self._default_policy = default_policy or SecurityPolicy()
        self._skip_paths = set(skip_paths or [
            "/.well-known/agent.json",
            "/health",
            "/ready",
        ])
        self._rate_limiter = rate_limiter

        # Skill-specific policies
        self._skill_policies: Dict[str, SecurityPolicy] = {}

        self.logger = logging.getLogger("A2A.Security.Middleware")

    def set_skill_policy(self, skill_id: str, policy: SecurityPolicy) -> None:
        """Set security policy for a specific skill."""
        self._skill_policies[skill_id] = policy

    def get_policy(self, skill_id: Optional[str] = None) -> SecurityPolicy:
        """Get policy for a skill or the default."""
        if skill_id and skill_id in self._skill_policies:
            return self._skill_policies[skill_id]
        return self._default_policy

    async def authenticate(self, request: web.Request) -> Optional[CallerIdentity]:
        """
        Authenticate an incoming request.

        Tries authentication methods in order:
        1. mTLS (if client certificate present)
        2. Bearer token (Authorization header)
        3. API key (X-API-Key header)
        4. HMAC signature
        5. Basic auth

        Args:
            request: aiohttp request

        Returns:
            CallerIdentity if authenticated, None otherwise
        """
        # Try mTLS first
        if self._mtls:
            identity = await self._mtls.validate_certificate(request)
            if identity:
                return identity

        # Check Authorization header
        if auth_header := request.headers.get(self.AUTH_HEADER):
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                if self._jwt:
                    identity = await self._jwt.validate_token(token)
                    if identity:
                        return identity
                # Try credential provider
                if self._provider:
                    identity = await self._provider.get_agent_by_token(token)
                    if identity:
                        return identity

            elif auth_header.startswith("Basic "):
                if self._provider:
                    with contextlib.suppress(Exception):
                        decoded = base64.b64decode(auth_header[6:]).decode()
                        username, password = decoded.split(":", 1)
                        identity = await self._provider.validate_basic_auth(
                            username, password
                        )
                        if identity:
                            return identity

        # Check API key header
        api_key = request.headers.get(self.API_KEY_HEADER)
        if api_key and self._provider:
            result = await self._provider.get_api_key(api_key)
            if result:
                return result.get("identity")

        # Check HMAC signature
        signature = request.headers.get(self.HMAC_SIGNATURE_HEADER)
        timestamp = request.headers.get(self.HMAC_TIMESTAMP_HEADER)
        if signature and timestamp and self._provider:
            body = await request.read()
            agent_name = request.headers.get(self.AGENT_NAME_HEADER)
            identity = await self._provider.validate_hmac(
                signature, body, timestamp, agent_name
            )
            if identity:
                return identity

        return None

    async def authorize(
        self,
        identity: CallerIdentity,
        policy: SecurityPolicy,
        skill_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Authorize an authenticated identity against a policy.

        Args:
            identity: Authenticated caller identity
            policy: Security policy to check
            skill_id: Optional skill being invoked

        Returns:
            Tuple of (authorized: bool, error_message: Optional[str])
        """
        # Check if agent is allowed
        if not policy.is_agent_allowed(identity.agent_name):
            return False, f"Agent '{identity.agent_name}' not allowed"

        # Check auth scheme
        if identity.auth_scheme and not policy.allows_scheme(identity.auth_scheme):
            return False, f"Auth scheme '{identity.auth_scheme.value}' not allowed"

        # Check permissions
        if not policy.check_permissions(identity):
            return False, "Insufficient permissions"

        # Check roles
        if not policy.check_roles(identity):
            return False, "Required role not present"

        # Check scopes
        if not policy.check_scopes(identity):
            return False, "Required scope not present"

        # Check skill-specific permission
        if skill_id and not identity.can_invoke_skill(skill_id):
            return False, f"Cannot invoke skill '{skill_id}'"

        return True, None

    @web.middleware
    async def middleware(
        self,
        request: web.Request,
        handler: Callable,
    ) -> web.Response:
        """
        aiohttp middleware for security.

        Intercepts requests, performs authentication/authorization,
        and either allows the request or returns an error response.
        """
        path = request.path

        # Skip authentication for certain paths
        if path in self._skip_paths:
            return await handler(request)

        # Get applicable policy
        skill_id = request.match_info.get("skill_id")
        policy = self.get_policy(skill_id)

        # Skip auth if not required
        if not policy.require_auth:
            return await handler(request)

        # Check HTTPS requirement
        if policy.require_https and request.scheme != "https":
            return web.json_response(
                {"error": "HTTPS required"},
                status=403
            )

        # Authenticate
        identity = await self.authenticate(request)

        if not identity:
            self.logger.warning(f"Authentication failed for {path}")
            return web.json_response(
                {"error": "Authentication required"},
                status=401,
                headers={"WWW-Authenticate": 'Bearer realm="a2a"'},
            )

        # Check identity expiration
        if identity.is_expired():
            return web.json_response(
                {"error": "Token expired"},
                status=401,
            )

        # Authorize
        authorized, error = await self.authorize(identity, policy, skill_id)

        if not authorized:
            self.logger.warning(
                f"Authorization failed for {identity.agent_name}: {error}"
            )
            return web.json_response(
                {"error": error or "Access denied"},
                status=403,
            )

        # Rate limiting
        if self._rate_limiter and policy.rate_limit:
            allowed = await self._rate_limiter.check(
                identity.agent_name,
                policy.rate_limit,
            )
            if not allowed:
                return web.json_response(
                    {"error": "Rate limit exceeded"},
                    status=429,
                    headers={"Retry-After": "60"},
                )

        # Store identity in request for handlers
        request["a2a_identity"] = identity

        return await handler(request)


# ─────────────────────────────────────────────────────────────────────────────
# Secure A2A Client
# ─────────────────────────────────────────────────────────────────────────────

class SecureA2AClient:
    """
    Wrapper for A2AClient with automatic authentication.

    Handles credential management and automatic token refresh.

    Example:
        # With API key
        client = SecureA2AClient(
            "http://agent:8080",
            auth_scheme=AuthScheme.API_KEY,
            api_key="your-api-key",
        )

        # With JWT
        client = SecureA2AClient(
            "http://agent:8080",
            auth_scheme=AuthScheme.BEARER,
            token=jwt_token,
        )

        # With JWT auto-refresh
        client = SecureA2AClient(
            "http://agent:8080",
            auth_scheme=AuthScheme.BEARER,
            jwt_authenticator=jwt_auth,
            agent_name="MyAgent",
            permissions=["skill:*"],
        )

        # With mTLS
        client = SecureA2AClient(
            "https://agent:8443",
            auth_scheme=AuthScheme.MTLS,
            cert_path="/path/to/client.crt",
            key_path="/path/to/client.key",
            ca_cert_path="/path/to/ca.crt",
        )

        async with client:
            task = await client.send_message("Hello!")
    """

    def __init__(
        self,
        base_url: str,
        *,
        auth_scheme: AuthScheme = AuthScheme.API_KEY,
        # API Key auth
        api_key: Optional[str] = None,
        api_key_header: str = "X-API-Key",
        # Bearer auth
        token: Optional[str] = None,
        jwt_authenticator: Optional[JWTAuthenticator] = None,
        agent_name: Optional[str] = None,
        permissions: Optional[List[str]] = None,
        roles: Optional[List[str]] = None,
        scopes: Optional[List[str]] = None,
        token_refresh_threshold: int = 300,  # Refresh 5 min before expiry
        # mTLS
        cert_path: Optional[str] = None,
        key_path: Optional[str] = None,
        ca_cert_path: Optional[str] = None,
        key_password: Optional[str] = None,
        # HMAC
        hmac_secret: Optional[str] = None,
        # Common
        timeout: float = 60.0,
        headers: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize secure A2A client.

        Args:
            base_url: Remote agent URL
            auth_scheme: Authentication scheme to use
            api_key: API key for API_KEY scheme
            api_key_header: Header name for API key
            token: Pre-generated token for BEARER scheme
            jwt_authenticator: JWT auth for auto token generation/refresh
            agent_name: Agent name for JWT claims
            permissions: Permissions for JWT claims
            roles: Roles for JWT claims
            scopes: Scopes for JWT claims
            token_refresh_threshold: Seconds before expiry to refresh
            cert_path: Client certificate for mTLS
            key_path: Client key for mTLS
            ca_cert_path: CA certificate for mTLS
            key_password: Password for encrypted key
            hmac_secret: Secret for HMAC signing
            timeout: Request timeout
            headers: Additional headers
        """
        self._base_url = base_url
        self._auth_scheme = auth_scheme
        self._api_key = api_key
        self._api_key_header = api_key_header
        self._token = token
        self._jwt_auth = jwt_authenticator
        self._agent_name = agent_name
        self._permissions = permissions or []
        self._roles = roles or []
        self._scopes = scopes or []
        self._token_refresh_threshold = token_refresh_threshold
        self._cert_path = cert_path
        self._key_path = key_path
        self._ca_cert_path = ca_cert_path
        self._key_password = key_password
        self._hmac_secret = hmac_secret
        self._timeout = timeout
        self._extra_headers = headers or {}

        self._token_expires_at: Optional[datetime] = None
        self._client: Optional["A2AClient"] = None
        self._ssl_context: Optional[ssl.SSLContext] = None

        self.logger = logging.getLogger("A2A.SecureClient")

        # Validate configuration
        self._validate_config()

    def _validate_config(self) -> None:
        """Validate authentication configuration."""
        scheme = self._auth_scheme

        if scheme == AuthScheme.API_KEY:
            if not self._api_key:
                raise ValueError("api_key required for API_KEY scheme")

        elif scheme == AuthScheme.BEARER:
            if not self._token and not self._jwt_auth:
                raise ValueError(
                    "token or jwt_authenticator required for BEARER scheme"
                )
            if self._jwt_auth and not self._agent_name:
                raise ValueError("agent_name required for JWT auto-generation")

        elif scheme == AuthScheme.MTLS:
            if not self._cert_path or not self._key_path:
                raise ValueError("cert_path and key_path required for MTLS")

        elif scheme == AuthScheme.HMAC:
            if not self._hmac_secret:
                raise ValueError("hmac_secret required for HMAC scheme")
            if not self._agent_name:
                raise ValueError("agent_name required for HMAC scheme")

    async def _ensure_token(self) -> str:
        """Ensure we have a valid token, refreshing if needed."""
        # If we have a static token, use it
        if self._token and not self._jwt_auth:
            return self._token

        # Check if token needs refresh
        needs_refresh = (
            self._token is None or self._token_expires_at is None
            or datetime.now(timezone.utc) + timedelta(
                seconds=self._token_refresh_threshold
            ) > self._token_expires_at
        )

        if needs_refresh and self._jwt_auth:
            self._token = self._jwt_auth.create_token(
                agent_name=self._agent_name,
                permissions=self._permissions,
                roles=self._roles,
                scopes=self._scopes,
            )

            # Decode to get expiry
            payload = self._jwt_auth.decode_without_verification(self._token)
            if payload and "exp" in payload:
                self._token_expires_at = datetime.fromtimestamp(
                    payload["exp"],
                    tz=timezone.utc
                )

        return self._token

    def _get_ssl_context(self) -> Optional[ssl.SSLContext]:
        """Get SSL context for mTLS."""
        if self._auth_scheme != AuthScheme.MTLS:
            return None

        if self._ssl_context is None:
            mtls = MTLSAuthenticator(ca_cert_path=self._ca_cert_path)
            self._ssl_context = mtls.create_client_ssl_context(
                cert_path=self._cert_path,
                key_path=self._key_path,
                key_password=self._key_password,
            )

        return self._ssl_context

    def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers based on scheme."""
        headers = dict(self._extra_headers)

        if self._auth_scheme == AuthScheme.API_KEY:
            headers[self._api_key_header] = self._api_key

        elif self._auth_scheme == AuthScheme.BEARER:
            # Token will be added in _prepare_request
            pass

        elif self._auth_scheme == AuthScheme.HMAC:
            headers[A2ASecurityMiddleware.AGENT_NAME_HEADER] = self._agent_name

        return headers

    def _sign_request(self, body: bytes) -> Dict[str, str]:
        """Sign request body with HMAC."""
        timestamp = str(int(time.time()))
        message = timestamp.encode() + body

        signature = hmac.new(
            self._hmac_secret.encode(),
            message,
            hashlib.sha256
        ).hexdigest()

        return {
            A2ASecurityMiddleware.HMAC_SIGNATURE_HEADER: signature,
            A2ASecurityMiddleware.HMAC_TIMESTAMP_HEADER: timestamp,
        }

    async def connect(self) -> "A2AClient":
        """
        Create and return a configured A2AClient.

        Returns:
            Connected A2AClient with authentication configured
        """
        from .client import A2AClient  # pylint: disable=C0415

        # Get base headers
        headers = self._get_auth_headers()

        # Add bearer token if needed
        if self._auth_scheme == AuthScheme.BEARER:
            token = await self._ensure_token()
            headers["Authorization"] = f"Bearer {token}"

        # Create client
        self._client = A2AClient(
            self._base_url,
            timeout=self._timeout,
            headers=headers,
        )

        # Connect with SSL context if mTLS
        if ssl_ctx := self._get_ssl_context():
            # For mTLS, we need to create session with SSL
            connector = aiohttp.TCPConnector(ssl=ssl_ctx)
            session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._timeout),
                headers=headers,
                connector=connector,
            )
            await self._client.connect(session=session)
        else:
            await self._client.connect()

        return self._client

    async def disconnect(self) -> None:
        """Disconnect the client."""
        if self._client:
            await self._client.disconnect()
            self._client = None

    async def __aenter__(self) -> "A2AClient":
        return await self.connect()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    # Proxy methods to underlying client
    async def send_message(self, content: str, **kwargs):
        """Send message through secure client."""
        if not self._client:
            await self.connect()
        return await self._client.send_message(content, **kwargs)

    async def stream_message(self, content: str, **kwargs):
        """Stream message through secure client."""
        if not self._client:
            await self.connect()
        async for chunk in self._client.stream_message(content, **kwargs):
            yield chunk

    async def invoke_skill(self, skill_id: str, params=None, **kwargs):
        """Invoke skill through secure client."""
        if not self._client:
            await self.connect()
        return await self._client.invoke_skill(skill_id, params, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# Utility Functions
# ─────────────────────────────────────────────────────────────────────────────
def generate_api_key(prefix: str = "a2a") -> str:
    """Generate a secure API key."""
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def generate_hmac_secret() -> str:
    """Generate a secure HMAC secret."""
    return secrets.token_urlsafe(32)


def hash_password(password: str) -> str:
    """Hash a password for storage."""
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
    return salt.hex() + key.hex()


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a hash."""
    salt = bytes.fromhex(hashed[:32])
    stored_key = bytes.fromhex(hashed[32:])
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
    return secrets.compare_digest(key, stored_key)


def get_request_identity(request: web.Request) -> Optional[CallerIdentity]:
    """Get the authenticated identity from a request."""
    return request.get("a2a_identity")


def require_permission(permission: str):
    """
    Decorator to require a specific permission.

    Example:
        @require_permission("skill:admin")
        async def admin_handler(request):
            ...
    """
    def decorator(handler):
        @wraps(handler)
        async def wrapper(request):
            identity = get_request_identity(request)
            if not identity:
                return web.json_response(
                    {"error": "Authentication required"},
                    status=401
                )
            if not identity.has_permission(permission):
                return web.json_response(
                    {"error": f"Permission '{permission}' required"},
                    status=403
                )
            return await handler(request)
        return wrapper
    return decorator


def require_role(role: str):
    """
    Decorator to require a specific role.

    Example:
        @require_role("admin")
        async def admin_handler(request):
            ...
    """
    def decorator(handler):
        @wraps(handler)
        async def wrapper(request):
            identity = get_request_identity(request)
            if not identity:
                return web.json_response(
                    {"error": "Authentication required"},
                    status=401
                )
            if not identity.has_role(role):
                return web.json_response(
                    {"error": f"Role '{role}' required"},
                    status=403
                )
            return await handler(request)
        return wrapper
    return decorator
