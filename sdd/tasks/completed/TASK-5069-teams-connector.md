# TASK-5069: `TeamsConnector` — guarded connect / disconnect / status / picker (`connect_commands.py`)

**Feature**: FEAT-775 — Connections on MS Teams
**Spec**: `sdd/specs/connections-msteams.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5063, TASK-5064, TASK-5066, TASK-5068
**Assigned-to**: unassigned

---

## Context

Spec §2 "Commands (M3)", "Legacy status is row-driven" (§7), §3 Module 3, AC-2, AC-5, AC-8, AC-10, AC-14,
AC-15, AC-16. `TeamsConnector` is the one object both the slash commands (TASK-5070) and the automatic
needs-auth offer (TASK-5075) call. Every path runs the same guard: personal conversation → live principal →
trusted permission context; refusal replies **once** and makes **no service call**.

---

## Scope

- `TeamsGuard` (dataclass: `principal`, `context`) and `TeamsConnector.__init__(*, principal_source,
  service_factory, provider_ids, bot_app_id, auth_enabled)` (spec skeleton, fixed).
- `require_guard(turn_context) -> Optional[TeamsGuard]` and the spec's `require_personal_principal(turn_context)
  -> Optional[Principal]` (thin wrapper). Refusals: non-personal or unknown `conversation.conversation_type` →
  "message me directly" hint; no principal → "Please `/login` first, then try again." (auth lane disabled:
  "Connections need Navigator sign-in; ask an operator to enable it.").
- `connect(turn_context, provider_id, *, scopes=None)` and `connect_guarded(turn_context, guard, provider_id, *, scopes)`:
  requested scopes = sorted union of `scopes`, or provider defaults when empty; legacy migration (below);
  status `connected` and `set(requested) <= set(scopes_granted)` → account reply, no new state; else
  `start_connect(principal.user_id, provider_id, channel="msteams", principal=, scopes=requested,
  permission_context=, extra_state=TeamsConnectState(...).model_dump())` → `connect_card`.
- `disconnect(turn_context, provider_id)` → `service.disconnect(..., channel="msteams", principal=, permission_context=)`.
- `status(turn_context, provider_id=None)` → `connections_status_card` of `list_for_principal` (or one provider's status).
- `pick_provider(turn_context)` → `provider_picker_card`.
- `PermissionError` → "You're not allowed to use <Provider> connections." ; `ValueError` (unknown provider) →
  "Unknown provider '<id>'. Try `/connect` to see the list."
- **Legacy migration (AC-10, §7)**: when the descriptor is `disconnected`, call
  `provider.manager.get_valid_token("msteams", principal.user_id, channel_user_id=principal.channel_user_id)`;
  a token → `service.persist_credential(principal.user_id, provider_id, token, channel="msteams",
  canonical_identity=principal.canonical_identity)` → re-read status. Never infer granted scopes from requested ones.
- Tests in `test_msteams_connect_commands.py` (connector-level cases).

**NOT in scope**: router registration and Jira aliases (TASK-5070), wrapper wiring (TASK-5072), needs-auth
grouping (TASK-5075).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/connect_commands.py` | CREATE | `TeamsGuard`, `TeamsConnector` |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_connect_commands.py` | CREATE | connector tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from botbuilder.core import TurnContext                                       # verified: jira_commands.py:33
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry                # verified: registry.py (get :106, all :117)
from parrot.auth.principal import Principal                                   # verified: principal.py:18
from parrot.auth.permission import PermissionContext                          # verified: permission.py:81
from parrot.integrations.msteams.connections import (                         # TASK-5066/5067/5068
    MSTeamsPrincipalSource, TeamsConnectState, build_msteams_permission_context,
    connect_card, connections_status_card, provider_picker_card, send_adaptive_card,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/oauth2/service.py (after TASK-5063/5064)
async def list_for_principal(self, user_id, request=None, *, principal=None, permission_context=None) -> List[IntegrationDescriptor]
async def status(self, user_id, provider_id, request=None, *, principal=None, permission_context=None) -> IntegrationDescriptor
async def start_connect(self, user_id, provider_id, return_origin=None, *, channel, principal, scopes,
                        request=None, extra_state=None, permission_context=None) -> ConnectInitResponse  # .auth_url
async def disconnect(self, user_id, provider_id, request=None, *, channel="web", principal=None, permission_context=None)
async def persist_credential(self, user_id, provider_id, token_set, *, channel, canonical_identity=None)   # :403
# packages/ai-parrot/src/parrot/auth/oauth2_base.py
async def get_valid_token(self, channel, user_id, *, channel_user_id=None) -> Optional[AbstractOAuth2TokenSet]   # :642 (honours OAUTH2_LEGACY_KEYS_UNTIL, :79)
# MSTeamsPrincipalSource.session_for_turn / principal_for_turn (TASK-5066)
# conversation ref: TurnContext.get_conversation_reference(turn_context.activity).serialize()   # jira_commands.py:203-222
```

