# TASK-4187: Telegram adapter — `/ingest_book` and `/ingest_wiki`

**Feature**: FEAT-647 — Chat-driven document upload into Bookstore / LLM Wiki
**Spec**: `sdd/specs/teams-telegram-uploader-bookstore.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4183, TASK-4186
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (and §2 Overview "User-facing behavior" / "Identity"). The
Telegram wrapper must let an authorized, logged-in user send a PDF/DOCX/MD in
a private chat with caption `/ingest_book …` or `/ingest_wiki …` (or reply to
an already-sent document with the command). The adapter resolves identity
from the navigator-auth session, downloads the bytes **into memory**
(never the `tg_doc_` temp file the default `handle_document` leaks), and hands
an `UploadRequest` to `KnowledgeUploadService.submit()` (TASK-4183). The
default document handler must never see these messages.

---

## Scope

- Create `telegram/knowledge_upload.py` with `TelegramKnowledgeUpload` and
  `parse_ingest_args` (spec §3 M8 skeleton).
- Register, inside `_register_handlers`, **before** the operator/group/text/
  document handlers (aiogram dispatches in registration order):
  1. caption command on a `DOCUMENT` message (private chat),
  2. command in a `TEXT` message that replies to a document (private chat),
  3. bare command without a document → usage help.
  Only commands whose target is configured (`config.knowledge_upload.bookstore`
  / `.wiki` not `None`) are registered and added to the menu via
  `_add_platform_commands`.
- Build the service lazily (first use, under an `asyncio.Lock`) with
  `await KnowledgeUploadService.from_config(config.knowledge_upload)`;
  a target that is configured but unavailable answers "not available".
- Require `session.authenticated and session.nav_user_id` in the handler
  itself, independently of `force_authentication` (AC4 of the spec).
- Shut the service down from `TelegramAgentWrapper.close()`.
- Tests with fake wrapper/bot/service — no Telegram network.

**NOT in scope**: changes to `handle_document`, `force_authentication`
defaults, the service/targets (TASK-4183/4184/4185), Teams/Slack, group chats,
wiring `close()` into `IntegrationBotManager` (it is not called today —
manager.py:1008 only closes the bot session; the staging sweep in
`from_config` covers crashes).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/knowledge_upload.py` | CREATE | adapter + arg parser |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | register handlers in `_register_handlers`; shutdown in `close()` |
| `packages/ai-parrot-integrations/tests/knowledge_upload/test_telegram_upload.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiogram import Bot, Router, F                    # telegram/wrapper.py:21
from aiogram.enums import ChatType                     # telegram/wrapper.py:22
from aiogram.filters import Command                    # telegram/wrapper.py:37
from aiogram.filters.command import CommandObject     # .venv aiogram 3.31.0, filters/command.py (class CommandObject; fields prefix/command/args :208-214)
from aiogram.types import ContentType, Message         # telegram/wrapper.py:23-25 (ContentType imported from aiogram.types)
from parrot.integrations.knowledge_upload.models import (   # TASK-4182 (spec §2 Data Models)
    KnowledgeUploadConfig, UploaderIdentity, UploadRequest, UploadOutcome, UploadStatus, UploadTargetKind,
)
from parrot.integrations.knowledge_upload.service import KnowledgeUploadService   # TASK-4183 (spec §3 M1)
```

