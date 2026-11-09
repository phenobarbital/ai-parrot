# TASK-5418: `browser_login.py` — state registry, verifier contract, result pages

**Feature**: FEAT-854 — Telegram Auth Open Mode (webview | browser)
**Spec**: `sdd/specs/telegram-auth-open-mode.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 and §2 "Browser identity verification boundary". This new module is
the shared vocabulary every later task imports:

- the `browser.` CSRF-state namespace and the single-use, TTL-bound
  `BrowserLoginRegistry` that correlates a state with a Telegram chat;
- the app-scoped keys (`telegram_browser_login`, `telegram_browser_identity_verifiers`,
  `telegram_wrappers`) and the completion path constant;
- the `BrowserIdentityVerifier` protocol, its Pydantic `VerifiedBrowserIdentity`
  result and the two typed errors (401 vs 503);
- the browser success / error HTML pages with the `https://t.me/<bot>` deep link.

The HTTP handler and route setup are appended to this same file later by TASK-5424.

---

## Scope

- Create `browser_login.py` with the constants, `new_browser_state()`,
  `is_browser_state()`, `BrowserLoginEntry`, `BrowserLoginRegistry`
  (`register`/`consume`/`peek`), `get_or_create_browser_login_registry(app)`,
  `VerifiedBrowserIdentity`, `BrowserVerificationError`,
  `BrowserVerifierUnavailableError`, `BrowserIdentityVerifier` (Protocol),
  `register_browser_identity_verifier`, `get_browser_identity_verifier`,
  `telegram_deep_link`, `render_browser_success`, `render_browser_error`.
- Create `test_browser_login.py` with the M2 unit tests.

**NOT in scope**: `browser_complete_handler` / `setup_browser_auth_routes`
(TASK-5424), concrete verifiers (TASK-5420), any wrapper change.
**Never import** `auth.py` or `wrapper.py` from this module: `auth.py` imports
`BROWSER_COMPLETE_PATH` from here (TASK-5419), so a back-import creates a cycle.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/browser_login.py` | CREATE | Registry, state, verifier contract, result pages |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login.py` | CREATE | M2 unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against dev @ `0083e04b62` (2026-11-09).

### Verified Imports
```python
from navconfig.logging import logging          # verified: telegram/oauth2_callback.py:11
from pydantic import BaseModel, ConfigDict      # pydantic v2 is a core dependency (codebase conventions)
import html as html_mod                         # pattern: telegram/oauth2_callback.py:8
```

### Existing Signatures to Use
```python
# Pattern to mirror for the app-scoped accessor:
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/connection_notifier.py:227
def get_or_create_telegram_notifier(
    app: MutableMapping[str, Any],
    *,
    identity_service: Optional[Any] = None,
) -> TelegramConnectionNotifier:
    notifier = app.get(_APP_KEY)
    if notifier is None:
        notifier = TelegramConnectionNotifier(identity_service=identity_service)
        app[_APP_KEY] = notifier
        ...
    return notifier

# TTL policy to reuse: packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py:1058
_STATE_TTL_SECONDS = 600  # 10 minutes  (do NOT import it — duplicate the value; see Scope)

# Escape discipline to follow: telegram/oauth2_callback.py:138-192 (html_mod.escape on every
# user-provided value; error pages never echo auth data).
```

### Does NOT Exist
- ~~`parrot/integrations/telegram/browser_login.py`~~ — created by THIS task.
- ~~`BrowserLoginRegistry.sweep()` public method~~ — sweeping is internal (`_sweep`), triggered by `register`.
- ~~Redis-backed state~~ — the registry is in-process by design (spec §1 Non-Goals, §8 Q1).
- ~~`app["telegram_wrappers"]`~~ / ~~`app["telegram_browser_identity_verifiers"]`~~ — no such keys exist yet; this task only defines the key constants and the verifier accessors. TASK-5423 populates the wrapper map.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/browser_login.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/connection_notifier.py#get_or_create_telegram_notifier"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `consume()` must validate the TTL and pop the entry **synchronously, with no
  `await`** — two concurrent callbacks for one state must yield exactly one entry
  (spec M2, `test_oauth2_browser_concurrent_callbacks`).
