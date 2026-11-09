# TASK-5422: Wrapper `_complete_auth_payload` — transport-agnostic completion + verification boundary

**Feature**: FEAT-854 — Telegram Auth Open Mode (webview | browser)
**Spec**: `sdd/specs/telegram-auth-open-mode.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5418, TASK-5420
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 items 2 and 4, and §2 "Browser identity verification boundary".
Today the primary-auth success path lives inside `handle_web_app_data`, which needs an
aiogram `Message`. Browser mode completes logins from HTTP handlers (TASK-5424/5425)
that only know the Telegram ids stored in a `BrowserLoginEntry`. This task extracts the
success path into `_complete_auth_payload(data, *, telegram_id, chat_id, notify=True,
browser_entry=None) -> bool` (signature fixed by the spec) and makes it the **sole
owner of primary authentication**:

- webview (no `browser_entry`): the unchanged legacy strategy callback, once;
- browser + OAuth2: the strategy callback, exactly once (PKCE consume, code exchange,
  userinfo all happen inside it);
- browser + basic/azure/google: **never** the trusting legacy callbacks — the token is
  verified by the registered `BrowserIdentityVerifier` (TASK-5420) and the session is
  built only from verified values.

`handle_web_app_data` becomes a thin webview adapter over it. The staged
`post_auth_actions` lane gains a `Message`-free entry point for browser logins.

---

## Scope

- Add `_complete_auth_payload` and its private helpers to `TelegramAgentWrapper`.
- Refactor `handle_web_app_data` into the webview adapter (see blueprint).
- Extract `_start_login_attempt`'s body into `_begin_login_attempt(candidate, *, chat_id, send)`;
  keep `_start_login_attempt(message, candidate)` as a one-line adapter (existing tests call it).
- Keep `_handle_combined_auth(message, data, session)` unchanged (webview combined lane).
- Append the M4 tests to `test_browser_identity_verification.py`.

**NOT in scope**: `handle_login` changes, wrapper app registration and startup
validation (TASK-5423), HTTP handlers (TASK-5424/5425), any change to strategy classes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `_complete_auth_payload`, helpers, webview adapter, `_begin_login_attempt` |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_identity_verification.py` | MODIFY | Append completion-boundary tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against dev @ `0083e04b62` (2026-11-09).

### Verified Imports
```python
# already in wrapper.py:
from aiogram.types import (Message, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton)  # :24-37
from .auth import (TelegramUserSession, AbstractAuthStrategy, ..., CompositeAuthStrategy)            # :46-54
from .models import TelegramAgentConfig                                                               # :45
# new (TASK-5418):
from .browser_login import (
    PAGE_AUTH_METHODS, BrowserLoginEntry, BrowserVerificationError,
    BrowserVerifierUnavailableError, get_browser_identity_verifier,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
class TelegramAgentWrapper(OperatorCommandsMixin):                      # line 105
    self.app                     # line 174 (Optional aiohttp app)
    self._bot_id: Optional[str]  # line 184
    self._user_sessions: Dict[int, TelegramUserSession]   # line 211
    self._auth_strategy          # line 244
    async def _persist_principal_link(self, session: TelegramUserSession) -> bool:   # line 717
    def _is_combined_payload(self, data: Dict[str, Any]) -> bool:                    # line 772
    def _get_user_session(self, message: Message) -> TelegramUserSession:           # line 1242
    async def _initialize_user_context(self, session, message: Optional[Message] = None) -> None:  # line 1514
    async def handle_web_app_data(self, message: Message) -> None:                    # line 2583 (body to 2625)
    #   "# Standard (single-step) auth flow."  line 2608 ; success answer + ReplyKeyboardRemove 2611-2623
    async def _handle_combined_auth(self, message, data, session) -> None:            # line 2627
    async def _start_login_attempt(self, message: Message, candidate: TelegramUserSession) -> None:  # line 2652
    #   uses message.chat.id (attempt chat_id) and message.answer(text, reply_markup=keyboard, parse_mode=None)
    async def _finalize_login_attempt(self, attempt: PendingLoginAttempt) -> None:   # line 2707
    async def _typing_indicator(self, chat_id: int) -> None:                          # line 2802 (swallows errors)

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py
class TelegramUserSession:                                     # line 44
    def set_authenticated(self, nav_user_id: str, session_token: str,
        display_name: Optional[str] = None, email: Optional[str] = None, **extra_meta) -> None:  # line 123
    metadata: Dict                                             # line 58
class CompositeAuthStrategy(AbstractAuthStrategy):             # line 1439 — .strategies: Dict[str, AbstractAuthStrategy]
    async def handle_callback(self, data, session) -> bool:    # dispatches on data["auth_method"]; sets metadata["auth_method"]
```