### Existing Signatures to Use
```python
# aiogram 3.31.0 (installed in .venv)
# filters/command.py:109  async def __call__(self, message: Message, bot: Bot) -> bool | dict[str, Any]:
# filters/command.py:113      text = message.text or message.caption      ← captions ARE matched
# filters/command.py:121      result = {"command": command}               ← handler receives `command: CommandObject`
# client/bot.py:419  async def download_file(self, file_path: str | pathlib.Path,
#                        destination: BinaryIO | pathlib.Path | str | None = None, timeout: int = 30,
#                        chunk_size: int = 65536, seek: bool = True) -> BinaryIO | None

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
class TelegramAgentWrapper(OperatorCommandsMixin):                      # :70
    def __init__(self, agent, bot: Bot, config: TelegramAgentConfig, agent_commands: list = None, *, app=None)  # :123
    self.bot = bot (:133); self.config = config (:134); self.router = Router() (:140)
    self.logger = logging.getLogger(f"TelegramWrapper.{config.name}")  # :142
    self._platform_commands: list[tuple[str, str]] = []                 # :174
    self._register_handlers()                                           # :229 (called from __init__)
    def _register_handlers(self) -> None:                               # :231
    #   operator block anchor  `        # ─── Operator Commands (FEAT-210) — before generic text handler ───`  :289
    #   generic private TEXT handler handle_message registered at :318-322
    #   default DOCUMENT handler handle_document registered at :333-338
    def _add_platform_commands(self, entries: list[tuple[str, str]]) -> None:   # :368
    def _is_authorized(self, chat_id: int) -> bool:                     # :1044
    def _get_user_session(self, message: Message) -> TelegramUserSession:   # :1080
    async def handle_document(self, message: Message) -> None:          # :3146 (size check pattern :3171-3179)
    async def close(self) -> None:                                      # :3287 (ends with synthesizer close :3300-3302)

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py
class TelegramUserSession:                                              # :44
    nav_user_id: Optional[str] = None (:52); nav_email: Optional[str] = None (:55); authenticated: bool = False (:56)
```

Service contract (TASK-4183, spec §3 M1 skeleton — binding):
`KnowledgeUploadService.from_config(config) -> KnowledgeUploadService` (async classmethod),
`.available_targets() -> set[UploadTargetKind]`, `.max_bytes(platform_cap_mb=None) -> int`,
`.submit(request, notify) -> UploadOutcome`, `.shutdown()`;
`Notify = Callable[[UploadOutcome], Awaitable[None]]`.

### Does NOT Exist
- ~~Telegram knowledge-upload handlers~~ — this task adds them
- ~~Groups/roles on `TelegramUserSession`~~ — groups come from `UserInfoService` inside the service
- ~~`IntegrationBotManager` calling `TelegramAgentWrapper.close()`~~ (manager.py:1008 closes only `bot.session`)
- ~~`TelegramAgentWrapper._knowledge_upload`~~ — this task adds it
- ~~Using `@telegram_command` for these commands~~ — decorated methods get no message/session (decorators.py:5); do not use it

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/knowledge_upload.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/knowledge_upload/test_telegram_upload.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._register_handlers",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._add_platform_commands",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._is_authorized",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._get_user_session",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper.close",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py#TelegramUserSession"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Edit-site drift vs spec §6**: the spec anchors the registration at
  `# Document messages (private only for now)` (wrapper.py:333). That is too
  late — the generic private TEXT handler (`handle_message`, :318-322) would
  swallow a text reply `/ingest_book`. Register at the operator-commands
  anchor (:289) instead, which the wrapper itself documents as "before generic
  text handler".
- **Skeleton extension**: the spec skeleton is `__init__(wrapper, service)`;
  because the service is built asynchronously and handlers register in the
  synchronous `__init__`, the signature is `__init__(wrapper, service=None)`
  with lazy `_get_service()`. Tests inject the fake service through `service=`.
- Telegram Bot API cannot download > 20 MB → `service.max_bytes(platform_cap_mb=20)`.
- Never write the bytes to disk here (spec G4/AC5); `io.BytesIO` only.
- Replies never echo allow-lists, paths or tracebacks (spec §7).
- `self.logger` only; no `print`.

---

## Implementation Blueprint

### Steps (in order)
1. Create `telegram/knowledge_upload.py` from the block below — *why*: keeps the 3.5k-line wrapper diff to two small inserts.
2. Insert the registration block at the operator anchor — *why*: aiogram matches in registration order; it must precede the TEXT and DOCUMENT handlers.
3. Append the shutdown call at the end of `close()` — *why*: cancel running jobs so the staging `finally` deletes files.
4. Write tests; run validation — *why*: AC1–AC7.

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/knowledge_upload.py` (CREATE)
```python
"""Telegram commands for chat-driven knowledge upload (FEAT-647)."""
from __future__ import annotations

