# TASK-5423: Wrapper browser-mode wiring — `/login` state registration + startup validation

**Feature**: FEAT-854 — Telegram Auth Open Mode (webview | browser)
**Spec**: `sdd/specs/telegram-auth-open-mode.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5417, TASK-5418, TASK-5420, TASK-5422
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 items 1, 3 and 4. In browser mode, `/login` must:
- generate the state as `browser.` + `secrets.token_urlsafe(32)` and pass that exact
  value to the strategy (OAuth2 stores PKCE under it, so the provider redirect carries
  the prefix back);
- register `state → (telegram_id, chat_id, bot_id, bot_username)` in the app-scoped
  `BrowserLoginRegistry` **before** sending the keyboard;
- tell the user the link opens in their browser.

At construction, a browser-mode wrapper must fail **clearly and early** when browser
mode cannot work: no shared aiohttp app (the completion endpoints and the wrapper must
share it — spec §7), no bot id, or a page-based method (basic/azure/google, including
composite members) without a `BrowserIdentityVerifier`. It then self-registers in
`app["telegram_wrappers"][bot_id]` so the HTTP handlers can find it (pattern:
`app.get("telegram_connection_notifier")`, wrapper.py:2717).

Startup failures surface through the existing per-bot `try/except` in both startup
paths (`IntegrationBotManager.startup`, integrations/manager.py:356-373, logs
"Failed to start bot"; `TelegramBotManager._start_bot`, telegram/manager.py:155).

---

## Scope

- Add `_setup_browser_mode()` (called at the end of `__init__`), `_enabled_auth_methods()`
  and `_get_bot_username()` to `TelegramAgentWrapper`.
- Change `handle_login` for browser mode (state, registry entry, cleanup on keyboard
  error, prompt copy).
- Append startup / `/login` tests to `test_browser_identity_verification.py`.

**NOT in scope**: HTTP handlers and route mounting (TASK-5424/5425), editing or deleting
the inline login message after success (spec §8 Q2 — decided: leave it; the success
notice is a new message), webview behavior changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `_setup_browser_mode`, `_enabled_auth_methods`, `_get_bot_username`, `handle_login` browser branch |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_identity_verification.py` | MODIFY | Append startup + `/login` tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against dev @ `0083e04b62` (2026-11-09). Line numbers are pre-TASK-5422;
> re-locate anchors by text (each occurs once).

### Verified Imports
```python
# wrapper.py already imports: secrets (:19), time (:20), json, asyncio
# extend the `.browser_login` import added by TASK-5422 with:
from .browser_login import (
    TELEGRAM_WRAPPERS_APP_KEY, BrowserLoginEntry, PAGE_AUTH_METHODS,
    get_or_create_browser_login_registry, new_browser_state,
)
from .browser_verifiers import ensure_navigator_browser_verifiers   # TASK-5420
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
def __init__(self, agent, bot, config, agent_commands=None, *, app=None):   # line 158
    self.app = app                                         # line 174
    self._bot_id: Optional[str] = self._resolve_bot_id(bot, config)   # line 184
    self._auth_strategy = self._build_auth_strategy(config)            # line 244
    self._register_handlers()                              # line 280 (last statement of __init__; occurs once)
async def handle_login(self, message: Message) -> None:    # line 2485
    #   session = self._get_user_session(message)          # line 2492
    #   state = secrets.token_urlsafe(32)                  # line 2510 (occurs once)
    #   keyboard = await self._auth_strategy.build_login_keyboard(self.config, state)   # line 2513
    #   except ValueError as exc: await message.answer(f"❌ Login configuration error: {exc}")  # line 2515
    #   await message.answer(prompt_text, reply_markup=keyboard, parse_mode="Markdown") # line 2539 (occurs once)

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py
class CompositeAuthStrategy:  .strategies: Dict[str, AbstractAuthStrategy]   # line 1439 / ~1490
class AbstractAuthStrategy:   name: str                                      # line 318
```

