# TASK-4188: MS Teams adapter — `/ingest_book` and `/ingest_wiki`

**Feature**: FEAT-647 — Chat-driven document upload into Bookstore / LLM Wiki
**Spec**: `sdd/specs/teams-telegram-uploader-bookstore.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4183, TASK-4186
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (and §2 "User-facing behavior" / "Identity"). In Teams the
user sends a message with a file attachment whose text is `/ingest_book …` or
`/ingest_wiki …`. `MSTeamsAgentWrapper.on_message_activity` already dispatches
`/commands` through `MSTeamsCommandRouter` (wrapper.py:570) **before** the
loop that stores every attachment in `SessionFileStore` (wrapper.py:608-610),
so a registered command handler that returns normally keeps the file out of
the persistent store (spec AC5). The handler resolves the uploader's email
(`TeamsInfo.get_member`), downloads the bytes into memory with a streamed
size cap, submits an `UploadRequest` to `KnowledgeUploadService` (TASK-4183)
and later notifies through a proactive message (`continue_conversation`),
because the ingest outlives the turn.

---

## Scope

- Create `msteams/commands/knowledge_upload.py` with
  `register_knowledge_upload_commands(router, wrapper, service=None)` and a
  small `TeamsKnowledgeUpload` holder (lazy service, handlers).
- Register only commands whose target block is configured.
- Pick the file attachment: prefer
  `application/vnd.microsoft.teams.file.download.info` (pre-authenticated
  `content["downloadUrl"]`, no auth header); else the first attachment with a
  `content_url` that is not `text/html` / an adaptive card (bot token from
  `wrapper._get_attachment_token`).
- Stream the download with aiohttp and abort past `service.max_bytes()`.
- Identity: `TeamsInfo.get_member(turn_context, activity.from_property.id)` →
  `email or user_principal_name`; failure/missing → deny "identity could not
  be verified".
- Notify via `wrapper.adapter.continue_conversation(conv_ref, callback,
  wrapper.config.client_id)`; without `client_id` log a warning (the
  acknowledgement was already sent in-turn).
- Wire it in `MSTeamsAgentWrapper.__init__` right after the agent commands.
- Tests with mocks — no Teams/Graph network.

**NOT in scope**: changing `_handle_document_attachment` / `SessionFileStore`
behavior for normal messages, `IntegrationBotManager` shutdown wiring (the
staging sweep covers crashes), Telegram/Slack, the service and targets.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/knowledge_upload.py` | CREATE | command handlers |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | register the commands after `agent_cmd_handler.register` |
| `packages/ai-parrot-integrations/tests/knowledge_upload/test_msteams_upload.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import aiohttp                                                   # msteams/wrapper.py:16
from botbuilder.core import TurnContext                          # msteams/wrapper.py:18-24
from botbuilder.core.teams import TeamsInfo                      # .venv botbuilder/core/teams/__init__.py:9
from botbuilder.schema import Activity, Attachment               # msteams/wrapper.py:26
from parrot.integrations.msteams.commands import MSTeamsCommandRouter   # msteams/wrapper.py:44
from parrot.integrations.knowledge_upload.models import (       # TASK-4182 (spec §2)
    UploaderIdentity, UploadOutcome, UploadRequest, UploadTargetKind,
)
from parrot.integrations.knowledge_upload.service import KnowledgeUploadService   # TASK-4183 (spec §3 M1)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
class MSTeamsAgentWrapper(ActivityHandler, MessageHandler):                   # :94
    self.config: MSTeamsAgentConfig; self.logger = logging.getLogger(f"MSTeamsWrapper.{config.name}")
    self.adapter = Adapter(config=..., logger=..., conversation_state=...)    # :174 (Adapter(CloudAdapter), adapter.py:18)
    self._command_router: MSTeamsCommandRouter = MSTeamsCommandRouter()       # :180
    agent_cmd_handler.register(self._command_router)                          # :182
    async def on_message_activity(self, turn_context: TurnContext)           # :547 — try_dispatch :570 BEFORE attachment store loop :608-610
    def _remove_mentions(self, activity: Activity, text: str) -> str:        # :761
    def _find_document_attachments(self, activity: Activity) -> list[Attachment]:   # :827 (skips audio and attachments without content_url)
    async def _get_attachment_token(self, turn_context: TurnContext) -> Optional[str]:   # :964
# msteams/handler.py:35  async def send_text(self, text: str, turn_context: TurnContext)   (MessageHandler mixin)
# msteams/models.py:33   client_id: Optional[str] = None

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py
class MSTeamsCommandRouter:                                                   # :30
    def register(self, command: str, handler: Callable) -> None:             # :56 — handler: async (turn_context) -> None
    async def try_dispatch(self, text: str, turn_context) -> bool:           # :74 — text must start with "/", cmd = first token
# Handler arg parsing precedent: AgentCommandHandler._extract_text (commands/agent_commands.py:63-66)
#   text = turn_context.activity.text or ""; self.wrapper._remove_mentions(turn_context.activity, text).strip()

# botbuilder (installed .venv)
# core/teams/teams_info.py:257-260  @staticmethod async def get_member(turn_context: TurnContext, member_id: str) -> TeamsChannelAccount
# schema/teams/_models_py3.py:1916-1917  TeamsChannelAccount.email (str), .user_principal_name (str)
# core/turn_context.py:321  @staticmethod def get_conversation_reference(activity: Activity) -> ConversationReference
# core/cloud_adapter_base.py:149  async def continue_conversation(self, reference, callback: Callable, bot_app_id: str = None, ...)
# Proactive precedent: msteams/oauth_callback.py:127  await self._adapter.continue_conversation(conv_ref, _callback, self._app_id)
# Conversation-reference precedent: msteams/commands/jira_commands.py:146  TurnContext.get_conversation_reference(turn_context.activity)
```