- `register()` accepts only states matching `browser.` + `secrets.token_urlsafe(32)`
  (43 url-safe chars). Anything else raises `ValueError`.
- A miss is a miss: never let a registry miss select legacy routing (that decision is
  made from the `browser.` prefix alone, by the endpoints).
- HTML pages: escape everything, never include tokens, never load
  `telegram-web-app.js` (they run in the system browser).
- `telegram_deep_link` returns a link only for a valid Telegram username
  (`^[A-Za-z0-9_]{5,32}$`), otherwise `None` — the link is server-derived (spec §7 open-redirect).

---

## Implementation Blueprint

### Steps (in order)
1. Write block 1 (constants, state helpers, entry, registry, accessor) — *why*: every later block and task depends on these names.
2. Write block 2 (verifier contract) — *why*: TASK-5420/5422 implement and consume it.
3. Write block 3 (deep link + HTML pages) — *why*: TASK-5424/5425 render them.
4. Write the tests; run them.

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/browser_login.py` (CREATE — block 1/3)
```python
"""Browser-mode Telegram login (FEAT-854).

State registry correlating a CSRF ``state`` with a Telegram chat, the browser
identity-verification contract, and the browser result pages. The aiohttp
completion handler is appended by TASK-5424.

Never import ``auth.py`` or ``wrapper.py`` here: ``auth.py`` imports
``BROWSER_COMPLETE_PATH`` from this module.
"""
from __future__ import annotations

import html as html_mod
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Dict, MutableMapping, Optional, Protocol, runtime_checkable

from navconfig.logging import logging
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

BROWSER_LOGIN_APP_KEY = "telegram_browser_login"
BROWSER_VERIFIERS_APP_KEY = "telegram_browser_identity_verifiers"
TELEGRAM_WRAPPERS_APP_KEY = "telegram_wrappers"
BROWSER_STATE_PREFIX = "browser."
BROWSER_COMPLETE_PATH = "/api/auth/telegram/browser-complete"
PAGE_AUTH_METHODS = frozenset({"basic", "azure", "google"})
_REGISTRY_TTL_SECONDS = 600  # same policy as auth.py:1058 (_STATE_TTL_SECONDS)
_STATE_RE = re.compile(r"browser\.[A-Za-z0-9_-]{43}")


def new_browser_state() -> str:
    """Return a fresh browser-mode CSRF state (``browser.`` + 32 random bytes)."""
    return BROWSER_STATE_PREFIX + secrets.token_urlsafe(32)


def is_browser_state(state: Optional[str]) -> bool:
    """Return True when ``state`` is in the browser namespace (routing only, not proof)."""
    return isinstance(state, str) and state.startswith(BROWSER_STATE_PREFIX)


@dataclass
class BrowserLoginEntry:
    """One pending browser-mode login, keyed by CSRF state."""

    state: str
    telegram_id: int
    chat_id: int
    bot_id: str
    bot_username: Optional[str]
    created_at: float  # time.monotonic()


