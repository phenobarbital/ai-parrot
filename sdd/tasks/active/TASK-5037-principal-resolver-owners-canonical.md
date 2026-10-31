# TASK-5037: IdentityPrincipalResolver — Slack exactly-one-owner + cli/a2a canonical-identity lookup (D4)

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Two resolver changes share `services/identity_principal.py` and are therefore one task:

1. **Slack (spec M2).** `navigator_auth.identity.store.IdentityStore.find_user_by_provider_account` returns `rows[0]` of
   the enabled matches even when several Navigator users own the same `("slack", "T:U")`. Resolution must succeed only
   for exactly one owner, otherwise fail closed with a non-secret diagnostic.
2. **cli / a2a (spec M3 "Canonical-identity lookup", D4, AC-16).** S-1 never built an e-mail/OID lookup: the resolver
   returns `None` for any `a2a` id containing `@` and has no `cli` branch, so the O365 device-code resolver (TASK-5046
   resolves `("cli", <email/OID>)`) would always fail closed. This task adds that lookup.

---

## Scope

- `channel == "slack"`: query `auth.user_identities` directly over `self._db_pool` for every row with
  `auth_provider='slack' AND provider_user_id=$1` (disabled included). Resolve only when all rows belong to exactly one
  `user_id` and at least one of its rows is enabled; otherwise `None` + `self.logger.warning` with the row count only.
  `canonical_identity` stays `None` for Slack (unchanged behaviour of the secondary lookup is NOT used for Slack).
  No fallback to a bare `slack_user_id` (spec §7).
- `channel in ("cli", "a2a")`:
  - id contains `@` → lower-case and match `lower(auth.users.email) = $1 AND is_active = true`; `alt_email` is never matched.
  - otherwise → treat as an Entra OID: match enabled `auth.user_identities` rows with `provider_user_id = $1` and
    `auth_provider = ANY($2)` over the Entra-backed providers (verified: `"msteams"` — see contract; verify any other before adding).
  - exactly one distinct `user_id` → `Principal(user_id=str(id), canonical_identity=<lower e-mail | OID>, channel, channel_user_id)`;
    zero / several / inactive / disabled → `None` + non-secret diagnostic (channel + match count).
  - This replaces the current unconditional `a2a`+`@` → `None` branch.
- Every other channel keeps the existing `find_user_by_provider_account` path unchanged.
- Any DB exception → `None` (existing fail-closed behaviour).
- Update the tests: replace `test_a2a_email_fails_closed_without_email_lookup`; add Slack and canonical cases.

**NOT in scope**: writing identities (TASK-5036), the device-code resolver (TASK-5046), navigator-auth changes (none authorized).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/services/identity_principal.py` | MODIFY | Slack owner query, cli/a2a canonical lookup |
| `packages/ai-parrot-server/tests/unit/test_identity_principal_resolver.py` | MODIFY | Replace a2a e-mail test, add Slack + canonical tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.principal import Principal                        # verified: packages/ai-parrot/src/parrot/auth/principal.py:18 (already imported at identity_principal.py:8)
from parrot.services.identity_mapping import _raw_connection       # verified: packages/ai-parrot-server/src/parrot/services/identity_mapping.py:101
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/services/identity_principal.py (73 lines)
class IdentityPrincipalResolver:                                    # :11
    def __init__(self, db_pool: Any) -> None                        # :14 (self._db_pool, self.logger)
    def _store(self) -> Any                                         # :23 — navigator_auth IdentityStore(self._db_pool)
    async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]   # :29
        # web passthrough :34-35
        # `if channel == "a2a" and "@" in channel_user_id:` → return None   :40-41   (REPLACED by this task)
        # store.find_user_by_provider_account(channel, channel_user_id) :45; canonical via get_by_provider :50-57
        # except Exception → warning + None :71-73
# Principal(user_id: str, canonical_identity: Optional[str] = None, tenant_id: Optional[str] = None, channel: str, channel_user_id: str)

# navigator-auth (installed .venv): IdentityStore.find_user_by_provider_account(provider, provider_user_id) → rows[0].user_id of
#   enabled matches (does NOT detect multiple owners); no e-mail lookup method exists.
# Tables: auth.users(user_id, email, alt_email, is_active, ...); auth.user_identities(user_id, auth_provider, provider_user_id, enabled, email, ...)
# Pool acquire pattern for the authdb pool: `async with self._db_pool.acquire() as conn: raw = _raw_connection(conn)`
#   (identity_mapping.py:242-244); asyncpg `raw.fetch(sql, *args)` returns records.
# Entra-backed provider verified: "msteams" — the resolver itself treats msteams provider_user_id as the canonical
#   identity (identity_principal.py:53-54). navigator-auth's Azure backend `_service_name = "azure"`
#   (.venv/.../navigator_auth/backends/azure.py:94) — NOT verified to write auth.user_identities rows.
```