### Does NOT Exist
- ~~`TeamsInfo` usage elsewhere in `parrot.integrations`~~ — first use; API verified only against the installed botbuilder
- ~~A Teams command decorator or identity-aware router~~ — handlers receive only `turn_context`
- ~~A size field on `file.download.info` attachments~~ — size is unknown before download; stream with a cap
- ~~`MSTeamsAgentWrapper.close()`~~ — only `close_formdesigner_client` / `close_voice_transcriber` exist (called by manager.py:1034-1044)
- ~~`MSTeamsAgentWrapper._knowledge_upload`~~ — this task adds it

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/knowledge_upload.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/knowledge_upload/test_msteams_upload.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper._remove_mentions",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper._get_attachment_token",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py#MSTeamsCommandRouter.register",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/handler.py#MessageHandler.send_text"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Skeleton extension**: spec skeleton is
  `register_knowledge_upload_commands(router, wrapper, service)`; `service`
  becomes optional (`None` → built lazily with `from_config` on first use,
  under an `asyncio.Lock`) because `__init__` is synchronous. Tests inject a
  fake.
- Ignore `text/html` attachments — Teams adds the message body as one.
- Never write bytes to disk; never call `_handle_document_attachment` /
  `SessionFileStore` here (spec AC5).
- The open question in spec §8 (which attachment shape real tenants send)
  is resolved in code by supporting both shapes; record what you can confirm
  in the Completion Note.

---

## Implementation Blueprint

### Steps (in order)
1. Create `commands/knowledge_upload.py` — *why*: keeps wrapper.py changes to one insert.
2. Insert the registration after `agent_cmd_handler.register(...)` — *why*: router must know the commands before the first turn.
3. Write tests; run validation — *why*: AC1–AC7.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/knowledge_upload.py` (CREATE)
```python
"""MS Teams commands for chat-driven knowledge upload (FEAT-647)."""
from __future__ import annotations

