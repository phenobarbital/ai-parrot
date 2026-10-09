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
    UploaderIdentity,
    UploadOutcome,
    UploadRequest,
    UploadTargetKind,
)
from parrot.integrations.knowledge_upload.service import KnowledgeUploadService

if TYPE_CHECKING:
    from parrot.integrations.msteams.commands import MSTeamsCommandRouter

FILE_DOWNLOAD_INFO = "application/vnd.microsoft.teams.file.download.info"
COMMANDS: dict[str, UploadTargetKind] = {
    "ingest_book": UploadTargetKind.BOOKSTORE,
    "ingest_wiki": UploadTargetKind.WIKI,
}


def _parse_ingest_args(text: str) -> dict[str, Any]:
    """Parse supported upload options from command text."""
    result: dict[str, Any] = {"force": False, "title": None, "authors": [], "topics": []}
    try:
        tokens = shlex.split(text or "")
    except ValueError:
        tokens = (text or "").split()

    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--force":
            result["force"] = True
        elif token in ("--title", "--author", "--topic") and index + 1 < len(tokens):
            value = tokens[index + 1]
            index += 1
            if token == "--title":
                result["title"] = value
            elif token == "--author":
                result["authors"].append(value)
            else:
                result["topics"].append(value)
        index += 1
    return result


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
        """Return a Teams file attachment, preferring file download metadata."""
        fallback = None
        for attachment in activity.attachments or []:
            content_type = (attachment.content_type or "").lower()
            if content_type == FILE_DOWNLOAD_INFO:
                return attachment
            if content_type == "text/html" or "adaptive" in content_type:
                continue
            if fallback is None and attachment.content_url:
                fallback = attachment
        return fallback

    async def download(self, turn_context: TurnContext, attachment: Attachment, max_bytes: int) -> Optional[bytes]:
        """Stream the file into memory within the configured size limit."""
        if attachment.content_type == FILE_DOWNLOAD_INFO:
            url = (attachment.content or {}).get("downloadUrl")
            headers: dict[str, str] = {}
        else:
            token = await self.wrapper._get_attachment_token(turn_context)
            url = attachment.content_url
            headers = {"Authorization": f"Bearer {token}"} if token else {}
        if not url:
            return None

        chunks: list[bytes] = []
        size = 0
        async with aiohttp.ClientSession() as http:
            async with http.get(url, headers=headers) as response:
                if response.status != 200:
                    return None
                async for chunk in response.content.iter_chunked(65536):
                    size += len(chunk)
                    if size > max_bytes:
                        return None
                    chunks.append(chunk)
        return b"".join(chunks)

    async def resolve_email(self, turn_context: TurnContext) -> Optional[str]:
        """Return the member email or UPN, denying unverified identities."""
        try:
            member = await TeamsInfo.get_member(turn_context, turn_context.activity.from_property.id)
        except Exception:  # noqa: BLE001 - roster lookup failure denies the upload
            self.logger.warning("Teams member lookup failed", exc_info=True)
            return None
        return getattr(member, "email", None) or getattr(member, "user_principal_name", None)

    async def handle(self, turn_context: TurnContext, target: UploadTargetKind) -> None:
        """Validate, download, submit, and arrange a proactive completion notice."""
        text = self.wrapper._remove_mentions(turn_context.activity, turn_context.activity.text or "").strip()
        parts = text.split(maxsplit=1)
        args_text = parts[1] if len(parts) > 1 else ""
        service = await self._get_service()
        if target not in service.available_targets():
            await self.wrapper.send_text("This upload target is not available right now.", turn_context)
            return

        attachment = self.pick_attachment(turn_context.activity)
        command = parts[0] if parts else "/ingest"
        if attachment is None:
            await self.wrapper.send_text(
                f"Attach a PDF, DOCX or Markdown file to the {command} message.", turn_context
            )
            return

        filename = attachment.name or "document"
        allowed = {extension.lower() for extension in self.config.allowed_extensions}
        if Path(filename).suffix.lower() not in allowed:
            await self.wrapper.send_text("Unsupported file type. Allowed: " + ", ".join(sorted(allowed)), turn_context)
            return

        email = await self.resolve_email(turn_context)
        if email is None:
            await self.wrapper.send_text("Your identity could not be verified.", turn_context)
            return

        max_bytes = service.max_bytes()
        data = await self.download(turn_context, attachment, max_bytes)
        if data is None:
            limit_mb = max_bytes / (1024 * 1024)
            await self.wrapper.send_text(f"File is too large or could not be downloaded (limit {limit_mb:g} MB).", turn_context)
            return

        identity = UploaderIdentity(
            platform="msteams",
            platform_user_id=turn_context.activity.from_property.id,
            email=email,
        )
        request = UploadRequest(
            target=target,
            identity=identity,
            filename=filename,
            data=data,
            **_parse_ingest_args(args_text),
        )
        conv_ref = TurnContext.get_conversation_reference(turn_context.activity)

        async def notify(outcome: UploadOutcome) -> None:
            if not self.wrapper.config.client_id:
                self.logger.warning("No client_id: cannot deliver upload outcome %s proactively", outcome.job_id)
                return

            async def callback(context: TurnContext) -> None:
                await context.send_activity(outcome.message)

            await self.wrapper.adapter.continue_conversation(conv_ref, callback, self.wrapper.config.client_id)

        outcome = await service.submit(request, notify)
        await self.wrapper.send_text(outcome.message, turn_context)


def register_knowledge_upload_commands(
    router: "MSTeamsCommandRouter", wrapper: Any, service: Optional[KnowledgeUploadService] = None
) -> TeamsKnowledgeUpload:
    """Register configured upload commands and return their shared holder."""
    holder = TeamsKnowledgeUpload(wrapper, service)
    for name, kind in COMMANDS.items():
        is_configured = (kind is UploadTargetKind.BOOKSTORE and holder.config.bookstore is not None) or (
            kind is UploadTargetKind.WIKI and holder.config.wiki is not None
        )
        if is_configured:
            async def handler(turn_context: TurnContext, upload_target: UploadTargetKind = kind) -> None:
                await holder.handle(turn_context, upload_target)

            router.register(name, handler)
    return holder