Existing tests that pin behavior (must stay green **without editing assertions**):
- `tests/integrations/telegram/test_staged_combined_login.py` — calls `_start_login_attempt(message, candidate)` and `_handle_combined_auth(message, data, session)` directly (`:88-239`).
- `tests/integrations/telegram/test_oauth2_integration.py:269-334` — `handle_web_app_data` must call `message.answer` exactly once with the ✅/❌ text.
- `tests/integrations/telegram/test_principal_link_lifecycle.py`, `test_post_auth_capability_gate.py`.

### Does NOT Exist
- ~~`TelegramAgentWrapper._complete_auth_payload`~~ — created by THIS task.
- ~~`_get_user_session(telegram_id)`~~ — it takes a `Message`; the core uses `self._user_sessions.get(telegram_id)`.
- ~~`BrowserLoginEntry.verified`~~ / any "verified" flag from JSON — identity is only what the verifier returns.
- ~~`functools` import in wrapper.py~~ — not imported; use a local closure for the chat sender.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_identity_verification.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper.handle_web_app_data",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._handle_combined_auth",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._start_login_attempt",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._persist_principal_link",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._initialize_user_context",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py#TelegramUserSession.set_authenticated",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py#CompositeAuthStrategy.handle_callback"
  ]
}
```

---

## Implementation Notes

### Decided behavior
- **Method resolution (browser only)**: composite → `data["auth_method"]` must be a key of
  `self._auth_strategy.strategies`; single strategy → `data.get("auth_method")` must be
  absent or equal `self._auth_strategy.name`, and absent is accepted **only** for `basic`
  (legacy basic payloads). Anything else → `BrowserVerificationError`.
- **Verification (browser + page method)**: token must be a non-empty string; verifier =
  `get_browser_identity_verifier(self.app, bot_id=browser_entry.bot_id, auth_method=method)`
  (`None` → `BrowserVerifierUnavailableError`); `identity = await verifier.verify(token,
  auth_method=method, bot_id=browser_entry.bot_id, tenant_id=self.config.tenant)`. For each
  of `user_id`, `display_name`, `email`: if the payload supplies a non-empty value **and**
  the verified value is not `None`, they must be equal as strings, else
  `BrowserVerificationError`. Supplied values are **never** copied into the session.
  Then `target.set_authenticated(nav_user_id=identity.user_id, session_token=token,
  display_name=identity.display_name, email=identity.email)`; for a composite strategy set
  `target.metadata["auth_method"] = method`.
- **Telegram ids**: always from the arguments (`telegram_id`, `chat_id`), which HTTP
  adapters take from `browser_entry` — never from `data`.
- **Target session**: non-staged → the existing `self._user_sessions[telegram_id]` object is
  authenticated in place (today's webview behavior; created bare if absent); staged
  (`post_auth_actions` or a combined payload) → a fresh candidate copied from the session's
  Telegram fields, handed to `_begin_login_attempt` (promotion stays with the coordinator).
- **Failure**: typed errors (`BrowserVerificationError` / `BrowserVerifierUnavailableError`)
  propagate to the HTTP adapter (401 / 503) after the ❌ chat message (when `notify`);
  an ordinary failed callback returns `False`. No session mutation, link, or post-auth action on failure.
- **Success (non-staged)**: store the session, send ✅ via `self.bot.send_message(chat_id=...)`
  when `notify`, `_persist_principal_link`, then `_initialize_user_context(target)` wrapped in a
  `_typing_indicator(chat_id)` task (cancelled in `finally`).
- **Webview adapter**: calls the core with `notify=False` and answers ✅ (with
  `ReplyKeyboardRemove()`) / ❌ through `message.answer` itself, so the existing assertions hold.
  Known, accepted change: the webview ✅ now follows link persistence and context
  initialization (a typing indicator covers the wait); assertion text and count are unchanged.

---

## Implementation Blueprint

### Steps (in order)
1. Add the `.browser_login` import below `from .models import TelegramAgentConfig` (line 45, occurs once).
2. Insert `_complete_auth_payload` and helpers BEFORE `    async def _handle_combined_auth(` (line 2627, occurs once).
3. Replace the body of `handle_web_app_data` (lines 2584-2625) with the adapter.
4. Split `_start_login_attempt` into adapter + `_begin_login_attempt`.
5. Append tests; run the validation command and the pinned regression files.

### `wrapper.py` (MODIFY — core)
```python
# occurrences: 1 (verified: grep -c '    async def _handle_combined_auth(' telegram/wrapper.py) — line 2627
# BEFORE — insert above `    async def _handle_combined_auth(`
    async def _complete_auth_payload(
        self,
        data: Dict[str, Any],
        *,
        telegram_id: int,
        chat_id: int,
        notify: bool = True,
        browser_entry: Optional[BrowserLoginEntry] = None,
    ) -> bool:
        """Run the primary auth step and the post-success pipeline (FEAT-854).

        Transport-agnostic core shared by ``handle_web_app_data`` (webview) and the
        browser completion endpoints. ``browser_entry`` is server-owned correlation
        context, never read from JSON; when present, basic/azure/google payloads are
        authenticated only through the registered BrowserIdentityVerifier.

        Raises:
            BrowserVerificationError: browser credential/identity rejected (HTTP 401).
            BrowserVerifierUnavailableError: verifier/backend unavailable (HTTP 503).
        """
        if not self._auth_strategy:
            return False
        # Never insert into _user_sessions before success (no mutation on failure).
        session = self._user_sessions.get(telegram_id) or TelegramUserSession(telegram_id=telegram_id)
        staged = bool(getattr(self.config, "post_auth_actions", None) or self._is_combined_payload(data))
        target = self._new_login_candidate(session) if staged else session
        try:
            method = self._resolve_browser_auth_method(data) if browser_entry is not None else None
            if browser_entry is not None and method in PAGE_AUTH_METHODS:
                await self._authenticate_browser_identity(data, method, target, browser_entry)
                ok = True
            else:
                ok = await self._auth_strategy.handle_callback(data, target)  # exactly once
        except (BrowserVerificationError, BrowserVerifierUnavailableError):
            if notify:
                await self._notify_login_failed(chat_id)
            raise
        if not ok or not target.authenticated or not target.nav_user_id:
            if notify:
                await self._notify_login_failed(chat_id)
            return False
        if staged:
            # FILL IN: mirror _handle_combined_auth's guard (nav_session_token required, else
            # notify + return False), then:
            # await self._begin_login_attempt(target, chat_id=chat_id, send=self._chat_sender(chat_id))
            return True
        self._user_sessions[telegram_id] = target
        if notify:
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Authenticated as *{target.display_name}* (`{target.nav_user_id}`).\n\n"
                "Your identity will be used for all interactions.",
                parse_mode="Markdown",
            )
        await self._persist_principal_link(target)
        typing_task = asyncio.create_task(self._typing_indicator(chat_id))
        try:
            await self._initialize_user_context(target)
        finally:
            typing_task.cancel()
        return True
