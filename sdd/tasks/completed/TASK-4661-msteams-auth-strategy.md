# TASK-4661: MSTeamsAuthStrategy — Bot Framework Token Service to Navigator

**Feature**: FEAT-729 — MS Teams user authentication lane
**Spec**: `sdd/specs/msteams-user-auth-lane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4659, TASK-4660
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 3** — the heart of the feature. It acquires a
user-bound delegated Graph credential through the Bot Framework Token Service
and drives the exchange built in TASK-4660.

**The lane choice is already settled by verification, not preference** (spec §8,
resolved): the classic `msteams` lane, because the installed
`BotFrameworkAdapter` already exposes `get_user_token`, `exchange_token`,
`get_oauth_sign_in_link`, `get_token_status` and `sign_out_user`, and
`OAuthPrompt` is installed. **No new SDK, and no hand-written OBO** — do not
introduce `msagentsdk` here, and do not write `acquire_token_on_behalf_of`.

> ### Blocking precondition — spec §8 Q1
> The one link the proof of concept could **not** exercise is whether the Azure
> Bot OAuth connection returns a token whose `aud` is Graph and whose `appid` is
> trusted. The PoC substituted a token from the Navigator Azure login. **Verify
> this against a real connection before building on it**: decode the token the
> connection hands back and confirm `aud == "https://graph.microsoft.com"` and
> that `appid` is `AZURE_ADFS_CLIENT_ID` or listed in `AZURE_TRUSTED_APPIDS`.
> If `appid` differs, the fix is configuration (spec §7 Ops prerequisite 3), not
> code. Record the finding in the Completion Note either way.

---

## Scope

- Add `MSTeamsAuthStrategy` to the `msteams/auth.py` created by TASK-4659.
- Resolution order, exactly: a cached unexpired session wins → else
  `adapter.get_user_token` → else, on a `signin/tokenExchange` invoke,
  `adapter.exchange_token` → else report "needs auth" without sending anything.
- On a token, call `TokenExchangeClient.exchange` and populate the session.
- `send_signin_card` builds the sign-in prompt but is called by the **caller**,
  never by `ensure_authenticated`.
- Unit tests over a fake adapter.

**NOT in scope**: the `/login` command (TASK-4662); wrapper changes
(TASK-4663); `msagentsdk`; OBO; identity persistence (TASK-4664).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py` | MODIFY | Append `MSTeamsAuthStrategy` |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_strategy.py` | CREATE | Unit tests over a fake adapter |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from botbuilder.core import BotFrameworkAdapter, TurnContext                  # installed
from botframework.connector.token_api.models import TokenExchangeRequest      # installed
from parrot.auth.token_exchange import (                                      # TASK-4660
    REASON_OK, ExchangeResult, TokenExchangeClient,
)
from parrot.integrations.msteams.auth import (                                # TASK-4659
    MSTeamsSessionStore, MSTeamsUserSession, user_key,
)
```

### Existing Signatures to Use
```python
# botbuilder.core.BotFrameworkAdapter — signatures read via inspect from the
# installed package. Use them EXACTLY; a fake adapter that drifts from these
# passes a test against a shape the real adapter does not have.
async def get_user_token(self, context: TurnContext, connection_name: str,
                         magic_code: str = None,
                         oauth_app_credentials: AppCredentials = None) -> TokenResponse
async def exchange_token(self, turn_context: TurnContext, connection_name: str,
                         user_id: str,
                         exchange_request: TokenExchangeRequest) -> TokenResponse
async def get_oauth_sign_in_link(self, context: TurnContext, connection_name: str,
                                 final_redirect: str = None,
                                 oauth_app_credentials: AppCredentials = None) -> str
async def get_token_status(self, context: TurnContext, connection_name: str = None,
                           user_id: str = None, include_filter: str = None,
                           oauth_app_credentials: AppCredentials = None) -> List[TokenStatus]

# TokenResponse attributes: connection_name, token, expiration, channel_id
# (botframework.connector.token_api.models.TokenResponse)

# From TASK-4659, same file:
def user_key(turn_context: TurnContext) -> str
class MSTeamsSessionStore:
    async def get_or_create(self, turn_context: TurnContext) -> MSTeamsUserSession
    async def save(self, session: MSTeamsUserSession) -> None
    def is_expired(self, session: MSTeamsUserSession) -> bool

# From TASK-4660:
class TokenExchangeClient:
    async def exchange(self, token: str, *, provider: str = "azure",
                       id_token: Optional[str] = None,
                       token_type: str = "Bearer") -> ExchangeResult
```

### Does NOT Exist
- ~~`OAuthPrompt` used anywhere under `packages/ai-parrot-integrations/src/parrot/integrations/msteams/`~~ — 0 hits. It is installed
  in `botbuilder.dialogs.prompts` but unused here; a dialog stack is **not**
  required for this task and adding one is out of scope.
