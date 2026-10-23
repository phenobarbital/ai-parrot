# TASK-4667: Carry the Navigator user id into the Teams Jira OAuth state

**Feature**: FEAT-729 — MS Teams user authentication lane
**Spec**: `sdd/specs/msteams-user-auth-lane.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4664
**Assigned-to**: unassigned
**Discovered-from**: `issue:187ce3fe3b93`

---

## Context

Review finding on FEAT-729 (`ledger issue:187ce3fe3b93`, major).

`TASK-4664` fixed the SQL arbiter so `IdentityMappingService.upsert_identity()`
can land a row, but the MS Teams Jira call site still feeds it the **wrong
value**:

1. `msteams/commands/jira_commands.py::_get_user_id` returns the **AAD object
   id** — a GUID — and `connect_jira_handler` stores it as
   `extra_state["user_id"]`.
2. `JiraOAuthManager.create_authorization_url` puts the same value at
   `state_payload["user_id"]` (`jira_oauth.py:413-418`).
3. `msteams/oauth_callback.py:241` reads exactly that key into `nav_user_id`
   and passes it to `upsert_identity(nav_user_id=...)`.
4. `_UPSERT_SQL` casts it with `$1::text::bigint`
   (`identity_mapping.py:43-54`). A GUID is not a bigint, so the write raises,
   the `except Exception` sets `identity_saved = False`, and **every real Teams
   user sees the "your Teams account link could not be saved" warning** on the
   success page. The old 42P10 failure simply became a cast failure.

The regression test added by TASK-4664 cannot catch this: it asserts
`call_kwargs["nav_user_id"] == "aad-obj-123"` (the bug, pinned as the expected
value) and the Postgres-backed tests skip without a database.

The two identifiers were conflated. They are different things:

| Value | What it is | Used for |
|---|---|---|
| AAD object id (GUID) | the Teams/Entra account id | the `JiraOAuthManager` token-store key, and `provider_user_id` on the identity row |
| `MSTeamsUserSession.nav_user_id` | navigator-auth `auth.users.user_id` (**bigint**) | the `user_id` column of `auth.user_identities` |

FEAT-729 already resolves the second one: the auth lane stores it on the
session (`msteams/auth.py:52`) and `MSTeamsAgentWrapper._effective_user_id`
(`wrapper.py:338-356`) already reads it without ever triggering an exchange.
It was simply never threaded into the Jira OAuth state.

## Scope

- Add a **separate** `nav_user_id` key to the Teams Jira OAuth state, resolved
  from the authenticated `MSTeamsUserSession`; keep the AAD object id as the
  `JiraOAuthManager` key so `validate_token` / `revoke` / `/jira_status`
  continue to resolve the same tokens.
- Make `handle_msteams_jira_callback` consume that key, use the AAD object id
  for `provider_user_id` / `auth_data.aad_object_id`, and **fail closed**:
  never write an identity row with a value that is not a Navigator bigint.
- Guard `IdentityMappingService.upsert_identity` so a non-numeric
  `nav_user_id` raises a clear `ValueError` client-side instead of a Postgres
  cast error, on both the SQL and the `IdentityStore` paths.
- Tests that pin the new behaviour with a **GUID** id and no Postgres.

### NOT in scope

- The Slack call site has the same class of defect
  (`slack/oauth_callback.py:222` falls back to `"<team>:<user>"`). It is
  already tracked as its own claimed ledger issue — do not touch it here.
- `telegram/post_auth_jira.py` (its ids are numeric Telegram/Navigator ids).
- Backfilling or migrating rows already written.
- Any change to `_UPSERT_SQL`'s arbiter or to the `$1::text::bigint` cast —
  the cast is deliberate (`identity_mapping.py:40-42`) and stays.

## Files to Create / Modify

**Modify**
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/jira_commands.py`
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py`
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`
- `packages/ai-parrot-server/src/parrot/services/identity_mapping.py`
- `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_jira_commands.py`
- `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_oauth_callback.py`
- `packages/ai-parrot/tests/unit/test_identity_mapping.py`

**Create** — none.

## Codebase Contract (Anti-Hallucination)

### Verified Imports
- `from parrot.integrations.msteams.oauth_callback import handle_msteams_jira_callback, MSTeamsOAuthNotifier`
- `from parrot.integrations.msteams.commands.jira_commands import connect_jira_handler, register_jira_commands, _get_user_id, _MSTEAMS_CHANNEL`
- `from parrot.services.identity_mapping import IdentityMappingService`
- `from parrot.integrations.msteams.auth import MSTeamsUserSession, MSTeamsSessionStore, user_key`