### Does NOT Exist
- ~~`IdentityStore.find_user_by_email` / any navigator-auth e-mail lookup~~ — query `auth.users` directly.
- ~~An `"entra"` / `"o365"` auth_provider value in `auth.user_identities`~~ — not found in src; do not add without evidence.
- ~~A Slack fallback on the bare `slack_user_id`~~ — forbidden (spec §7).
- ~~`alt_email` matching~~ — excluded by D4.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/services/identity_principal.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/unit/test_identity_principal_resolver.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/services/identity_principal.py#IdentityPrincipalResolver",
    "sym:packages/ai-parrot-server/src/parrot/services/identity_principal.py#IdentityPrincipalResolver.resolve",
    "sym:packages/ai-parrot-server/src/parrot/services/identity_mapping.py#_raw_connection"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Trust decision (spec §7 D4): only identities the auth DB already holds are accepted; never pick one of several matches.
- Diagnostics are non-secret: log channel and match count, never the id, e-mail or OID.
- Keep the queries in small private coroutines so tests can monkeypatch them without a database.
- Behaviour change to announce in the Completion Note: a non-`@` `a2a` id is now matched as an Entra OID, not as a
  `provider="a2a"` row.

---

## Implementation Blueprint

### Steps (in order)
1. Add the SQL constants and `_ENTRA_PROVIDERS` at module level — *why*: queries stay greppable and testable.
2. Add `_slack_owner`, `_canonical_owner` private coroutines — *why*: tests monkeypatch them.
3. Replace the `a2a`+`@` early return with the two new branches.
4. Update tests; run them.

### `packages/ai-parrot-server/src/parrot/services/identity_principal.py` (MODIFY — constants)
```python
# occurrences: 1 (verified: grep -c '^class IdentityPrincipalResolver:' packages/ai-parrot-server/src/parrot/services/identity_principal.py)
# BEFORE — insert above `class IdentityPrincipalResolver:` (verified: identity_principal.py:11)
# FEAT-777 D4: providers whose provider_user_id is an Entra object id.
_ENTRA_PROVIDERS: tuple[str, ...] = ("msteams",)  # FILL IN: add "azure" ONLY if verified to write auth.user_identities rows
_CANONICAL_CHANNELS = frozenset({"cli", "a2a"})
_SLACK_OWNERS_SQL = """
SELECT user_id, enabled FROM auth.user_identities
WHERE auth_provider = 'slack' AND provider_user_id = $1
"""
_EMAIL_OWNERS_SQL = "SELECT DISTINCT user_id FROM auth.users WHERE lower(email) = $1 AND is_active IS TRUE"
_OID_OWNERS_SQL = """
SELECT DISTINCT user_id FROM auth.user_identities
WHERE provider_user_id = $1 AND auth_provider = ANY($2::text[]) AND enabled IS TRUE
"""
```

