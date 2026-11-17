---
type: feature
base_branch: dev
projects: [integrations]
tags: [telegram, authentication, security]
discovered_from: issue:21146a531a96
e2e:
  policy: optional
docs:
  policy: required
  pages:
    - wiki/integrations/telegram-auth-open-mode.md
  api_modules:
    - parrot.integrations.telegram.browser_login
---

# Feature Specification: Telegram browser login confirmation

**Feature ID**: FEAT-906
**Date**: 2026-11-17
**Author**: Codex
**Status**: approved

## 1. Motivation & Business Requirements

`issue:21146a531a96` reports login-link phishing in browser-mode Telegram authentication.
The browser POST and OAuth2 callback consume a state identifying the chat that initiated
`/login`, then authenticate that chat as the identity verified in the browser. The
browser user need not control the initiating Telegram account. An attacker can therefore
forward their login URL to a victim and acquire the victim's identity in the attacker's chat.

The existing `test_browser_mode_full_flow_oauth2` and
`test_browser_identity_uses_verified_claims` tests pass on the baseline and explicitly
expect immediate publication of the browser identity to the initiating Telegram session.

### Goals

- Require proof that the authenticated browser user can return a browser-only secret
  through the initiating Telegram user and chat before activating their identity.
- Cover basic, Azure, Google and OAuth2 browser flows, including composite strategies.
- Preserve webview behavior, provider verification and post-auth orchestration.

### Non-Goals

- Replacing provider authentication, adding a persistent distributed registry, or changing webview login.
- Preventing social engineering where a victim deliberately shares the final confirmation code.
- Treating a confirmation button in the initiating chat as sufficient: the attacker already controls that chat.

## 2. Architectural Design

### Approved user flow

1. The user sends `/login` in Telegram and opens the existing browser link.
2. The browser completes provider authentication. The server verifies into an isolated candidate session.
3. The browser shows a one-time command, `/login CODE`, and explains that it must be sent
   only to the bot/chat where the user personally started login. No authenticated session
   or persistent Telegram identity link exists yet.
4. The user sends that command in the initiating chat. The bot checks the bot ID,
   Telegram sender ID and chat ID, then atomically consumes the code.
5. Only then does the existing completion pipeline publish the session, persist the
   identity link, initialize user context, or begin required post-auth actions.

The code is generated after identity verification with at least 128 bits of randomness,
is independent of the login state, expires no later than the original 600-second login
deadline, and is single-use. It never appears in the initiating chat automatically, in
a URL, in logs, in telemetry, or in persistent browser storage. Browser responses use
`Cache-Control: no-store` and `Referrer-Policy: no-referrer`.

### State and concurrency

The app-scoped registry retains the current attempt identity through provider verification
and confirmation. Consuming the initial state prevents callback replay but must not discard
the attempt's generation marker. After an awaited verifier returns, staging a candidate
rechecks that the attempt is current and unexpired. A new `/login` and `/logout` invalidate
pending states, in-flight attempts and confirmation codes for that user and bot.

Redemption checks bot/user/chat before consuming a code. A mismatched sender cannot steal
or burn another user's code. Redemption consumes synchronously before any await; concurrent
redemptions cannot run the success pipeline twice. No HTTP endpoint accepts confirmation
as proof of Telegram ownership. Browser-controlled identity/correlation fields remain ignored.

The registry remains in-process, consistent with FEAT-854. Restart loses pending attempts
and fails closed. Expired and invalidated candidates are removed during registry operations.

## 3. Module Breakdown

### M1: Confirmation registry and result rendering

Path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/browser_login.py`.
Extend the existing registry with current-attempt tracking, candidate staging, scoped
confirmation consumption and cancellation. Use Pydantic v2 for new structured result
models; preserve the existing `BrowserLoginEntry` API where possible. Avoid runtime imports
of `auth.py` or `wrapper.py` to preserve the existing import cycle constraint.

The POST handler returns a pending response with the one-time confirmation command and
safe bot link, never credentials or the raw candidate. Add escaped HTML rendering of
the same pending step for OAuth2. Do not label pending authentication as complete.

### M2: Verification and Telegram redemption

Path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py`.
Separate browser candidate verification from the existing session publication pipeline.
Browser page methods continue using the registered verifier; OAuth2 continues its real
strategy callback with PKCE into a new, unpublished candidate. Browser paths cannot reach
the legacy immediate-publication path accidentally.

