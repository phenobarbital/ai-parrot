# TASK-5046: Device-code resolver on the shared O365 record (principal-keyed, manager-backed, legacy migration)

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5045
**Assigned-to**: unassigned

---

## Context

Spec §2 "O365 consolidation (M3, D3)", §3 Module 3 resolver/factory skeletons; AC-8, AC-15, AC-16 (D4).
Today `O365DeviceCodeCredentialResolver` reads and writes its own `VaultTokenSync` `o365:*` record keyed by
the raw e-mail/OID. After this task it:

1. resolves the platform principal first (`resolve_principal(channel, user_id)`; `None` → fail closed),
2. reads through `O365OAuthManager.get_valid_token(channel, principal.user_id)` (Redis → store → locked refresh),
3. on a miss, migrates a legacy `o365:*` entry once via `migrate_legacy_device_grant` (TASK-5045),
4. otherwise runs the device flow and persists through `store_device_grant` (TASK-5045).

`VaultTokenSync` survives only as the optional `legacy_vault` read/delete for the migration window.
D4 (the `cli`/`a2a` e-mail/OID lookup in `IdentityPrincipalResolver`) is a separate task; this resolver only
calls `resolve_principal`, so tests register a fake resolver.

---

## Scope

- Rewrite `O365DeviceCodeCredentialResolver.__init__` / `resolve` / `is_connected` / `_run_device_flow` /
  `_persist_token_set` per the blueprint; add `_migrate_legacy(...)`.
- `_build_device_code` in `broker/factory.py`: require `o365_client`|`o365_interface` + `o365_oauth_manager`;
  pass `legacy_vault=self._deps.get("legacy_vault") or self._deps.get("vault")` (optional).
- `vault_token_sync.py` module docstring: `o365` is no longer served (legacy read only).
- Update the resolver/factory unit tests and the CLI device-code e2e test (`test_cli_device_code_end_to_end`).
  Mark `test_devicecode_token_consumable_by_workiq_obo` `xfail(strict=True)` — WorkIQ moves to the manager in TASK-5047.

**NOT in scope**: `O365OAuthManager` changes (TASK-5045), WorkIQ (TASK-5047), the principal resolver lookup (D4 task),
a generic RFC 8628 engine (FEAT-774).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py` | MODIFY | manager-backed, principal-keyed resolver + legacy migration |
| `packages/ai-parrot/src/parrot/auth/broker/factory.py` | MODIFY | `_build_device_code` deps |
| `packages/ai-parrot-server/src/parrot/services/vault_token_sync.py` | MODIFY | docstring: `o365` no longer served |
| `packages/ai-parrot/tests/auth/test_o365_devicecode_resolver.py` | MODIFY | rewrite for the manager-backed resolver |
| `packages/ai-parrot/tests/auth/test_broker_devicecode.py` | MODIFY | deps without `vault` |
| `packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py` | MODIFY | assert the shared record; xfail the WorkIQ test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.credentials import CredentialResolver          # verified: o365_devicecode_provider.py:41
from parrot.auth.principal import Principal, resolve_principal  # verified: principal.py:18, :73
from parrot.auth.oauth2_base import RefreshTransientError       # verified: oauth2_base.py:108
from parrot.auth.o365_oauth import DEFAULT_O365_SCOPES          # verified: o365_oauth.py:34 (imported lazily in __init__ today)
from parrot.conf import OAUTH2_LEGACY_KEYS_UNTIL                # verified: conf.py:749 (use oauth2_base._legacy_window_open instead of parsing it)
from parrot.auth.oauth2_base import _legacy_window_open         # verified: oauth2_base.py:79 (module-private; S-1's single window check)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py
_O365_VAULT_PREFIX: str = "o365"          # :46 — keep, legacy read only
_EXPIRY_SKEW_SECONDS: int = 60            # :50
_DEVICE_LOGIN_URL = "https://microsoft.com/devicelogin"   # :54
def _default_prompt_callback(flow) -> None                # :57 (prints the CLI prompt — keep unchanged)
class O365DeviceCodeCredentialResolver(CredentialResolver):   # :73
    def __init__(self, o365_client, o365_oauth_manager, vault_token_sync, scopes=None, prompt_callback=None)  # :100-116
    async def resolve(self, channel, user_id) -> Optional[str]        # :117
    async def get_auth_url(self, channel, user_id) -> str             # :180 (unchanged)
    async def is_connected(self, channel, user_id) -> bool            # :188
    async def _run_device_flow(self, user_id) -> str                  # :206 — self._o365.interactive_login(scopes=, open_browser=False, device_flow_callback=)
    async def _persist_token_set(self, user_id, payload, fallback_refresh_token=None) -> None  # :237 (vault write :272)
    @staticmethod _coerce_epoch(value) -> Optional[float]             # :275

# packages/ai-parrot/src/parrot/auth/oauth2_base.py (AbstractOAuth2Manager)
async def get_valid_token(self, channel, user_id, *, channel_user_id=None) -> Optional[AbstractOAuth2TokenSet]  # :642 — refreshes; InvalidGrantError (a PermissionError) on dead refresh token
async def is_connected(self, channel, user_id) -> bool   # :739 (calls get_valid_token)

# TASK-5045 (packages/ai-parrot/src/parrot/auth/o365_oauth.py — created there)
async def store_device_grant(self, principal, payload, *, channel) -> O365TokenSet
async def migrate_legacy_device_grant(self, principal, legacy, *, channel) -> Optional[O365TokenSet]
async def legacy_migration_allowed(self, user_id) -> bool

# packages/ai-parrot/src/parrot/auth/broker/factory.py
def _build_device_code(self, cfg, opts) -> CredentialResolver   # :167-200; deps read :184-186; constructor call :195-200

# packages/ai-parrot-server/src/parrot/services/vault_token_sync.py
"Providers served here: fireflies, workiq, entra, o365."   # :12
async def read_tokens(self, nav_user_id, provider) -> Optional[Dict[str, Any]]   # :303
async def delete_tokens(self, nav_user_id, provider) -> None                      # :317
```