import asyncio
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import aiohttp
from botbuilder.core import TurnContext
from botbuilder.core.teams import TeamsInfo
from botbuilder.schema import Activity, Attachment

from parrot.integrations.knowledge_upload.models import (
    UploaderIdentity, UploadOutcome, UploadRequest, UploadTargetKind,
)
from parrot.integrations.knowledge_upload.service import KnowledgeUploadService

if TYPE_CHECKING:
    from parrot.integrations.msteams.commands import MSTeamsCommandRouter

FILE_DOWNLOAD_INFO = "application/vnd.microsoft.teams.file.download.info"
COMMANDS: dict[str, UploadTargetKind] = {
    "ingest_book": UploadTargetKind.BOOKSTORE,
    "ingest_wiki": UploadTargetKind.WIKI,
}


class TeamsKnowledgeUpload:
    """Holds the lazily-built service and the two command handlers."""

    def __init__(self, wrapper: Any, service: Optional[KnowledgeUploadService] = None) -> None:
        self.wrapper = wrapper
        self.config = wrapper.config.knowledge_upload
        self.logger = wrapper.logger
        self._service = service
        self._service_lock = asyncio.Lock()

    async def _get_service(self) -> KnowledgeUploadService:
        if self._service is None:
            async with self._service_lock:
                if self._service is None:
                    self._service = await KnowledgeUploadService.from_config(self.config)
        return self._service

    @staticmethod
    def pick_attachment(activity: Activity) -> Optional[Attachment]:
        """First file attachment: file.download.info first, else any non-HTML attachment with content_url."""
        # FILL IN: iterate activity.attachments; skip "text/html" and adaptive cards — bounded by spec §7 Teams risk
        raise NotImplementedError

    async def download(self, turn_context: TurnContext, attachment: Attachment, max_bytes: int) -> Optional[bytes]:
        """Stream the file into memory; None when the cap is exceeded or the HTTP status is not 200."""
        if attachment.content_type == FILE_DOWNLOAD_INFO:
            url, headers = (attachment.content or {}).get("downloadUrl"), {}
        else:
            token = await self.wrapper._get_attachment_token(turn_context)
            url, headers = attachment.content_url, ({"Authorization": f"Bearer {token}"} if token else {})
        # FILL IN: aiohttp.ClientSession GET; iterate resp.content.iter_chunked(65536); abort (return None) when
        #   the running total exceeds max_bytes — bounded by spec AC10
        raise NotImplementedError

    async def resolve_email(self, turn_context: TurnContext) -> Optional[str]:
        """Member email/UPN via TeamsInfo.get_member; None on any failure (caller denies)."""
        try:
            member = await TeamsInfo.get_member(turn_context, turn_context.activity.from_property.id)
        except Exception:  # noqa: BLE001 - roster lookup failure means identity cannot be verified
            self.logger.warning("Teams member lookup failed", exc_info=True)
            return None
        return getattr(member, "email", None) or getattr(member, "user_principal_name", None)