Handle `/login CODE` before generating a new login state. Use the actual message sender
and chat identifiers, never payload-supplied identifiers. On failure show a generic
invalid/expired-code response without revealing candidate identity. On success run the
existing completion or post-auth path exactly once. Plain `/login` and `/logout` cancel
older pending attempts even when the active session is unauthenticated.

### M3: HTTP and shipped page integration

Paths: `oauth2_callback.py`, and `static/login.html`, `static/azure_login.html`,
`static/login_multi.html` under the Telegram integration source directory.
The OAuth2 browser callback returns the confirmation page instead of activating the chat.
The three shipped pages render the pending command using safe DOM text APIs and retain
their existing completion-origin validation and legacy webview behavior. Missing or
malformed confirmation responses fail closed instead of displaying completed login.

### M4: Regression coverage and operator documentation

Update the affected browser and OAuth2 tests, add focused confirmation-security tests,
and update `wiki/integrations/telegram-auth-open-mode.md` after the code tasks.
Tests use fake provider verification and actual wrapper/registry behavior, with no live accounts.

### Interface skeletons

```python
# browser_login.py; candidate is an existing TelegramUserSession, kept opaque here
# to avoid the auth.py -> browser_login.py import cycle.
class PendingBrowserConfirmation(BaseModel):
    """Private verified candidate awaiting proof from Telegram; never serialized publicly."""
    entry: BrowserLoginEntry
    candidate: Any
    requires_post_auth: bool = False

# New methods on BrowserLoginRegistry:
def cancel(self, *, bot_id: str, telegram_id: int) -> None:
    """Invalidate pending and in-flight attempts for this bot and sender."""

def stage(self, entry: BrowserLoginEntry, candidate: Any, *, requires_post_auth: bool) -> str:
    """Return a fresh confirmation code for a consumed, current, unexpired attempt."""

def confirm(self, code: str, *, bot_id: str, telegram_id: int, chat_id: int) -> Optional[PendingBrowserConfirmation]:
    """Atomically consume a code only when its bot, sender and chat match."""

def render_browser_confirmation(bot_username: Optional[str], code: str) -> str:
    """Render the escaped browser-only command and safe return link."""

# New methods on TelegramAgentWrapper:
async def _prepare_browser_login(self, data: Dict[str, Any], *, browser_entry: BrowserLoginEntry) -> str:
    """Verify into an unpublished candidate and return its browser-only confirmation code."""

async def _finish_authentication(self, target: TelegramUserSession, *, chat_id: int,
                                 staged: bool, notify: bool = True, run_post_success: bool = True) -> bool:
    """Run the existing publication/post-auth pipeline for a confirmed candidate or webview login."""
```

Use a bot-local async lock around browser `/login` and `/logout` handling so logout
cannot interleave with confirmation publication and re-persist a just-unlinked identity.
Provider verification stays outside this lock; staging rechecks current-attempt identity.
Store confirmation lookup keys as SHA-256 digests and exclude candidates from model repr
and serialization. HTTP pending JSON is `{"ok": true, "pending_confirmation": true,
"confirmation_code": "...", "redirect_url": "https://t.me/<bot>"}` with status 202;
OAuth2 uses a 200 confirmation page. Neither response means authentication is complete.

## 4. Test Specification

- Forwarded-link regression: victim credential completes an attacker's state; attacker's
  session, persistent identity link and post-login side effects remain unchanged.
- Valid confirmation: the browser-only command authenticates only the correct bot/user/chat.
- Wrong bot, sender, chat, state-as-code and random code cannot confirm.
- Replay, expired code, unknown code, cancelled login and process restart fail closed.
- New login and logout invalidate both staged candidates and verifications blocked on await.
- Concurrent callback requests verify at most once; concurrent code redemptions publish once.
- Browser verification never mutates an existing authenticated session before confirmation.
- OAuth2 and composite OAuth2 exchange the authorization code once and retain resulting credentials
  only in the unpublished candidate until confirmation.