### Does NOT Exist
- ~~A `cli` / e-mail branch in `IdentityPrincipalResolver` on dev today~~ — added by the D4 task; until it lands every production `resolve_principal("cli", email)` returns `None` (fail closed). Tests must register a fake resolver with `set_principal_resolver`.
- ~~`"o365:` string literals~~ — legacy keys are `_O365_VAULT_PREFIX` + VaultTokenSync's `{provider}:{field}`.
- ~~A required `vault` dep for `device_code`~~ after this task; `vault` stays a dep of other auth kinds in the same factory (`factory.py:98, :148, :162`) — do not touch those.
- ~~In-tree production wiring of this resolver~~ — `bots/abstract.py` attrs `_vault`, `_o365_interface`, `_o365_oauth_manager` are set nowhere.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/auth/broker/factory.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/services/vault_token_sync.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/auth/test_o365_devicecode_resolver.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/auth/test_broker_devicecode.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py#O365DeviceCodeCredentialResolver",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py#O365DeviceCodeCredentialResolver.resolve",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py#O365DeviceCodeCredentialResolver._persist_token_set",
    "sym:packages/ai-parrot/src/parrot/auth/broker/factory.py#CredentialResolverFactory._build_device_code",
    "sym:packages/ai-parrot/src/parrot/auth/principal.py#resolve_principal",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_base.py#AbstractOAuth2Manager.get_valid_token",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_base.py#_legacy_window_open"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Fail closed: empty `user_id` → `ValueError` (keep); unresolvable principal → `PermissionError`, no device flow, no store access (AC-8).
- Never call `VaultTokenSync.store_tokens` for `o365` again (AC-8). Only `legacy_vault.read_tokens` / `delete_tokens`, and only while `_legacy_window_open()`.
- Delete legacy data only after `migrate_legacy_device_grant` returns a token set (durable success). A deletion failure is
  logged and retried on a later resolve; it must not re-import (the current record now wins in TASK-5045) nor publish again.
- `InvalidGrantError` from migration → fall through to the device flow, legacy kept. `RefreshTransientError` → propagate (retryable).
- The legacy key is the raw e-mail/OID (`user_id` as passed in), not the Navigator id.

---

## Implementation Blueprint

