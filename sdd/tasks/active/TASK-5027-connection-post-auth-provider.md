# TASK-5027: `ConnectionPostAuthProvider` + Jira preset + generic `post_auth_actions` registration

**Feature**: FEAT-776 — Connections on Telegram
**Spec**: `sdd/specs/connections-telegram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5018, TASK-5022, TASK-5026
**Assigned-to**: unassigned

---

## Context

Spec §2 "Combined login", §3 Module 9 (provider half), AC-12. The combined `/login` flow supports only Jira, and
`JiraPostAuthProvider` both exchanges the code and writes identity rows. This task introduces the generic
`ConnectionPostAuthProvider(provider_id, …)` (writes no identity rows or tokens — FEAT-773 persists connections,
TASK-5020/5029 publish the link), turns `JiraPostAuthProvider` into a thin preset, defines the `PendingLoginAttempt`
data carrier the provider builds state from, and makes `_init_post_auth_providers` / config validation accept any
provider registered in `OAuth2ProviderRegistry`.

The staged lifecycle (pending candidate, correlation, finalization) is TASK-5028 (coordinator) and TASK-5029
(wrapper). Between this task and TASK-5029, `build_auth_url` refuses anything that is not a `PendingLoginAttempt`, so
the old pre-login `_build_next_auth_url` path degrades to "no secondary URL" (already handled by its `except`).
`test_wrapper_combined_auth.py` is rewritten by TASK-5029 — do not edit it here.

---

## Scope

- Create `telegram/post_auth_connection.py`: `PendingLoginAttempt` (dataclass), `ConnectionPostAuthProvider`.
- `build_auth_url(session, config, callback_base_url)`: `session` must be a `PendingLoginAttempt` (else `ValueError`);
  `start_connect(attempt.principal.user_id, provider_id, channel="telegram", principal=attempt.principal,
  extra_state={"chat_id", "bot_id", "attempt_id", "combined": True}, permission_context=attempt.permission_context)`
  → `auth_url`. Missing provider/manager, denial, URL failure → raise (required-step failure, never implicit skip).
- `handle_result(data, session, primary_auth_data)`: compatibility entry for a retained WebApp code/state — route it
  through the single FEAT-773 callback consumer exactly once; never re-exchange a consumed state; never publish a link.
- `post_auth_jira.py`: `JiraPostAuthProvider(ConnectionPostAuthProvider)`, `provider_name = "jira"`,
  `__init__(*, service, app, session_hook=None)`; remove `_write_identity_records` and the oauth/identity/vault params.
- `wrapper._init_post_auth_providers`: resolve any action whose provider is in `OAuth2ProviderRegistry` (manager present);
  Jira uses the preset, others `ConnectionPostAuthProvider(provider_id, ...)`; unknown → warning
  "not a registered provider at startup".
- `models.py`: `TelegramBotsConfig.validate` soft warning no longer tied to `{"jira"}` — warn only when the
  provider is not in `OAuth2ProviderRegistry` at validation time; remove/rename `_KNOWN_POST_AUTH_PROVIDERS`.
- Tests: `test_jira_post_auth_preset_compat`, `test_post_auth_any_registered_provider`, plus provider unit tests;
  update `packages/ai-parrot/tests/unit/test_post_auth_jira.py` for the preset.

**NOT in scope**: coordinator/correlation (TASK-5028), staged wrapper flow and strategy changes (TASK-5029).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_connection.py` | CREATE | provider + attempt carrier |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py` | MODIFY | preset |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `_init_post_auth_providers` |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` | MODIFY | validation warning |
| `packages/ai-parrot/tests/unit/test_post_auth_jira.py` | MODIFY | preset tests |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_post_auth_connection.py` | CREATE | provider tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.core.auth.post_auth import PostAuthProvider, PostAuthRegistry   # verified: post_auth.py:34, :92
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry                           # verified: registry.py:69
from parrot.auth.permission import PermissionContext                                     # verified: permission.py:81
from parrot.auth.principal import Principal                                              # verified: principal.py:18
from parrot.integrations.telegram.connection_notifier import SessionHook                 # TASK-5022
from parrot.integrations.telegram.models import PostAuthAction                           # verified: models.py:23
```