### Existing Signatures
- `jira_commands.connect_jira_handler(turn_context: "TurnContext", oauth_manager: "JiraOAuthManager") -> None`
- `jira_commands.register_jira_commands(router: "MSTeamsCommandRouter", oauth_manager: "JiraOAuthManager") -> None`
- `jira_commands._get_user_id(turn_context: "TurnContext") -> str` — returns
  `from_property.aad_object_id` when set, else `from_property.id`.
- `oauth_callback.handle_msteams_jira_callback(request, token_set, state_payload: Dict[str, Any]) -> "web.Response"`
- `JiraOAuthManager.create_authorization_url(channel: str, user_id: str, extra_state: Optional[Dict[str, Any]] = None) -> Tuple[str, str]`
  — builds `{"channel": channel, "user_id": user_id, "extra": extra_state or {}}` (`jira_oauth.py:413-418`).
- `IdentityMappingService.upsert_identity(*, nav_user_id: str, auth_provider: str, provider_user_id: str, auth_data: Dict[str, Any], display_name: Optional[str] = None, email: Optional[str] = None, token: Optional["TokenResponse"] = None) -> None`
- `MSTeamsAgentWrapper._effective_user_id(turn_context: TurnContext, fallback: str) -> str` (async, `wrapper.py:338`)
  — returns `session.nav_user_id` when the session is authenticated, unexpired and has one; else `fallback`. Never triggers an exchange.
- `MSTeamsUserSession.nav_user_id: Optional[str]` (`msteams/auth.py:52`).

### Verified Anchors
- `jira_commands.py:198-223` — `connect_jira_handler` body (`user_id = _get_user_id(turn_context)` … `extra_state={...}`).
- `jira_commands.py:300-335` — `register_jira_commands` and its `_connect` closure.
- `oauth_callback.py:240-267` — `nav_user_id` resolution and the `upsert_identity` call.
- `wrapper.py:199-200` — `register_jira_commands(self._command_router, oauth_manager)`.
- `identity_mapping.py:207-216` — the `provider_user_id` / secret-key guards at the top of `upsert_identity`.
- `identity_mapping.py:226` — `user_id: Any = int(nav_user_id) if str(nav_user_id).isdigit() else nav_user_id` on the `IdentityStore` path.
- `test_msteams_oauth_callback.py:31,34` — the `msteams_state_payload` fixture; `:188` and `:328` assert `nav_user_id == "aad-obj-123"`.

### Does NOT Exist — do not use
- There is **no** `nav_user_id` key in the Teams OAuth state today, at any level.
- `MSTeamsAgentWrapper` has no `_nav_user_id(...)` helper — reuse `_effective_user_id`.
- `handle_msteams_jira_callback` has **no** access to `MSTeamsSessionStore`; the
  aiohttp app holds only `identity_mapping_service` and
  `msteams_jira_oauth_notifier`. Do not invent an app key for the session store.
- `IdentityMappingService` has no validation helper for `nav_user_id`.

## Complexity Contract

Small, local change: one extra optional parameter threaded through three
functions, one new guard, and tests. No new module, no new class, no new
abstraction. Target ≤ 120 changed source lines across the four source files.

## Implementation Notes

- **Keep the token key unchanged.** `connect_jira_handler` must keep calling
  `oauth_manager.validate_token` / `create_authorization_url` with
  `_get_user_id(turn_context)`. `/disconnect_jira` and `/jira_status` use the
  same key and are not in this task — changing it would strand every existing
  token.
- **Resolver shape.** Give `connect_jira_handler` and `register_jira_commands`
  an optional keyword `nav_user_id_resolver: Optional[Callable[["TurnContext"], Awaitable[str]]] = None`.
  `wrapper.py` passes `lambda tc: self._effective_user_id(tc, "")`. The lambda
  is evaluated at dispatch time, so it is safe that
  `register_jira_commands` runs (line 200) before `self._auth` /
  `self._session_store` are assigned (lines 216-229).
- Only add `"nav_user_id"` to `extra_state` when the resolver returns a
  truthy value — an unauthenticated user (or a deployment with the auth lane
  disabled, `navigator_auth_url` unset) must produce a state **without** the
  key, not a state with an empty one.
- **Callback fail-closed rule**: read `nav_user_id` from
  `extra["nav_user_id"]` (falling back to a top-level `nav_user_id`, never to
  `user_id`). Then:
  - absent → skip the identity write, `logger.info`, and leave
    `identity_saved = True` (nothing was expected to be saved, so the user
    gets no warning);
  - present but not all-digits → skip the write, `logger.warning`, and set
    `identity_saved = False` so the page warns. This is the case that used to
    reach Postgres and blow up.
