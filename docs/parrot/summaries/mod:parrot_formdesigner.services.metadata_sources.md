---
type: Wiki Summary
title: parrot_formdesigner.services.metadata_sources
id: mod:parrot_formdesigner.services.metadata_sources
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Built-in resolvers for ``FormMetadataField`` sources.
relates_to:
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.services.submissions
  rel: references
---

# `parrot_formdesigner.services.metadata_sources`

Built-in resolvers for ``FormMetadataField`` sources.

This module owns the dispatch table that maps a ``MetadataSource``
literal (e.g. ``"user_id"``, ``"locale"``) to an async resolver that
extracts the corresponding value from the inbound aiohttp request,
the in-flight ``FormSubmission`` record, and the parent ``FormSchema``.

The resolvers deliberately stay tolerant of missing context (returning
``None`` rather than raising) so the enricher can apply the field's
``default`` substitution and ``required`` semantics uniformly.