```
**Why**: Spec M4 skeleton signature verbatim; the branch structure enforces "endpoints
must not call handle_callback / _consume_state / exchange_code / fetch_userinfo" —
only this method does.

### `wrapper.py` (MODIFY — helpers, insert right after `_complete_auth_payload`)
```python
    def _new_login_candidate(self, session: TelegramUserSession) -> TelegramUserSession:
        """Fresh unauthenticated candidate carrying the session's Telegram fields."""
        return TelegramUserSession(
            telegram_id=session.telegram_id,
            telegram_username=session.telegram_username,
            telegram_first_name=session.telegram_first_name,
            telegram_last_name=session.telegram_last_name,
        )

    def _resolve_browser_auth_method(self, data: Dict[str, Any]) -> str:
        """Return the enabled method a browser payload targets, or raise BrowserVerificationError."""
        # FILL IN: "Method resolution" rule in Implementation Notes (composite vs single; absent
        # auth_method only for a single basic strategy).

    async def _authenticate_browser_identity(
        self,
        data: Dict[str, Any],
        method: str,
        target: TelegramUserSession,
        browser_entry: BrowserLoginEntry,
    ) -> None:
        """Authenticate ``target`` from a verifier-proven identity (never from JSON fields)."""
        # FILL IN: "Verification" rule in Implementation Notes. Log failures at warning
        # level without the token. Must not touch self._user_sessions or persist anything.

    def _chat_sender(self, chat_id: int) -> Callable[..., Awaitable[Any]]:
        """Return ``send(text, **kwargs)`` bound to ``chat_id`` via the bot (no Message needed)."""
        async def send(text: str, **kwargs: Any) -> Any:
            return await self.bot.send_message(chat_id=chat_id, text=text, **kwargs)
        return send

    async def _notify_login_failed(self, chat_id: int) -> None:
        """Tell the chat the login failed; never raises."""
        try:
            await self.bot.send_message(
                chat_id=chat_id, text="❌ Login failed. Please try again with /login.", parse_mode=None
            )
        except Exception:  # noqa: BLE001 - notification is best effort
            self.logger.warning("Could not send login-failure notice to chat %s", chat_id, exc_info=True)
