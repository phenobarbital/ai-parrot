---
type: Wiki Overview
title: 'Feature Specification: Telegram Multi-Auth Negotiation'
id: doc:sdd-specs-feat-109-telegram-multi-auth-negotiation-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: (`BasicAuthStrategy` | `AzureAuthStrategy` | `OAuth2AuthStrategy`) at
relates_to:
- concept: mod:parrot.integrations.telegram
  rel: mentions
---

# Feature Specification: Telegram Multi-Auth Negotiation

**Feature ID**: FEAT-109
**Date**: 2026-04-20
**Author**: Jesus / Claude
**Status**: approved
**Target version**: 0.9.1

---

## 1. Motivation & Business Requirements

### Problem Statement

`TelegramAgentWrapper` selects ONE authentication strategy
(`BasicAuthStrategy` | `AzureAuthStrategy` | `OAuth2AuthStrategy`) at
construction time based on a single-valued `auth_method` field in
`integrations_bots.yaml`:

```python
# wrapper.py:103-119 (today)
if config.auth_method == "azure" and config.azure_auth_url:
    self._auth_strategy = AzureAuthStrategy(...)
elif config.auth_method == "oauth2" and config.oauth2_client_id:
    self._auth_strategy = OAuth2AuthStrategy(config)
elif config.auth_url:
    self._auth_strategy = BasicAuthStrategy(config.auth_url, config.login_page_url)
```

This collapses the user's options to whatever the bot owner wired up
ahead of time. Consequences:

- **User experience is rigid**. A bot deployed for a mixed-identity
  audience (internal AAD users + external basic-auth accounts) forces
  the admin to pick one and exclude the other.
- **Page proliferation**. Each strategy ships its own HTML
  (`static/telegram/login.html`, `static/telegram/azure_login.html`)
  and its own query-param contract. There is no shared chooser.
- **Post-auth coupling is method-specific**. FEAT-108's
  `post_auth_actions` redirect chain is hardcoded to
  `isinstance(self._auth_strategy, BasicAuthStrategy)` at
  `wrapper.py:1021`, so the combined Telegram → Jira flow is only
  available when the primary method happens to be BasicAuth.

Navigator's backend already exposes both authentication endpoints
side-by-side (`/api/v1/login`, `/api/v1/auth/azure/`). The capability
exists on the server — the Telegram integration just refuses to offer
both at once.

### Goals

- A single Telegram WebApp page (`login_multi.html`) renders **all**
  configured authentication options as buttons; the user chooses at
  login time.
- `integrations_bots.yaml` accepts a list form — `auth_methods: [basic,
  azure]` — while keeping the existing `auth_method: "basic"` as a
  backward-compatible singleton.
- A new `CompositeAuthStrategy` bundles the per-method strategies and
  dispatches `handle_callback` to the correct one based on the
  `auth_method` key in the WebApp `sendData` payload.
- The FEAT-108 `post_auth_actions` redirect chain works from any
  primary method that supports it (BasicAuth and Azure at launch;
  OAuth2 later), via a `supports_post_auth_chain` capability flag on
  `AbstractAuthStrategy` — replacing the `isinstance(...,
  BasicAuthStrategy)` gate.
- Existing single-method deployments (`auth_method: "basic"` /
  `"azure"` / `"oauth2"`) continue to work unchanged.

### Non-Goals (explicitly out of scope)

- Dynamic discovery of available methods from Navigator at runtime
  (e.g., a `/api/v1/auth/options` endpoint). The admin still declares
  the methods in YAML; the page only renders what it was told.
- Splitting the strategy pattern across other channels (MS Teams,
  Slack, AgenTalk). Multi-auth is Telegram-only for this feature.
- Per-user persistent preference ("always sign me in with Azure"). The
  chooser is stateless each session.
- Reworking `OAuth2AuthStrategy` beyond the capability-flag refactor.
  Enabling it inside Composite is a follow-up.
- Replacing or deprecating `login.html` / `azure_login.html` — both
  stay as opt-in entry points for single-method bots.