### Existing Signatures to Use
```python
# core/auth/post_auth.py
class PostAuthProvider(Protocol):   # :34
    provider_name: str
    async def build_auth_url(self, session, config, callback_base_url: str) -> str
    async def handle_result(self, data: Dict[str, Any], session, primary_auth_data: Dict[str, Any]) -> bool
class PostAuthRegistry: register :109 / get / providers / __contains__ / __len__        # :92-153

# telegram/post_auth_jira.py
class JiraPostAuthProvider:                         # :39 ; provider_name = "jira" :53
    def __init__(self, oauth_manager, identity_service, vault_sync) -> None   # :55-60
    async def build_auth_url(...)                   # :68 ; async def handle_result(...) :123 ; _write_identity_records :206
from parrot.integrations.telegram.jira_commands import _TELEGRAM_CHANNEL      # :27

# telegram/wrapper.py
def _init_post_auth_providers(self) -> None         # :562 ; loop `for action in actions:` with `if action.provider == "jira":`

# telegram/models.py
_KNOWN_POST_AUTH_PROVIDERS = frozenset({"jira"})    # :16 ; used in TelegramBotsConfig.validate :410-420
# IntegrationsService.start_connect AFTER FEAT-775: see TASK-5018 Completion Note (permission_context keyword)
```

