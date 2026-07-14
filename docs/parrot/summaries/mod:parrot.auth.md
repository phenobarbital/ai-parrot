---
type: Wiki Summary
title: parrot.auth
id: mod:parrot.auth
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Authentication and authorization module for AI-Parrot.
relates_to:
- concept: mod:parrot
  rel: references
- concept: mod:parrot.exceptions
  rel: references
- concept: mod:parrot.models
  rel: references
---

# `parrot.auth`

Authentication and authorization module for AI-Parrot.

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
