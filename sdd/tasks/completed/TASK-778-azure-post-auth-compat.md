# TASK-778: AzureAuthStrategy Post-Auth Chain Compatibility

**Feature**: FEAT-109 — Telegram Multi-Auth Negotiation
**Spec**: `sdd/specs/FEAT-109-telegram-multi-auth-negotiation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S-M (2-3h)
**Depends-on**: TASK-777
**Assigned-to**: unassigned

---

## Context

Today only `BasicAuthStrategy` participates in FEAT-108's
`post_auth_actions` redirect chain — `AzureAuthStrategy` ignores the
`next_auth_url` / `next_auth_required` kwargs and its
`handle_callback` never invokes the chained providers. For
`CompositeAuthStrategy` (TASK-779) to be useful when the primary
method is Azure, the chain must work from Azure too.

This task teaches Azure to carry `next_auth_url` /
`next_auth_required` across the Microsoft round-trip (using the same
`preserveParams` pattern `azure_login.html:205-213` already uses for
`azure_auth_url`) and to kick the FEAT-108 chain after JWT
validation.

Implements **Module 2** of the spec.

---

## Scope

- `AzureAuthStrategy.build_login_keyboard` (`auth.py:402`) accepts
  `next_auth_url: Optional[str] = None` and
  `next_auth_required: bool = False`. When set, both are embedded in
  the query string passed to `azure_login.html` so the page preserves
  them across the redirect to Microsoft and back.
- `AzureAuthStrategy.handle_callback` (`auth.py:440`) invokes the
  FEAT-108 post_auth chain on success — same pattern as
  `BasicAuthStrategy`'s callback. Reuse the wrapper's chain helper
  (`TelegramAgentWrapper._run_post_auth_chain` or equivalent) — do
  NOT duplicate its logic.
- Flip `AzureAuthStrategy.supports_post_auth_chain` to `True`.
- `static/telegram/azure_login.html` preserves `next_auth_url` /
  `next_auth_required` on the outbound Navigator-Azure redirect and
  on the inbound token-callback redirect, mirroring how it already
  preserves `azure_auth_url`.

**NOT in scope**:
- `CompositeAuthStrategy` — TASK-779.
- Capability-flag gate in wrapper — TASK-782.
- Changes to `BasicAuthStrategy` — TASK-777 already touched it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/auth.py` | MODIFY | Azure `build_login_keyboard` accepts new kwargs; `handle_callback` invokes post_auth chain; capability flag flipped |
| `static/telegram/azure_login.html` | MODIFY | Preserve `next_auth_url` / `next_auth_required` across redirects |
| `packages/ai-parrot/tests/integrations/telegram/test_azure_post_auth.py` | CREATE | Tests for kwargs propagation + chain invocation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# auth.py already imports what we need:
from urllib.parse import urlencode
from typing import Any, Dict, Optional
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, WebAppInfo
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/integrations/telegram/auth.py

class AzureAuthStrategy(AbstractAuthStrategy):                  # line 374
    def __init__(                                                # line 390
        self, auth_url: str, azure_auth_url: str,
        login_page_url: Optional[str] = None,
    ) -> None: ...
    async def build_login_keyboard(                             # line 402
        self, config: Any, state: str,
    ) -> ReplyKeyboardMarkup: ...
    async def handle_callback(                                  # line 440
        self, data: Dict[str, Any], session: TelegramUserSession,
    ) -> bool: ...
```

```python
# packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py
class TelegramAgentWrapper:
    # The FEAT-108 post_auth chain helper — verify its current name by
    # grepping for "_post_auth_registry" uses. Today BasicAuthStrategy
    # does NOT call it directly; the wrapper drives the chain before
    # build_login_keyboard. Azure will need the wrapper to expose a
    # helper, OR the Azure callback will need to call
    # self._post_auth_registry.execute(...) via a back-reference.
    #
    # RECOMMENDED DESIGN: strategies receive the registry at __init__
    # (as an optional kwarg) so handle_callback can trigger the chain
    # without a circular import to the wrapper. Concrete wiring is
    # decided by the agent during implementation.
```

### azure_login.html preserveParams pattern

```html
<!-- static/telegram/azure_login.html:205-213 (existing pattern):
     The page builds a redirect URL that preserves azure_auth_url
     across the Microsoft round-trip. Extend the same dict to
     include next_auth_url and next_auth_required. -->
