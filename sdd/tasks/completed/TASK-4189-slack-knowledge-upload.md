# TASK-4189: Slack knowledge-upload adapter

**Feature**: FEAT-647 — Chat-driven document upload into Bookstore / LLM Wiki
**Spec**: `sdd/specs/teams-telegram-uploader-bookstore.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4183, TASK-4186
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 10** (Slack adapter). Slack slash commands cannot
carry files, so the adapter offers two entry points (spec §2 Overview):

1. a file shared with the message text `ingest_book …` / `ingest_wiki …`
   (no leading `/` — the Slack client would treat it as a slash command),
   consumed by a **message interceptor**;
2. the slash command `/ingest_book` / `/ingest_wiki`, which arms a **pending
   window** (`slack_pending_window_s`, default 300 s) during which the next
   file shared by that user in that channel is consumed.

Identity is the Slack user's email (`users.info`) mapped by the core service
to `auth.vw_users` (spec §2 Identity). Bytes are downloaded with a hard cap
and handed to `KnowledgeUploadService.submit()`; the outcome is posted back
with `post_message`. It implements AC1, AC2, AC3, AC5, AC10, AC11 (Slack
parts) and AC16.

Two findings made while writing this task (supersede/extend spec §3 M10):
- `users.info` already works through `_slack_api` (JSON POST) — verified
  precedent `slack/devloop/actions.py:256`. This resolves spec §8 open
  question "Slack: users.info via `_slack_api`" → **use `_slack_api`**.
- **Socket mode** (`socket_handler.py`) returns early on empty text
  (`socket_handler.py:236-239`) *before* running interceptors, so a file
  shared without text (the pending-window flow) never reaches the
  interceptor. The spec's file list omits `socket_handler.py`; this task
  adds it (MODIFY). In webhook mode a `file_share` message (subtype set)
  already skips the assistant-DM branch (`wrapper.py:290` requires no
  subtype) and reaches the interceptors at `wrapper.py:320`; the spec still
  asks for interceptors before the assistant-DM dispatch (`wrapper.py:288`),
  which this task adds for text messages that carry `files` without a
  subtype.

---

## Scope

- Create `slack/knowledge_upload.py` with `SlackKnowledgeUpload`
  (`register`, `on_command`, `intercept`, `_download`, `_email`) and the
  pending-window state.
- In `SlackAgentWrapper.start()`: when `self.config.knowledge_upload.enabled`,
  build the service (`await KnowledgeUploadService.from_config(...)`),
  create `SlackKnowledgeUpload` and call `register()`; in `stop()`: call
  `await service.shutdown()`.
- Webhook path: run `_run_interceptors(event)` before the assistant-mode DM
  dispatch, after `_is_authorized(channel, user)`; keep first-`True`-wins.
- Socket path: run `_run_interceptors(event)` for messages that carry files
  **before** the empty-text early return, after authorization.
- Write `tests/knowledge_upload/test_slack_upload.py`.

**NOT in scope**: the core service / policy / staging (TASK-4182, TASK-4183),
targets (TASK-4184, TASK-4185), `SlackAgentConfig.knowledge_upload` field
(TASK-4186), Telegram/Teams adapters (TASK-4187, TASK-4188), docs
(TASK-4190), reusing `slack/files.download_slack_file`, Slack app manifest
changes (documented in TASK-4190).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/knowledge_upload.py` | CREATE | `SlackKnowledgeUpload` adapter |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` | MODIFY | build/register in `start()`, shutdown in `stop()`, interceptors before assistant-DM dispatch |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/socket_handler.py` | MODIFY | interceptors for file messages before the empty-text return |
| `packages/ai-parrot-integrations/tests/knowledge_upload/test_slack_upload.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import ClientSession, ClientTimeout          # aiohttp (ClientSession used at slack/wrapper.py:13; ClientTimeout at slack/files.py:132)
from parrot.integrations.slack.commands import SlackCommandRouter   # verified: slack/commands/__init__.py:27
from parrot.integrations.slack.wrapper import SlackAgentWrapper     # verified: slack/wrapper.py:76
from parrot.integrations.slack.socket_handler import SlackSocketHandler  # verified: slack/socket_handler.py:20
# Created by dependencies (spec §3 M1 / M7) — verify they exist before use:
from parrot.integrations.knowledge_upload.models import (   # TASK-4182
    UploadTargetKind, UploaderIdentity, UploadRequest, UploadOutcome, UploadStatus,
)
from parrot.integrations.knowledge_upload.service import KnowledgeUploadService  # TASK-4183
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py
MessageInterceptor = Callable[[Dict[str, Any]], Awaitable[bool]]          # :27
class SlackAgentWrapper:                                                   # :76
    def __init__(self, agent, config: SlackAgentConfig, app: web.Application, oauth_manager=None)  # :87
    self._message_interceptors: List[MessageInterceptor]                   # :122
    self._command_router = SlackCommandRouter()                            # :125
    self._background_tasks: set[asyncio.Task]                              # :119
    async def start(self) -> None:                                         # :161 (await self._dedup.start() :163)
    async def stop(self) -> None:                                          # :166 (last line logger.info :175)
    def _is_authorized(self, channel_id: str, user_id: str = None) -> bool:  # :183
    async def _handle_events(self, request: web.Request) -> web.Response:  # :224
        # assistant-DM branch :287-294 →
        #   if event_type == "message" and event.get("channel_type") == "im":   (:288)
        #       if not event.get("subtype") and not event.get("bot_id"):         (:290)
        #           task = asyncio.create_task(self._assistant_handler.handle_user_message(event)) ...
        # standard path: auth :302-311; interceptors :320-322 → `if await self._run_interceptors(event): return web.json_response({"ok": True})`
    async def _handle_command(self, request) -> web.Response:              # :340 — router dispatch :381-386:
        #   router_result = await self._command_router.dispatch(command_word, command_payload)
        #   if router_result is not None: return web.json_response(router_result)
        #   command_payload keys: team_id, user_id, channel_id, text, response_url
    def add_message_interceptor(self, interceptor: MessageInterceptor) -> None:  # :586 (registration order, first True wins)
    async def _run_interceptors(self, event: Dict[str, Any]) -> bool:      # :595 (errors logged = not consumed)
    async def _slack_api(self, method: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:  # :609 JSON POST, None on error/ok:false
    async def post_message(self, channel: str, text: str, blocks=None, thread_ts=None) -> Optional[str]:  # :645
    self.config.bot_token  # SlackAgentConfig.bot_token (slack/models.py:54)

# users.info precedent — packages/ai-parrot-integrations/src/parrot/integrations/slack/devloop/actions.py:256-257
data = await self.wrapper._slack_api("users.info", {"user": requester.user_id})
email = ((data or {}).get("user", {}).get("profile", {}) or {}).get("email", "")

# packages/ai-parrot-integrations/src/parrot/integrations/slack/socket_handler.py
class SlackSocketHandler:                                                  # :20
    def __init__(self, wrapper: 'SlackAgentWrapper')                       # :36
    async def _handle_event(self, payload: Dict[str, Any]) -> None:        # :173
        # assistant-DM branch :205-218 skips ANY subtype (file_share falls through)
        # :236  # Skip empty messages (e.g., file uploads with no text)
        # :237  text = (event.get("text") or "").strip()
        # :238  if not text:
        # :239      return
        # auth :242-245 (channel = event.get("channel"); user = event.get("user") or "unknown")
        # interceptors :252-253 `if await self.wrapper._run_interceptors(event): return`
    async def _handle_slash_command(self, payload) -> None:                # :270 — uses wrapper._command_router.dispatch (:305) and posts the result to response_url

# packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/__init__.py
class SlackCommandRouter:                                                  # :27
    def register(self, command: str, handler: Callable) -> None:           # :50 handler = async (payload: dict) -> dict | None
    async def dispatch(self, command: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:  # :68

# packages/ai-parrot-integrations/src/parrot/integrations/slack/files.py
def extract_files_from_event(event: Dict[str, Any]) -> List[Dict[str, Any]]:  # :48 — event["files"] or [event["file"]] for subtype file_share
# Slack file objects carry: name, size, filetype, mimetype, url_private_download
```

