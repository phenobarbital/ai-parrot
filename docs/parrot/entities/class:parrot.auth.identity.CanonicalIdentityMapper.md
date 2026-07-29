---
type: Wiki Entity
title: CanonicalIdentityMapper
id: class:parrot.auth.identity.CanonicalIdentityMapper
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Maps raw per-surface identity data to a single canonical vault key.
---

# CanonicalIdentityMapper

Defined in [`parrot.auth.identity`](../summaries/mod:parrot.auth.identity.md).

```python
class CanonicalIdentityMapper
```

Maps raw per-surface identity data to a single canonical vault key.

The canonical key is used as the *user_id* parameter when the broker looks
up credentials in the vault.  Credentials stored under one surface are
automatically reusable on any other surface that resolves to the same
canonical key.

Precedence (most stable → least stable):
1. Entra OID (UUID string) — stable across surface changes and email renames.
2. Email address (lower-cased) — stable across surfaces but not renames.
3. ``None`` — anonymous / development identity; callers **must** fail closed.

The mapper is stateless; call :meth:`to_canonical` directly or use the
module-level singleton :data:`identity_mapper`.

## Methods

- `def to_canonical(raw_identity: Dict[str, Any]) -> Optional[str]` — Map a raw identity dict to a canonical vault key.