- Required post-auth actions start only after confirmation.
- All three login pages show the command as text, avoid premature success and preserve webview behavior.
- Pending responses carry no-store/no-referrer headers and never echo provider credentials.

### Validation Contract

tests:
- packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login.py
- packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login_confirmation.py
- packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_identity_verification.py
- packages/ai-parrot-integrations/tests/integrations/telegram/test_oauth2_integration.py
- packages/ai-parrot-integrations/tests/integrations/telegram/test_oauth2_callback.py
- packages/ai-parrot-integrations/tests/integrations/telegram/test_login_pages_browser_mode.py
- packages/ai-parrot-integrations/tests/integrations/telegram/test_post_auth_connection.py
markers: none

## 5. Acceptance Criteria

- AC1: A browser callback alone cannot activate or persist a Telegram identity.
- AC2: Only the initiating bot/user/chat can redeem the independently generated browser code.
- AC3: Code expiry, cancellation, replay and concurrency are fail-closed.
- AC4: No success side effects occur before confirmation; valid redemption triggers them once.
- AC5: Basic, Azure, Google, OAuth2 and composite browser paths use the gate; webview is unchanged.
- AC6: Shipped pages and operator documentation explain the new step accurately.
- AC7: Focused regression tests and changed-file lint pass; independent security review is recorded.

## 6. Codebase Contract

Verified against the main checkout during investigation on 2026-11-17; reverify after
worktree provisioning before task blueprints are finalized.

| Existing interface | Location | Relevant contract |
|---|---|---|
| `BrowserLoginRegistry.register(entry)` | `browser_login.py` | Replaces earlier states for the same bot/chat. |
| `BrowserLoginRegistry.consume(state)` | `browser_login.py` | Synchronous one-use state removal with TTL. |
| `browser_complete_handler(request)` | `browser_login.py` | Strips reserved correlation fields and currently calls `_complete_auth_payload`. |
| `_browser_oauth2_callback(request, state)` | `oauth2_callback.py` | Consumes state then currently calls `_complete_auth_payload` with OAuth2 code/state. |
| `TelegramAgentWrapper.handle_login(message)` | `wrapper.py` | Registers the browser state and sends the login URL. |
| `TelegramAgentWrapper.handle_logout(message)` | `wrapper.py` | Cancels post-auth coordination and unlinks the active principal. |
| `_complete_auth_payload(data, *, telegram_id, chat_id, notify=True, browser_entry=None, run_post_success=True)` | `wrapper.py` | Currently verifies and publishes identity in one call. |
| `_new_login_candidate(session)` | `wrapper.py` | Returns an unauthenticated session preserving Telegram identity fields. |
| `_authenticate_browser_identity(data, method, target, browser_entry)` | `wrapper.py` | Validates via server-owned verifier and populates target. |
| `_begin_login_attempt(candidate, chat_id=..., send=...)` | `wrapper.py` | Starts required post-auth orchestration. |
| `TelegramUserSession` | `auth.py` | Existing mutable session type with Navigator and OAuth2 credentials. |
| `completeLogin(payload, legacySend)` | Three shipped login pages | POSTs browser completion, currently displays immediate success. |

Verified dependencies: `aiohttp`, `aiogram`, Pydantic v2 and Python standard library
`secrets`, `time`, `html`; no new package is required. No browser confirmation registry,
code redemption API or browser-to-Telegram proof currently exists.

## 7. Worktree Strategy

Base: `dev`. Provision with `parrot sdd worktree ensure --slug telegram-browser-login-fixes
--feature-id FEAT-906` after publishing the approved specification and validated task set.
Implementation changes belong only in that worktree. Tasks must cite
`**Discovered-from**: issue:21146a531a96` for evidence-based ledger closure.

## 8. Open Questions

- [x] Owner approved the browser-displayed one-time command flow on 2026-11-17.
- [x] TASK-5736 owns server confirmation and regression tests; TASK-5737 consumes its
  pending response in the three pages; TASK-5738 documents the final behavior.