### Steps (in order)
1. Replace `__init__` (drop `vault_token_sync`, add keyword-only `legacy_vault`) — *why*: spec §3 M3 skeleton fixes this signature.
2. Rewrite `resolve` around principal → manager → legacy → device flow — *why*: one record for both grant types (D3).
3. Replace `_persist_token_set` with a delegate to `store_device_grant` — *why*: durable-first S-1 path, `grant_origin="device_code"`.
4. Update the module docstring (resolution steps + "no VaultTokenSync o365 writes").
5. Update the factory and the three test files; run the Validation Commands.

### `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py` (MODIFY — constructor)
```python
# occurrences: 1 (verified: grep -c '    def __init__(' packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py)
# REPLACE `    def __init__(` … end of its body (verified: :100-115) with:
    def __init__(
        self,
        o365_client: Any,
        o365_oauth_manager: Any,
        scopes: Optional[List[str]] = None,
        prompt_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        *,
        legacy_vault: Any = None,
    ) -> None:
        from parrot.auth.o365_oauth import DEFAULT_O365_SCOPES

        self._o365 = o365_client
        self._manager = o365_oauth_manager
        self._legacy_vault = legacy_vault
        self._scopes: List[str] = list(scopes) if scopes else list(DEFAULT_O365_SCOPES)
        self._prompt_callback = prompt_callback or _default_prompt_callback
        self.logger = logger
```
Update the class docstring `Args:` accordingly (remove `vault_token_sync`, document `legacy_vault`).

### `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py` (MODIFY — resolve / is_connected)
```python
# occurrences: 1 (verified: grep -c '    async def resolve(self, channel: str, user_id: str) -> Optional[str]:' …)
# REPLACE the body of `resolve` (verified: :117-178) with:
        if not user_id:
            raise ValueError(
                "O365DeviceCodeCredentialResolver.resolve: user_id is required — refusing an anonymous resolve."
            )
        principal = await resolve_principal(channel, user_id)
        if principal is None:
            raise PermissionError(f"No platform principal bound for channel {channel!r}; device code refused")
        try:
            token_set = await self._manager.get_valid_token(channel, principal.user_id)
        except PermissionError:   # InvalidGrantError: dead refresh token → re-authorize
            token_set = None
        if token_set is not None:
            await self._retry_legacy_cleanup(user_id)
            return str(token_set.access_token)
        migrated = await self._migrate_legacy(user_id, principal, channel=channel)
        if migrated is not None:
            return migrated
        return await self._run_device_flow(user_id, principal=principal, channel=channel)

# occurrences: 1 (verified: grep -c '    async def is_connected(self, channel: str, user_id: str) -> bool:' …)
# REPLACE the body of `is_connected` (verified: :188-202) with:
        if not user_id:
            return False
        principal = await resolve_principal(channel, user_id)
        if principal is None:
            return False
        return await self._manager.is_connected(channel, principal.user_id)
```
**Why**: the manager owns cache, store and the locked refresh; the resolver no longer reads expiry itself.

### `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py` (MODIFY — internals)
```python
# occurrences: 1 (verified: grep -c '    async def _run_device_flow(self, user_id: str) -> str:' …)
# CHANGE the signature (verified: :206) to:
    async def _run_device_flow(self, user_id: str, *, principal: Principal, channel: str) -> str:
#   and replace `await self._persist_token_set(user_id, result)` with
#   `await self._persist_token_set(principal, result, channel=channel)`.

# occurrences: 1 (verified: grep -c '    async def _persist_token_set(' …)
# REPLACE `_persist_token_set` (verified: :237-273) with:
    async def _persist_token_set(self, principal: Principal, payload: Dict[str, Any], *, channel: str) -> None:
        """Persist a fresh device-code response through the shared, durable-first O365 record."""
        await self._manager.store_device_grant(principal, payload, channel=channel)

    async def _migrate_legacy(self, canonical_id: str, principal: Principal, *, channel: str) -> Optional[str]:
        """Import one legacy ``o365:*`` grant (keyed by e-mail/OID) while the S-1 window is open; ``None`` if none."""
        if self._legacy_vault is None or not _legacy_window_open():
            return None
        legacy = await self._legacy_vault.read_tokens(canonical_id, _O365_VAULT_PREFIX)
        if not legacy or not legacy.get("access_token"):
            return None
        try:
            token_set = await self._manager.migrate_legacy_device_grant(principal, legacy, channel=channel)
        except PermissionError:   # terminal: dead legacy refresh token → device flow; keep the data
            self.logger.info("Legacy o365 grant unusable for principal %s; device flow required", principal.user_id)
            return None
        if token_set is None:      # a current record or a disconnect won
            return None
        await self._delete_legacy(canonical_id)
        return str(token_set.access_token)

    async def _delete_legacy(self, canonical_id: str) -> None:
        """Best-effort legacy delete; failure leaves a retry marker, never a re-import."""
        # FILL IN: await self._legacy_vault.delete_tokens(canonical_id, _O365_VAULT_PREFIX); on exception log
        #          type(exc).__name__ only and remember canonical_id in self._pending_cleanup (a set created in __init__)
        #          — bounded by AC-15 ("cleanup retries do not mint duplicate completion events")

    async def _retry_legacy_cleanup(self, canonical_id: str) -> None:
        """Retry a previously failed legacy delete for this id, if one is pending."""
        # FILL IN: if canonical_id in self._pending_cleanup → _delete_legacy again; discard on success — bounded by AC-15
```
**Why**: `_coerce_epoch` and `_EXPIRY_SKEW_SECONDS` become unused — delete them unless a test still needs them
(ruff F401/F841 must stay clean). `time` import likewise.

### `packages/ai-parrot/src/parrot/auth/broker/factory.py` (MODIFY)
```python
# occurrences of '        vault = self._deps.get("vault")': 4 (verified: grep -c … factory.py → :98, :148, :162, :186)
# FILL IN: disambiguate — edit ONLY the block inside `def _build_device_code(` (verified: :167); quote:
#         o365 = self._deps.get("o365_client") or self._deps.get("o365_interface")
#         manager = self._deps.get("o365_oauth_manager")
#         vault = self._deps.get("vault")
#         if o365 is None or manager is None or vault is None:
# and replace :184-200 with:
        o365 = self._deps.get("o365_client") or self._deps.get("o365_interface")
        manager = self._deps.get("o365_oauth_manager")
        if o365 is None or manager is None:
            raise KeyError(
                "CredentialResolverFactory: 'o365_client'/'o365_interface' and 'o365_oauth_manager' deps are "
                f"required for auth='device_code' (provider={cfg.provider!r})"
            )
        legacy_vault = self._deps.get("legacy_vault") or self._deps.get("vault")   # optional: one-time legacy migration
        return O365DeviceCodeCredentialResolver(
            o365_client=o365,
            o365_oauth_manager=manager,
            scopes=opts.get("scopes"),
            legacy_vault=legacy_vault,
        )
```
Update its docstring "Expected deps" line. **Why** `vault` fallback: existing deployments pass `vault`, so their legacy
`o365:*` entries still migrate without a config change.

### `packages/ai-parrot-server/src/parrot/services/vault_token_sync.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'Providers served here: fireflies, workiq, entra, o365.' …vault_token_sync.py)
# REPLACE line :12 with:
Providers served here: fireflies, workiq, entra. ``o365`` is no longer served: O365 3LO and device-code
grants share one principal-keyed record (FEAT-777); legacy ``o365:*`` keys are only read once for migration.
```

### Tests (MODIFY)
```python
# packages/ai-parrot/tests/auth/test_o365_devicecode_resolver.py — replace FakeManager with one exposing
#   get_valid_token / is_connected / store_device_grant / migrate_legacy_device_grant (AsyncMocks), keep FakeO365Client,
#   rename FakeVault → legacy double (read_tokens / delete_tokens). Register a fake resolver:
#     from parrot.auth.principal import Principal, set_principal_resolver
#   and reset it in a fixture finalizer (set_principal_resolver(None)).
# FILL IN: test_devicecode_resolver_reads_through_manager — cache hit / refresh via get_valid_token, legacy vault untouched
# FILL IN: test_devicecode_resolver_fails_closed_without_principal — resolver → None ⇒ PermissionError, interactive_login not called
# FILL IN: test_devicecode_legacy_migration_once — legacy read, migrated, deleted; 2nd resolve no legacy read;
#          monkeypatch parrot.auth.oauth2.o365_devicecode_provider._legacy_window_open → False ⇒ no read
# FILL IN: test_devicecode_legacy_concurrent_replace_revoke — migrate returns None ⇒ legacy kept, device flow not re-run;
#          delete failure ⇒ retried on next resolve, store_device_grant/migrate not called again
# FILL IN: keep test_get_auth_url_returns_device_login_url and test_no_partial_write_on_timeout (store_device_grant not awaited)
#          delete the expires_at/VaultTokenSync-specific tests (:209-300) — the manager owns expiry now

# packages/ai-parrot/tests/auth/test_broker_devicecode.py
# FILL IN: test_broker_device_code_deps_without_vault — build with o365_client + o365_oauth_manager only;
#          resolver._legacy_vault is None; with vault=X → _legacy_vault is X; partial deps (no manager) still KeyError

# packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py
# FILL IN: test_cli_device_code_end_to_end — FakeO365OAuthManager gains store_device_grant/get_valid_token over a dict;
#          assert the grant landed via store_device_grant(grant_origin device_code) and NOT in vault._store; second call cache hit
# test_devicecode_token_consumable_by_workiq_obo:
@pytest.mark.xfail(strict=True, reason="WorkIQ reads the shared O365 record after TASK-5047")
```

### FILL IN checklist
- [ ] `_delete_legacy` / `_retry_legacy_cleanup` and `self._pending_cleanup` — bounded by AC-15
- [ ] dead-code removal (`_coerce_epoch`, `_EXPIRY_SKEW_SECONDS`, `time`) — bounded by ruff clean
- [ ] factory docstring + disambiguated edit — bounded by "only `_build_device_code`"
- [ ] resolver tests (5), factory test, e2e test — bounded by spec §4 M3 rows

---

## Acceptance Criteria

- [ ] No `store_tokens(..., "o365", ...)` call remains under `packages/*/src` (`grep -rn '_O365_VAULT_PREFIX' packages/ai-parrot/src` shows only legacy read/delete) (AC-8).
- [ ] Unresolvable principal raises before any device flow or store access (AC-8).
- [ ] Legacy `o365:*` migrates once, is deleted only after durable success, never after the window closes (AC-15).
- [ ] `_build_device_code` builds with `o365_client` + `o365_oauth_manager` only.
- [ ] `ruff check` clean on the three source files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/auth/test_o365_devicecode_resolver.py -q`
- `pytest packages/ai-parrot/tests/auth/test_broker_devicecode.py -q`
- `pytest packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py -q`
- `pytest packages/ai-parrot/tests/auth/test_credentials_devicecode.py -q`

---

## Test Specification

| Test | Module | Must assert |
|---|---|---|
| `test_devicecode_resolver_reads_through_manager` | M3 | cache hit and refresh both via `get_valid_token`; legacy double never read |
| `test_devicecode_resolver_fails_closed_without_principal` | M3 | `PermissionError`; `interactive_login` not called |
| `test_devicecode_legacy_migration_once` | M3 | read → migrate → delete; second resolve skips legacy; closed window → no read |
| `test_devicecode_legacy_concurrent_replace_revoke` | M3 | migrate `None` keeps legacy and does not run the device flow twice; failed delete retried without re-import |
| `test_broker_device_code_deps_without_vault` | M3 | builds without `vault` |

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/connections-web-slack.json`
4. **Verify the Codebase Contract** before writing ANY code (re-read TASK-5045's merged `o365_oauth.py` signatures)
5. **Update status** in the per-spec index → `"in-progress"` and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — stage only the files listed above
9. **Close the task** with `scripts/sdd/close_task.sh TASK-5046 connections-web-slack verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seats codex terra/sol/luna + native sonnet
**Date**: 2026-10-31
**Notes**: Implemented per task; merged and merge-tier validated (only red: 3 failures that also fail on origin/dev: test_o365_refresh x2, slack test_manager_payload_drives_identity_and_dm).

**Deviations from spec**: none | describe if any