### Does NOT Exist
- ~~`parrot.integrations.core.auth` command core~~ — FEAT-776 M5 owns it; Teams keeps `TeamsConnector` (spec Q2).
- ~~`IntegrationDescriptor.connected` setter~~ — read `status`.
- ~~using `AuthRequiredPayload.auth_url`~~ — never; its state lacks the conversation reference (spec §2 M6).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/connect_commands.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_connect_commands.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService.start_connect",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService.status",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService.disconnect",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService.persist_credential",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_base.py#AbstractOAuth2Manager.get_valid_token"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Module + guard block. 2. Operations block. 3. Tests (fake service recording calls; fake principal source).

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/connect_commands.py` (CREATE) — part 1
```python
"""Generic Teams connection commands (FEAT-775 M3): one guarded connector for commands and automatic offers."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, List, Optional

from botbuilder.core import TurnContext

from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.auth.permission import PermissionContext
from parrot.auth.principal import Principal
from parrot.integrations.msteams.connections import (
    MSTEAMS_CHANNEL, MSTeamsPrincipalSource, TeamsConnectState, build_msteams_permission_context,
    connect_card, connections_status_card, provider_picker_card, send_adaptive_card,
)

if TYPE_CHECKING:  # pragma: no cover
    from parrot.integrations.msteams.commands import MSTeamsCommandRouter

logger = logging.getLogger(__name__)

PERSONAL_ONLY = "Connections are personal — message me directly (1:1 chat) to manage them."
LOGIN_FIRST = "Please `/login` first, then try again."
AUTH_DISABLED = "Connections need Navigator sign-in; ask an operator to enable it."


@dataclass(frozen=True)
class TeamsGuard:
    """A turn that passed the personal + live-principal guard."""

    principal: Principal
    context: PermissionContext


class TeamsConnector:
    """Principal + IntegrationsService calls + cards, shared by commands and automatic needs-auth offers."""

    def __init__(self, *, principal_source: MSTeamsPrincipalSource, service_factory: Callable[[], Any],
                 provider_ids: Callable[[], List[str]], bot_app_id: str, auth_enabled: bool) -> None:
        self._principals = principal_source
        self._service_factory = service_factory
        self._provider_ids = provider_ids
        self._bot_app_id = bot_app_id
        self._auth_enabled = auth_enabled

    async def require_guard(self, turn_context: TurnContext) -> Optional[TeamsGuard]:
        """Personal conversation + live principal, else reply once and return ``None`` (no service call)."""
        conversation = getattr(turn_context.activity, "conversation", None)
        if getattr(conversation, "conversation_type", None) != "personal":
            await turn_context.send_activity(PERSONAL_ONLY)
            return None
        # FILL IN: auth disabled → AUTH_DISABLED; session = await self._principals.session_for_turn(...);
        # None → LOGIN_FIRST; else TeamsGuard(principal from principal_for_turn rule, build_msteams_permission_context(session))
        # — bounded by AC-2, AC-5, AC-16 (exactly one reply on refusal)
        ...

    async def require_personal_principal(self, turn_context: TurnContext) -> Optional[Principal]:
        """Spec-named guard; returns only the principal."""
        guard = await self.require_guard(turn_context)
        return guard.principal if guard else None

    def _state(self, turn_context: TurnContext) -> dict:
        """Serialized conversation reference + issuing bot app id for the OAuth state."""
        ref = TurnContext.get_conversation_reference(turn_context.activity)
        return TeamsConnectState(
            conversation_reference=json.loads(json.dumps(ref.serialize())), bot_app_id=self._bot_app_id,
        ).model_dump()
```

### Same file — part 2 (operations)
```python
    async def connect(self, turn_context: TurnContext, provider_id: str, *, scopes: Optional[List[str]] = None) -> None:
        """Guard, then :meth:`connect_guarded`."""
        guard = await self.require_guard(turn_context)
        if guard is not None:
            await self.connect_guarded(turn_context, guard, provider_id, scopes=scopes)

    async def connect_guarded(self, turn_context: TurnContext, guard: TeamsGuard, provider_id: str, *,
                              scopes: Optional[List[str]] = None) -> None:
        """Account reply for a sufficient active grant; otherwise mint a Teams-state connect card."""
        provider = OAuth2ProviderRegistry().get(provider_id)
        if provider is None:
            await turn_context.send_activity(f"Unknown provider '{provider_id}'. Try `/connect` to see the list.")
            return
        requested = sorted(set(scopes or [])) or list(provider.default_scopes)
        service = self._service_factory()
        p, ctx = guard.principal, guard.context
        try:
            descriptor = await self._status_with_legacy(service, provider, p, ctx)
            # FILL IN: sufficient = status == "connected" and set(requested) <= set(descriptor.scopes_granted)
            #   → send "<Provider> is already connected as **<display_account_name>**."; return — bounded by AC-15
            resp = await service.start_connect(
                p.user_id, provider_id, channel=MSTEAMS_CHANNEL, principal=p, scopes=requested,
                permission_context=ctx, extra_state=self._state(turn_context),
            )
            await send_adaptive_card(turn_context, connect_card(provider.display_name, resp.auth_url))
        except PermissionError:
            await turn_context.send_activity(f"You're not allowed to use {provider.display_name} connections.")

    async def _status_with_legacy(self, service: Any, provider: Any, principal: Principal, ctx: PermissionContext) -> Any:
        """Status; when disconnected, migrate a legacy-window token into a row and re-read (spec §7)."""
        # FILL IN: status(...) → if "disconnected": token = provider.manager.get_valid_token(MSTEAMS_CHANNEL,
        #   principal.user_id, channel_user_id=principal.channel_user_id); token → persist_credential(..., channel=
        #   MSTEAMS_CHANNEL, canonical_identity=principal.canonical_identity) and status(...) again — bounded by AC-10
        ...

    async def disconnect(self, turn_context: TurnContext, provider_id: str) -> None:
        """Guard; channel-aware disconnect; "<Provider> disconnected." (FILL IN, PermissionError/ValueError replies)."""
        ...

    async def status(self, turn_context: TurnContext, provider_id: Optional[str] = None) -> None:
        """Guard; status card for one provider or every registered provider (list denial → empty card)."""
        ...

    async def pick_provider(self, turn_context: TurnContext) -> None:
        """Guard; provider picker card from ``provider_ids()`` with registry display names."""
        ...
```

### `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_connect_commands.py` (CREATE)
```python
"""FEAT-775 M3: TeamsConnector."""
import pytest

# FILL IN fixtures: personal/group turn contexts (conversation_type, bot.id "28:app-1", turn_state dict,
#   send_activity AsyncMock); fake principal source; recording fake service; a registered fake "jira" provider.
# test_connect_requires_principal — no session → LOGIN_FIRST, start_connect not called (AC-2)
# test_connect_personal_only — group / channel / missing type → PERSONAL_ONLY, no service call (AC-5, AC-16)
# test_connect_calls_start_connect_with_teams_state — channel "msteams", principal, permission_context, extra_state
#   has conversation_reference + bot_app_id
# test_connect_already_connected — status == "connected" and scopes_granted ⊇ requested → account reply, no start_connect
# test_teams_connect_scope_union_and_upgrade — insufficient grant → start_connect(scopes=union)
# test_pbac_denied_renders_message — PermissionError → "not allowed"
# test_teams_preexisting_jira_connection_kept — no row + legacy token → persist_credential then "connected", no consent (AC-10)
# test_legacy_window_closed_requires_consent — get_valid_token None → start_connect
# test_disconnect_channel_aware — disconnect(channel="msteams", principal=, permission_context=)
```

### FILL IN checklist
- [ ] guard body
- [ ] sufficiency check, legacy migration
- [ ] disconnect / status / pick_provider bodies
- [ ] nine tests

---

## Acceptance Criteria

- [ ] No principal → sign-in reply, no OAuth state (AC-2); non-personal → hint, no service call (AC-5, AC-16).
- [ ] Connect uses `channel="msteams"`, the trusted context and Teams state; sufficient grant skips consent (AC-15).
- [ ] Legacy grant inside the window is reported connected without re-consent (AC-10).
- [ ] PBAC denial → "not allowed" reply (AC-14). `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_connect_commands.py -q`

---

## Test Specification

Nine tests listed in the test-file block.

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

Implemented by gpt-5.6-terra (codex), 1 attempt, merged via sdd-worker; fidelity gate passed; merge-tier validation green; own tests 11 passed. 0 review corrections.

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