import asyncio
import io
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import ContentType, Message

from parrot.integrations.knowledge_upload.models import (
    UploaderIdentity, UploadOutcome, UploadRequest, UploadTargetKind,
)
from parrot.integrations.knowledge_upload.service import KnowledgeUploadService

if TYPE_CHECKING:
    from .wrapper import TelegramAgentWrapper

TELEGRAM_MAX_DOWNLOAD_MB = 20
COMMANDS: dict[str, UploadTargetKind] = {
    "ingest_book": UploadTargetKind.BOOKSTORE,
    "ingest_wiki": UploadTargetKind.WIKI,
}


def parse_ingest_args(text: str) -> dict[str, Any]:
    """Parse ``--force``, ``--title``, repeatable ``--author`` / ``--topic`` (shlex quoting)."""
    # FILL IN: shlex.split(text or ""); unknown tokens ignored; return
    #   {"force": bool, "title": str|None, "authors": list[str], "topics": list[str]} — bounded by spec §2 user-facing syntax
    raise NotImplementedError


class TelegramKnowledgeUpload:
    """Registers /ingest_book and /ingest_wiki on the wrapper's router."""

    def __init__(self, wrapper: "TelegramAgentWrapper", service: Optional[KnowledgeUploadService] = None) -> None:
        self.wrapper = wrapper
        self.config = wrapper.config.knowledge_upload
        self.logger = wrapper.logger
        self._service = service
        self._service_lock = asyncio.Lock()

    def configured_commands(self) -> dict[str, UploadTargetKind]:
        """Commands whose target block is present in the config."""
        return {
            name: kind for name, kind in COMMANDS.items()
            if (kind is UploadTargetKind.BOOKSTORE and self.config.bookstore is not None)
            or (kind is UploadTargetKind.WIKI and self.config.wiki is not None)
        }

    def register(self, router: Router) -> list[tuple[str, str]]:
        """Register handlers (private chats) and return menu entries for _add_platform_commands."""
        names = list(self.configured_commands())
        if not names:
            return []
        private = F.chat.type == ChatType.PRIVATE
        router.message.register(self._on_document, Command(*names), private, F.content_type == ContentType.DOCUMENT)
        router.message.register(self._on_reply, Command(*names), private, F.reply_to_message.document)
        router.message.register(self._on_usage, Command(*names), private)
        descriptions = {"ingest_book": "Upload a document to the Bookstore", "ingest_wiki": "Upload a document to the wiki"}
        return [(name, descriptions[name]) for name in names]

    async def _get_service(self) -> KnowledgeUploadService:
        if self._service is None:
            async with self._service_lock:
                if self._service is None:
                    self._service = await KnowledgeUploadService.from_config(self.config)
        return self._service

    async def _on_document(self, message: Message, command: CommandObject) -> None:
        await self.handle(message, COMMANDS[command.command], message.document, command.args or "")

    async def _on_reply(self, message: Message, command: CommandObject) -> None:
        await self.handle(message, COMMANDS[command.command], message.reply_to_message.document, command.args or "")

    async def _on_usage(self, message: Message, command: CommandObject) -> None:
        await message.answer(f"Attach a PDF, DOCX or Markdown file with the caption /{command.command}, "
                             f"or reply to a document with /{command.command}.")

    async def shutdown(self) -> None:
        """Cancel running upload jobs (no-op when the service was never built)."""
        if self._service is not None:
            await self._service.shutdown()
