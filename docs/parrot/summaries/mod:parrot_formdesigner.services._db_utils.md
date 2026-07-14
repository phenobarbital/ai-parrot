---
type: Wiki Summary
title: parrot_formdesigner.services._db_utils
id: mod:parrot_formdesigner.services._db_utils
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Shared database utilities for parrot-formdesigner services.
relates_to:
- concept: func:parrot_formdesigner.services._db_utils.is_unique_violation
  rel: defines
---

# `parrot_formdesigner.services._db_utils`

Shared database utilities for parrot-formdesigner services.

## Functions

- `def is_unique_violation(exc: Exception) -> bool` — Return True when ``exc`` is a Postgres UNIQUE constraint violation.
