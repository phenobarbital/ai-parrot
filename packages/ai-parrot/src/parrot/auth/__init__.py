"""Authentication and authorization module for AI-Parrot.

This module provides granular permission control for tools and toolkits.

Public API:
    Data Models:
    - UserSession: Immutable session with user identity and role claims
    - PermissionContext: Request-scoped wrapper for permission checking

    Resolvers:
    - AbstractPermissionResolver: ABC for custom permission implementations
    - DefaultPermissionResolver: RBAC implementation with hierarchy and caching
    - AllowAllResolver: Development/testing resolver (allows everything)
    - DenyAllResolver: Lockdown resolver (denies restricted tools)

Example:
    >>> from parrot.auth import UserSession, PermissionContext, DefaultPermissionResolver
    >>> session = UserSession(
    ...     user_id="user-123",
    ...     tenant_id="acme-corp",
    ...     roles=frozenset({'jira.write', 'github.read'})
    ... )
    >>> ctx = PermissionContext(session=session, request_id="req-456")
    >>> resolver = DefaultPermissionResolver(role_hierarchy={'jira.write': {'jira.read'}})
    >>> result = await resolver.can_execute(ctx, "create_issue", {'jira.write'})
    True
"""

from .context import UserContext
from .permission import PermissionContext, UserSession
from .resolver import (
    AbstractPermissionResolver,
    AllowAllResolver,
    DefaultPermissionResolver,
    DenyAllResolver,
    PBACPermissionResolver,
)
from .pbac import setup_pbac
from .models import PolicyRuleConfig
from .exceptions import AuthorizationRequired
from .credentials import (
    CredentialResolver,
    OAuthCredentialResolver,
    StaticCredentialResolver,
    StaticCredentials,
)

__all__ = [
    # Data models
    "UserSession",
    "PermissionContext",
    "UserContext",
    # Resolvers
    "AbstractPermissionResolver",
    "DefaultPermissionResolver",
    "AllowAllResolver",
    "DenyAllResolver",
    "PBACPermissionResolver",
    # PBAC setup
    "setup_pbac",
    # Policy models
    "PolicyRuleConfig",
    # Exceptions
    "AuthorizationRequired",
    # Credential resolvers
    "CredentialResolver",
    "OAuthCredentialResolver",
    "StaticCredentialResolver",
    "StaticCredentials",
]