```
**Why this shape**: three registrations cover caption, reply and bare command
(spec §2); `configured_commands` implements "menu entries only for configured
targets"; the lazy service honors the async `from_config` (skeleton extension
noted above).

```python
# continued — same file: the handler (keep in the class)
    async def handle(self, message: Message, target: UploadTargetKind, document: Any, args_text: str) -> None:
        """Authorize, download into memory and submit; never touches the default document path."""
        chat_id = message.chat.id
        if not self.wrapper._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return
        session = self.wrapper._get_user_session(message)
        if not (session.authenticated and session.nav_user_id):
            await message.answer("🔒 Sign in with /login before uploading knowledge.")
            return
        service = await self._get_service()
        if target not in service.available_targets():
            await message.answer("This upload target is not available right now.")
            return
        max_bytes = service.max_bytes(platform_cap_mb=TELEGRAM_MAX_DOWNLOAD_MB)
        filename = document.file_name or "document"
        # FILL IN: reject before download when Path(filename).suffix.lower() not in self.config.allowed_extensions
        #   or document.file_size > max_bytes (message names the limit in MB) — bounded by spec AC2/AC10
        buffer = io.BytesIO()
        file = await self.wrapper.bot.get_file(document.file_id)
        await self.wrapper.bot.download_file(file.file_path, buffer)
        data = buffer.getvalue()
        # FILL IN: reject when len(data) > max_bytes (size may be unknown before download) — bounded by AC10
        options = parse_ingest_args(args_text)
        identity = UploaderIdentity(
            platform="telegram", platform_user_id=str(message.from_user.id),
            nav_user_id=session.nav_user_id, email=session.nav_email,
        )
        request = UploadRequest(target=target, identity=identity, filename=filename, data=data, **options)

        async def notify(outcome: UploadOutcome) -> None:
            await message.answer(outcome.message)

        outcome = await service.submit(request, notify)
        await message.answer(outcome.message)
```
**Why**: identity check is in the handler (defense in depth, spec AC4);
download into `BytesIO` (spec G4/AC5); `submit` returns ACCEPTED/DENIED/INVALID
synchronously and the job later calls `notify` (spec G6).

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        # ─── Operator Commands (FEAT-210) — before generic text handler ───' telegram/wrapper.py)
# BEFORE — insert above that line (verified: telegram/wrapper.py:289)
        # ─── Knowledge upload (FEAT-647) — before generic text/document handlers ───
        self._knowledge_upload = None
        if self.config.knowledge_upload.enabled:
            from .knowledge_upload import TelegramKnowledgeUpload

            self._knowledge_upload = TelegramKnowledgeUpload(self)
            self._add_platform_commands(self._knowledge_upload.register(self.router))

# occurrences: 1 (verified: grep -c '            await self._synthesizer.close()' telegram/wrapper.py)
# AFTER — insert below the two lines
#             await self._synthesizer.close()
#             self._synthesizer = None          (verified: telegram/wrapper.py:3301-3302, end of close())
        # FEAT-647: cancel running knowledge-upload jobs (their finally deletes staged files)
        if getattr(self, "_knowledge_upload", None) is not None:
            await self._knowledge_upload.shutdown()
```
**Why**: the lazy import keeps the knowledge stack out of bots that do not
enable the feature (spec §7 "Lazy imports"); `getattr` guards wrappers built
by tests that bypass `_register_handlers`. Indentation: the shutdown lines are
at method-body level (8 spaces), not inside the `if self._synthesizer` block.

