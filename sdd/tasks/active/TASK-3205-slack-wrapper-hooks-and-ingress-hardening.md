# TASK-3205: Slack wrapper hooks + ingress hardening (signature on interactive route, Socket Mode user whitelist)

**Feature**: FEAT-555 — Dev-Loop Slack Kick-off
**Spec**: `sdd/specs/dev-loop-slack.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 9**. The Slack dev-loop adapter (TASK-3206/3207) needs three additive
capabilities the wrapper does not have today: a message-posting helper that **returns the
message `ts`** (`_post_message` returns `None`, `wrapper.py:585`), a `chat.update` helper, and a
**pre-LLM message interceptor** so replies in a run thread never reach `_safe_answer`
(`wrapper.py:307`, `socket_handler.py:251`).

Design research S5 (verified) also found two **pre-existing ingress gaps** that the new
gate approve/reject/cancel buttons would widen: the webhook interactive route is mounted
straight on `SlackInteractiveHandler.handle` with **no Slack signature check**
(`wrapper.py:144`; `interactive.py` never calls `verify_slack_signature_raw`), and Socket Mode
authorizes by **channel only** (`socket_handler.py:243` and `:279` call `_is_authorized(channel)`
without the user). Both are fixed here, before any dev-loop code lands (spec AC20, AC17).

---

## Scope

- Add `MessageInterceptor` type alias and `SlackAgentWrapper.add_message_interceptor()`;
  consult registered interceptors in `_handle_events` after authorization and before the
  `_safe_answer` task (`wrapper.py:307`) — the first interceptor returning `True` consumes the
  event and nothing is sent to the LLM.
- Add `SlackAgentWrapper.post_message()` returning the Slack `ts` (or `None`), make
  `_post_message()` a thin wrapper that discards the return value.
- Add `SlackAgentWrapper.update_message()` (`chat.update`, returns `bool`, never raises).
- Add `SlackAgentWrapper.open_dm()` (`conversations.open` → channel id or `None`).
- Add `SlackAgentWrapper._handle_interactive()` as the new target of `self.interactive_route`:
  verify the Slack signature exactly like `_handle_events`/`_handle_command`, check
  `_is_authorized(channel, user)`, then delegate the parsed payload dict to
  `self._interactive_handler.handle(payload)`.
- Socket Mode parity: pass `user` to `_is_authorized` in `_handle_event` (`:243`) and
  `_handle_slash_command` (`:279`); add the same check in `_handle_interactive` (`:352`);
  consult the wrapper's interceptors in `_handle_event` before `_safe_answer` (`:251`).
- Unit tests in `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_wrapper_hooks.py`.

**NOT in scope**: any `parrot.integrations.devloop` code, the `/devloop` command, blocks,
gate cards, the status card, `SlackAgentConfig.devloop` (TASK-3200), manager wiring
(TASK-3208). Do not change `SlackInteractiveHandler` internals beyond what is listed.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` | MODIFY | interceptor registry + consult; `post_message`/`update_message`/`open_dm`; signed `_handle_interactive` route target |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/socket_handler.py` | MODIFY | user-level whitelist in event/slash/interactive paths; interceptor consult |
| `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_wrapper_hooks.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# Already present at the top of wrapper.py — do NOT re-add:
import asyncio, json, logging, re                                    # verified: slack/wrapper.py:6-9
from typing import Any, Dict, List, Optional, TYPE_CHECKING          # verified: slack/wrapper.py:10
from aiohttp import web, ClientSession                               # verified: slack/wrapper.py:12
from .interactive import SlackInteractiveHandler                     # verified: slack/wrapper.py:18
from .security import verify_slack_signature_raw                     # verified: slack/wrapper.py:21
# Already present at the top of socket_handler.py:
import asyncio, logging                                              # verified: slack/socket_handler.py:7-8
from typing import Any, Dict, Optional, TYPE_CHECKING                # verified: slack/socket_handler.py:9
from aiohttp import ClientSession                                    # verified: slack/socket_handler.py:11
# New (add to wrapper.py typing import): Awaitable, Callable — stdlib typing
# Tests:
from parrot.integrations.slack.wrapper import SlackAgentWrapper      # verified: slack/__init__.py:20
from parrot.integrations.slack.models import SlackAgentConfig        # verified: slack/models.py (dataclass)
from parrot.integrations.slack.socket_handler import SlackSocketHandler  # verified: slack/socket_handler.py:20
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py
class SlackAgentWrapper:                                                              # line 72
    def __init__(self, agent, config: SlackAgentConfig, app: web.Application, oauth_manager=None)  # line 83
    #   self.conversations: Dict[str, 'ConversationMemory'] = {}                      # line 106
    #   self._background_tasks: set[asyncio.Task] = set()                             # line 115
    #   self._interactive_handler = SlackInteractiveHandler(self)                     # line 143
    #   app.router.add_post(self.interactive_route, self._interactive_handler.handle) # line 144  ← replaced
    def _is_authorized(self, channel_id: str, user_id: str = None) -> bool:           # line 179
    async def _handle_events(self, request: web.Request) -> web.Response:             # line 201
    #   raw_body = await request.read(); verify_slack_signature_raw(raw_body, request.headers, self.config.signing_secret)  # lines 224-231
    #   channel/user auth → text/thread_ts/session_id/files → "# 8. Process in background — return 200 immediately"  # lines 290-307
    async def _handle_command(self, request: web.Request) -> web.Response:            # line 323 (signature check pattern lines 326-336)
    async def _safe_answer(self, channel, user, text, thread_ts, session_id, files=None) -> None  # line 414
    async def _post_message(self, channel: str, text: str, blocks=None, thread_ts=None) -> None  # line 585 — returns None; body posts chat.postMessage with ClientSession (lines 600-626)
    async def _delete_message(self, channel: str, ts: str) -> None                    # line 713

