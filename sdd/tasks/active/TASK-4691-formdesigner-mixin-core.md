# TASK-4691: TeamsFormDesignerMixin: commands, serving, toolkit wiring (M4 part 1)

**Feature**: FEAT-734 — Serve FormDesigner forms from a Teams agent
**Spec**: `sdd/specs/formdesigner-serve-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-4682, TASK-4683, TASK-4684, TASK-4686, TASK-4687, TASK-4688, TASK-4689, TASK-4690
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 4**, first half: the `TeamsFormDesignerMixin` that makes
`class MyAgent(TeamsFormDesignerMixin, Agent)` serve forms. This task builds
configuration, identity resolution, the remote/local reader choice, the
`/getform` and `/listforms` commands, `serve_form` (single card or wizard start),
the toolkit contribution, the normal-turn context/flush hooks, and `aclose`.

The card-submission handler (`handle_formdesigner_card`: picker, wizard steps,
terminal submit) is TASK-4692, which extends this same file.

Depends on: TASK-4682 (client), TASK-4683 (identity), TASK-4684 (wizard store),
TASK-4686 (turn context), TASK-4687 (config fields read by `apply_teams_config`),
TASK-4688 (cards), TASK-4689 (toolkit), TASK-4690 (local reader). Wave 3.

**Decisions made at task time (spec gaps, recorded here):**
1. **Attributes are set BEFORE `super().__init__()`.** `Agent.__init__` calls
   `self.agent_tools()` (`agent.py:156`) during construction, so the toolkit
   contribution must already work. (This is the opposite order from
   `SkillRegistryMixin`; it is deliberate.)
2. **`apply_teams_config(config)`** — a NEW getattr-guarded seam the wrapper calls
   at wiring (TASK-4693). It fills only values the constructor left unset from
   `MSTeamsAgentConfig` (`formdesigner_base_url`, `_tenant`, `_public_url`, `_mode`,
   `_api_base_path`, `_render_timeout`, `_submit_timeout`, `_allowed_hosts`,
   `formdesigner_submit_secret` as the signing/verification secret) and reads
   FEAT-733's `formdesigner_tenant_map` with `getattr(config, …, None)` so it
   works before and after FEAT-733 merges. Without it the spec's new config
   fields would never reach the agent.
3. **`formdesigner_serving: ClassVar[bool] = True`** — the marker the wrapper
   checks (`getattr(type(agent), "formdesigner_serving", False) is True`) before
   using any seam. Existing wrapper tests wrap `MagicMock` agents, where a plain
   `getattr(agent, "flush_formdesigner_cards")` returns a non-awaitable mock.
4. **The mixin sends cards itself** (`_fd_send_card`, same body as
   `MessageHandler.send_card`, `handler.py:60`) — the agent has no `send_card`.
5. **1:1 only (spec §1 Non-Goals):** `conversation_type in ("channel", "groupChat")`
   → error card, nothing fetched.
6. `PICKER_ACTION_KEY` is defined in `formdesigner_cards.py` (TASK-4688) and
   re-exported here.

---

## Scope

- Create `formdesigner_mixin.py` with `TeamsFormDesignerMixin`: `__init__`,
  `apply_teams_config`, `bind_teams_identity`, `teams_commands`,
  `handle_getform`, `handle_listforms`, `serve_form`, `agent_tools`,
  `formdesigner_turn`, `flush_formdesigner_cards`, `aclose`, plus private
  `_fd_*` helpers listed in the blueprint.
- Never call `ensure_authenticated()`; read the session only via
  `get_or_create` + `is_expired` on the store injected by `bind_teams_identity`.
- No session/bearer → login card and ZERO reads. No tenant → error card.
- Multi-section forms (`len(form.sections) > 1`) start a wizard (`WizardStore.start`)
  and send section 0 with every `Action.Submit` decorated with the wizard control object.
- Create `tests/msteams/test_formdesigner_serve.py` with the tests listed under Test Specification.

**NOT in scope**: `handle_formdesigner_card` and everything inbound (TASK-4692);
wrapper edits (TASK-4693); Redis wizard state.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_mixin.py` | CREATE | TeamsFormDesignerMixin outbound half |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_serve.py` | CREATE | mixin command/serve/toolkit tests |


---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import aiohttp
from botbuilder.core import CardFactory, TurnContext            # handler.py:4-8 imports these from botbuilder.core
from botbuilder.schema import Activity, ActivityTypes           # handler.py:9
from .formdesigner_cards import (PICKER_ACTION_KEY, PICKER_GET_FORM, append_render_warnings, build_empty_forms_card,
    build_error_card, build_form_not_found_card, build_login_required_card, build_picker_card)   # TASK-4688
from .formdesigner_client import FormDescriptor, FormDesignerClient, FormDesignerError, RenderedCard, parse_form_ref  # TASK-4682
from .formdesigner_identity import (LocalFormAuthorizer, TeamsSessionStoreLike, TenantUnresolved,
    resolve_bearer, resolve_form_tenant)                         # TASK-4683
from .formdesigner_local import LocalFormReader                  # TASK-4690
from .formdesigner_submit import RecentActivityCache             # formdesigner_submit.py:201
from .formdesigner_turn import FormDesignerTurn, active_turn, bind_turn   # TASK-4686
from .formdesigner_wizard import WizardState, WizardStore        # TASK-4684
from .tools.formdesigner import FormDesignerToolkit              # TASK-4689
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/agent.py
        extra_tools = self.agent_tools()                         # line 156 — called INSIDE Agent.__init__
    def agent_tools(self) -> List[AbstractTool]: return []       # line 469

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/handler.py
async def send_card(self, card_data, turn_context) -> None:      # line 60 — body: CardFactory.adaptive_card(card) ->
#   Activity(type=ActivityTypes.message, attachments=[attachment]) -> await turn_context.send_activity(message)

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py (MSTeamsAgentConfig, read via getattr)
#   formdesigner_allowed_hosts (62), formdesigner_submit_secret (64), formdesigner_submit_timeout (65),
#   formdesigner_api_base_path (66); TASK-4687 adds formdesigner_mode/_base_url/_tenant/_public_url/_render_timeout.
#   formdesigner_tenant_map: FEAT-733 (NOT on dev yet) -> getattr(config, "formdesigner_tenant_map", None)

# TurnContext facts used (msteams/wrapper.py precedent)
#   turn_context.activity.conversation.id ; .conversation.conversation_type in ("channel", "groupChat") = group (wrapper.py:754-755)
#   turn_context.activity.channel_data -> dict or object; tenant GUID at ["tenant"]["id"] (auth.py:159-164 reads it the same way)
#   turn_context.activity.text -> raw text, may still contain an <at>mention</at>

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
#   FormSchema.sections (487), .version (484), .published_version (498), .form_uid (482)
```