---

## 2. Architectural Design

### Overview

Introduce a composite that orchestrates the existing strategies but
owns no callback logic of its own:

```
TelegramAgentWrapper
    └─ self._auth_strategy : AbstractAuthStrategy
           │
           ├── (single)   BasicAuthStrategy   ──→  login.html
           ├── (single)   AzureAuthStrategy   ──→  azure_login.html
           ├── (single)   OAuth2AuthStrategy  ──→  oauth2_login.html
           └── (multi)    CompositeAuthStrategy
                              ├── wraps BasicAuthStrategy
                              ├── wraps AzureAuthStrategy
                              └── renders login_multi.html
                                   (buttons driven by ?auth_url=… &
                                    ?azure_auth_url=… query params)
```

The page contract stays stateless and additive: `login_multi.html`
reads every known auth-URL query param and shows one button per
present value. If the user clicks "Sign in with Azure", the page
behaves exactly like `azure_login.html` for that half of its life —
building a Navigator Azure redirect URL, preserving state, and
posting `tg.sendData({auth_method: "azure", token: …})` on return.
Pick "Sign in to Navigator" and it behaves like `login.html` —
renders the email/password form, posts `tg.sendData({auth_method:
"basic", user_id, token, …})`.

The wrapper's existing callback handler (`wrapper.py:handle_web_app_data`)
keeps calling `self._auth_strategy.handle_callback(data, session)`.
When `self._auth_strategy` is a `CompositeAuthStrategy`, dispatch
happens internally by `data["auth_method"]`.

### Component Diagram

```
    ┌──────────────── Telegram WebApp ────────────────┐
    │       ┌─────────────────────────────┐           │
    │       │   login_multi.html          │           │
    │       │   (chooser w/ N buttons)    │           │
    │       └──────┬──────────────┬───────┘           │
    │              │ basic        │ azure             │
    │              ▼              ▼                   │
    │     [form → POST]   [redirect → callback]       │
    │              │              │                   │
    │              └──────┬───────┘                   │
    │                     │ sendData({auth_method})    │
    └─────────────────────┼──────────────────────────┘
                          │
                          ▼
         ┌──────────────────────────────────────────┐
         │  TelegramAgentWrapper.handle_web_app_data│
         └──────────────────┬───────────────────────┘
                            │
                            ▼
         ┌──────────────────────────────────────────┐
         │    CompositeAuthStrategy.handle_callback │
         │    dispatches by data["auth_method"]     │
         └──────┬───────────────────┬───────────────┘
                │                   │
                ▼                   ▼
         BasicAuthStrategy    AzureAuthStrategy
         .handle_callback     .handle_callback
                │                   │
                └──────────┬────────┘
                           ▼
              post_auth_chain (FEAT-108)
              (capability-gated, not isinstance-gated)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractAuthStrategy` (`auth.py:178`) | extends | Adds `name` class attr + `supports_post_auth_chain` class attr; `build_login_keyboard` grows optional `next_auth_url` / `next_auth_required` kwargs |
| `BasicAuthStrategy` / `AzureAuthStrategy` (`auth.py:238`, `:374`) | modifies | Set capability flags; Azure's `build_login_keyboard` accepts `next_auth_url`/`next_auth_required` (today only Basic does); Azure's `handle_callback` invokes the post_auth chain when applicable |
| `TelegramAgentConfig` (`models.py:79-90`) | extends | New optional `auth_methods: List[str]` field; `auth_method: str` kept for single-method compat; `__post_init__` normalizes to a canonical list |
| `TelegramAgentWrapper.__init__` (`wrapper.py:103`) | refactors | Strategy selection switches from an if/elif chain to `_build_auth_strategy(config)` that returns Composite when `len(auth_methods) > 1` |
| `TelegramAgentWrapper` post_auth chain (`wrapper.py:1021`) | modifies | Replaces `isinstance(self._auth_strategy, BasicAuthStrategy)` with `getattr(self._auth_strategy, "supports_post_auth_chain", False)` — or, for Composite, an "any member supports it" collapse |
| `integrations_bots.yaml` loader (`models.py:from_dict`) | modifies | Accepts `auth_methods` as a list OR string; validates each entry against the known set |
| `static/telegram/login_multi.html` | creates | New HTML page; receives `?auth_url` + `?azure_auth_url` (+ future params); renders one button per non-empty param |