class BrowserLoginRegistry:
    """In-process, TTL-bound state -> chat correlation for browser-mode logins."""

    def __init__(self, ttl_seconds: float = _REGISTRY_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._entries: Dict[str, BrowserLoginEntry] = {}

    def _expired(self, entry: BrowserLoginEntry, now: float) -> bool:
        return (now - entry.created_at) > self._ttl

    def _sweep(self) -> None:
        now = time.monotonic()
        for state in [s for s, e in self._entries.items() if self._expired(e, now)]:
            del self._entries[state]

    def register(self, entry: BrowserLoginEntry) -> None:
        """Store a pending login; sweeps expired entries first."""
        # FILL IN: raise ValueError unless _STATE_RE.fullmatch(entry.state) — bounded by spec M2
        # ("register accepts only states generated with BROWSER_STATE_PREFIX + token_urlsafe(32)").
        self._sweep()
        self._entries[entry.state] = entry

    def consume(self, state: str) -> Optional[BrowserLoginEntry]:
        """Pop and return the entry (single-use); None if unknown or expired. Never awaits."""
        # FILL IN: pop first, then return None if expired — no await anywhere (atomic in asyncio).

    def peek(self, state: str) -> Optional[BrowserLoginEntry]:
        """Non-destructive lookup; never use a miss to select legacy routing."""
        # FILL IN: return the live (non-expired) entry or None, without removing it.

    def __len__(self) -> int:
        return len(self._entries)


def get_or_create_browser_login_registry(app: MutableMapping[str, Any]) -> BrowserLoginRegistry:
    """Return the app-scoped registry, creating it under BROWSER_LOGIN_APP_KEY."""
    registry = app.get(BROWSER_LOGIN_APP_KEY)
    if registry is None:
        registry = BrowserLoginRegistry()
        app[BROWSER_LOGIN_APP_KEY] = registry
    return registry
```
**Why**: Names, key strings and the TTL are fixed by spec §3 M2. The `peek` docstring
carries the spec's routing warning verbatim.

### `browser_login.py` (CREATE — block 2/3, append after block 1)
```python
class VerifiedBrowserIdentity(BaseModel):
    """Identity proven by a server-side verifier (never by browser JSON)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str
    display_name: Optional[str] = None
    email: Optional[str] = None


class BrowserVerificationError(Exception):
    """The credential or identity was rejected (maps to HTTP 401)."""


class BrowserVerifierUnavailableError(Exception):
    """The verifier or its backend could not answer (maps to HTTP 503)."""


@runtime_checkable
class BrowserIdentityVerifier(Protocol):
    """Server-owned verifier bound to one issuer, audience/application and tenant."""

    async def verify(
        self,
        token: str,
        *,
        auth_method: str,
        bot_id: str,
        tenant_id: Optional[str],
    ) -> VerifiedBrowserIdentity:
        """Return the verified identity or raise one of the two typed errors."""
        ...


def register_browser_identity_verifier(
    app: MutableMapping[str, Any],
    *,
    bot_id: str,
    auth_method: str,
    verifier: BrowserIdentityVerifier,
) -> None:
    """Register ``verifier`` under app[BROWSER_VERIFIERS_APP_KEY][bot_id][auth_method]."""
    # FILL IN: reject auth_method not in PAGE_AUTH_METHODS (ValueError); setdefault the
    # two nested dicts; overwrite is allowed (host wiring wins when it runs later).


def get_browser_identity_verifier(
    app: Optional[MutableMapping[str, Any]],
    *,
    bot_id: str,
    auth_method: str,
) -> Optional[BrowserIdentityVerifier]:
    """Return the registered verifier, or None when app/bot/method has none."""
    # FILL IN: tolerate app None and missing nested keys; never raise.
```
**Why**: Spec §2 fixes the `verify(token, *, auth_method, bot_id, tenant_id)` contract,
the three result fields and the app map path. No caller-supplied identity field is a
parameter of `verify` — keep it that way.

### `browser_login.py` (CREATE — block 3/3, append after block 2)
```python
_TG_USERNAME_RE = re.compile(r"[A-Za-z0-9_]{5,32}")


def telegram_deep_link(bot_username: Optional[str]) -> Optional[str]:
    """Return ``https://t.me/<bot_username>`` for a valid username, else None."""
    if bot_username and _TG_USERNAME_RE.fullmatch(bot_username):
        return f"https://t.me/{bot_username}"
    return None


def render_browser_success(bot_username: Optional[str], display_name: str) -> str:
    """HTML success page with a t.me deep link back to the chat."""
    # FILL IN: self-contained page (inline CSS, no external scripts). Escape
    # display_name with html_mod.escape; include an <a href> to telegram_deep_link(...)
    # only when it is not None, otherwise a "return to Telegram" sentence. Bounded by
    # spec AC "success page contains the https://t.me/<bot_username> deep link".


def render_browser_error(message: str) -> str:
    """HTML error page (no auth data echoed back)."""
    # FILL IN: same shell as the success page; html_mod.escape(message); a hint to send
    # /login again. Never interpolate request parameters other than ``message``.
```
**Why**: Spec M2 interfaces. Pages are rendered by TASK-5424/5425, so keep the
signatures exact.

### `packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login.py` (CREATE)
```python
"""FEAT-854: browser-mode login registry, state format, verifier contract and pages."""
import time

import pytest

from parrot.integrations.telegram.browser_login import (
    BROWSER_LOGIN_APP_KEY,
    BrowserLoginEntry,
    BrowserLoginRegistry,
    VerifiedBrowserIdentity,
    get_browser_identity_verifier,
    get_or_create_browser_login_registry,
    is_browser_state,
    new_browser_state,
    register_browser_identity_verifier,
    render_browser_error,
    render_browser_success,
    telegram_deep_link,
)


def _entry(state: str, created_at: float | None = None) -> BrowserLoginEntry:
    return BrowserLoginEntry(
        state=state, telegram_id=1, chat_id=1, bot_id="7001",
        bot_username="parrot_test_bot",
        created_at=time.monotonic() if created_at is None else created_at,
    )


def test_new_browser_state_format():
    state = new_browser_state()
    assert is_browser_state(state) and len(state) == len("browser.") + 43


def test_registry_register_consume_single_use():
    # FILL IN: register -> consume returns entry -> second consume returns None


def test_registry_ttl_expiry():
    # FILL IN: entry with created_at = time.monotonic() - 601 -> consume/peek return None


def test_registry_rejects_non_browser_state():
    # FILL IN: legacy secrets.token_urlsafe(32) state -> ValueError


def test_registry_accessor_is_app_scoped():
    # FILL IN: two calls on the same dict return the same object under BROWSER_LOGIN_APP_KEY


def test_verifier_registry_lookup():
    # FILL IN: register a dummy verifier for ("7001", "basic"); lookup hits; other bot/method
    # and app=None return None; method "oauth2" is rejected with ValueError


def test_verified_identity_forbids_extra_fields():
    # FILL IN: VerifiedBrowserIdentity(user_id="1", verified=True) raises pydantic ValidationError


def test_success_page_has_deep_link_and_escapes():
    # FILL IN: render_browser_success("parrot_test_bot", "<b>x</b>") contains
    # "https://t.me/parrot_test_bot" and no raw "<b>"; telegram_deep_link("bad name!") is None


def test_error_page_escapes_message():
    # FILL IN: render_browser_error("<script>") contains "&lt;script&gt;"
```

### FILL IN checklist
- [ ] `BrowserLoginRegistry.register` — strict state format; spec M2
- [ ] `BrowserLoginRegistry.consume` / `peek` — sync pop + TTL; spec M2 concurrency rule
- [ ] `register_browser_identity_verifier` / `get_browser_identity_verifier` — nested app map; spec §2
- [ ] `render_browser_success` / `render_browser_error` — escaped, no tokens, deep link
- [ ] test bodies

---

## Acceptance Criteria

- [ ] `from parrot.integrations.telegram.browser_login import BrowserLoginRegistry, BROWSER_COMPLETE_PATH, VerifiedBrowserIdentity` works.
- [ ] `browser_login.py` imports nothing from `auth.py` / `wrapper.py`.
- [ ] Registry is single-use, TTL-bound (600 s) and rejects non-`browser.` states.
- [ ] Success page contains `https://t.me/<bot_username>`; pages escape all input.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login.py -q`

---

## Test Specification

See the test block above (spec §4 rows `test_registry_register_consume_single_use`,
`test_registry_ttl_expiry`).

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
9. **Close the task** with `parrot sdd task close TASK-5418 telegram-auth-open-mode verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seat gpt-5.6-sol (codex), attempt 1, 214s
**Date**: 2026-11-09
**Notes**: Created browser_login.py (registry, state, verifier contract, result pages) and test_browser_login.py. Merge-tier validation green (50 passed, chunk 0). Delivery diff reviewed against task file list: no out-of-scope files. No review fixes.

**Deviations from spec**: none