# packages/ai-parrot-integrations/src/parrot/integrations/slack/interactive.py
class SlackInteractiveHandler:                                                        # line 96
    async def handle(self, request_or_payload: web.Request | dict) -> Optional[web.Response]  # line 124 — accepts a dict; returns None for dicts unless a view_submission handler returns a dict

# packages/ai-parrot-integrations/src/parrot/integrations/slack/socket_handler.py
class SlackSocketHandler:                                                             # line 20
    async def _handle_event(self, payload: Dict[str, Any]) -> None                    # line 173
    #   if not channel or not self.wrapper._is_authorized(channel): return           # line 243  ← add user
    #   user = event.get("user") or "unknown"                                          # line 246
    #   # Process in background using the wrapper's safe_answer                       # line 251 (2 occurrences in file)
    async def _handle_slash_command(self, payload: Dict[str, Any]) -> None            # line 266
    #   if channel and not self.wrapper._is_authorized(channel):                       # line 279  ← add user
    async def _handle_interactive(self, payload: Dict[str, Any]) -> None              # line 352 — delegates to wrapper._interactive_handler.handle(payload)
    async def _send_response(self, response_url: str, body: Dict[str, Any]) -> None   # line 369

# packages/ai-parrot-integrations/src/parrot/integrations/slack/security.py (re-exported slack/__init__.py:17)
def verify_slack_signature_raw(raw_body: bytes, headers, signing_secret: str) -> bool   # used at wrapper.py:227, :333
```

### Does NOT Exist
- ~~`SlackAgentWrapper.post_message()` / `update_message()` / `open_dm()` / `add_message_interceptor()` / `_handle_interactive()`~~ — this task creates them.
- ~~`SlackAgentWrapper._message_interceptors`~~ — new attribute created in `__init__` by this task.
- ~~signature verification inside `SlackInteractiveHandler.handle`~~ — none; that is why the wrapper must wrap the route.
- ~~`SlackSocketHandler` user-level whitelist~~ — today channel-only (`:243`, `:279`); `_handle_interactive` (`:352`) has no auth at all.
- ~~`slack_sdk` in wrapper.py~~ — the wrapper uses raw `aiohttp.ClientSession` against `https://slack.com/api/*` (`:600-626`); keep that pattern (do NOT import `AsyncWebClient` here; `SlackOAuthNotifier` in `oauth_callback.py:73` uses it only for DMs).
- ~~`requests` / `httpx`~~ — banned (ruff TID251).