### Data Models

```python
# parrot/integrations/telegram/models.py — additions

# TelegramAgentConfig gains:
auth_methods: List[str] = field(default_factory=list)
# Derived from YAML. Empty means "fall back to legacy auth_method".
# Canonical values: "basic", "azure", "oauth2".

# After __post_init__ normalization, exactly one of these invariants
# holds:
#   - auth_methods == []          → legacy single-method mode (auth_method)
#   - len(auth_methods) == 1      → single-method, new-style config
#   - len(auth_methods) >= 2      → multi-method, CompositeAuthStrategy
```

### New Public Interfaces

```python
# parrot/integrations/telegram/auth.py

class AbstractAuthStrategy(ABC):
    #: Canonical short name used by the WebApp to tag callbacks
    #: (data["auth_method"]). Must match the value the config uses.
    name: str = "abstract"

    #: True if this strategy can carry a FEAT-108 post_auth redirect chain
    #: through its login flow. Replaces wrapper.py's isinstance(BasicAuthStrategy) gate.
    supports_post_auth_chain: bool = False

    @abstractmethod
    async def build_login_keyboard(
        self,
        config: Any,
        state: str,
        *,
        next_auth_url: Optional[str] = None,
        next_auth_required: bool = False,
    ) -> ReplyKeyboardMarkup: ...


class CompositeAuthStrategy(AbstractAuthStrategy):
    """Groups multiple strategies and dispatches by callback payload.

    ``build_login_keyboard`` emits a single WebApp button pointing to
    ``login_multi.html`` with one query-param per member strategy.
    ``handle_callback`` reads ``data['auth_method']`` and delegates to
    the matching member.
    """
    name = "composite"

    def __init__(
        self,
        strategies: Dict[str, AbstractAuthStrategy],
        login_page_url: str,
    ) -> None: ...

    @property
    def supports_post_auth_chain(self) -> bool:
        # True iff every member supports the chain, so the wrapper can
        # safely build next_auth_url without introspecting which member
        # the user will actually pick.
        ...
```

---

## 3. Module Breakdown

### Module 1: AbstractAuthStrategy capability refactor
- **Path**: `packages/ai-parrot/src/parrot/integrations/telegram/auth.py`
- **Responsibility**: Add `name` + `supports_post_auth_chain` class
  attributes; lift `next_auth_url` / `next_auth_required` kwargs from
  `BasicAuthStrategy.build_login_keyboard` onto the abstract base (as
  optional kwargs ignored by strategies that don't support them).
  Concrete classes override `name` ("basic", "azure", "oauth2") and
  set `supports_post_auth_chain` explicitly.
- **Depends on**: existing auth.py

### Module 2: AzureAuthStrategy post_auth compatibility
- **Path**: `packages/ai-parrot/src/parrot/integrations/telegram/auth.py`
- **Responsibility**: `AzureAuthStrategy.build_login_keyboard` accepts
  `next_auth_url` / `next_auth_required`; forwards them in the
  `azure_auth_url` query string so `azure_login.html` can preserve
  them across the Microsoft round-trip (same preservation trick it
  already uses for `azure_auth_url`). `handle_callback` invokes the
  FEAT-108 post_auth chain on success. Sets
  `supports_post_auth_chain = True`.
- **Depends on**: Module 1

### Module 3: CompositeAuthStrategy
- **Path**: `packages/ai-parrot/src/parrot/integrations/telegram/auth.py`
- **Responsibility**: New class. Holds `strategies: dict[str, AbstractAuthStrategy]`
  keyed by `.name`. `build_login_keyboard` mounts a WebApp button to
  `login_multi.html` with query params: `auth_url=…` (from Basic),
  `azure_auth_url=…` (from Azure), etc. `handle_callback` reads
  `data["auth_method"]`, delegates to the matching member, forwards
  the `session` through. `validate_token` delegates to the strategy
  whose name matches the session's stored `auth_method`.
- **Depends on**: Module 1, Module 2

### Module 4: TelegramAgentConfig.auth_methods
- **Path**: `packages/ai-parrot/src/parrot/integrations/telegram/models.py`
- **Responsibility**: Add `auth_methods: List[str]` field (default
  empty). Extend `__post_init__` to:
  1. If `auth_methods` is empty and `auth_method` is set → normalize
     to `[auth_method]`.
  2. Validate every entry against `{"basic", "azure", "oauth2"}`.
  3. Resolve each method's env-var requirements as today (Azure URL
     derivation, OAuth2 client id/secret).
  `from_dict` accepts `auth_methods` either as a list or a string
  (converted to list of one).