var preserveParams = new URLSearchParams();
preserveParams.set('azure_auth_url', azureUrl);
var redirectUrl = pageBase + '?' + preserveParams.toString();
```

### Does NOT Exist

- ~~`AzureAuthStrategy` already supports `next_auth_url`~~ — no, only
  BasicAuth does today (TASK-777 lifted the kwarg into the abstract
  signature as a no-op for Azure; this task wires the behavior).
- ~~`azure_login.html` receives `next_auth_url`~~ — not today; added
  in this task.
- ~~`AzureAuthStrategy.handle_callback` calls post_auth chain~~ —
  not today; added in this task.

---

## Implementation Notes

### Wiring the post_auth chain into AzureAuthStrategy

Two viable approaches. Pick one and document it:

**A)** Pass the `PostAuthRegistry` into `AzureAuthStrategy.__init__`
as an optional kwarg. The wrapper does the injection when it
instantiates the strategy (TASK-781 already has to refactor the
construction path; having `AzureAuthStrategy(registry=...)` is
clean).

**B)** Put the chain execution back on the wrapper by having
`AzureAuthStrategy.handle_callback` return an enriched result
(instead of bool) that includes `auth_method`, `user_id`, etc., so
the wrapper can run the chain centrally.

Approach **A** is preferred — the strategy owns its callback,
including post-auth. The wrapper stays thin. Make sure the registry
is optional so tests and single-method-non-chain setups don't break.

### URL preservation in azure_login.html

Today the preservation at line 205-213 is:
```js
var preserveParams = new URLSearchParams();
preserveParams.set('azure_auth_url', azureUrl);
```

After this task:
```js
var preserveParams = new URLSearchParams();
preserveParams.set('azure_auth_url', azureUrl);
if (nextAuthUrl) preserveParams.set('next_auth_url', nextAuthUrl);
if (nextAuthRequired) preserveParams.set('next_auth_required', 'true');
```

Where `nextAuthUrl` / `nextAuthRequired` come from
`params.get('next_auth_url')` / `params.get('next_auth_required')`
at the top of the script.

---

## Acceptance Criteria

- [ ] `AzureAuthStrategy.build_login_keyboard` accepts
      `next_auth_url` / `next_auth_required` kwargs and embeds them
      in the WebApp URL when set.
- [ ] `AzureAuthStrategy.supports_post_auth_chain is True`.
- [ ] `AzureAuthStrategy.handle_callback` invokes the post_auth
      chain (via registry injected at construction or equivalent).
- [ ] `azure_login.html` preserves `next_auth_url` /
      `next_auth_required` across both the outbound redirect to
      Navigator and the inbound token callback.
- [ ] Tests prove `next_auth_url` propagation end-to-end.
- [ ] All existing Telegram tests still pass.

---

## Test Specification (sketch)

```python
# tests/integrations/telegram/test_azure_post_auth.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.integrations.telegram.auth import AzureAuthStrategy


@pytest.mark.asyncio
async def test_build_login_keyboard_embeds_next_auth_url():
    strat = AzureAuthStrategy(
        auth_url="https://h/api/v1/login",
        azure_auth_url="https://h/api/v1/auth/azure/",
        login_page_url="https://h/static/telegram/azure_login.html",
    )
    kb = await strat.build_login_keyboard(
        config=MagicMock(login_page_url=None),
        state="nonce",
        next_auth_url="https://jira.example.com/oauth/authorize?x=y",
        next_auth_required=True,
    )
    url = kb.keyboard[0][0].web_app.url
    assert "next_auth_url=https" in url
    assert "next_auth_required=true" in url


@pytest.mark.asyncio
async def test_handle_callback_triggers_post_auth_chain():
    registry = MagicMock()
    registry.execute = AsyncMock(return_value=None)
    strat = AzureAuthStrategy(
        auth_url="https://h/api/v1/login",
        azure_auth_url="https://h/api/v1/auth/azure/",
        post_auth_registry=registry,  # injection per approach A
    )
    session = MagicMock()
    ok = await strat.handle_callback(
        {"auth_method": "azure", "token": "<fake-jwt>"},
        session,
    )
    assert ok is True
    registry.execute.assert_awaited_once()


def test_capability_flag_is_true():
    assert AzureAuthStrategy.supports_post_auth_chain is True
```

---

## Agent Instructions

1. Read the spec and TASK-777 completion to see how the capability
   flag was introduced.
2. Decide Approach A vs B for the registry wiring; document in the
   completion note.
3. Verify `azure_login.html`'s preservation block is still at the
   lines noted above; update if it moved.
4. Implement + test + commit.

---

## Completion Note

*(Agent fills this in when done)*
