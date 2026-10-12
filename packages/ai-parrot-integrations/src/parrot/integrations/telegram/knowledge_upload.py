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
    UploaderIdentity,
    UploadOutcome,
    UploadRequest,
    UploadTargetKind,
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
    """Parse ``--force``, ``--title``, repeatable ``--author`` / ``--topic``.

    Args:
        text: Raw argument text after the command (shlex quoting supported).

    Returns:
        Dict with ``force``, ``title``, ``authors`` and ``topics`` keys.
        Unknown tokens (and unparseable quoting) are ignored.
    """
    result: dict[str, Any] = {"force": False, "title": None, "authors": [], "topics": []}
    try:
        tokens = shlex.split(text or "")
    except ValueError:
        tokens = (text or "").split()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "--force":
            result["force"] = True
        elif token in ("--title", "--author", "--topic") and i + 1 < len(tokens):
            value = tokens[i + 1]
            i += 1
            if token == "--title":
                result["title"] = value
            elif token == "--author":
                result["authors"].append(value)
            else:
                result["topics"].append(value)
        i += 1
    return result


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
            name: kind
            for name, kind in COMMANDS.items()
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
        descriptions = {
            "ingest_book": "Upload a document to the Bookstore",
            "ingest_wiki": "Upload a document to the wiki",
        }
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
        await message.answer(
            f"Attach a PDF, DOCX or Markdown file with the caption /{command.command}, "
            f"or reply to a document with /{command.command}."
        )

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
        limit_mb = max_bytes / (1024 * 1024)
        filename = document.file_name or "document"
        allowed = {ext.lower() for ext in self.config.allowed_extensions}
        if Path(filename).suffix.lower() not in allowed:
            await message.answer("Unsupported file type. Allowed: " + ", ".join(sorted(allowed)))
            return
        if document.file_size is not None and document.file_size > max_bytes:
            await message.answer(f"File is too large (limit {limit_mb:g} MB).")
            return
        buffer = io.BytesIO()
        file = await self.wrapper.bot.get_file(document.file_id)
        await self.wrapper.bot.download_file(file.file_path, buffer)
        data = buffer.getvalue()
        if len(data) > max_bytes:
            await message.answer(f"File is too large (limit {limit_mb:g} MB).")
            return
        options = parse_ingest_args(args_text)
        identity = UploaderIdentity(
            platform="telegram",
            platform_user_id=str(message.from_user.id),
            nav_user_id=session.nav_user_id,
            email=session.nav_email,
        )
        request = UploadRequest(target=target, identity=identity, filename=filename, data=data, **options)

        async def notify(outcome: UploadOutcome) -> None:
            await message.answer(outcome.message)

        outcome = await service.submit(request, notify)
        await message.answer(outcome.message)

    async def shutdown(self) -> None:
        """Cancel running upload jobs (no-op when the service was never built)."""
        if self._service is not None:
            await self._service.shutdown()