### Does NOT Exist
- ~~`app["telegram_wrappers"]`~~ — created by THIS task (`TELEGRAM_WRAPPERS_APP_KEY`).
- ~~`self._bot_username`~~ — created by THIS task (lazy cache).
- ~~`TelegramAgentWrapper.start()` / an async startup hook~~ — there is none; validation runs synchronously in `__init__`.
- ~~`message.chat.username` as the bot username~~ — use `(await self.bot.get_me()).username`.

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
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper.__init__",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper.handle_login",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py#CompositeAuthStrategy"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Webview mode: `handle_login` unchanged (still `secrets.token_urlsafe(32)`, no registry).
- Browser mode without an auth strategy (`enable_login=False`) wires nothing and does not raise.
- Register the entry before building the keyboard; if `build_login_keyboard` raises
  `ValueError`, `consume(state)` the entry (no orphan) and keep today's error reply.
- `_get_bot_username` never raises; a failure caches nothing and returns `None` (the
  success page then shows a plain "return to Telegram" line).

---

## Implementation Blueprint

### Steps (in order)
1. Extend the imports.
2. Add the three methods (insert BEFORE `    async def handle_login(self, message: Message) -> None:`, occurs once).
3. Call `self._setup_browser_mode()` after `self._register_handlers()` at the end of `__init__`.
4. Change `handle_login`.
5. Append tests.

### `wrapper.py` (MODIFY — new methods)
```python
    def _enabled_auth_methods(self) -> set:
        """Names of the auth methods this bot's strategy actually serves."""
        strategy = self._auth_strategy
        if strategy is None:
            return set()
        if isinstance(strategy, CompositeAuthStrategy):
            return set(strategy.strategies)
        return {strategy.name}

    def _setup_browser_mode(self) -> None:
        """Validate and wire browser-mode login at construction (FEAT-854).

        Raises:
            ValueError: browser mode is configured but cannot work (no shared app,
                no bot id, or a page-based method without an identity verifier).
        """
        if getattr(self.config, "auth_open_mode", "webview") != "browser" or self._auth_strategy is None:
            return
        name = getattr(self.config, "name", "?")
        if self.app is None:
            raise ValueError(
                f"Agent '{name}': auth_open_mode='browser' requires the shared aiohttp app "
                "(the completion endpoints and the bot must run in the same server)."
            )
        if not self._bot_id:
            raise ValueError(f"Agent '{name}': auth_open_mode='browser' could not resolve the bot id.")
        bot_id = str(self._bot_id)
        get_or_create_browser_login_registry(self.app)
        page_methods = sorted(self._enabled_auth_methods() & PAGE_AUTH_METHODS)
        missing = ensure_navigator_browser_verifiers(
            self.app, bot_id=bot_id, methods=page_methods, tenant_id=self.config.tenant
        )
        if missing:
            # FILL IN: raise ValueError naming the agent and the missing methods, and stating the
            # two remedies: register a verifier under
            # app["telegram_browser_identity_verifiers"][<bot_id>][<method>] before startup, or
            # configure AUTH_SECRET_KEY / OAUTH_JWT_KEYS shared with the Navigator issuer.
            pass
        self.app.setdefault(TELEGRAM_WRAPPERS_APP_KEY, {})[bot_id] = self
        self.logger.info("Browser-mode login enabled for bot %s (methods: %s)", bot_id,
                         sorted(self._enabled_auth_methods()))

    async def _get_bot_username(self) -> Optional[str]:
        """Return the bot's @username (cached after the first success), or None."""
        cached = getattr(self, "_bot_username", None)
        if cached:
            return cached
        try:
            me = await self.bot.get_me()
        except Exception:  # noqa: BLE001 - deep link is optional
            self.logger.debug("get_me() failed; browser success page will omit the deep link", exc_info=True)
            return None
        self._bot_username = getattr(me, "username", None)
        return self._bot_username
```
**Why**: Spec M4 items 3-4 and §2 "Browser startup fails clearly when any enabled
basic/azure/google method (including composite members) lacks a verifier". OAuth2-only
bots need no verifier (`page_methods` is empty).

