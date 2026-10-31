# TASK-5074: `IdentityPrincipalResolver` — `msteams` → (`msteams`, `azure`) identity-provider alias

**Feature**: FEAT-775 — Connections on MS Teams
**Spec**: `sdd/specs/connections-msteams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §1 gap 3, §2 "Server (M7)", §3 Module 7, AC-3. FEAT-773's resolver looks up `auth.user_identities` by
`(channel, channel_user_id)` = `("msteams", aad_oid)`, but Teams `/login` writes provider **`azure`**
(navigator-auth `backends/exchange.py:190`). Out-of-turn resolution (e.g. tool calls through
`OAuthCredentialResolver`, notifier fallbacks) therefore misses logged-in Teams users. Add an alias table tried in
order, first hit wins; `canonical_identity` = the AAD oid.

**Cross-feature note**: FEAT-776 TASK-5019 and FEAT-777 TASK-5037/5047 also edit this file. Rebase onto `origin/dev`
before starting and touch only the lookup loop.

---

## Scope

- `_CHANNEL_IDENTITY_PROVIDERS: Dict[str, Tuple[str, ...]] = {"msteams": ("msteams", "azure")}`.
- `resolve`: for each provider in `_CHANNEL_IDENTITY_PROVIDERS.get(channel, (channel,))` call
  `store.find_user_by_provider_account(provider, channel_user_id)`; first non-empty id wins; remember which provider
  matched for the `get_by_provider` canonical-identity read; for `msteams` set `canonical_identity` to the oid when
  the identity row has no `provider_user_id`.
- Tests: `test_resolver_alias_msteams_falls_back_to_azure` + regression for other channels.

**NOT in scope**: writing identity rows; Telegram/Slack lookups.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/services/identity_principal.py` | MODIFY | alias loop |
| `packages/ai-parrot-server/tests/unit/test_identity_principal_resolver.py` | MODIFY | alias tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.principal import Principal                                   # verified: principal.py:18
# navigator_auth.identity.store.IdentityStore — imported lazily in _store() (identity_principal.py:25)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/services/identity_principal.py
    async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]:          # :29
        ...
            store = self._store()
            nav_user_id = await store.find_user_by_provider_account(channel, channel_user_id)     # :45
            if nav_user_id is None or str(nav_user_id) == "": return None
            identity = await store.get_by_provider(nav_user_id, channel)                           # :51
            #   msteams → canonical_identity = identity.provider_user_id; else lower-cased email
            return Principal(user_id=str(nav_user_id), canonical_identity=..., channel=channel, channel_user_id=channel_user_id)
# navigator_auth 0.28.9: IdentityStore.find_user_by_provider_account(provider, provider_user_id) -> Optional[Any]   # identity/store.py:497
```

### Does NOT Exist
- ~~an `msteams` identity row written at Teams `/login`~~ — login writes `azure` (spec §6).
- ~~`IdentityStore.find_user_by_email`~~ — no e-mail lookup (identity_principal.py:39 comment).

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
    "sym:packages/ai-parrot-server/src/parrot/services/identity_principal.py#IdentityPrincipalResolver.resolve"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Module constant. 2. Replace the single lookup with the loop. 3. Use the matched provider for `get_by_provider`. 4. Tests.

### `.../services/identity_principal.py` (MODIFY)
```python
# module level, near the top (after imports)
_CHANNEL_IDENTITY_PROVIDERS: Dict[str, Tuple[str, ...]] = {"msteams": ("msteams", "azure")}

# REPLACE `            nav_user_id = await store.find_user_by_provider_account(channel, channel_user_id)`
#   (verified: identity_principal.py:45, occurrences: 1)
            nav_user_id = None
            matched_provider = channel
            for provider in _CHANNEL_IDENTITY_PROVIDERS.get(channel, (channel,)):
                candidate = await store.find_user_by_provider_account(provider, channel_user_id)
                if candidate is not None and str(candidate) != "":
                    nav_user_id, matched_provider = candidate, provider
                    break

# REPLACE `                identity = await store.get_by_provider(nav_user_id, channel)` (verified: :51, occurrences: 1)
                identity = await store.get_by_provider(nav_user_id, matched_provider)
```
Then `canonical_identity`: keep the `channel == "msteams"` branch; FILL IN: fall back to `channel_user_id` (the oid)
when the matched row has no `provider_user_id` — bounded by spec §2 M7 ("canonical_identity = the AAD oid").
Add `Dict, Tuple` to the typing import.

### Test additions (`test_identity_principal_resolver.py`)
```python
# test_resolver_alias_msteams_falls_back_to_azure — fake store: ("msteams", oid) → None, ("azure", oid) → "42" →
#   Principal(user_id="42", channel="msteams", channel_user_id=oid, canonical_identity=oid); lookup order recorded
# test_resolver_msteams_row_wins_first — msteams row present → azure never queried
# test_resolver_other_channels_single_lookup — telegram → exactly one lookup with provider "telegram"
```

### FILL IN checklist
- [ ] canonical-identity fallback
- [ ] three tests

---

## Acceptance Criteria

- [ ] `resolve("msteams", oid)` returns the principal from an `azure` row when no `msteams` row exists (AC-3).
- [ ] Other channels unchanged. `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot-server/tests/unit/test_identity_principal_resolver.py -q`

---

## Test Specification

Three tests listed above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-msteams --feature-id FEAT-775`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/connections-msteams.json`
4. **Verify the Codebase Contract** — before writing ANY code confirm every import and signature still exists;
   if anything changed, update the contract FIRST; never reference anything listed under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH` pointing at the changed packages
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-<NNN> connections-msteams verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