Core API consumed (spec §3 M1 skeleton — fixed names):
`KnowledgeUploadService.from_config(config)` (async classmethod),
`.available_targets() -> set[UploadTargetKind]`,
`.max_bytes(platform_cap_mb=None) -> int`,
`.submit(request, notify) -> UploadOutcome`, `.shutdown()`;
`UploaderIdentity(platform="slack", platform_user_id=…, email=…)`;
`UploadRequest(target, identity, filename, data, force, title, authors, topics)`;
`UploadOutcome.status/.message`; `UploadStatus.ACCEPTED/DENIED/INVALID`.
`self.config.knowledge_upload: KnowledgeUploadConfig` (TASK-4186) with
`.enabled`, `.slack_pending_window_s`, `.allowed_extensions`.

### Does NOT Exist
- ~~`SlackAgentWrapper.knowledge_upload` / any upload feature in the Slack wrapper~~ — this task adds `_knowledge_upload`
- ~~`slack/files.download_slack_file` being called anywhere~~ — and it must NOT be reused (unsanitized `dest_dir / filename`, MIME allowlist)
- ~~a Slack users-lookup helper on the wrapper~~ — call `_slack_api("users.info", …)` directly
- ~~interceptors in the webhook assistant-DM branch or before socket mode's empty-text return~~ — added here
- ~~`SlackCommandRouter` handlers receiving anything but the payload dict~~
- ~~`UserInfoService` calls in this adapter~~ — profile resolution happens inside the core service

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/slack/knowledge_upload.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/slack/socket_handler.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/knowledge_upload/test_slack_upload.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py#SlackAgentWrapper",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py#SlackAgentWrapper.start",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py#SlackAgentWrapper.stop",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py#SlackAgentWrapper._is_authorized",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py#SlackAgentWrapper._handle_events",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py#SlackAgentWrapper.add_message_interceptor",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py#SlackAgentWrapper._run_interceptors",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py#SlackAgentWrapper._slack_api",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py#SlackAgentWrapper.post_message",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/socket_handler.py#SlackSocketHandler._handle_event",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/__init__.py#SlackCommandRouter.register",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/files.py#extract_files_from_event"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Interceptor contract: `async (event: dict) -> bool`, registered with
  `wrapper.add_message_interceptor` (FEAT-555 dev-loop does the same).