### `wrapper.py` (MODIFY — `__init__`)
```python
# occurrences: 1 (verified: grep -c '        self._register_handlers()' telegram/wrapper.py) — line 280
# AFTER — insert below `        self._register_handlers()`
        # FEAT-854: browser-mode login wiring (no-op in webview mode).
        self._setup_browser_mode()
```

### `wrapper.py` (MODIFY — `handle_login`)
```python
# occurrences: 1 (verified: grep -c '        state = secrets.token_urlsafe(32)' telegram/wrapper.py) — line 2510
# REPLACE that line with:
        browser_mode = getattr(self.config, "auth_open_mode", "webview") == "browser"
        registry = None
        if browser_mode:
            state = new_browser_state()
            registry = get_or_create_browser_login_registry(self.app)
            registry.register(
                BrowserLoginEntry(
                    state=state,
                    telegram_id=session.telegram_id,
                    chat_id=chat_id,
                    bot_id=str(self._bot_id or ""),
                    bot_username=await self._get_bot_username(),
                    created_at=time.monotonic(),
                )
            )
        else:
            state = secrets.token_urlsafe(32)

# occurrences: 1 (verified: grep -c 'Login configuration error: {exc}")' telegram/wrapper.py) — line 2515
# BEFORE that line (inside `except ValueError as exc:`) insert:
            if registry is not None:
                registry.consume(state)

# occurrences: 1 (verified: grep -c '        await message.answer(prompt_text, reply_markup=keyboard, parse_mode="Markdown")' telegram/wrapper.py) — line 2539
# BEFORE it insert:
        if browser_mode:
            prompt_text += "\n\nThe link opens in your browser. Come back here when you are done."
```

### `test_browser_identity_verification.py` (MODIFY — append)
```python
# Append below the TASK-5422 tests. Construct real wrappers like
# test_oauth2_integration.py:29-47 (_make_wrapper) but pass app=web.Application().

async def test_browser_startup_requires_verifiers(monkeypatch):
    # FILL IN: browser basic config, no key material and no host verifier -> ValueError naming
    # "basic"; host-registered verifier -> constructs and registers the wrapper under
    # app["telegram_wrappers"][bot_id]; OAuth2-only browser config needs no verifier;
    # composite basic+azure missing azure -> ValueError naming "azure"; app=None -> ValueError.

async def test_handle_login_browser_mode_registers_state():
    # FILL IN: /login -> registry has exactly one entry whose state starts with "browser.",
    # telegram_id/chat_id from the message, bot_username from bot.get_me(); reply markup is an
    # InlineKeyboardMarkup; prompt mentions the browser.

async def test_handle_login_webview_mode_unchanged():
    # FILL IN: webview config -> no registry created in app; ReplyKeyboardMarkup sent.

async def test_handle_login_keyboard_error_drops_entry():
    # FILL IN: strategy.build_login_keyboard raising ValueError -> registry empty, error reply sent.
```

### FILL IN checklist
- [ ] `_setup_browser_mode` missing-verifier error message (both remedies named)
- [ ] Four tests

---

## Acceptance Criteria

- [ ] Browser `/login` registers a `browser.` state (single-use, 600 s TTL) with the chat ids and sends an inline URL keyboard.
- [ ] The same state value reaches `build_login_keyboard` (OAuth2 PKCE stored under it).
- [ ] Startup raises `ValueError` for: no app, no bot id, any enabled page method without a verifier; OAuth2-only needs none.
- [ ] Wrapper registered in `app["telegram_wrappers"][bot_id]`.
- [ ] Webview `/login` unchanged (`test_oauth2_integration.py` login tests pass unchanged).
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_identity_verification.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_oauth2_integration.py -q`

---

## Test Specification

See the appended test block (spec §4 row `test_browser_startup_requires_verifiers`).

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
9. **Close the task** with `parrot sdd task close TASK-5423 telegram-auth-open-mode verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seat gpt-5.6-terra (codex), attempt 1, 300s
**Date**: 2026-11-09
**Notes**: wrapper.py: _setup_browser_mode, _enabled_auth_methods, _get_bot_username, handle_login browser branch; startup + /login tests appended. Merge-tier validation green (22 passed). File list matches the task; no review fixes.

**Deviations from spec**: none
