---
type: Wiki Summary
title: parrot.tools.dataset_manager.sources.authorizing
id: mod:parrot.tools.dataset_manager.sources.authorizing
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AuthorizingDataSource — DataSource decorator for FEAT-228.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.authorizing.AuthorizingDataSource
  rel: defines
- concept: mod:parrot.auth.dataplane_guard
  rel: references
- concept: mod:parrot.auth.exceptions
  rel: references
- concept: mod:parrot.auth.permission
  rel: references
- concept: mod:parrot.auth.rls_registry
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.base
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.dialects
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.mongo
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.query_slug
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.resolver
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.rls
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.sql
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.table
  rel: references
---

# `parrot.tools.dataset_manager.sources.authorizing`

AuthorizingDataSource — DataSource decorator for FEAT-228.

Wraps any :class:`~parrot.tools.dataset_manager.sources.base.DataSource` with
the full data-plane authorization + RLS enforcement chain (Spec §2, Module 7).

This is the keystone of Option D (enforcement at source construction time).
Its ``fetch()`` method runs the complete enforcement chain before delegating
to the inner source:

0. Sensitive-driver pre-check: if the driver is classed sensitive, reject any
   non-:class:`~parrot.tools.dataset_manager.sources.query_slug.QuerySlugSource`.
1. Get ``PermissionContext`` from the provider.  ``None`` → fail-open.
2. Resolve physical resources from the inner source via ``resolve_physical_resources``.
3. Call ``guard.authorize_source(ctx, resources)`` (raises on denial).
4. Collect RLS predicates from the guard.
5. Inject RLS predicates into the inner source/query.
6. Delegate to ``inner.fetch()``.

Transparent delegation:
- ``describe()`` → delegates to inner.
- ``cache_key`` → delegates to inner.
- ``has_builtin_cache`` → delegates to inner.
- ``prefetch_schema()`` → delegates to inner.

## Classes

- **`AuthorizingDataSource(DataSource)`** — Decorator that wraps a DataSource with authorization + RLS enforcement.