- ~~`get_user_token` called anywhere under `packages/ai-parrot-integrations/src/parrot/integrations/msteams/`~~ — 0 hits. The only
  existing caller is `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/auth.py:175`, a different lane. Do not
  import from `msagentsdk`.
- ~~`signin/tokenExchange` handled under `packages/ai-parrot-integrations/src/parrot/integrations/msteams/`~~ — 0 hits (only
  `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py:240-242`).
- ~~`acquire_token_on_behalf_of` anywhere in `packages/ai-parrot-integrations/src/parrot/integrations/`~~ — 0 hits. **There is no OBO
  implementation**; `obo_scopes` is configured and stored but never read. Do not
  write one: `adapter.exchange_token` is the supported path.
- ~~`TurnContext.activity.value["token"]`~~ — on a `signin/tokenExchange` invoke
  the payload is a `TokenExchangeInvokeRequest` shape; read it, do not assume a
  bare dict key.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_strategy.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py#MSTeamsSessionStore",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py#user_key",
    "sym:packages/ai-parrot/src/parrot/auth/token_exchange.py#TokenExchangeClient"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `ensure_authenticated` **never raises** for an unauthenticated user and
  **never sends a card**. The caller decides whether to prompt — that is what
  lets TASK-4663 honour `auth_required=False` by simply proceeding.
- **Never log a token**, including `TokenResponse.token`.
- The adapter is reached as `turn_context.adapter`; accept an explicit adapter in
  the constructor only if a test needs it, and never construct one here.

### Known gotcha from the PoC
`cap=89` was observed: the Navigator session is capped to the external token's
remaining life, so sessions can be short by design. `is_expired()` must drive
re-acquisition and the UX must not read as a bug. navigator-auth FEAT-103 G4
(`get_live_provider_token`) is the upstream fix; do not try to extend the
session here.

---

## Implementation Blueprint

### Steps (in order)
1. Write `ensure_authenticated` as a pure resolver with no side effects on the
   conversation — *why*: AC-2 asserts no card is sent from here.
2. Keep each adapter call in its own small method — *why*: the fake adapter in
   the tests then needs only the method under test, and the SSO path can be
   exercised without a full invoke pipeline.
3. Map `ExchangeResult.reason` onto the session untouched — *why*: TASK-4662
   renders the reason to the user and must see `user_not_found` verbatim.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class MSTeamsSessionStore:' packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py)
# AFTER — append below the end of `class MSTeamsSessionStore:` (created by TASK-4659)

class MSTeamsAuthStrategy:
    """Bot Framework Token Service → Navigator session."""

    def __init__(self, config: Any, store: MSTeamsSessionStore,
                 exchange: TokenExchangeClient, logger_: Any = None) -> None:
        self.config = config
        self.store = store
        self.exchange = exchange
        self.logger = logger_ or logger

    @property
    def connection_name(self) -> Optional[str]:
        """The Azure Bot OAuth connection to draw user tokens from."""
        return getattr(self.config, "oauth_connection_name", None)

    async def ensure_authenticated(self, turn_context: TurnContext) -> MSTeamsUserSession:
        """Return an authenticated session, or one with authenticated=False.

        Never raises for an unauthenticated user and never sends a card: the
        caller decides whether to prompt.
        """
        # FILL IN: (1) session = await self.store.get_or_create(ctx);
        # (2) if session.authenticated and not self.store.is_expired(session):
        #     return it; (3) token = await self.fetch_provider_token(ctx);
        # (4) no token -> return session unchanged (authenticated=False);
        # (5) result = await self.exchange.exchange(token.token, ...);
        # (6) on result.ok call session.set_authenticated(...) and
        #     await self.store.save(session); else record result.reason in
        #     session.metadata["auth_reason"]. Bounded by AC-1..AC-4.
        raise NotImplementedError

    async def fetch_provider_token(self, turn_context: TurnContext) -> Optional[Any]:
        """adapter.get_user_token(context, connection_name, magic_code=None).

        Returns the TokenResponse, or None when the user has no token on file
        or no connection is configured.
        """
        # FILL IN: guard on self.connection_name; call
        # turn_context.adapter.get_user_token(turn_context, self.connection_name, None);
        # treat a falsy .token as None. Swallow the adapter's error and log it
        # WITHOUT the token. Bounded by AC-3.
        raise NotImplementedError

    async def exchange_sso_token(self, turn_context: TurnContext,
                                 exchange_request: TokenExchangeRequest) -> Optional[Any]:
        """adapter.exchange_token(ctx, connection_name, user_id, exchange_request).

        The Teams SSO path; replaces a hand-written OBO.
        """
        # FILL IN: user_id is user_key(turn_context); return the TokenResponse or
        # None. Bounded by AC-5.
        raise NotImplementedError

    async def send_signin_card(self, turn_context: TurnContext) -> None:
        """Send the sign-in prompt. Called by the caller, never by ensure_authenticated."""
        # FILL IN: link = await turn_context.adapter.get_oauth_sign_in_link(
        #   turn_context, self.connection_name); render an OAuthCard-bearing
        # activity. Follow _connect_jira_card (jira_commands.py:39) for card
        # construction and use DEFAULT_ADAPTIVE_CARD_VERSION. Bounded by AC-6.
        raise NotImplementedError

    async def sign_out(self, turn_context: TurnContext) -> None:
        """Drop the Navigator session and the Token Service token."""
        # FILL IN: await self.store.clear(user_key(ctx)) then
        # turn_context.adapter.sign_out_user(...); the store clear must happen
        # even if the adapter call fails. Bounded by AC-7.
        raise NotImplementedError