### `packages/ai-parrot-integrations/tests/knowledge_upload/test_telegram_upload.py` (CREATE)
```python
"""FEAT-647 TASK-4187 — Telegram knowledge upload adapter (no network)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.knowledge_upload.models import (
    KnowledgeUploadConfig, UploadOutcome, UploadStatus, UploadTargetKind,
)
from parrot.integrations.telegram.knowledge_upload import TelegramKnowledgeUpload, parse_ingest_args


class FakeService:
    """Records submitted requests; returns ACCEPTED."""
    def __init__(self, targets=(UploadTargetKind.BOOKSTORE, UploadTargetKind.WIKI)):
        self.targets = set(targets)
        self.requests = []
    def available_targets(self):
        return self.targets
    def max_bytes(self, platform_cap_mb=None):
        return 10 * 1024 * 1024
    async def submit(self, request, notify):
        self.requests.append(request)
        return UploadOutcome(job_id="j1", status=UploadStatus.ACCEPTED, target=request.target,
                             filename=request.filename, message="Processing…")
    async def shutdown(self):
        pass


@pytest.fixture
def wrapper():
    # FILL IN: SimpleNamespace with config.knowledge_upload (enabled, bookstore+wiki configured), logger,
    #   _is_authorized -> True, _get_user_session -> authenticated session with nav_user_id/nav_email,
    #   bot.get_file / bot.download_file AsyncMocks writing b"%PDF-1.4" into the buffer — bounded by AC1
    ...


def test_parse_ingest_args_quoting():
    opts = parse_ingest_args('--force --title "Odoo 17 Manual" --author A --author B --topic sales')
    assert opts == {"force": True, "title": "Odoo 17 Manual", "authors": ["A", "B"], "topics": ["sales"]}


async def test_caption_submits_in_memory_bytes(wrapper):
    ...  # FILL IN: handle(message, BOOKSTORE, document, "--force") → one request, data bytes, nav identity — AC1/AC3


async def test_reply_to_document_submits(wrapper):
    ...  # FILL IN: _on_reply with reply_to_message.document — AC2


async def test_unauthenticated_session_denied(wrapper):
    ...  # FILL IN: session.authenticated False → login message, service.submit not called — AC4


async def test_oversize_and_bad_extension_rejected_before_download(wrapper):
    ...  # FILL IN: file_size > max_bytes and "x.exe" → no get_file call — AC5


def test_register_only_configured_commands():
    ...  # FILL IN: config with only bookstore → register() returns [("ingest_book", …)] — AC6
```
**Why**: the fake service isolates the adapter from TASK-4183 internals; no
aiogram Dispatcher or network is needed because handlers are plain coroutines.

### FILL IN checklist
- [ ] `parse_ingest_args` — shlex parsing, repeatable flags; bounded by spec §2 syntax
- [ ] `handle` — extension/size pre-check before download; bounded by AC5
- [ ] `handle` — post-download size check; bounded by spec AC10
- [ ] tests — fixture + five test bodies; bounded by AC1–AC6

---

## Acceptance Criteria

- [ ] AC1 — A private-chat document with caption `/ingest_book` or `/ingest_wiki` produces one `UploadRequest` with the downloaded bytes, the correct target and parsed options.
- [ ] AC2 — A text `/ingest_*` replying to a document message does the same for the replied document.
- [ ] AC3 — The request identity is `platform="telegram"`, `nav_user_id`/`email` from the session.
- [ ] AC4 — Unauthenticated sessions or sessions without `nav_user_id` are refused in the handler, regardless of `force_authentication`.
- [ ] AC5 — Wrong extension or a known size above `min(max_size_mb, 20)` MB is rejected before download; no file is written to disk by the adapter and `handle_document` is never invoked for these messages.
- [ ] AC6 — Only configured targets are registered and added to the menu; nothing is registered when `knowledge_upload.enabled` is false.
- [ ] AC7 — `close()` shuts the service down; `ruff check` clean on touched files.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/knowledge_upload/test_telegram_upload.py -q`
- `pytest packages/ai-parrot-integrations/tests/knowledge_upload/test_config_fields.py -q`

---

## Test Specification

See the CREATE test block above. Handlers are invoked directly with
`SimpleNamespace`/`MagicMock` messages (`chat.id`, `from_user.id`,
`document.file_name/file_size/file_id`, `reply_to_message`, `answer=AsyncMock()`);
`bot.download_file` is an `AsyncMock` whose side effect writes bytes into the
passed buffer. No real Telegram, no `KnowledgeUploadService.from_config`
(inject `FakeService` via `service=`).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug teams-telegram-uploader-bookstore --feature-id FEAT-647`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-4183 and TASK-4186 must be `"done"` in
   `sdd/tasks/index/teams-telegram-uploader-bookstore.json`
4. **Verify the Codebase Contract** — re-run every `grep -c`; confirm the final
   names TASK-4182/4183 shipped (`UploadRequest` fields, `submit`, `max_bytes`)
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
7. **Verify** with the Validation Commands (prefix `PYTHONPATH=packages/ai-parrot-integrations/src:packages/ai-parrot/src` inside the worktree)
8. **Commit the code** — stage only the files listed above
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4187 teams-telegram-uploader-bookstore verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
