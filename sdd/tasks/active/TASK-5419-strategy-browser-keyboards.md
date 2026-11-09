# TASK-5419: Browser-mode keyboards in all auth strategies

**Feature**: FEAT-854 — Telegram Auth Open Mode (webview | browser)
**Spec**: `sdd/specs/telegram-auth-open-mode.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5417, TASK-5418
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. In browser mode every strategy must present its login/authorize URL
as an `InlineKeyboardButton(url=...)` (opens the system browser) instead of a
`KeyboardButton(web_app=WebAppInfo(...))`. Page-based strategies (basic, azure,
google, composite) add `return_mode=browser&state=<state>&complete_url=<abs URL>` to
their login page URL; OAuth2 uses the raw provider authorize URL (the provider
redirects server-side). The mode is read from `config.auth_open_mode`
(decision `open-mode-config-driven` — **no new kwarg** on `build_login_keyboard`).
Webview mode must stay byte-for-byte identical.

---

## Scope

- Add module-level helpers `_is_browser_mode(config)`, `_browser_page_params(config, state)`
  and `_browser_keyboard(text, url)` to `auth.py`.
- Widen the `build_login_keyboard` return annotation to
  `Union[ReplyKeyboardMarkup, InlineKeyboardMarkup]` on the abstract method and all
  five implementations; update docstrings.
- Add the browser branch to `BasicAuthStrategy`, `AzureAuthStrategy`,
  `GoogleAuthStrategy`, `OAuth2AuthStrategy`, `CompositeAuthStrategy`.
- Append the M3 tests to `test_auth_strategies.py`.

**NOT in scope**: registering the state (TASK-5423 does it in `handle_login`), the
completion endpoints, the HTML pages, any change to webview URLs or button texts.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py` | MODIFY | Helpers + browser branch in 5 strategies |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_auth_strategies.py` | MODIFY | Append `TestBrowserModeKeyboards` |

---

## Codebase Contract (Anti-Hallucination)

> Verified against dev @ `0083e04b62` (2026-11-09).

### Verified Imports
```python
from typing import Optional, Dict, Any, Tuple, TYPE_CHECKING   # verified: telegram/auth.py:10 (add Union)
from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton, WebAppInfo)  # verified: telegram/auth.py:25-29
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton  # verified: telegram/wrapper.py:35-36 (same aiogram.types)
from urllib.parse import urlencode                              # verified: telegram/auth.py:17
from parrot.integrations.telegram.browser_login import BROWSER_COMPLETE_PATH  # created by TASK-5418
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py
class AbstractAuthStrategy(ABC):                 # line 302
    @abstractmethod
    async def build_login_keyboard(self, config: Any, state: str, *,
        next_auth_url: Optional[str] = None,
        next_auth_required: bool = False) -> ReplyKeyboardMarkup:   # line 322 (return at 329)

class BasicAuthStrategy(AbstractAuthStrategy):   # line 380 — build_login_keyboard 406
    #   params: Dict[str, Any] = {"auth_url": self.auth_url}   ... full_url line 446, return 448, button text line 451
class AzureAuthStrategy(AbstractAuthStrategy):   # line 531 — build_login_keyboard 569
    #   params = {"azure_auth_url": self.azure_auth_url}       ... full_url line 607, return 609, text line 612
class GoogleAuthStrategy(AbstractAuthStrategy):  # line 798 — build_login_keyboard 846
    #   params = {"google_auth_url": self.google_auth_url}     ... full_url line 881, return 883, text line 886
class OAuth2AuthStrategy(AbstractAuthStrategy):  # line 1061 — build_login_keyboard 1192
    #   authorize_url built at ~1227; provider_label line 1233; return 1234; text line 1237
    def build_authorize_url(self, state: str) -> str:   # line 1154 (stores PKCE under `state`)
class CompositeAuthStrategy(AbstractAuthStrategy):  # line 1439 — build_login_keyboard 1500
    #   full_url = f"{self.login_page_url}?{urlencode(params)}"  line 1552; return 1554; text line 1557