```
**Why this shape**: both attachment shapes are supported (spec §8 open item);
the lookup failure denies instead of raising (spec §2 "Profile not found ⇒ deny").

```python
# continued — same file: the handler and the registration function
    async def handle(self, turn_context: TurnContext, target: UploadTargetKind) -> None:
        """Validate, download into memory, submit; proactive notify when the job ends."""
        text = self.wrapper._remove_mentions(turn_context.activity, turn_context.activity.text or "").strip()
        args_text = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
        service = await self._get_service()
        if target not in service.available_targets():
            await self.wrapper.send_text("This upload target is not available right now.", turn_context)
            return
        attachment = self.pick_attachment(turn_context.activity)
        if attachment is None:
            await self.wrapper.send_text(f"Attach a PDF, DOCX or Markdown file to the {text.split()[0]} message.",
                                         turn_context)
            return
        filename = attachment.name or "document"
        # FILL IN: reject when Path(filename).suffix.lower() not in self.config.allowed_extensions — bounded by spec AC2
        email = await self.resolve_email(turn_context)
        # FILL IN: email None → send "identity could not be verified" and return — bounded by spec AC3
        data = await self.download(turn_context, attachment, service.max_bytes())
        # FILL IN: data None → send size/download error (limit in MB) and return — bounded by spec AC10
        # FILL IN: options = shlex-parse args_text into {"force", "title", "authors", "topics"} (same flags as
        #   TASK-4187) — do NOT import parrot.integrations.telegram (pulls aiogram) — bounded by spec §2 syntax
        identity = UploaderIdentity(platform="msteams", platform_user_id=turn_context.activity.from_property.id,
                                    email=email)
        request = UploadRequest(target=target, identity=identity, filename=filename, data=data, **options)
        conv_ref = TurnContext.get_conversation_reference(turn_context.activity)

        async def notify(outcome: UploadOutcome) -> None:
            if not self.wrapper.config.client_id:
                self.logger.warning("No client_id: cannot deliver upload outcome %s proactively", outcome.job_id)
                return

            async def _callback(ctx: TurnContext) -> None:
                await ctx.send_activity(outcome.message)

            await self.wrapper.adapter.continue_conversation(conv_ref, _callback, self.wrapper.config.client_id)

        outcome = await service.submit(request, notify)
        await self.wrapper.send_text(outcome.message, turn_context)


def register_knowledge_upload_commands(router: "MSTeamsCommandRouter", wrapper: Any,
                                       service: Optional[KnowledgeUploadService] = None) -> TeamsKnowledgeUpload:
    """Register configured /ingest_* commands; returns the holder (stored on the wrapper)."""
    holder = TeamsKnowledgeUpload(wrapper, service)
    # FILL IN: for name, kind in COMMANDS where the target block (config.bookstore / config.wiki) is set:
    #   router.register(name, <async (turn_context) -> holder.handle(turn_context, kind)>) — bounded by spec AC6
    return holder
```
**Why**: in-turn reply carries ACCEPTED/DENIED/INVALID; the final outcome
arrives later via `continue_conversation` (spec G6 / AC11). Bind `kind` per
command explicitly (avoid the late-binding closure bug in the loop).

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        agent_cmd_handler.register(self._command_router)' msteams/wrapper.py)
# AFTER — insert below `        agent_cmd_handler.register(self._command_router)` (verified: msteams/wrapper.py:182)

        # Chat-driven knowledge upload (FEAT-647) — /ingest_book, /ingest_wiki
        self._knowledge_upload = None
        if config.knowledge_upload.enabled:
            from .commands.knowledge_upload import register_knowledge_upload_commands

            self._knowledge_upload = register_knowledge_upload_commands(self._command_router, self)
```
**Why**: lazy import keeps the knowledge stack out of bots without the
feature (spec §7); `config` is the constructor argument already in scope.