- The AAD object id stays the provider-side account id: pass it as
  `provider_user_id` and keep it in `auth_data["aad_object_id"]`. Remove the
  now-wrong comment `# The Teams account id: the AAD object id (== nav_user_id here).`
- **Service guard**: at the top of `upsert_identity`, after the
  `provider_user_id` check, reject a `nav_user_id` that is not a non-empty
  digit string with a `ValueError` naming the offending value's shape (do not
  log the raw id at error level — it is an account identifier). This covers
  the `IdentityStore` path too, where `identity_mapping.py:226` would
  otherwise hand a GUID string to navigator-auth. Document it under `Raises:`.

## Implementation Blueprint

### 1. `jira_commands.py`

```python
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, Optional

NavUserIdResolver = Callable[["TurnContext"], Awaitable[str]]


async def _resolve_nav_user_id(
    turn_context: "TurnContext",
    resolver: Optional[NavUserIdResolver],
) -> str:
    """Return the Navigator user id for this turn, or ``""``.

    Never raises: a failing resolver must not block ``/connect_jira`` — the
    Jira link still works, only the identity row is skipped.
    """
    if resolver is None:
        return ""
    try:
        return (await resolver(turn_context)) or ""
    except Exception:  # noqa: BLE001 — identity is best-effort here
        logger.exception("Could not resolve the Navigator user id for /connect_jira")
        return ""


async def connect_jira_handler(
    turn_context: "TurnContext",
    oauth_manager: "JiraOAuthManager",
    nav_user_id_resolver: Optional[NavUserIdResolver] = None,
) -> None:
    ...
    user_id = _get_user_id(turn_context)          # unchanged: the Jira token key
    ...
    conv_ref = _get_conversation_reference(turn_context)
    extra_state: Dict[str, Any] = {
        "channel": _MSTEAMS_CHANNEL,
        "user_id": user_id,
        "conversation_reference": conv_ref,
    }
    nav_user_id = await _resolve_nav_user_id(turn_context, nav_user_id_resolver)
    if nav_user_id:
        extra_state["nav_user_id"] = nav_user_id
    url, _nonce = await oauth_manager.create_authorization_url(
        _MSTEAMS_CHANNEL, user_id, extra_state=extra_state
    )
    await _send_adaptive_card(turn_context, _connect_jira_card(url))
```

`register_jira_commands(router, oauth_manager, nav_user_id_resolver=None)`
forwards the resolver into its `_connect` closure only; `_disconnect`,
`_status` and `_menu` are unchanged. Update the module docstring's identity
paragraph to describe both ids.

### 2. `oauth_callback.py`

```python
    conv_ref: Dict[str, Any] = _conv_ref()
    # Two distinct identifiers (FEAT-729 / issue:187ce3fe3b93):
    #  * teams_user_id — the AAD object id, the JiraOAuthManager token key and
    #    the provider-side account id;
    #  * nav_user_id   — auth.users.user_id, a bigint, written to
    #    auth.user_identities.user_id. Only the Teams auth lane can supply it.
    teams_user_id: str = state_payload.get("user_id") or extra.get("user_id") or ""
    nav_user_id: str = extra.get("nav_user_id") or state_payload.get("nav_user_id") or ""

    identity_service = request.app.get("identity_mapping_service")
    identity_saved = True
    if identity_service is not None and teams_user_id:
        if not nav_user_id:
            logger.info(
                "No Navigator user id in the Teams Jira OAuth state — skipping the "
                "auth.user_identities write for teams_user=%s",
                teams_user_id,
            )
        elif not str(nav_user_id).isdigit():
            identity_saved = False
            logger.warning(
                "Refusing to write auth.user_identities for teams_user=%s: the state "
                "carries a non-numeric Navigator user id (%d chars)",
                teams_user_id,
                len(str(nav_user_id)),
            )
        else:
            try:
                await identity_service.upsert_identity(
                    nav_user_id=nav_user_id,
                    auth_provider="msteams",
                    provider_user_id=teams_user_id,
                    auth_data={
                        "aad_object_id": teams_user_id,
                        "tenant_id": (conv_ref.get("conversation", {}).get("tenantId") or ""),
                    },
                    display_name=token_set.display_name or None,
                    email=token_set.email or None,
                )
            except Exception:  # noqa: BLE001 — identity write must not break browser flow
                identity_saved = False
                logger.exception(
                    "Failed to write auth.user_identities for Teams user=%s",
                    teams_user_id,
                )
```