### Does NOT Exist
- ~~`ConnectionPostAuthProvider`, `PendingLoginAttempt`~~ — created here.
- ~~`PendingLoginCoordinator`~~ — TASK-5028.
- ~~Identity-row or token writes in any post-auth provider~~ — forbidden after this task.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_connection.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_post_auth_jira.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_post_auth_connection.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/core/auth/post_auth.py#PostAuthProvider",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py#JiraPostAuthProvider",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._init_post_auth_providers",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py#TelegramBotsConfig.validate"
  ]
}
```

---

## Implementation Notes

- `attempt_id` must be unpredictable (`secrets.token_urlsafe(32)`); created by the coordinator in TASK-5028 — here it
  is just a field.
- YAML stays compatible: `post_auth_actions: [{provider: jira, required: true}]`.
- Run `wikitoolkit symbols blast JiraPostAuthProvider` and `... _write_identity_records` first.

---

## Implementation Blueprint

### Steps (in order)
1. Create `post_auth_connection.py` (block below).
2. Rewrite `JiraPostAuthProvider` as the preset; delete `_write_identity_records`.
3. Generic `_init_post_auth_providers`; config validation warning.
4. Tests.

### `telegram/post_auth_connection.py` (CREATE)
```python
"""Generic secondary-authorization provider for the staged Telegram /login (FEAT-776 M9)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Set

from parrot.auth.permission import PermissionContext
from parrot.auth.principal import Principal

if TYPE_CHECKING:  # pragma: no cover
    from parrot.auth.oauth2.service import IntegrationsService
    from parrot.integrations.telegram.connection_notifier import SessionHook
    from parrot.integrations.telegram.models import PostAuthAction


@dataclass
class PendingLoginAttempt:
    """A validated primary login awaiting its secondary authorizations (never an active session)."""

    attempt_id: str
    telegram_id: int
    chat_id: int
    bot_id: str
    principal: Principal
    permission_context: PermissionContext
    candidate: Any                                   # TelegramUserSession built by the primary callback, not yet active
    actions: List["PostAuthAction"]
    expires_at: float
    completed: Set[str] = field(default_factory=set)
    failed: Set[str] = field(default_factory=set)
    finalized: bool = False
    cancelled: bool = False


class ConnectionPostAuthProvider:
    """``PostAuthProvider`` for any registered OAuth2 provider; writes no identity rows or tokens."""

    def __init__(self, provider_id: str, *, service: "IntegrationsService", app: Mapping[str, Any],
                 session_hook: Optional["SessionHook"] = None) -> None:
        self.provider_name = provider_id
        self._service = service
        self._app = app
        self.session_hook = session_hook
        self.logger = logging.getLogger(__name__)

    async def build_auth_url(self, session: Any, config: Any, callback_base_url: str) -> str:
        """Start a connect for a verified pending candidate; raise on any failure (required-step failure)."""
        if not isinstance(session, PendingLoginAttempt):
            raise ValueError("secondary authorization requires a verified pending login attempt")
        # FILL IN: start_connect(session.principal.user_id, self.provider_name, channel="telegram", principal=session.principal,
        # extra_state={"chat_id": session.chat_id, "bot_id": session.bot_id, "attempt_id": session.attempt_id, "combined": True},
        # permission_context=session.permission_context) → response.auth_url; unsupported auth mode → ValueError
        raise NotImplementedError

    async def handle_result(self, data: Dict[str, Any], session: Any, primary_auth_data: Dict[str, Any]) -> bool:
        """Route a retained code/state through the single FEAT-773 callback consumer, once."""
        # FILL IN: bounded by spec M9 lifecycle §4 — never exchange a state the callback already consumed; never publish a link
        raise NotImplementedError
```

### `telegram/post_auth_jira.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class JiraPostAuthProvider:' .../telegram/post_auth_jira.py)
# REPLACE the class (and its TYPE_CHECKING imports of JiraOAuthManager/IdentityMappingService/VaultTokenSync) with:
class JiraPostAuthProvider(ConnectionPostAuthProvider):
    """Jira preset of :class:`ConnectionPostAuthProvider` (YAML ``provider: jira``)."""

    provider_name = "jira"

    def __init__(self, *, service: "IntegrationsService", app: Mapping[str, Any],
                 session_hook: Optional["SessionHook"] = None) -> None:
        super().__init__("jira", service=service, app=app, session_hook=session_hook)
```

### `telegram/wrapper.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    def _init_post_auth_providers(self) -> None:' .../telegram/wrapper.py)
# REPLACE the method body (:562-631) — keep the "no actions"/"app is None" early returns, then:
        # FILL IN: registry = OAuth2ProviderRegistry(); service = the wrapper's IntegrationsService (same construction as
        # TASK-5025; factor a `_integrations_service()` helper if not already present);
        # for action in actions: provider = registry.get(action.provider); None or manager None → warning
        # "post_auth_actions provider '%s' is not a registered provider at startup; skipping."; "jira" → JiraPostAuthProvider(...)
        # else ConnectionPostAuthProvider(action.provider, ...); self._post_auth_registry.register(...)
```

### `telegram/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_KNOWN_POST_AUTH_PROVIDERS = frozenset({"jira"})' .../telegram/models.py)
# DELETE the constant (+ its comment :13-16); in validate() replace the `{jira}` membership test (:412-420) with a lazy
# OAuth2ProviderRegistry().get(action.provider) is None check and the message "... is not a registered provider at startup ..."
```

### FILL IN checklist
- [ ] `build_auth_url` / `handle_result` bodies
- [ ] Wrapper `_init_post_auth_providers` body
- [ ] Tests: `test_jira_post_auth_preset_compat`, `test_post_auth_any_registered_provider`, refusal of non-attempt sessions,
      required failure raises; `test_post_auth_jira.py` updated (identity-write assertions removed)

---

## Acceptance Criteria

- [ ] AC-12 (registration of any registered provider; preset writes no identity rows/tokens)
- [ ] `grep -rn "_write_identity_records\|_KNOWN_POST_AUTH_PROVIDERS" packages/` is empty; `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_post_auth_connection.py -q`
- `pytest packages/ai-parrot/tests/unit/test_post_auth_jira.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_config_validation_multi_auth.py -q`

---

## Test Specification

Test names fixed by spec §4 (M9 preset/registration rows).

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5018, TASK-5022, TASK-5026 are `done`
2. Implement from the blueprint; validate with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
3. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-5027 connections-telegram verified`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: `PendingLoginAttempt` carrier added to `post_auth_connection.py` (spec M9 lifecycle §2 fields)