---

## Implementation Notes

### Pattern to Follow
```python
# wrapper.py:224-231 — signature check pattern to copy into _handle_interactive
raw_body = await request.read()
if not verify_slack_signature_raw(raw_body, request.headers, self.config.signing_secret):
    self.logger.warning("Slack signature verification failed on /interactive")
    return web.Response(status=401, text="Unauthorized")
```

### Key Constraints
- Async throughout; `self.logger`; never raise out of the Slack API helpers (log and return `None`/`False`).
- The interactive payload arrives as `application/x-www-form-urlencoded` with a `payload` JSON field (see `interactive.py:135-142`); after signature verification, parse with `urllib.parse.parse_qsl` on the raw body (same trick as `_handle_command`, `wrapper.py:339`) then `json.loads(data["payload"])`.
- Interceptors receive the **raw Slack event dict** and return `True` when consumed. Exceptions inside an interceptor are logged and treated as "not consumed".
- Keep `_post_message` byte-compatible for existing callers (`_answer`, `assistant.py`).
- `120`-column lines, Google docstrings, `black`/`ruff` clean.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py:323-412` — `_handle_command` (signature + form parsing precedent)
- `packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py:73-120` — DM push precedent (`chat.postMessage` with a user id as channel)
- `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_wrapper_jira.py:14-60` — `_make_minimal_wrapper` fixture pattern to copy

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Add `Awaitable, Callable` to the `typing` import and the `MessageInterceptor` alias at module level in `wrapper.py` — *why*: the adapter (TASK-3206) imports the alias by name.
2. In `__init__`, create `self._message_interceptors: list[MessageInterceptor] = []` right after `_background_tasks` (`:115`) and replace the direct interactive mount (`:144`) with `self._handle_interactive` — *why*: the route must be signed before any dev-loop button exists.
3. Add `add_message_interceptor`, `post_message`, `update_message`, `open_dm`, `_run_interceptors`, `_handle_interactive` methods — *why*: they are the only Slack API surface the transport (TASK-3207) may use.
4. Consult `_run_interceptors(event)` in `_handle_events` just before the `# 8. Process in background` block — *why*: run-thread replies must never reach the LLM (spec §7 "Both Slack modes").
5. Patch `socket_handler.py` in the four places listed — *why*: webhook and Socket Mode must reject the same users and consume the same events (AC17, AC20).
6. Write the tests; run `pytest packages/ai-parrot-integrations/tests/integrations/slack -q` — *why*: the existing whitelist suites must stay green (AC19).

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` (MODIFY — imports + alias)
```python
# occurrences: 1 (verified: grep -c 'from typing import Any, Dict, List, Optional, TYPE_CHECKING' packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py)
# REPLACE line 10 `from typing import Any, Dict, List, Optional, TYPE_CHECKING` (verified: wrapper.py:10) with:
from typing import Any, Awaitable, Callable, Dict, List, Optional, TYPE_CHECKING

