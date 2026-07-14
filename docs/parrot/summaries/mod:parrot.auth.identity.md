---
type: Wiki Summary
title: parrot.auth.identity
id: mod:parrot.auth.identity
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Canonical identity mapper for cross-surface credential reuse.
relates_to:
- concept: class:parrot.auth.identity.CanonicalIdentityMapper
  rel: defines
---

# `parrot.auth.identity`

Canonical identity mapper for cross-surface credential reuse.

Normalises per-surface raw identity data to a single canonical vault key
so credentials captured on A2A are honoured in MSAgentSDK chat (and any
other surface) without re-authentication.

Precedence: Entra OID (UUID) → email (lower-cased) → ``None`` (fail closed).

## Classes

- **`CanonicalIdentityMapper`** — Maps raw per-surface identity data to a single canonical vault key.