```
`Callable` and `Awaitable` are already imported (wrapper.py:12).

### `wrapper.py` (MODIFY — webview adapter)
```python
# occurrences: 1 (verified: grep -c '    async def handle_web_app_data(self, message: Message) -> None:' telegram/wrapper.py) — line 2583
# REPLACE the docstring + body (lines 2584-2625) with:
        """Webview adapter: parse ``web_app_data`` and delegate to ``_complete_auth_payload``.

        Combined payloads keep the staged ``_handle_combined_auth`` lane; replies go
        through ``message.answer`` (with ``ReplyKeyboardRemove`` on success).
        """
        if not message.web_app_data or not message.from_user:
            return
        if not self._auth_strategy:
            return
        try:
            data = json.loads(message.web_app_data.data)
        except (json.JSONDecodeError, TypeError):
            await message.answer("❌ Invalid login response data.")
            return
        session = self._get_user_session(message)
        if getattr(self.config, "post_auth_actions", None) or self._is_combined_payload(data):
            await self._handle_combined_auth(message, data, session)
            return
        success = await self._complete_auth_payload(
            data, telegram_id=session.telegram_id, chat_id=message.chat.id, notify=False
        )
        if success:
            await message.answer(
                f"✅ Authenticated as *{session.display_name}* "
                f"(`{session.nav_user_id}`).\n\n"
                "Your identity will be used for all interactions.",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            await message.answer("❌ Login failed. Please try again with /login.")
```
**Why**: Same texts and the same single `message.answer` call as today
(wrapper.py:2597-2625), so `test_oauth2_integration.py` assertions hold.

### `wrapper.py` (MODIFY — staged lane without Message)
```python
# occurrences: 1 (verified: grep -c '    async def _start_login_attempt(self, message: Message, candidate: TelegramUserSession) -> None:' telegram/wrapper.py) — line 2652
# REPLACE the method with an adapter + the extracted body:
    async def _start_login_attempt(self, message: Message, candidate: TelegramUserSession) -> None:
        """Webview adapter over ``_begin_login_attempt``."""
        await self._begin_login_attempt(candidate, chat_id=message.chat.id, send=message.answer)

    async def _begin_login_attempt(
        self,
        candidate: TelegramUserSession,
        *,
        chat_id: int,
        send: Callable[..., Awaitable[Any]],
    ) -> None:
        """Create the pending attempt and send secondary Connect buttons (no Message needed)."""
        # FILL IN: the original body of _start_login_attempt (lines 2654-2705) with exactly two
        # substitutions: `message.chat.id` -> `chat_id`, and `await message.answer(` -> `await send(`.
```

### `test_browser_identity_verification.py` (MODIFY — append)
```python
# Append below the TASK-5420 tests. Build a wrapper double the way
# test_staged_combined_login.py:17-42 does (TelegramAgentWrapper.__new__ + attributes), with
# wrapper.app = {} and a stub verifier registered via register_browser_identity_verifier.

async def test_complete_auth_payload_success_notifies_chat():
    # FILL IN: oauth2 strategy mock returning True after set_authenticated -> True;
    # bot.send_message awaited with chat_id; session stored; link persisted once.

async def test_handle_web_app_data_delegates_to_complete():
    # FILL IN: spy _complete_auth_payload; webview message -> called once with notify=False and
    # no browser_entry; message.answer called once with ReplyKeyboardRemove.

async def test_browser_basic_rejects_forged_identity():
    # FILL IN: browser_entry + {"auth_method": "basic", "user_id": "admin", "token": ""} and a
    # forged token -> BrowserVerificationError; strategy.handle_callback NOT awaited; no session
    # authenticated; _persist_principal_link and post-auth NOT awaited.

async def test_browser_identity_uses_verified_claims():
    # FILL IN: verifier returns user_id "42"; payload user_id "43" -> 401 error; payload without
    # user_id -> session nav_user_id == "42"; composite rejects a method not in .strategies.

async def test_browser_verifier_unavailable_fails_closed():
    # FILL IN: verifier raising BrowserVerifierUnavailableError -> propagates; no legacy
    # callback; no mutation. Missing verifier registration -> BrowserVerifierUnavailableError.

async def test_browser_mode_combined_post_auth():
    # FILL IN: config with post_auth_actions -> _begin_login_attempt awaited with chat_id from
    # the arguments and a bot-bound sender; the session is NOT promoted.
```

### FILL IN checklist
- [ ] `_resolve_browser_auth_method` — method resolution rule
- [ ] `_authenticate_browser_identity` — verification rule; spec §2 (no JSON identity used)
- [ ] staged branch guard + `_begin_login_attempt` call
- [ ] `_begin_login_attempt` body — moved verbatim with the two substitutions
- [ ] Six tests

---

## Acceptance Criteria

- [ ] `_complete_auth_payload` signature exactly as spec M4.
- [ ] Browser basic/azure/google never call `handle_callback`; identity comes only from the verifier.
- [ ] Forged/mismatched credentials → `BrowserVerificationError`; verifier failure → `BrowserVerifierUnavailableError`; neither mutates sessions/links nor starts post-auth actions.
- [ ] OAuth2 (single and composite) → strategy callback exactly once.
- [ ] Regression files pass unchanged: `test_staged_combined_login.py`, `test_oauth2_integration.py`, `test_principal_link_lifecycle.py`, `test_post_auth_capability_gate.py`, `test_azure_wrapper.py` (run them; they are covered by the merge tier).
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_identity_verification.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_oauth2_integration.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_azure_integration.py -q`

---

## Test Specification

See the appended test block (spec §4 rows `test_complete_auth_payload_success_notifies_chat`,
`test_handle_web_app_data_delegates_to_complete`, `test_browser_basic_rejects_forged_identity`,
`test_browser_identity_uses_verified_claims`, `test_browser_verifier_unavailable_fails_closed`,
`test_browser_mode_combined_post_auth`).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug telegram-auth-open-mode --feature-id FEAT-854`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/telegram-auth-open-mode.json`
4. **Verify the Codebase Contract** before writing any code; fix stale entries first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-integrations/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5422 telegram-auth-open-mode verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