- Background work: `asyncio.create_task(...)` + add to
  `wrapper._background_tasks` + `add_done_callback(discard)` (pattern at
  `wrapper.py:291-293`) — the interceptor must return `True` fast; downloading
  happens in the task.
- Test wrapper construction without `__init__`: copy `_make_wrapper` from
  `tests/integrations/slack/test_slack_wrapper_hooks.py:16-60` into the new
  test file (do not import across test packages).

### Key Constraints
- aiohttp only; streamed download with a running byte counter — abort and
  answer INVALID-style text once `> max_bytes` (AC10). Check `file_info["size"]`
  first when present.
- Never echo allow-lists, paths or stack traces to Slack.
- Pending window key `(channel_id, user_id)`, expiry via `time.monotonic()`;
  consumed on first matching file (one-shot); expired entries are dropped
  lazily.
- Command text grammar: first word `ingest_book` / `ingest_wiki`
  (case-insensitive), rest parsed with `shlex.split` → `--force`,
  `--title`, `--author` (repeatable), `--topic` (repeatable). Implement the
  parser locally (`_parse_args`) — the Telegram adapter's `parse_ingest_args`
  lives in another task's file and must not be imported here.
- Interceptor ignores bot messages and events without files unless they start
  with the command word (then reply usage help and return `True`).
- Only register the command/target words for `service.available_targets()`.

### References in Codebase
- `slack/devloop/actions.py:239-266` — users.info → email
- `tests/integrations/slack/test_slack_wrapper_hooks.py` — wrapper test harness

---

## Implementation Blueprint

### Steps (in order)
1. Create `slack/knowledge_upload.py` (blocks A + B) — *why*: keeps the wrapper diff small and the adapter testable in isolation.
2. Wire `start()`/`stop()` in `wrapper.py` — *why*: `from_config` is async, so the service can only be built in the async start hook (AC16: nothing registered when disabled).
3. Insert the interceptor call before the assistant-DM dispatch in `wrapper.py` — *why*: spec M10 requires the assistant path not to bypass interceptors.
4. Insert the file-message interceptor call in `socket_handler.py` before the empty-text return — *why*: otherwise the pending-window flow never fires in socket mode.
5. Write the tests; run Validation Commands.

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/knowledge_upload.py` (CREATE) — block A
```python
"""Slack adapter for chat-driven knowledge upload (FEAT-647, spec §3 Module 10)."""
from __future__ import annotations

