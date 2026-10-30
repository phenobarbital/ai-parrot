---
id: F072
query_id: Q003
type: wiki_page
intent: "Follow-up: CanonicalIdentityMapper (FEAT-264 M5) — which principal does the broker key credentials by?"
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: FW-003
depth: 1
merged_from: [FW-019]
---

# F072 — `parrot/auth/identity.py::CanonicalIdentityMapper.to_canonical(raw) -> Entra OID (uuid) | lower-cased email | None` — the broker's vault key is an Entra/email identity, NOT the Navigator bigint `user_id` used by `auth.user_identities`

## Summary

Two incompatible "principal" keys coexist. FEAT-264's broker keys credentials by `CanonicalIdentityMapper.to_canonical()`: precedence OID fields (`oid`, `aad_object_id`, `aadObjectId`, `from_id`) → email fields (`email`, `upn`, `from_email`, `from.email`, `x-ms-user-email`, `sender`) → `None` (fail closed). FEAT-108/729/735's identity layer keys by Navigator `auth.users.user_id` (bigint) with `provider_user_id` per account. FEAT-729 proved the two can be bridged (`TokenExchangeAuth` returns `provider_user_id == oid` and `resolve_user_id` returns the Navigator id). The brainstorm's "principal = navigator-auth user" therefore needs an explicit mapping step from the broker's canonical key to the Navigator id (or vice-versa) — nothing does this today except the Teams lane at login.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/identity.py`
  lines: n/a
  symbol: `CanonicalIdentityMapper.to_canonical`, `_OID_FIELDS`, `_EMAIL_FIELDS`, `identity_mapper` singleton, `_get`
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/identity.py (score=0.77)
  excerpt: |
    Precedence: Entra OID (UUID) → email (lower-cased) → ``None`` (fail closed).
    _OID_FIELDS = ("oid", "aad_object_id", "aadObjectId", "from_id")
    _EMAIL_FIELDS = ("email", "upn", "from_email", "from.email", "x-ms-user-email", "x_ms_user_email", "sender")
- path: `packages/ai-parrot/tests/unit/test_canonical_identity.py`
  lines: n/a
  symbol: TASK-1671 tests
  wiki_page_id: file:packages/ai-parrot/tests/unit/test_canonical_identity.py (score=1.00)
- path: `packages/ai-parrot/src/parrot/cli/identity.py`
  lines: n/a
  symbol: CLI identity bootstrap (FEAT-266) using the mapper
  wiki_page_id: file:packages/ai-parrot/src/parrot/cli/identity.py (score=0.14)
- path: `packages/ai-parrot/src/parrot/auth/session_identity.py`
  lines: n/a
  symbol: `resolve_user_id(request, session)` — backend-independent Navigator user id (FEAT-729 contract `:90`)
  wiki_page_id: dir:packages/ai-parrot/src/parrot/auth

## Notes

Design fork for the proposal: unify on Navigator `user_id` (what `auth.user_identities` and `VaultTokenSync(nav_user_id, …)` use) or on the Entra OID/email canonical key (what the broker/A2A/MSAgentSDK use). Telegram users may have neither OID nor email until they `/login` to Navigator.
