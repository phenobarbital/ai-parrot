---
type: Wiki Summary
title: parrot_formdesigner.services.form_version
id: mod:parrot_formdesigner.services.form_version
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: FormVersionService — immutable semver publishing for FormSchema objects.
relates_to:
- concept: class:parrot_formdesigner.services.form_version.FormVersionService
  rel: defines
- concept: class:parrot_formdesigner.services.form_version.VersionMeta
  rel: defines
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.services._db_utils
  rel: references
- concept: mod:parrot_formdesigner.services.registry
  rel: references
---

# `parrot_formdesigner.services.form_version`

FormVersionService — immutable semver publishing for FormSchema objects.

Implements the form publishing lifecycle described in FEAT-300 §2 (RF-06):
- Publishing freezes the current form as a semver-tagged snapshot.
- Published snapshots are immutable — overwriting raises ``ValueError``.
- In-flight responses resolve against the version they started with.
- Deletion of a form/version with associated responses is blocked (caller
  provides a ``has_responses`` hook).

FEAT-300 — Module 4.

## Classes

- **`VersionMeta(BaseModel)`** — Metadata record for a published form version.
- **`FormVersionService`** — Immutable semver publishing service for ``FormSchema`` objects.