### `packages/ai-parrot-integrations/tests/knowledge_upload/test_msteams_upload.py` (CREATE)
```python
"""FEAT-647 TASK-4188 — MS Teams knowledge upload adapter (no network)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.knowledge_upload.models import (
    KnowledgeUploadConfig, UploadOutcome, UploadStatus, UploadTargetKind,
)
from parrot.integrations.msteams.commands import MSTeamsCommandRouter
from parrot.integrations.msteams.commands.knowledge_upload import (
    FILE_DOWNLOAD_INFO, TeamsKnowledgeUpload, register_knowledge_upload_commands,
)


class FakeService:
    """Records submissions; returns ACCEPTED (same shape as TASK-4187's fake)."""
    # FILL IN: available_targets / max_bytes / submit / shutdown — bounded by TASK-4183 contract


@pytest.fixture
def wrapper():
    # FILL IN: SimpleNamespace(config=SimpleNamespace(knowledge_upload=KnowledgeUploadConfig(enabled=True,
    #   bookstore=..., wiki=...), client_id="app-id"), logger=MagicMock(), _remove_mentions=lambda a, t: t,
    #   _get_attachment_token=AsyncMock(return_value="tok"), send_text=AsyncMock(),
    #   adapter=SimpleNamespace(continue_conversation=AsyncMock())) — bounded by AC1
    ...


def test_register_only_configured_commands(wrapper):
    ...  # FILL IN: only bookstore configured → router.registered_commands == ["ingest_book"] — AC6


def test_pick_attachment_prefers_download_info():
    ...  # FILL IN: [text/html, file.download.info, other] → file.download.info — AC1


async def test_download_variants_and_cap(wrapper):
    ...  # FILL IN: patch aiohttp.ClientSession; downloadUrl without auth header; content_url with Bearer;
         #   body > max_bytes → None — AC1/AC4


async def test_no_attachment_usage(wrapper):
    ...  # FILL IN: no attachments → usage text, submit not called — AC2


async def test_identity_failure_denies(wrapper):
    ...  # FILL IN: patch TeamsInfo.get_member to raise → "identity could not be verified", no submit — AC3


async def test_notify_uses_continue_conversation(wrapper):
    ...  # FILL IN: capture notify from FakeService.submit, await it → adapter.continue_conversation called
         #   with client_id — AC5
```

### FILL IN checklist
- [ ] `pick_attachment` — selection order; bounded by spec §7 Teams risk
- [ ] `download` — streamed cap; bounded by spec AC10
- [ ] `handle` — extension check, identity denial, size error, arg parsing; bounded by spec AC2/AC3/AC10
- [ ] `register_knowledge_upload_commands` — per-command closures for configured targets; bounded by AC6
- [ ] tests — fake service, fixture and six test bodies; bounded by AC1–AC6

---

## Acceptance Criteria

- [ ] AC1 — A Teams message `/ingest_book …` / `/ingest_wiki …` with a file attachment submits one `UploadRequest` with the in-memory bytes; both `file.download.info` (`downloadUrl`) and `content_url`+bot-token shapes work.
- [ ] AC2 — Command without a usable attachment → usage text; wrong extension → rejected; nothing submitted.
- [ ] AC3 — Identity is `platform="msteams"` + member email/UPN; lookup failure or missing email → denied with "identity could not be verified".
- [ ] AC4 — Downloads stop as soon as `min(max_size_mb)` bytes are exceeded; no file is written to disk and the attachment never reaches `SessionFileStore` (the router returns before wrapper.py:608).
- [ ] AC5 — The final outcome is delivered with `adapter.continue_conversation(ref, cb, client_id)`; without `client_id` a warning is logged and nothing raises.
- [ ] AC6 — Only configured targets are registered; nothing when `knowledge_upload.enabled` is false.
- [ ] AC7 — `ruff check` clean on touched files; existing `tests/msteams/*` still pass.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/knowledge_upload/test_msteams_upload.py -q`
- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wrapper.py -q`

---

## Test Specification

See the CREATE test block above. `turn_context` is a `SimpleNamespace` with
`activity` (`text`, `attachments`, `from_property.id`, conversation fields
needed by `get_conversation_reference` — or patch that static method).
`aiohttp.ClientSession` and `TeamsInfo.get_member` are patched; no Bot
Framework or Graph network calls.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug teams-telegram-uploader-bookstore --feature-id FEAT-647`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-4183 and TASK-4186 must be `"done"` in
   `sdd/tasks/index/teams-telegram-uploader-bookstore.json`
4. **Verify the Codebase Contract** — re-run the `grep -c`; confirm the names TASK-4182/4183 shipped
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
7. **Verify** with the Validation Commands (prefix `PYTHONPATH=packages/ai-parrot-integrations/src:packages/ai-parrot/src` inside the worktree)
8. **Commit the code** — stage only the files listed above
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4188 teams-telegram-uploader-bookstore verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