import asyncio
import logging
import shlex
import time
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from aiohttp import ClientSession, ClientTimeout

from ..knowledge_upload.models import (
    UploadOutcome,
    UploadRequest,
    UploadStatus,
    UploadTargetKind,
    UploaderIdentity,
)
from ..knowledge_upload.service import KnowledgeUploadService

if TYPE_CHECKING:
    from .wrapper import SlackAgentWrapper

COMMANDS: Dict[str, UploadTargetKind] = {
    "ingest_book": UploadTargetKind.BOOKSTORE,
    "ingest_wiki": UploadTargetKind.WIKI,
}
USAGE = "Usage: share a .pdf/.docx/.md file with the text `ingest_book [--force] [--title \"…\"]` or `ingest_wiki [--force]`."


class SlackKnowledgeUpload:
    """Registers ingest_book / ingest_wiki on a Slack wrapper."""

    def __init__(self, wrapper: "SlackAgentWrapper", service: KnowledgeUploadService) -> None:
        self.wrapper = wrapper
        self.service = service
        self.logger = logging.getLogger(f"SlackKnowledgeUpload.{wrapper.config.name}")
        self._window_s = wrapper.config.knowledge_upload.slack_pending_window_s
        # (channel_id, user_id) -> (expires_at_monotonic, target, parsed_args)
        self._pending: Dict[Tuple[str, str], Tuple[float, UploadTargetKind, Dict[str, Any]]] = {}

    def _commands(self) -> Dict[str, UploadTargetKind]:
        available = self.service.available_targets()
        return {word: kind for word, kind in COMMANDS.items() if kind in available}

    def register(self) -> None:
        """Register slash commands and the file-message interceptor."""
        for word in self._commands():
            self.wrapper._command_router.register(word, self.on_command)
        self.wrapper.add_message_interceptor(self.intercept)
        self.logger.info("Knowledge upload enabled: %s", sorted(self._commands()))

    async def on_command(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Arm the pending window for (channel_id, user_id); reply ephemerally."""
        text = (payload.get("text") or "").strip()
        # FILL IN: resolve the command word — Slack sends it in payload["command"]
        #   only to _handle_command, not in command_payload; derive it from the
        #   registered word that dispatched here (bind it with functools.partial in
        #   register()) — bounded by AC1.
        raise NotImplementedError

    @staticmethod
    def _parse_args(text: str) -> Dict[str, Any]:
        """shlex-based: --force, --title, --author (repeatable), --topic (repeatable)."""
        # FILL IN: parse; unknown flags → ValueError (caller answers USAGE) — bounded by AC1.
        raise NotImplementedError
```
**Why this shape**: names and the `register/on_command/intercept/_download/_email`
surface are fixed by spec §3 M10. `on_command` cannot see which slash command
fired (the router passes only the payload, `wrapper.py:370-386`), so bind the
target per registration (`functools.partial(self.on_command, target)` or a
small closure) — keep the public method name `on_command`.

### `slack/knowledge_upload.py` (CREATE) — block B (append to the class)
```python
    async def intercept(self, event: Dict[str, Any]) -> bool:
        """Consume a file message addressed to an ingest command or an armed window."""
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            return False
        channel = event.get("channel") or ""
        user = event.get("user") or ""
        files = event.get("files") or ([event["file"]] if event.get("file") else [])
        # FILL IN: decide — text prefix (first word in self._commands()) wins;
        #   else a live pending window for (channel, user) (pop it, check expiry);
        #   no command and no window → return False (normal chat) — bounded by AC1.
        # FILL IN: command word but no file → post USAGE and return True.
        # FILL IN: schedule self._process(...) as a tracked background task
        #   (wrapper._background_tasks) and return True — bounded by AC11.
        raise NotImplementedError

    async def _process(self, channel: str, user: str, thread_ts: Optional[str],
                       target: UploadTargetKind, args: Dict[str, Any], file_info: Dict[str, Any]) -> None:
        """Download, submit and relay the acknowledgement; notify posts the final outcome."""
        max_bytes = self.service.max_bytes()

        async def notify(outcome: UploadOutcome) -> None:
            await self.wrapper.post_message(channel, outcome.message, thread_ts=thread_ts)

        # FILL IN: size pre-check on file_info.get("size") → post too-large message — bounded by AC10.
        # FILL IN: data = await self._download(file_info, max_bytes); email = await self._email(user);
        #   identity = UploaderIdentity(platform="slack", platform_user_id=user, email=email);
        #   outcome = await self.service.submit(UploadRequest(...), notify);
        #   post outcome.message for ACCEPTED/DENIED/INVALID — bounded by AC3, AC5, AC11.
        raise NotImplementedError

    async def _download(self, file_info: Dict[str, Any], max_bytes: int) -> bytes:
        """GET url_private_download with Bearer bot_token, streamed with a hard byte cap."""
        url = file_info.get("url_private_download") or file_info.get("url_private")
        headers = {"Authorization": f"Bearer {self.wrapper.config.bot_token}"}
        async with ClientSession(timeout=ClientTimeout(total=120)) as session:
            async with session.get(url, headers=headers) as resp:
                resp.raise_for_status()
                # FILL IN: read resp.content.iter_chunked(64 * 1024) accumulating into a bytearray;
                #   raise ValueError("too large") once len > max_bytes — bounded by AC10.
                raise NotImplementedError

    async def _email(self, user_id: str) -> Optional[str]:
        """users.info → user.profile.email (scope users:read.email); None when unavailable."""
        data = await self.wrapper._slack_api("users.info", {"user": user_id})
        email = ((data or {}).get("user", {}).get("profile", {}) or {}).get("email", "")
        return email or None
```
**Why**: the interceptor must return quickly (Slack retries events not acked
in 3 s), so heavy work runs in `_process` as a tracked task. The download never
touches disk — bytes go straight to `submit()`, which owns staging and deletion
(AC5).

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` (MODIFY) — start/stop
```python
# occurrences: 1 (verified: grep -c '        await self._dedup.start()' slack/wrapper.py)
# AFTER — insert below `        await self._dedup.start()` (verified: slack/wrapper.py:163)
        if self.config.knowledge_upload.enabled:
            from ..knowledge_upload.service import KnowledgeUploadService
            from .knowledge_upload import SlackKnowledgeUpload

            service = await KnowledgeUploadService.from_config(self.config.knowledge_upload)
            self._knowledge_upload = SlackKnowledgeUpload(self, service)
            self._knowledge_upload.register()

# occurrences: 1 (verified: grep -c '    async def stop(self) -> None:' slack/wrapper.py)
# AFTER — insert as the first statement after the docstring of `    async def stop(self) -> None:` (verified: slack/wrapper.py:166-167)
        upload = getattr(self, "_knowledge_upload", None)
        if upload is not None:
            await upload.service.shutdown()
```
**Why**: lazy imports keep the knowledge stack out of disabled bots (spec §7);
`getattr` keeps `stop()` safe for wrappers built via `__new__` in tests. Also
add `self._knowledge_upload = None` in `__init__` after
`self._command_router = SlackCommandRouter()` (`wrapper.py:125`,
occurrences: 1).

### `slack/wrapper.py` (MODIFY) — assistant-DM interceptor
```python
# occurrences: 1 (verified: grep -c '            if event_type == "message" and event.get("channel_type") == "im":' slack/wrapper.py)
# AFTER — insert directly below that line (verified: slack/wrapper.py:288), before the subtype check at :290
                dm_channel = event.get("channel")
                dm_user = event.get("user") or "unknown"
                if (
                    event.get("files")
                    and dm_channel
                    and self._is_authorized(dm_channel, dm_user)
                    and await self._run_interceptors(event)
                ):
                    return web.json_response({"ok": True})
```
**Why**: authorize first (reuse `_is_authorized`), then first-`True`-wins via
`_run_interceptors`; unconsumed events continue to the assistant exactly as
before.

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/socket_handler.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        # Skip empty messages (e.g., file uploads with no text)' slack/socket_handler.py)
# BEFORE — insert directly above that line (verified: slack/socket_handler.py:236)
        if event.get("files") or event.get("subtype") == "file_share":
            file_channel = event.get("channel")
            file_user = event.get("user") or "unknown"
            if file_channel and self.wrapper._is_authorized(file_channel, file_user):
                if await self.wrapper._run_interceptors(event):
                    return
```
**Why**: socket mode drops text-less file uploads before the interceptors run
(`:236-239`); authorization mirrors `:242-245`. Messages not consumed keep the
existing flow (and are still dropped if empty, as today).

### `packages/ai-parrot-integrations/tests/knowledge_upload/test_slack_upload.py` (CREATE)
```python
"""Tests for the Slack knowledge-upload adapter (FEAT-647, TASK-4189)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.knowledge_upload.models import UploadTargetKind
from parrot.integrations.slack.knowledge_upload import SlackKnowledgeUpload


# FILL IN: copy _make_wrapper from tests/integrations/slack/test_slack_wrapper_hooks.py:16-60
#   and add config.knowledge_upload = KnowledgeUploadConfig(enabled=True, slack_pending_window_s=1).
# FILL IN: fake service = MagicMock(available_targets=lambda: {BOOKSTORE, WIKI},
#   max_bytes=lambda *a, **k: 1024, submit=AsyncMock(...), shutdown=AsyncMock()).
```

### FILL IN checklist
- [ ] `SlackKnowledgeUpload.on_command` — bind target per command word, arm window, ephemeral reply; AC1
- [ ] `SlackKnowledgeUpload._parse_args` — shlex grammar; AC1
- [ ] `SlackKnowledgeUpload.intercept` — prefix vs pending window vs pass-through; AC1, AC16
- [ ] `SlackKnowledgeUpload._process` — size pre-check, download, email, submit, relay; AC3, AC5, AC10, AC11
- [ ] `SlackKnowledgeUpload._download` — streamed byte cap; AC10
- [ ] tests — all cases in Test Specification

---

## Acceptance Criteria

- [ ] AC1 — `ingest_book …` / `ingest_wiki …` file messages are consumed (webhook and socket modes, including assistant-mode DMs); `/ingest_book` arms a window that consumes the next file from that user in that channel, and only within `slack_pending_window_s`.
- [ ] AC2 — non-allowed extensions are refused by the service; the adapter relays the INVALID message.
- [ ] AC3 — identity is the Slack email from `users.info`; no email ⇒ the service denies.
- [ ] AC5 — downloaded bytes never touch disk in the adapter; `download_slack_file` is not used.
- [ ] AC10 — oversize files (by `size` or by streamed count) are rejected; default 10 MB comes from the service.
- [ ] AC11 — the interceptor acknowledges immediately; the final outcome is posted with `post_message` (thread reply when `thread_ts` is known).
- [ ] AC16 — with `knowledge_upload.enabled` false nothing is registered and existing tests stay green.
- [ ] Non-file chat and dev-loop interceptors behave exactly as before (first `True` wins).
- [ ] `ruff check` clean on touched files.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/knowledge_upload/test_slack_upload.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/slack/test_slack_wrapper_hooks.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/slack/test_slack_devloop_commands.py -q`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/knowledge_upload/test_slack_upload.py
class TestSlackKnowledgeUpload:
    async def test_intercept_text_prefix(self):
        """'ingest_book' message with a file → True; service.submit called with target BOOKSTORE."""

    async def test_intercept_ignores_plain_chat(self):
        """Message without command word and without armed window → False, submit not called."""

    async def test_pending_window(self):
        """on_command arms (channel,user); next file consumed; after expiry → False."""

    async def test_pending_window_is_per_user_and_channel(self):
        """Another user / channel does not consume the window."""

    async def test_command_without_file_answers_usage(self):
        """'ingest_wiki' text with no file → True and USAGE posted."""

    async def test_oversize_rejected(self):
        """file_info size > max_bytes → no download, too-large message posted."""

    async def test_download_streamed_cap(self):
        """Streamed body larger than max_bytes raises / is rejected (aiohttp mocked)."""

    async def test_email_from_users_info(self):
        """_slack_api('users.info') mocked → email used in UploaderIdentity."""

    async def test_only_available_targets_registered(self):
        """available_targets() == {BOOKSTORE} → only ingest_book registered."""

    async def test_assistant_dm_runs_interceptors(self):
        """Webhook assistant-mode DM with files: interceptor consumes it, assistant not called."""

    async def test_socket_file_without_text_reaches_interceptor(self):
        """SlackSocketHandler._handle_event: file_share with empty text → interceptor consulted."""
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug teams-telegram-uploader-bookstore --feature-id FEAT-647`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-4183 and TASK-4186 must be `"done"` in
   `sdd/tasks/index/teams-telegram-uploader-bookstore.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/teams-telegram-uploader-bookstore.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4189 teams-telegram-uploader-bookstore verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