- **Depends on**: existing models.py

### Module 5: Wrapper strategy selection refactor
- **Path**: `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py`
- **Responsibility**: Extract lines 103-119 into
  `_build_auth_strategy(config) -> Optional[AbstractAuthStrategy]`.
  Logic:
  - `len(config.auth_methods) == 0` → `None` (auth disabled).
  - `len(config.auth_methods) == 1` → build that single strategy
    (current behavior).
  - `len(config.auth_methods) >= 2` → build each member and wrap in
    `CompositeAuthStrategy`. `login_page_url` MUST point to
    `login_multi.html`; validate and error loud if it still points to
    a single-method page.
- **Depends on**: Module 3, Module 4

### Module 6: Post_auth capability gating
- **Path**: `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py`
- **Responsibility**: Replace `isinstance(self._auth_strategy,
  BasicAuthStrategy)` at `wrapper.py:1021` with
  `getattr(self._auth_strategy, "supports_post_auth_chain", False)`.
  For `CompositeAuthStrategy`, the property returns True iff every
  member supports it — the wrapper pre-computes the `next_auth_url`
  once and the composite forwards it to every member's
  `build_login_keyboard`.
- **Depends on**: Module 1, Module 5

### Module 7: `login_multi.html`
- **Path**: `static/telegram/login_multi.html`
- **Responsibility**: Stateless HTML page. On load:
  1. Parse URL query: `auth_url`, `azure_auth_url`, `next_auth_url`,
     `next_auth_required`, plus the Azure redirect-back `token`.
  2. If `token` is present → behave exactly like `azure_login.html`'s
     token-callback path, posting `{auth_method: "azure", token}`.
  3. Otherwise render a button for each non-empty auth URL:
     - `auth_url` → "🔐 Sign in to Navigator" — reveals the
       email/password form identical to `login.html`.
     - `azure_auth_url` → "🪟 Sign in with Azure" — identical to
       `azure_login.html`'s redirect flow.
  4. Each click path forwards `next_auth_url` /
     `next_auth_required` across redirects so FEAT-108 continues to
     work.
- **Depends on**: None (pure static file)

### Module 8: Validation + documentation
- **Path**: `packages/ai-parrot/src/parrot/integrations/telegram/models.py`
  + `env/integrations_bots.yaml` example
- **Responsibility**: `TelegramBotsConfig.validate()` grows rules for
  `auth_methods`:
  - Every entry must be one of `{"basic", "azure", "oauth2"}`.
  - `"azure"` requires `azure_auth_url` (or successful derivation).
  - `"oauth2"` requires `oauth2_client_id` / `oauth2_client_secret`.
  - If `len(auth_methods) >= 2`, `login_page_url` MUST end with
    `login_multi.html` (case-insensitive substring) — otherwise emit
    a clear error telling the admin which file to reference.
- **Depends on**: Module 4