Keep the rest of the function (notifier, success page, warning splice)
untouched. Update the module docstring bullet 1 accordingly.

### 3. `wrapper.py`

```python
        if oauth_manager is not None:
            register_jira_commands(
                self._command_router,
                oauth_manager,
                # Resolved per turn: the auth lane may not be wired yet here.
                nav_user_id_resolver=lambda tc: self._effective_user_id(tc, ""),
            )
```

### 4. `identity_mapping.py`

```python
        if not str(nav_user_id or "").isdigit():
            raise ValueError(
                "nav_user_id must be the numeric navigator-auth user_id "
                "(auth.user_identities.user_id is bigint); got a non-numeric "
                f"value of {len(str(nav_user_id or ''))} chars for provider "
                f"{auth_provider!r}"
            )
```

placed directly after the `provider_user_id` guard, with a matching
`ValueError` line in the `Raises:` block of the docstring.

## Acceptance Criteria

1. `/connect_jira` from an authenticated Teams user produces an OAuth state
   whose `extra["nav_user_id"]` is the session's `nav_user_id`, while
   `state_payload["user_id"]` remains the AAD object id.
2. `/connect_jira` from an unauthenticated user (or with no resolver wired)
   produces a state with **no** `nav_user_id` key.
3. `handle_msteams_jira_callback` with a GUID-only state performs **no**
   `upsert_identity` call and returns a success page **without** the
   identity warning.
4. `handle_msteams_jira_callback` with a numeric `nav_user_id` calls
   `upsert_identity` with `nav_user_id=<the bigint>` and
   `provider_user_id=<the AAD GUID>`, and `auth_data["aad_object_id"]` is the
   GUID.
5. `handle_msteams_jira_callback` with a non-numeric `nav_user_id` in the
   state performs no write and returns the page **with** the identity warning.
6. `IdentityMappingService.upsert_identity(nav_user_id="<guid>", ...)` raises
   `ValueError` before touching the pool, with no Postgres required.
7. `/disconnect_jira` and `/jira_status` still key on the AAD object id
   (existing tests unchanged and passing).
8. `ruff check` clean on every changed file.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src:packages/ai-parrot-server/src \
  pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_jira_commands.py \
         packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_oauth_callback.py \
         packages/ai-parrot/tests/unit/test_identity_mapping.py -q

ruff check packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/jira_commands.py \
           packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py \
           packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py \
           packages/ai-parrot-server/src/parrot/services/identity_mapping.py
```

## Test Specification

`test_msteams_jira_commands.py` — class `TestConnectJiraNavUserId`:
- `test_authenticated_state_carries_nav_user_id` — resolver returns `"42"`;
  assert `create_authorization_url` was called with the AAD GUID as the
  positional `user_id` and `extra_state["nav_user_id"] == "42"`.
- `test_unauthenticated_state_omits_nav_user_id` — resolver returns `""`;
  assert `"nav_user_id" not in extra_state`.
- `test_no_resolver_omits_nav_user_id` — handler called without the kwarg.
- `test_failing_resolver_still_sends_card` — resolver raises; the card is
  still sent and the state has no `nav_user_id`.

`test_msteams_oauth_callback.py`:
- Update the `msteams_state_payload` fixture and the two existing
  `nav_user_id == "aad-obj-123"` assertions (`:188`, `:328`) to the new split.
- `test_guid_only_state_skips_identity_write` — AAD GUID
  (`"7f1c0b2e-9a3d-4c8e-9b61-0c3f1e0a5d44"`) as `user_id`, no `nav_user_id`;
  assert `upsert_identity` not called and no warning in the HTML.
- `test_numeric_nav_user_id_is_written` — asserts criterion 4.
- `test_non_numeric_nav_user_id_warns_and_skips` — asserts criterion 5.

`packages/ai-parrot/tests/unit/test_identity_mapping.py` — a new
Postgres-free test (outside the DB-gated classes):
- `test_upsert_rejects_non_numeric_nav_user_id` — a service built on a pool
  whose `acquire` would raise if touched; `pytest.raises(ValueError)` for a
  GUID id.

## Agent Instructions

Touch only the seven files listed. Do not change `_get_user_id`, the
`JiraOAuthManager` key, `_UPSERT_SQL`, or the Slack/Telegram call sites. Run
the validation commands from the worktree root with the `PYTHONPATH` above.

## Completion Note

_To be filled on completion._
