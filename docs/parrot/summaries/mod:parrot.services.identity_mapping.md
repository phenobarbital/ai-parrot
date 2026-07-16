---
type: Wiki Summary
title: parrot.services.identity_mapping
id: mod:parrot.services.identity_mapping
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: IdentityMappingService — CRUD for navigator-auth ``user_identities``.
relates_to:
- concept: class:parrot.services.identity_mapping.IdentityMappingService
  rel: defines
---

# `parrot.services.identity_mapping`

IdentityMappingService — CRUD for navigator-auth ``user_identities``.

Links navigator-auth internal user IDs with external provider identities
(Telegram numeric IDs, Jira account IDs, etc.). Records live in the
``auth.users_identities`` table and have a unique composite key
``(user_id, auth_provider)``.

Uses raw SQL against the ``authdb`` connection pool because the
``UserIdentity`` ORM model from navigator-auth is not always importable
from ai-parrot, and raw SQL keeps the service portable.

## Classes

- **`IdentityMappingService`** — CRUD service for ``auth.user_identities`` records.
