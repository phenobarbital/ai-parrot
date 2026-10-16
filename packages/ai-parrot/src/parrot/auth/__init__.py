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

from typing import Any

_LAZY_ATTRS: dict[str, str] = {
    "UserContext": "parrot.auth.context",
    "PermissionContext": "parrot.auth.permission",
    "UserSession": "parrot.auth.permission",
    "AbstractPermissionResolver": "parrot.auth.resolver",
    "AllowAllResolver": "parrot.auth.resolver",
    "DefaultPermissionResolver": "parrot.auth.resolver",
    "DenyAllResolver": "parrot.auth.resolver",
    "PBACPermissionResolver": "parrot.auth.resolver",
    "setup_pbac": "parrot.auth.pbac",
    "build_eval_context": "parrot.auth.eval_context",
    "EmployeeProfile": "parrot.auth.userinfo",
    "UserInfoService": "parrot.auth.userinfo",
    "DatasetPolicyGuard": "parrot.auth.dataset_guard",
    "DataPlanePolicyGuard": "parrot.auth.dataplane_guard",
    "RlsRegistry": "parrot.auth.rls_registry",
    "RlsRule": "parrot.auth.rls_registry",
    "RlsPredicate": "parrot.auth.rls_registry",
    "PolicyRuleConfig": "parrot.auth.models",
    "AuthorizationRequired": "parrot.auth.exceptions",
    "AgentAccessDenied": "parrot.auth.agent_guard",
    "CredentialResolver": "parrot.auth.credentials",
    "OAuthCredentialResolver": "parrot.auth.credentials",
    "StaticCredentialResolver": "parrot.auth.credentials",
    "StaticCredentials": "parrot.auth.credentials",
    "AuthKind": "parrot.auth.credentials",
    "ProviderCredentialConfig": "parrot.auth.credentials",
    "ResolvedCredential": "parrot.auth.credentials",
    "NeedsAuth": "parrot.auth.credentials",
    "CredentialRequired": "parrot.auth.credentials",
    "CredentialBroker": "parrot.auth.broker",
    "CredentialResolverFactory": "parrot.auth.broker",
    "Grant": "parrot.auth.grants",
    "GrantConfig": "parrot.auth.grants",
    "GrantStore": "parrot.auth.grants",
    "InMemoryGrantStore": "parrot.auth.grants",
    "GrantGuard": "parrot.auth.grants",
    "GuardDecision": "parrot.auth.grants",
    "ConfirmationConfig": "parrot.auth.confirmation",
    "ConfirmationDecision": "parrot.auth.confirmation",
    "ConfirmationWindowStore": "parrot.auth.confirmation",
    "InMemoryConfirmationWindowStore": "parrot.auth.confirmation",
    "ConfirmationGuard": "parrot.auth.confirmation",
    "compute_args_hash": "parrot.auth.confirmation",
}

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
    # Canonical PBAC EvalContext builder (FEAT-446)
    "build_eval_context",
    # UserInfoService + EmployeeProfile (FEAT-406)
    "EmployeeProfile",
    "UserInfoService",
    # Dataset policy guard
    "DatasetPolicyGuard",
    # Data-plane policy guard (FEAT-228)
    "DataPlanePolicyGuard",
    # RLS registry (FEAT-228)
    "RlsRegistry",
    "RlsRule",
    "RlsPredicate",
    # Policy models
    "PolicyRuleConfig",
    # Exceptions
    "AuthorizationRequired",
    "AgentAccessDenied",
    # Credential resolvers (pre-FEAT-264)
    "CredentialResolver",
    "OAuthCredentialResolver",
    "StaticCredentialResolver",
    "StaticCredentials",
    # FEAT-264: broker models + signals
    "AuthKind",
    "ProviderCredentialConfig",
    "ResolvedCredential",
    "NeedsAuth",
    "CredentialRequired",
    "CredentialBroker",
    "CredentialResolverFactory",
    # Grants (bounded approval windows)
    "Grant",
    "GrantConfig",
    "GrantStore",
    "InMemoryGrantStore",
    "GrantGuard",
    "GuardDecision",
    # Confirmation (per-call HITL review — FEAT-235)
    "ConfirmationConfig",
    "ConfirmationDecision",
    "ConfirmationWindowStore",
    "InMemoryConfirmationWindowStore",
    "ConfirmationGuard",
    "compute_args_hash",
]


def __getattr__(name: str) -> Any:
    """Resolve a public auth export on first access and cache it.

    Args:
        name: Attribute requested on the package.

    Returns:
        The object defined in the owning submodule.

    Raises:
        AttributeError: If ``name`` is not a public auth export.
    """
    module_path = _LAZY_ATTRS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    import importlib

    value = getattr(importlib.import_module(module_path), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy exports to ``dir()``."""
    return sorted(set(globals()) | set(__all__))