### `packages/ai-parrot-server/src/parrot/services/identity_principal.py` (MODIFY — branches)
```python
# occurrences: 1 (verified: grep -c '        if channel == "a2a" and "@" in channel_user_id:' packages/ai-parrot-server/src/parrot/services/identity_principal.py)
# REPLACE lines :38-41 (the two comment lines + `if channel == "a2a" and "@" in channel_user_id:` + `return None`) with:
        if channel == "slack":
            nav_user_id = await self._slack_owner(channel_user_id)
            if nav_user_id is None:
                return None
            return Principal(user_id=nav_user_id, channel=channel, channel_user_id=channel_user_id)

        if channel in _CANONICAL_CHANNELS:
            # FILL IN: canonical = lower-cased e-mail if "@" in id else the OID; owner = await self._canonical_owner(id);
            #   None → return None; else Principal(user_id=owner, canonical_identity=canonical, channel, channel_user_id).
            #   Wrap in try/except → warning + None (fail closed) — bounded by AC-16
            ...
```
Then add, after `_store` (anchor `    def _store(self) -> Any:`, occurrences: 1, verified identity_principal.py:23):
```python
    async def _fetch(self, sql: str, *args: Any) -> list[Any]:
        """Run one read on the authdb pool (raw asyncpg connection)."""
        from parrot.services.identity_mapping import _raw_connection

        async with self._db_pool.acquire() as conn:
            return list(await _raw_connection(conn).fetch(sql, *args))

    async def _slack_owner(self, channel_user_id: str) -> Optional[str]:
        """Exactly one owner (disabled rows count) with an enabled row, else ``None``."""
        rows = await self._fetch(_SLACK_OWNERS_SQL, channel_user_id)
        # FILL IN: owners = {str(r["user_id"]) for r in rows}; resolve only if len(owners) == 1 and any(r["enabled"]);
        #   otherwise warn with len(rows) only — bounded by spec M2 "exactly one enabled owner or fail closed"
        ...

    async def _canonical_owner(self, channel_user_id: str) -> Optional[str]:
        """E-mail → active auth.users row; OID → enabled Entra identity row; exactly one distinct user or ``None``."""
        # FILL IN: pick _EMAIL_OWNERS_SQL(lower id) or _OID_OWNERS_SQL(id, list(_ENTRA_PROVIDERS)); exactly one distinct
        #   user_id → str(id), else warn with the match count — bounded by AC-16
        ...
```
**Why**: the Slack and canonical paths bypass `IdentityStore` because it cannot detect several owners or look up e-mails;
the pool is the one the resolver already holds, so no dependency change is needed (spec M2/M3).

### `packages/ai-parrot-server/tests/unit/test_identity_principal_resolver.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def test_a2a_email_fails_closed_without_email_lookup' packages/ai-parrot-server/tests/unit/test_identity_principal_resolver.py)
# REPLACE the test at :120-128 with the tests below (monkeypatch resolver._fetch with a stub keyed by SQL constant):

@pytest.mark.asyncio
async def test_resolver_canonical_identity_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """cli/a2a: unique active e-mail (case-insensitive) and unique enabled OID resolve; ambiguity/no match → None."""
    # FILL IN: e-mail "JLara@Example.com" → user "1042", canonical "jlara@example.com"; OID → "2042", canonical OID;
    #   zero rows, two distinct users → None; assert the e-mail query receives the lower-cased value and never alt_email
    ...


@pytest.mark.asyncio
async def test_slack_resolution_requires_single_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    """One owner with an enabled row resolves; two owners, only-disabled rows or no rows → None; bare id never looked up."""
    # FILL IN
    ...


@pytest.mark.asyncio
async def test_canonical_lookup_db_error_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: _fetch raises → resolve("cli", "x@y.z") is None
    ...
```

### FILL IN checklist
- [ ] `_ENTRA_PROVIDERS` — "msteams" verified; anything else only with evidence.
- [ ] Canonical branch + `_canonical_owner` — bounded by AC-16.
- [ ] `_slack_owner` decision — bounded by spec M2 and `test_channel_link_existing_ambiguous_or_disabled_owner`.
- [ ] Three new tests; the old a2a test removed.

---

## Acceptance Criteria

- [ ] AC-16: `resolve("cli"|"a2a", id)` resolves a unique active e-mail (case-insensitive) or unique enabled Entra OID; zero/multiple
  matches, inactive users, disabled identities and `alt_email` → `None`.
- [ ] Slack resolves only for exactly one owner; ambiguous/disabled-only → `None` with a non-secret warning.
- [ ] Telegram/msteams/web behaviour unchanged (existing tests pass).
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_identity_principal_resolver.py -q`

---

## Test Specification

See the MODIFY test block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** (§3 Module 2 resolver comment, Module 3 "Canonical-identity lookup (M3, D4)", AC-16, §7 risks)
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing code
5. **Update status** → `"in-progress"` and commit only the index file
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — only the listed files
9. **Close the task** with `scripts/sdd/close_task.sh TASK-5037 connections-web-slack verified`
10. **Fill in the Completion Note** (announce the non-`@` a2a behaviour change), then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