### Module 9: Tests
- **Path**: `packages/ai-parrot/tests/integrations/telegram/`
- **Responsibility**:
  - Unit — `CompositeAuthStrategy.handle_callback` dispatches by
    `data["auth_method"]`; unknown method → returns False with a log;
    `build_login_keyboard` emits all configured query params.
  - Unit — `supports_post_auth_chain` property collapse; wrapper's
    post_auth decision now uses capability instead of isinstance.
  - Unit — `TelegramAgentConfig` normalization (string vs list, env
    var derivation, validation errors).
  - Integration — a synthetic Telegram message exercising
    `handle_web_app_data` with `{auth_method: "azure", token: "..."}`
    through a Composite reaches `AzureAuthStrategy.handle_callback`
    with the session populated.
- **Depends on**: Modules 1-6

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_abstract_strategy_defaults_name_and_chain_flag` | M1 | Base class exposes `name` and `supports_post_auth_chain` class attrs |
| `test_basic_strategy_declares_post_auth_support` | M1 | `BasicAuthStrategy.supports_post_auth_chain is True` and `name == "basic"` |
| `test_azure_strategy_forwards_next_auth_url` | M2 | `build_login_keyboard(next_auth_url="X")` embeds it in the built URL |
| `test_azure_callback_triggers_post_auth_chain` | M2 | On successful JWT validation, the registered post_auth provider is invoked |
| `test_composite_build_login_keyboard_emits_all_urls` | M3 | Both `auth_url` and `azure_auth_url` appear as query params |
| `test_composite_handle_callback_dispatches_by_method` | M3 | `{auth_method: "azure"}` reaches AzureAuthStrategy; `{auth_method: "basic"}` reaches BasicAuthStrategy |
| `test_composite_handle_callback_unknown_method_returns_false` | M3 | Unknown `auth_method` logs a warning and returns False |
| `test_composite_supports_post_auth_chain_all_members` | M3 | True iff every member supports it |
| `test_config_auth_methods_from_list` | M4 | `auth_methods: [basic, azure]` parses into two entries |
| `test_config_auth_methods_from_legacy_string` | M4 | `auth_method: "basic"` normalizes to `auth_methods=["basic"]` |
| `test_config_validate_multi_requires_login_multi_html` | M8 | Missing `login_multi.html` in page url → validation error |
| `test_wrapper_picks_composite_for_multi` | M5 | `len(auth_methods) == 2` → `isinstance(self._auth_strategy, CompositeAuthStrategy)` |
| `test_wrapper_post_auth_uses_capability_flag` | M6 | Strategy with `supports_post_auth_chain = True` but not a BasicAuth subclass still gets the redirect chain |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_multi_auth_basic_path` | Inject a Telegram message simulating BasicAuth sendData, verify session + post_auth chain fire |
| `test_end_to_end_multi_auth_azure_path` | Same but with `{auth_method: "azure", token: "<fake>"}` + mocked Navigator validator |
| `test_single_method_deployments_unchanged` | Load a legacy YAML with only `auth_method: azure` — wrapper still picks `AzureAuthStrategy` directly (no Composite) |

### Test Data / Fixtures

```python
@pytest.fixture
def multi_auth_config() -> TelegramAgentConfig:
    return TelegramAgentConfig(
        name="JiraTroc",
        chatbot_id="jira_specialist",
        bot_token="fake",
        auth_methods=["basic", "azure"],
        auth_url="https://host/api/v1/login",
        azure_auth_url="https://host/api/v1/auth/azure/",
        login_page_url="https://host/static/telegram/login_multi.html",
        enable_login=True,
        force_authentication=True,
    )
```

---

## 5. Acceptance Criteria

- [ ] `auth_methods: [basic, azure]` in YAML produces a working
      `/login` that opens `login_multi.html` with both buttons.
- [ ] Clicking "Sign in to Navigator" in `login_multi.html` completes
      a BasicAuth login and populates the user session identically to
      `auth_method: basic` today.
- [ ] Clicking "Sign in with Azure" completes an Azure SSO login
      (redirect round-trip through Microsoft) and populates the
      session identically to `auth_method: azure` today.