```
**Why this shape**: the five methods map one-to-one onto the resolution order in
spec §3 M3, so a reviewer can check the order by reading the method list. The
`connection_name` property exists so that a deployment without an OAuth
connection degrades to "no token" instead of raising — which is what makes
`auth_required=False` safe.

### FILL IN checklist
- [ ] `ensure_authenticated` — the six-step resolution; bounded by AC-1..AC-4
- [ ] `fetch_provider_token` — adapter call + None handling; bounded by AC-3
- [ ] `exchange_sso_token` — SSO exchange; bounded by AC-5
- [ ] `send_signin_card` — sign-in link + card; bounded by AC-6
- [ ] `sign_out` — clear-then-adapter ordering; bounded by AC-7

---

## Acceptance Criteria

- [ ] AC-1 a cached, unexpired, authenticated session is returned without any
      adapter or HTTP call
- [ ] AC-2 with no token on file, `ensure_authenticated` returns
      `authenticated=False`, raises nothing, and sends **no** activity
- [ ] AC-3 a `TokenResponse` with a token drives exactly one
      `TokenExchangeClient.exchange` call, and a successful result leaves the
      session authenticated with the Navigator id
- [ ] AC-4 a failed exchange leaves `authenticated=False` and records the
      verbatim `reason` in `session.metadata["auth_reason"]`
- [ ] AC-5 `exchange_sso_token` calls `adapter.exchange_token` with
      `user_id == user_key(turn_context)`
- [ ] AC-6 `send_signin_card` is never reached from `ensure_authenticated`
- [ ] AC-7 `sign_out` clears the stored session even when the adapter call fails
- [ ] No token value in any log record
- [ ] No import from `parrot.integrations.msagentsdk`, and no
      `acquire_token_on_behalf_of` anywhere in the diff
- [ ] `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_strategy.py -q` passes

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_strategy.py -q`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_strategy.py
import pytest

from parrot.integrations.msteams.auth import MSTeamsAuthStrategy


@pytest.fixture
def fake_adapter():
    """Stubs get_user_token / exchange_token / get_oauth_sign_in_link.

    Signatures must match BotFrameworkAdapter exactly (see the Codebase
    Contract) or this suite passes against a shape the real adapter lacks.
    """
    # FILL IN


class TestEnsureAuthenticated:
    async def test_returns_unauthenticated_without_token(self, fake_adapter):
        """No token on file: authenticated=False, no raise, no card."""
        # FILL IN: assert no activity was sent

    async def test_cached_session_skips_adapter(self, fake_adapter):
        """An unexpired session short-circuits before any adapter call."""
        # FILL IN

    async def test_failed_exchange_records_reason(self, fake_adapter):
        """The verbatim reason reaches session.metadata for TASK-4662."""
        # FILL IN: assert metadata["auth_reason"] == "user_not_found"


class TestSsoPath:
    async def test_exchange_sso_passes_user_key(self, fake_adapter):
        """exchange_token receives user_id == user_key(ctx)."""
        # FILL IN
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug msteams-user-auth-lane --feature-id FEAT-729`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/msteams-user-auth-lane.json`
4. **Verify the Codebase Contract** before writing ANY code. Re-grep every
   anchor: this task was written on `dev @ 0eb59926a` and the spec's §6 was
   verified on `37dc1da44`, so two anchors had already drifted once (see
   Context where noted). If anything moved, fix the contract FIRST.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`)
   and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every
   `# FILL IN:` marker, never change a signature or path it fixes
7. **Verify** the Acceptance Criteria — run the Validation Commands with
   `PYTHONPATH` set per changed package (the shared `.venv` is editable-installed
   against the MAIN checkout, so a bare `pytest` in a worktree imports the wrong
   branch)
8. **Commit the code** — stage only the files this task lists (never `git add .`)
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4661 msteams-user-auth-lane verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed**: Seat: gpt-5.6-terra · codex · Attempts: 1 · Duration: 355s. Teams auth strategy (Token Service → Navigator exchange) added to msteams/auth.py with tests; merge-tier validation green; reviewed against AC-1..7, no corrections.
**Deviations from scope**: none
**Ambiguities found in the spec**: none
**Follow-up needed**: none