### Does NOT Exist
- ~~`TeamsFormDesignerMixin`~~, ~~`apply_teams_config`~~, ~~`formdesigner_serving`~~ — created here.
- ~~`Agent.send_card`~~ / ~~`AbstractBot.send_card`~~ — the agent cannot send cards; use `_fd_send_card`.
- ~~`MSTeamsAgentWrapper.send_card`~~ as a method the agent can reach — it is inherited from `MessageHandler` on the wrapper only.
- ~~`MSTeamsAuthStrategy.ensure_authenticated()` usage~~ — FORBIDDEN here (side effect: sends a sign-in card).
- ~~`WizardFormDialog`~~ — not used (spec §2, §7).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_mixin.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/msteams/test_formdesigner_serve.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/handler.py#MessageHandler.send_card",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent.agent_tools"
  ]
}
```

---

## Implementation Notes

- Tenant source is logged on every fetch (`self._fd_logger.info("formdesigner: tenant %s via %s", …)`); never log the bearer.
- `form_version` for wizard state = `form.published_version or form.version` — the same expression `TeamsFormRenderer.build_envelope` uses (`renderers/teams.py:118`), so the terminal envelope matches.
- After a wizard section render, require `rendered.metadata["total_sections"] == len(form.sections)` — guards against a server/schema mismatch.

---

## Implementation Blueprint

### Steps (in order)
1. Part 1: imports, marker, `__init__` (attrs before `super()`), `apply_teams_config`, `bind_teams_identity`, `teams_commands` — *why*: construction must survive `Agent.__init__` calling `agent_tools()`.
2. Part 2: `_fd_identity`, `_fd_reader`, `_fd_send_card`, `_fd_enabled` — *why*: every command and the flush share one identity path.
3. Part 3: commands, `serve_form`, `_fd_decorate_wizard` — *why*: the user-visible behaviour.
4. Part 4: reader proxy, `agent_tools`, `formdesigner_turn`, `flush_formdesigner_cards`, HTTP session, `aclose`.
5. Tests with a plain base class standing in for `Agent`, a fake store and a fake reader injected via the `formdesigner_client=` test seam.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_mixin.py` (CREATE) — part 1
```python
"""TeamsFormDesignerMixin (FEAT-734 M4): serve FormDesigner forms as Adaptive Cards from a Teams agent."""
from __future__ import annotations

import copy
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable, ClassVar, Literal
from urllib.parse import urlparse

import aiohttp
from botbuilder.core import CardFactory, TurnContext
from botbuilder.schema import Activity, ActivityTypes

from .formdesigner_cards import (
    PICKER_ACTION_KEY, PICKER_GET_FORM, append_render_warnings, build_empty_forms_card, build_error_card,
    build_form_not_found_card, build_login_required_card, build_picker_card,
)
from .formdesigner_client import FormDescriptor, FormDesignerClient, FormDesignerError, RenderedCard, parse_form_ref
from .formdesigner_identity import (
    LocalFormAuthorizer, TeamsSessionStoreLike, TenantUnresolved, resolve_bearer, resolve_form_tenant,
)
from .formdesigner_local import LocalFormReader
from .formdesigner_submit import RecentActivityCache
from .formdesigner_turn import FormDesignerTurn, active_turn, bind_turn
from .formdesigner_wizard import WizardState, WizardStore
from .tools.formdesigner import FormDesignerToolkit

__all__ = ["PICKER_ACTION_KEY", "TeamsFormDesignerMixin"]


class TeamsFormDesignerMixin:
    """Adds FormDesigner form serving to a Teams-exposed Agent.  Usage: class MyAgent(TeamsFormDesignerMixin, Agent)."""

    formdesigner_serving: ClassVar[bool] = True  # wrapper seam marker (see TASK-4693)
    formdesigner_mode: Literal["remote", "local"] = "remote"

    def __init__(
        self,
        *args: Any,
        formdesigner_mode: Literal["remote", "local"] | None = None,
        formdesigner_base_url: str | None = None,
        formdesigner_api_base_path: str | None = None,
        formdesigner_public_url: str | None = None,
        formdesigner_signing_secret: str | None = None,
        formdesigner_tenant: str | None = None,
        formdesigner_registry: Any | None = None,
        formdesigner_authorizer: LocalFormAuthorizer | None = None,
        formdesigner_session_store: TeamsSessionStoreLike | None = None,  # TEST seam; wrapper injects the real one
        formdesigner_client: Any | None = None,  # TEST seam: a FormDesignerClient-compatible reader
        **kwargs: Any,
    ) -> None:
        """Set every attribute BEFORE super().__init__ — Agent.__init__ calls agent_tools() (agent.py:156)."""
        self._fd_mode_explicit = formdesigner_mode is not None
        self.formdesigner_mode = formdesigner_mode or type(self).formdesigner_mode
        self._fd_base_url = formdesigner_base_url
        self._fd_api_base_path = formdesigner_api_base_path or "/api/v1"
        self._fd_public_url = formdesigner_public_url
        self._fd_signing_secret = formdesigner_signing_secret
        self._fd_tenant = formdesigner_tenant
        self._fd_registry = formdesigner_registry
        self._fd_authorizer = formdesigner_authorizer
        self._fd_store: TeamsSessionStoreLike | None = formdesigner_session_store
        self._fd_client = formdesigner_client
        self._fd_tenant_map: dict[str, str] = {}
        self._fd_allowed_hosts: list[str] = []
        self._fd_render_timeout = 15.0
        self._fd_submit_timeout = 15.0
        self._fd_http: aiohttp.ClientSession | None = None
        self._fd_wizards = WizardStore()
        self._fd_recent = RecentActivityCache()
        self._fd_logger = logging.getLogger(__name__)
        super().__init__(*args, **kwargs)

    def apply_teams_config(self, config: Any) -> None:
        """Fill values the constructor left unset from MSTeamsAgentConfig (constructor wins)."""
        # FILL IN: for each of base_url/tenant/public_url/signing_secret(<- formdesigner_submit_secret)/api_base_path:
        #   keep the constructor value when set, else getattr(config, "formdesigner_<x>", None);
        #   mode only when not self._fd_mode_explicit; timeouts, allowed_hosts (lower-cased list) and
        #   tenant_map = dict(getattr(config, "formdesigner_tenant_map", None) or {}) always from config.
        raise NotImplementedError

    def bind_teams_identity(self, store: TeamsSessionStoreLike) -> None:
        """Receive the wrapper's single MSTeamsSessionStore (wrapper.py:223); never build our own."""
        self._fd_store = store

    def teams_commands(self) -> dict[str, Callable[[TurnContext], Awaitable[None]]]:
        """Commands that DO receive the TurnContext (unlike config.commands)."""
        return {"getform": self.handle_getform, "listforms": self.handle_listforms}
```
**Why this shape**: constructor kwargs are the spec §3 M4 skeleton plus the `formdesigner_client` test seam (mirrors the spec's own `formdesigner_session_store` test seam). `formdesigner_api_base_path` defaults to `None` so `apply_teams_config` can tell "unset" from "/api/v1".

### `formdesigner_mixin.py` (CREATE) — part 2 (append inside the class)
```python
    def _fd_enabled(self) -> bool:
        if self.formdesigner_mode == "local":
            return self._fd_registry is not None
        return bool(self._fd_base_url) or self._fd_client is not None

    async def _fd_identity(self, turn_context: TurnContext) -> FormDesignerTurn:
        """Read-only identity for this turn: store.get_or_create + is_expired, never an exchange."""
        activity = turn_context.activity
        turn = FormDesignerTurn(conversation_id=activity.conversation.id)
        if getattr(activity.conversation, "conversation_type", None) in ("channel", "groupChat"):
            turn.error = "Forms are only available in 1:1 chats."
            return turn
        if self._fd_store is None:
            turn.login_required = True
            return turn
        session = await self._fd_store.get_or_create(turn_context)
        turn.bearer = resolve_bearer(session, expired=self._fd_store.is_expired(session))
        if not turn.bearer:
            turn.login_required = True
            return turn
        turn.user_id = getattr(session, "nav_user_id", None)
        # FILL IN: asserted = channel_data["tenant"]["id"] (channel_data may be a dict OR an object — handle both, None-safe)
        try:
            resolution = resolve_form_tenant(
                asserted_tenant_id=asserted, session_tenant_id=getattr(session, "tenant_id", None),
                tenant_map=self._fd_tenant_map, config_tenant=self._fd_tenant,
            )
        except TenantUnresolved:
            turn.error = "No forms workspace is configured for your organization."
            return turn
        turn.tenant, turn.tenant_source = resolution.tenant, resolution.source
        self._fd_logger.info("formdesigner: tenant %s via %s", resolution.tenant, resolution.source)
        return turn

    def _fd_reader(self, turn: FormDesignerTurn | None) -> Any:
        """FormDesignerClient (remote) or a per-turn LocalFormReader (local)."""
        if self.formdesigner_mode == "local":
            return LocalFormReader(
                self._fd_registry, authorizer=self._fd_authorizer,
                user_id_resolver=lambda: turn.user_id if turn is not None else None,
                public_base_url=self._fd_public_url, signing_secret=self._fd_signing_secret,
                api_base_path=self._fd_api_base_path,
            )
        if self._fd_client is None:
            if not self._fd_base_url:
                raise FormDesignerError("FormDesigner is not configured", status=500)
            self._fd_client = FormDesignerClient(
                self._fd_base_url, api_base_path=self._fd_api_base_path, timeout=self._fd_render_timeout
            )
        return self._fd_client

    async def _fd_send_card(self, card: dict[str, Any], turn_context: TurnContext) -> None:
        """Same body as MessageHandler.send_card (handler.py:60)."""
        attachment = CardFactory.adaptive_card(card)
        await turn_context.send_activity(Activity(type=ActivityTypes.message, attachments=[attachment]))

    async def _fd_send_turn_problem(self, turn: FormDesignerTurn, turn_context: TurnContext) -> bool:
        """Send the login/error card for an unusable turn; True when one was sent."""
        if turn.login_required:
            await self._fd_send_card(build_login_required_card(), turn_context)
            return True
        if turn.error or not turn.tenant:
            await self._fd_send_card(build_error_card(turn.error or "Forms are unavailable."), turn_context)
            return True
        return False
```

### `formdesigner_mixin.py` (CREATE) — part 3 (append inside the class)
```python
    async def handle_getform(self, turn_context: TurnContext) -> None:
        """`/getform [slug-or-uid]`; with no argument sends the picker."""
        # FILL IN: arg = the token right after the one that equals "/getform" in turn_context.activity.text
        #   (text may carry an <at>…</at> mention first); no arg -> await self.handle_listforms(turn_context)
        await self.serve_form(turn_context, form_ref=arg)

    async def handle_listforms(self, turn_context: TurnContext) -> None:
        """Sends the tenant's picker card (or the empty-state card)."""
        turn = await self._fd_identity(turn_context)
        if await self._fd_send_turn_problem(turn, turn_context):
            return
        # FILL IN: reader.list_forms(tenant, bearer); [] -> build_empty_forms_card; else build_picker_card;
        #   FormDesignerError(403) -> error card "You don't have access to these forms."; other -> generic error card
        raise NotImplementedError

    async def serve_form(
        self, turn_context: TurnContext, *, form_ref: str | uuid.UUID, turn: FormDesignerTurn | None = None
    ) -> None:
        """Resolve tenant/bearer, render (remote or local), send the card. Never raises."""
        turn = turn or await self._fd_identity(turn_context)
        if await self._fd_send_turn_problem(turn, turn_context):
            return
        if not self._fd_enabled():
            await self._fd_send_card(build_error_card("Forms are not configured for this bot."), turn_context)
            return
        try:
            reader = self._fd_reader(turn)
            ref = parse_form_ref(form_ref)
            # FILL IN: slug -> reader.get_form_by_slug (None -> build_form_not_found_card(str(form_ref))) -> uid;
            #   form = await reader.get_form(...);
            #   len(form.sections) > 1 -> state = self._fd_wizards.start(conversation_id=turn.conversation_id,
            #       form_uid=form.form_uid, tenant=turn.tenant, total_sections=len(form.sections),
            #       owner_user_id=turn.user_id or "", form_version=form.published_version or form.version);
            #       rendered = await reader.render_teams(..., section_index=0); check metadata total_sections;
            #       card = self._fd_decorate_wizard(rendered.content, state)
            #   else rendered = await reader.render_teams(...); card = rendered.content
            #   card = append_render_warnings(card, rendered.warnings); await self._fd_send_card(card, turn_context)
            raise NotImplementedError
        except FormDesignerError as exc:
            self._fd_logger.warning("formdesigner: serve_form failed status=%s", exc.status)
            # FILL IN: 404 -> not-found card; 403 -> access card; 500 in local mode -> "not configured" card; else generic
            raise NotImplementedError

    def _fd_decorate_wizard(self, card: dict[str, Any], state: WizardState) -> dict[str, Any]:
        """Copy `card`; add the wizard control object to every next/cancel/submit Action.Submit."""
        decorated = copy.deepcopy(card)
        for action in decorated.get("actions", []):
            data = action.get("data") if action.get("type") == "Action.Submit" else None
            if isinstance(data, dict) and data.get("_action") in ("next", "cancel", "submit"):
                data[PICKER_ACTION_KEY] = {
                    "kind": "wizard", "action": data["_action"], "form_uid": str(state.form_uid),
                    "wizard_id": str(state.wizard_id), "section_index": state.section_index,
                }
        return decorated
```
**Why**: the control-object shape is spec §3 Delivery contracts verbatim; the original `_action` and terminal `_formdesigner` keys stay untouched.

### `formdesigner_mixin.py` (CREATE) — part 4 (append; `_TurnReaderProxy` at MODULE level, the rest inside the class)
```python
class _TurnReaderProxy:
    """FormReader resolved at call time from the active turn, so config applied after __init__ is honoured."""

    def __init__(self, owner: "TeamsFormDesignerMixin") -> None:
        self._owner = owner

    def _reader(self) -> Any:
        turn = active_turn()
        if turn is None:
            raise FormDesignerError("no active turn", status=403)
        return self._owner._fd_reader(turn)

    async def list_forms(self, **kw: Any) -> list[FormDescriptor]:
        return await self._reader().list_forms(**kw)

    async def get_form(self, **kw: Any) -> Any:
        return await self._reader().get_form(**kw)

    async def get_form_by_slug(self, **kw: Any) -> FormDescriptor | None:
        return await self._reader().get_form_by_slug(**kw)

# --- inside TeamsFormDesignerMixin ---
    def agent_tools(self) -> list[Any]:
        """super().agent_tools() + the FormDesignerToolkit's tools (bound to the request-local turn)."""
        toolkit = FormDesignerToolkit(
            _TurnReaderProxy(self),
            tenant_resolver=lambda: (t.tenant if (t := active_turn()) else None),
            bearer_resolver=lambda: (t.bearer if (t := active_turn()) else None),
            enqueue_card=lambda uid: (t.enqueue(uid) if (t := active_turn()) else False),
        )
        return [*super().agent_tools(), *toolkit.get_tools()]

    @asynccontextmanager
    async def formdesigner_turn(self, turn_context: TurnContext) -> AsyncIterator[None]:
        """Bind a fresh request-local identity and pending queue; always clean up (bind_turn's finally)."""
        turn = await self._fd_identity(turn_context)
        async with bind_turn(turn):
            yield None

    async def flush_formdesigner_cards(self, turn_context: TurnContext) -> None:
        """Drain this turn's distinct queued UIDs through serve_form (which re-checks the session)."""
        turn = active_turn()
        if turn is None:
            return
        for form_uid in turn.drain():
            await self.serve_form(turn_context, form_ref=form_uid)

    async def _fd_get_http(self) -> aiohttp.ClientSession:
        if self._fd_http is None or self._fd_http.closed:
            self._fd_http = aiohttp.ClientSession()
        return self._fd_http

    async def aclose(self) -> None:
        """Close the FormDesigner client and the submission session."""
        # FILL IN: await self._fd_client.close() when it has a close(); close self._fd_http when open; set both None
        raise NotImplementedError
```
**Why**: `_TurnReaderProxy` keeps the toolkit's `FormReader` contract while deferring the remote/local choice to call time; serve_form on flush re-resolves identity so an expired session yields a login card (spec: "Flush rechecks session expiry and authorization").

### `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_serve.py` (CREATE)
```python
"""FEAT-734 M4 — TeamsFormDesignerMixin (outbound half) with fakes; no Bot Framework adapter."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

pytest.importorskip("botbuilder")
from parrot.integrations.msteams.formdesigner_mixin import TeamsFormDesignerMixin  # noqa: E402

GUID = "11111111-2222-3333-4444-555555555555"


class _Base:  # stands in for Agent: agent_tools() is called during __init__
    def __init__(self, *args, **kwargs):
        self.tools = self.agent_tools()
    def agent_tools(self):
        return []


class FDAgent(TeamsFormDesignerMixin, _Base):
    pass


class FakeStore:
    """Records every attribute touched; ensure_authenticated must never be."""
    # FILL IN: get_or_create -> session; is_expired -> bool; __getattr__ records + raises for anything else


def _ctx(text="/getform", conv_type="personal"):
    ctx = MagicMock()
    ctx.activity.text = text
    ctx.activity.conversation.id = "conv-1"
    ctx.activity.conversation.conversation_type = conv_type
    ctx.activity.channel_data = {"tenant": {"id": GUID}}
    ctx.send_activity = AsyncMock()
    return ctx

# FILL IN: tests listed in the Test Specification below
```

### FILL IN checklist
- [ ] `apply_teams_config` — constructor-wins rule; bounded by decision 2 above
- [ ] `_fd_identity` — channel_data dict/object tenant extraction
- [ ] `handle_getform` arg parsing; `handle_listforms` body
- [ ] `serve_form` body + error mapping; bounded by AC "slug that matches nothing → no form found card"
- [ ] `aclose`
- [ ] `FakeStore`, fake reader, and the tests below

---

## Acceptance Criteria

- [ ] `FDAgent(...)` constructs with `agent_tools()` called inside the base `__init__`, and exposes the two `formdesigner_*` tools.
- [ ] `/getform <slug>`, `/getform <uid>` and `/getform` (picker) behave per spec §5; unknown slug → "no form found" card.
- [ ] No session → login card, zero reader calls; group chat → error card, zero reads.
- [ ] Remote mode sends the server's card (with its envelope) unchanged except warnings; local mode without secret → error card, no card with an unsigned envelope.
- [ ] Sectioned forms send section 0 with wizard control objects on Next/Cancel/Submit.
- [ ] Toolkit calls inside `formdesigner_turn` are isolated per turn; flush sends each distinct queued form once; nothing leaks after the context exits.
- [ ] `ensure_authenticated` never touched; `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_serve.py -q`


---

## Test Specification

In `test_formdesigner_serve.py` (spec §4 rows owned by this task):
`test_mixin_never_calls_ensure_authenticated`, `test_getform_slug_sends_card_remote`,
`test_getform_uid_sends_card_remote`, `test_getform_unknown_slug_sends_not_found`,
`test_getform_no_arg_sends_picker`, `test_listforms_empty_state`,
`test_no_session_sends_login_card_and_fetches_nothing`, `test_group_chat_refused`,
`test_local_mode_renders_with_teams_renderer`, `test_local_mode_without_secret_refuses`,
`test_local_membership_denied_before_registry`, `test_local_membership_authorized`,
`test_sectioned_form_starts_wizard_with_control_objects`,
`test_toolkit_turn_isolation_and_cleanup`, `test_flush_rechecks_expired_session`,
`test_apply_teams_config_constructor_wins`, `test_aclose_closes_sessions`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug formdesigner-serve-forms --feature-id FEAT-734`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/formdesigner-serve-forms.json`
4. **Verify the Codebase Contract** — confirm every import/signature before writing code; never use anything under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker, never change a fixed signature or path
7. **Verify** — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-integrations/src:packages/ai-parrot/src:packages/parrot-formdesigner/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4691 formdesigner-serve-forms verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