- [ ] `post_auth_actions` (FEAT-108 Jira chain) fires after BasicAuth
      AND after Azure when at least one matching action is configured.
- [ ] `auth_method: basic` / `auth_method: azure` / `auth_method:
      oauth2` YAMLs that worked before this feature continue to work
      byte-for-byte (no Composite wrapping).
- [ ] Config validator rejects `auth_methods: [basic, azure]` if
      `login_page_url` does not reference `login_multi.html`.
- [ ] `pytest packages/ai-parrot/tests/integrations/telegram/ -v` green.
- [ ] `wrapper.py` no longer contains `isinstance(..., BasicAuthStrategy)`
      for the post_auth gate.
- [ ] Documentation: `env/integrations_bots.yaml` header comments
      updated with a `auth_methods: [basic, azure]` example.

---

## 6. Codebase Contract

> Anchored to the code at commit `e0a514d6` (`dev`). Every entry has
> been verified with `read` / `grep` below. Agents MUST NOT import or
> reference anything outside this contract without first verifying it.

### Verified Imports

```python
# From parrot/integrations/telegram/auth.py (verified in situ):
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from urllib.parse import urlencode
from aiogram.types import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

# From parrot/integrations/telegram/wrapper.py (verified):
from .auth import (
    AbstractAuthStrategy,
    AzureAuthStrategy,
    BasicAuthStrategy,
    OAuth2AuthStrategy,
    TelegramUserSession,
)
from .post_auth import PostAuthRegistry

# From parrot/integrations/telegram/models.py (verified):
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from navconfig import config
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/integrations/telegram/auth.py
class AbstractAuthStrategy(ABC):                                # line 178
    async def build_login_keyboard(                             # line 188
        self, config: Any, state: str,
    ) -> ReplyKeyboardMarkup: ...
    async def handle_callback(                                  # line 205
        self, data: Dict[str, Any], session: TelegramUserSession,
    ) -> bool: ...
    async def validate_token(self, token: str) -> bool: ...     # line 222

class BasicAuthStrategy(AbstractAuthStrategy):                  # line 238
    async def build_login_keyboard(                             # line 261
        self, config: Any, state: str, *,
        next_auth_url: Optional[str] = None,
        next_auth_required: bool = False,
    ) -> ReplyKeyboardMarkup: ...
    async def handle_callback(                                  # line 313
        self, data: Dict[str, Any], session: TelegramUserSession,
    ) -> bool: ...

class AzureAuthStrategy(AbstractAuthStrategy):                  # line 374
    async def build_login_keyboard(                             # line 402
        self, config: Any, state: str,
    ) -> ReplyKeyboardMarkup: ...
    async def handle_callback(                                  # line 440
        self, data: Dict[str, Any], session: TelegramUserSession,
    ) -> bool: ...

class OAuth2AuthStrategy(AbstractAuthStrategy):                 # line 577
    async def build_login_keyboard(                             # line 667
        self, config: Any, state: str,
    ) -> ReplyKeyboardMarkup: ...
    async def handle_callback(                                  # line 714
        self, data: Dict[str, Any], session: TelegramUserSession,
    ) -> bool: ...


# packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py
class TelegramAgentWrapper:
    # Strategy selection block at lines 103-119 (verified in situ).
    # Post-auth isinstance gate at line 1021 (verified).
    # handle_login at line 992; handle_web_app_data elsewhere in the file.


# packages/ai-parrot/src/parrot/integrations/telegram/models.py
@dataclass
class TelegramAgentConfig:
    auth_url: Optional[str]          # line 75
    login_page_url: Optional[str]    # line 76
    enable_login: bool = True        # line 77
    auth_method: str = "basic"       # line 81
    azure_auth_url: Optional[str] = None  # line 89
    post_auth_actions: List[PostAuthAction] = field(default_factory=list)  # line 93
    def __post_init__(self): ...     # line 95
    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'TelegramAgentConfig': ...  # line 143

@dataclass

…(truncated)…