```

### Does NOT Exist
- ~~`build_login_keyboard(..., open_mode=...)`~~ — forbidden by decision `open-mode-config-driven`.
- ~~`config.auth_open_mode` on `_DummyConfig` in the tests~~ — the test stand-in has only `login_page_url`; read the mode with `getattr(config, "auth_open_mode", "webview")` so stand-ins keep working.
- ~~`TelegramAgentConfig.complete_url`~~ — the completion URL is derived: `public_base_url.rstrip("/") + BROWSER_COMPLETE_PATH`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_auth_strategies.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py#AbstractAuthStrategy.build_login_keyboard",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py#BasicAuthStrategy.build_login_keyboard",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py#AzureAuthStrategy.build_login_keyboard",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py#GoogleAuthStrategy.build_login_keyboard",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py#OAuth2AuthStrategy.build_login_keyboard",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py#CompositeAuthStrategy.build_login_keyboard"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Webview mode: same params dict, same `full_url`, same `ReplyKeyboardMarkup` — add the
  browser params **only** inside the browser branch.
- Browser mode button texts: reuse each strategy's existing text verbatim.
- OAuth2 / composite-OAuth2: pass the `state` you received unchanged to the PKCE store
  (`_store_state` / `build_authorize_url`) — TASK-5425 relies on the `browser.` prefix
  surviving into the provider redirect.

---

## Implementation Blueprint

### Steps (in order)
1. Add `Union` to the typing import and `InlineKeyboardMarkup`, `InlineKeyboardButton` to the aiogram import; import `BROWSER_COMPLETE_PATH`.
2. Insert the three helpers above the "Auth strategy abstraction" banner — *why*: shared by all five strategies.
3. Widen the six return annotations (`-> ReplyKeyboardMarkup:` occurs 6 times, lines 329/413/576/853/1199/1507).
4. Add the browser branch in each strategy just before its `return ReplyKeyboardMarkup(`.
5. Append the tests.

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py` (MODIFY — imports)
```python
# occurrences: 1 (verified: grep -c '    WebAppInfo,' telegram/auth.py)  — line 28
# AFTER — insert below `    WebAppInfo,`
    InlineKeyboardMarkup,
    InlineKeyboardButton,
# occurrences: 1 — line 10: change
#   from typing import Optional, Dict, Any, Tuple, TYPE_CHECKING
# to
#   from typing import Optional, Dict, Any, Tuple, TYPE_CHECKING, Union
# occurrences: 1 (verified: grep -c 'from parrot.integrations.core.auth.oauth2_providers import get_provider, OAuth2ProviderConfig' telegram/auth.py) — line 33
# AFTER — insert below it:
from parrot.integrations.telegram.browser_login import BROWSER_COMPLETE_PATH
```

### `auth.py` (MODIFY — helpers)
```python
# occurrences: 1 (verified: grep -c '# Auth strategy abstraction' telegram/auth.py) — line 299
# BEFORE — insert above the `# ----...` banner line that precedes `# Auth strategy abstraction`
# (i.e. after `        return bool(token)`, line 295, which also occurs exactly once)

def _is_browser_mode(config: Any) -> bool:
    """Return True when the bot is configured for system-browser auth (FEAT-854)."""
    return getattr(config, "auth_open_mode", "webview") == "browser"


def _browser_page_params(config: Any, state: str) -> Dict[str, str]:
    """Query params a login page needs to complete a browser-mode login.

    Raises:
        ValueError: when ``public_base_url`` is not configured.
    """
    base = (getattr(config, "public_base_url", None) or "").rstrip("/")
    if not base:
        raise ValueError("public_base_url is required when auth_open_mode='browser'")
    return {
        "return_mode": "browser",
        "state": state,
        "complete_url": f"{base}{BROWSER_COMPLETE_PATH}",
    }


def _browser_keyboard(text: str, url: str) -> InlineKeyboardMarkup:
    """Inline keyboard whose single button opens ``url`` in the system browser."""
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=url)]])
```
**Why**: Spec M3 skeleton names `_browser_keyboard(text, url)` as the shared helper.
`ValueError` is what `handle_login` already catches and reports (wrapper.py:2514-2516).

### `auth.py` (MODIFY — browser branch, page-based strategies)
```python
# Basic (line 446), Azure (line 607), Google (line 881):
# `        full_url = f"{page_url}?{urlencode(params)}"` occurs 3 times — disambiguate by the
# enclosing class and the button text that follows (`Sign in to Navigator",` line 451,
# `Sign in with Azure",` line 612, `Sign in with Google",` line 886; each occurs once).
# In each of the three: REPLACE the single `full_url = ...` line with:
        if _is_browser_mode(config):
            params.update(_browser_page_params(config, state))
            return _browser_keyboard("\U0001f510 Sign in to Navigator", f"{page_url}?{urlencode(params)}")
        full_url = f"{page_url}?{urlencode(params)}"
# (use "\U0001f510 Sign in with Azure" / "\U0001f510 Sign in with Google" in the other two)

# Composite (line 1552, `        full_url = f"{self.login_page_url}?{urlencode(params)}"` occurs once):
# BEFORE that line insert:
        if _is_browser_mode(config):
            params.update(_browser_page_params(config, state))
            return _browser_keyboard("\U0001f510 Sign in", f"{self.login_page_url}?{urlencode(params)}")