# occurrences: 1 (verified: grep -c 'from .security import verify_slack_signature_raw' …/slack/wrapper.py)
# AFTER — insert below `from .security import verify_slack_signature_raw` (verified: wrapper.py:21), after the import block ends:
MessageInterceptor = Callable[[Dict[str, Any]], Awaitable[bool]]
"""Async callable given the raw Slack event dict; returns True when it consumed the event (no LLM answer)."""
```
**Why**: the alias is part of the public contract (spec §3 M9); TASK-3206 imports it.

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` (MODIFY — `__init__`)
```python
# occurrences: 1 (verified: grep -c '        self._background_tasks: set\[asyncio.Task\] = set()' …/slack/wrapper.py)
# AFTER — insert below `        self._background_tasks: set[asyncio.Task] = set()` (verified: wrapper.py:115)
        # Pre-LLM message interceptors (FEAT-555 M9): consulted in _handle_events and SlackSocketHandler._handle_event.
        self._message_interceptors: List[MessageInterceptor] = []

# occurrences: 1 (verified: grep -c 'app.router.add_post(self.interactive_route, self._interactive_handler.handle)' …/slack/wrapper.py)
# REPLACE `        app.router.add_post(self.interactive_route, self._interactive_handler.handle)` (verified: wrapper.py:144) with:
        app.router.add_post(self.interactive_route, self._handle_interactive)
```
**Why**: the interactive route must go through signature verification (design research S5); the handler object itself is unchanged so `socket_handler._handle_interactive` keeps working.

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` (MODIFY — new methods)
```python
# occurrences: 1 (verified: grep -c '    async def _post_message(' …/slack/wrapper.py)
# BEFORE — insert ABOVE `    async def _post_message(` (verified: wrapper.py:585)
    def add_message_interceptor(self, interceptor: MessageInterceptor) -> None:
        """Register a pre-LLM interceptor; interceptors run in registration order, first ``True`` wins."""
        self._message_interceptors.append(interceptor)

    async def _run_interceptors(self, event: Dict[str, Any]) -> bool:
        """Return True when a registered interceptor consumed *event*; interceptor errors count as not consumed."""
        for interceptor in list(self._message_interceptors):
            try:
                if await interceptor(event):
                    return True
            except Exception:  # noqa: BLE001 — an interceptor bug must not break normal chat
                self.logger.exception("message interceptor failed")
        return False

    async def _slack_api(self, method: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """POST *payload* to ``https://slack.com/api/<method>``; return the JSON body or None on transport/API error."""
        if not self.config.bot_token:
            self.logger.warning("Slack bot token is not configured; cannot call %s", method)
            return None
        headers = {"Authorization": f"Bearer {self.config.bot_token}", "Content-Type": "application/json; charset=utf-8"}
        try:
            async with ClientSession() as session:
                async with session.post(f"https://slack.com/api/{method}", headers=headers, data=json.dumps(payload)) as resp:
                    data = await resp.json()
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Slack API %s transport error: %s", method, exc)
            return None
        if not data.get("ok"):
            self.logger.error("Slack API %s error: %s", method, data.get("error"))
            # FILL IN: on error == "ratelimited" expose Retry-After to callers (attach data["retry_after"]) — bounded by AC16
            return None
        return data

    async def post_message(self, channel: str, text: str, blocks: Optional[List[Dict[str, Any]]] = None,
                           thread_ts: Optional[str] = None) -> Optional[str]:
        """chat.postMessage; return the new message ``ts`` or None on failure (never raises)."""
        payload: Dict[str, Any] = {"channel": channel, "text": text}
        if blocks:
            payload["blocks"] = blocks
        if thread_ts:
            payload["thread_ts"] = thread_ts
        data = await self._slack_api("chat.postMessage", payload)
        return data.get("ts") if data else None

    async def update_message(self, channel: str, ts: str, text: str, blocks: Optional[List[Dict[str, Any]]] = None) -> bool:
        """chat.update; False on failure (rate-limit ⇒ log + False, never raise)."""
        payload: Dict[str, Any] = {"channel": channel, "ts": ts, "text": text}
        if blocks:
            payload["blocks"] = blocks
        return (await self._slack_api("chat.update", payload)) is not None

    async def open_dm(self, user_id: str) -> Optional[str]:
        """conversations.open ⇒ DM channel id, or None (fallback thread root when the bot is not in the channel)."""
        data = await self._slack_api("conversations.open", {"users": user_id})
        return (data or {}).get("channel", {}).get("id")

    async def _handle_interactive(self, request: web.Request) -> web.Response:
        """Signed webhook target for ``self.interactive_route``: verify signature, authorize, delegate to the handler."""
        if not self.config.signing_secret:
            self.logger.error("Slack signing_secret not configured — rejecting request")
            return web.Response(status=401, text="Unauthorized")
        raw_body = await request.read()
        if not verify_slack_signature_raw(raw_body, request.headers, self.config.signing_secret):
            self.logger.warning("Slack signature verification failed on /interactive")
            return web.Response(status=401, text="Unauthorized")
        # FILL IN: parse `payload` JSON from the urlencoded raw body (parse_qsl, as in _handle_command :339);
        #          400 on missing/invalid JSON — bounded by AC20
        # FILL IN: channel = payload.get("channel", {}).get("id") or payload.get("view", {}).get("private_metadata"-derived) ;
        #          user = payload.get("user", {}).get("id"); if channel and not self._is_authorized(channel, user): 200 {"ok": True} + warning
        #          (view_submission payloads carry no channel — authorize on user only) — bounded by AC20
        # FILL IN: result = await self._interactive_handler.handle(payload); return web.json_response(result or {"ok": True})
        raise NotImplementedError
```
**Why this shape**: one private `_slack_api` helper keeps every Slack Web API call in the wrapper (design research S10) and preserves the raw-`aiohttp` pattern of `_post_message`. `post_message` is what `SlackDevLoopTransport` (TASK-3207) uses for the thread root; `_post_message` must become `await self.post_message(...)` with the result discarded so existing callers are untouched.

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` (MODIFY — `_handle_events` consult)
```python
# occurrences: 1 (verified: grep -c '        # 8. Process in background — return 200 immediately' …/slack/wrapper.py)
# BEFORE — insert ABOVE `        # 8. Process in background — return 200 immediately` (verified: wrapper.py:307)
        # FEAT-555 M9: a registered interceptor (e.g. a dev-loop run thread) may consume the event.
        if await self._run_interceptors(event):
            return web.json_response({"ok": True})
```
**Why**: the consult must sit after authorization (`:293`) and before the LLM task so unauthorized users never reach an interceptor.

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/socket_handler.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        if not channel or not self.wrapper._is_authorized(channel):' …/slack/socket_handler.py)
# REPLACE (verified: socket_handler.py:243-246) — move `user` above the check and pass it:
        user = event.get("user") or "unknown"
        if not channel or not self.wrapper._is_authorized(channel, user):
            return
        # FILL IN: delete the now-duplicate `user = event.get("user") or "unknown"` line that followed (:246) — bounded by ruff F841/redefinition

# occurrences: 2 (verified: grep -c "        # Process in background using the wrapper's safe_answer" …/slack/socket_handler.py)
# FILL IN: disambiguate — the target is the FIRST occurrence, inside _handle_event, preceded by
#          `        session_id = f"{channel}:{user}"` and `        files = event.get("files")` (verified: socket_handler.py:248-251).
# BEFORE that comment insert:
        if await self.wrapper._run_interceptors(event):
            return

# occurrences: 1 (verified: grep -c '        if channel and not self.wrapper._is_authorized(channel):' …/slack/socket_handler.py)
# REPLACE (verified: socket_handler.py:279) with:
        if channel and not self.wrapper._is_authorized(channel, user):

# occurrences: 1 (verified: grep -c '    async def _handle_interactive(self, payload: Dict\[str, Any\]) -> None:' …/slack/socket_handler.py)
# INSIDE _handle_interactive (verified: socket_handler.py:352), before delegating to handler.handle(payload):
        # FILL IN: channel = payload.get("channel", {}).get("id"); user = payload.get("user", {}).get("id");
        #          if channel and not self.wrapper._is_authorized(channel, user): log + return — bounded by AC20
```
**Why**: Socket Mode must enforce `allowed_user_ids` exactly like the webhook path (`wrapper.py:293`, `:347`) and consume intercepted thread replies identically (AC17).

### `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_wrapper_hooks.py` (CREATE)
```python
"""Unit tests for FEAT-555 M9 — wrapper hooks and ingress hardening (TASK-3205)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.slack.socket_handler import SlackSocketHandler  # verified: slack/socket_handler.py:20
from parrot.integrations.slack.wrapper import SlackAgentWrapper  # verified: slack/__init__.py:20


def _make_wrapper(allowed_user_ids=None):
    """Minimal wrapper without running __init__ (pattern: test_slack_wrapper_jira.py:14-60)."""
    # FILL IN: copy the `_make_minimal_wrapper` construction from test_slack_wrapper_jira.py, set
    #          config.allowed_user_ids, wrapper._message_interceptors = [], wrapper._interactive_handler = MagicMock(handle=AsyncMock())
    raise NotImplementedError


@pytest.mark.asyncio
async def test_interceptor_consumes_event_webhook_path():
    """An interceptor returning True prevents _safe_answer in _handle_events."""
    # FILL IN: build a signed request mock (patch verify_slack_signature_raw → True), register an interceptor
    #          returning True, assert wrapper._safe_answer was not called — bounded by AC17


@pytest.mark.asyncio
async def test_interceptor_consumes_event_socket_path():
    """The same interceptor consumes the event in SlackSocketHandler._handle_event."""
    # FILL IN — bounded by AC17


@pytest.mark.asyncio
async def test_post_message_returns_ts():
    """post_message returns the ts from chat.postMessage."""
    # FILL IN: patch wrapper._slack_api → {"ok": True, "ts": "1.2"}; assert "1.2"


@pytest.mark.asyncio
async def test_interactive_route_rejects_bad_signature():
    """_handle_interactive returns 401 when the signature does not verify."""
    # FILL IN: patch verify_slack_signature_raw → False; assert status 401 and handler.handle not awaited — bounded by AC20


@pytest.mark.asyncio
async def test_socket_mode_enforces_user_whitelist():
    """Socket Mode drops events, slash commands and interactive payloads from a non-whitelisted user."""
    # FILL IN: allowed_user_ids=["U_OK"]; payloads from "U_BAD" → _safe_answer / handle not called — bounded by AC20
```
**Why**: covers the four spec tests for M9 (`test_wrapper_interceptor_consumes_event`, `test_post_message_returns_ts`, `test_interactive_route_rejects_bad_signature`, `test_socket_mode_enforces_user_whitelist`).

### FILL IN checklist
- [ ] `wrapper.py::_slack_api` — surface `ratelimited`/`retry_after` for TASK-3209; bounded by AC16
- [ ] `wrapper.py::_handle_interactive` — form parsing, channel/user authorization, delegation; bounded by AC20
- [ ] `wrapper.py::_post_message` — becomes `await self.post_message(...)` (return discarded); bounded by AC19 (existing callers unchanged)
- [ ] `socket_handler.py::_handle_event` — remove the duplicate `user =` line; interceptor consult placement; bounded by AC17
- [ ] `socket_handler.py::_handle_interactive` — channel+user authorization; bounded by AC20
- [ ] tests — five bodies; bounded by AC17/AC19/AC20

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/slack -v` (new file + existing whitelist/jira suites — spec AC19)
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/slack`
- [ ] Imports work: `from parrot.integrations.slack.wrapper import SlackAgentWrapper, MessageInterceptor`
- [ ] Webhook interactive route returns 401 on an unsigned payload (spec AC20)
- [ ] Socket Mode enforces `allowed_user_ids` for events, slash commands and interactive payloads (spec AC20, AC17)
- [ ] `post_message()` returns the Slack `ts`; `_post_message()` behaviour for existing callers is unchanged (spec AC19)

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/slack/test_slack_wrapper_hooks.py — see blueprint block above.
# Required cases: interceptor consumed (webhook + socket), post_message ts, interactive 401, socket user whitelist.
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/dev-loop-slack.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3205-slack-wrapper-hooks-and-ingress-hardening.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