```
**Why**: The browser params are appended after the existing ones, so the
webview URL is untouched. Composite already pre-generates the OAuth2 authorize URL
with the same `state` (line ~1540), which keeps the `browser.` prefix intact.

### `auth.py` (MODIFY — browser branch, OAuth2)
```python
# occurrences: 1 (verified: grep -c '        provider_label = self._provider.name.capitalize()' telegram/auth.py) — line 1233
# AFTER — insert below it:
        if _is_browser_mode(config):
            return _browser_keyboard(f"\U0001f510 Sign in with {provider_label}", authorize_url)
```
**Why**: OAuth2 needs no page params — the provider redirects to the server
callback, which TASK-5425 routes by the state prefix.

### `packages/ai-parrot-integrations/tests/integrations/telegram/test_auth_strategies.py` (MODIFY)
```python
# AFTER — append at end of file (after TestAuthOpenModeConfig from TASK-5417)
# Add to imports: from urllib.parse import parse_qs, urlsplit
#                 from aiogram.types import InlineKeyboardMarkup
#                 AzureAuthStrategy, GoogleAuthStrategy, OAuth2AuthStrategy, CompositeAuthStrategy
#                 from parrot.integrations.telegram.browser_login import BROWSER_COMPLETE_PATH, new_browser_state


class _BrowserConfig(_DummyConfig):
    auth_open_mode = "browser"
    public_base_url = "https://parrot.example"


class TestBrowserModeKeyboards:
    """FEAT-854 M3."""

    async def test_basic_keyboard_browser_mode_inline_url(self, basic_strategy):
        state = new_browser_state()
        kb = await basic_strategy.build_login_keyboard(_BrowserConfig(), state)
        assert isinstance(kb, InlineKeyboardMarkup)
        button = kb.inline_keyboard[0][0]
        assert button.url and button.web_app is None
        query = parse_qs(urlsplit(button.url).query)
        assert query["return_mode"] == ["browser"] and query["state"] == [state]
        assert query["complete_url"] == [f"https://parrot.example{BROWSER_COMPLETE_PATH}"]

    async def test_oauth2_keyboard_browser_mode_authorize_url(self):
        # FILL IN: OAuth2AuthStrategy(TelegramAgentConfig(... oauth2 fields ...,
        # auth_open_mode="browser", public_base_url="https://parrot.example")) → button.url
        # starts with the provider authorization_url, carries state=<browser state> and
        # code_challenge; strategy._consume_state(state) returns a verifier (PKCE stored).

    async def test_azure_google_composite_browser_mode(self):
        # FILL IN: each returns InlineKeyboardMarkup with the three browser params.

    async def test_all_strategies_webview_mode_unchanged(self, basic_strategy, dummy_config):
        # FILL IN: for all five strategies with a webview config, the result is a
        # ReplyKeyboardMarkup whose button has web_app.url and NO return_mode/state/complete_url.

    async def test_browser_mode_without_public_base_url_raises(self, basic_strategy):
        # FILL IN: _DummyConfig subclass with auth_open_mode="browser" and no
        # public_base_url -> pytest.raises(ValueError)
```
Async tests need no marker: `asyncio_mode = "auto"` (ai-parrot-integrations/pyproject.toml:148).

### FILL IN checklist
- [ ] Browser branch in all five strategies (texts reused verbatim)
- [ ] Return annotations widened on all six signatures; docstrings mention browser mode
- [ ] Test bodies (OAuth2 PKCE stored under the browser state; webview regression)

---

## Acceptance Criteria

- [ ] Webview (default) keyboards are byte-identical: `pytest test_auth_strategies.py test_composite_auth.py test_oauth2_strategy.py test_azure_auth_strategy.py test_google_auth_strategy.py` pass without editing existing assertions.
- [ ] Browser mode returns `InlineKeyboardMarkup` with a plain `url` (no `web_app`) for all five strategies.
- [ ] Page-based URLs carry exactly `return_mode=browser`, the given `state`, and `complete_url=<public_base_url><BROWSER_COMPLETE_PATH>`.
- [ ] OAuth2 inline URL == authorize URL; PKCE stored under the given state.
- [ ] No `open_mode` kwarg anywhere; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_auth_strategies.py -q`

---

## Test Specification

See the `TestBrowserModeKeyboards` block (spec §4 rows
`test_basic_keyboard_browser_mode_inline_url`, `test_oauth2_keyboard_browser_mode_authorize_url`,
`test_all_strategies_webview_mode_unchanged`).

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
9. **Close the task** with `parrot sdd task close TASK-5419 telegram-auth-open-mode verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
