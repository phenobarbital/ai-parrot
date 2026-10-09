"""Slack adapter for chat-driven knowledge upload (FEAT-647, spec §3 Module 10)."""

from __future__ import annotations

import asyncio
import functools
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
USAGE = (
    'Usage: share a .pdf/.docx/.md file with the text `ingest_book [--force] [--title "…"]` '
    "or `ingest_wiki [--force]`."
)


class SlackKnowledgeUpload:
    """Register Slack commands and intercept file messages for knowledge upload."""

    def __init__(self, wrapper: "SlackAgentWrapper", service: KnowledgeUploadService) -> None:
        """Initialize the adapter and its per-user pending command windows."""
        self.wrapper = wrapper
        self.service = service
        self.logger = logging.getLogger(f"SlackKnowledgeUpload.{wrapper.config.name}")
        self._window_s = wrapper.config.knowledge_upload.slack_pending_window_s
        self._pending: Dict[Tuple[str, str], Tuple[float, UploadTargetKind, Dict[str, Any]]] = {}

    def _commands(self) -> Dict[str, UploadTargetKind]:
        """Return only commands for targets available from the core service."""
        available = self.service.available_targets()
        return {word: kind for word, kind in COMMANDS.items() if kind in available}

    def register(self) -> None:
        """Register available slash commands and the file-message interceptor."""
        for word, target in self._commands().items():
            handler = functools.partial(self.on_command, target)
            self.wrapper._command_router.register(word, handler)
        self.wrapper.add_message_interceptor(self.intercept)
        self.logger.info("Knowledge upload enabled: %s", sorted(self._commands()))

    async def on_command(self, target: UploadTargetKind, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Arm a one-shot pending window for the command's channel and user."""
        channel = payload.get("channel_id") or ""
        user = payload.get("user_id") or ""
        try:
            args = self._parse_args((payload.get("text") or "").strip())
        except ValueError:
            return {"response_type": "ephemeral", "text": USAGE}
        if not channel or not user:
            return {"response_type": "ephemeral", "text": USAGE}
        self._pending[(channel, user)] = (time.monotonic() + self._window_s, target, args)
        return {
            "response_type": "ephemeral",
            "text": "Command armed. Share the file in this channel before the window expires.",
        }

    @staticmethod
    def _parse_args(text: str) -> Dict[str, Any]:
        """Parse supported ingest options using shell-style quoting."""
        try:
            tokens = shlex.split(text or "")
        except ValueError as exc:
            raise ValueError("invalid command arguments") from exc
        result: Dict[str, Any] = {"force": False, "title": None, "authors": [], "topics": []}
        value_options = {"--title": "title", "--author": "authors", "--topic": "topics"}
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token == "--force":
                result["force"] = True
            elif token in value_options:
                if index + 1 >= len(tokens) or tokens[index + 1].startswith("--"):
                    raise ValueError("missing option value")
                index += 1
                key = value_options[token]
                if key == "title":
                    result[key] = tokens[index]
                else:
                    result[key].append(tokens[index])
            else:
                raise ValueError("unknown option")
            index += 1
        return result

    async def intercept(self, event: Dict[str, Any]) -> bool:
        """Consume a command-addressed file or a file from a live pending window."""
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            return False
        channel = event.get("channel") or ""
        user = event.get("user") or ""
        files = event.get("files") or ([event["file"]] if event.get("file") else [])
        commands = self._commands()
        text = (event.get("text") or "").strip()
        try:
            words = shlex.split(text) if text else []
        except ValueError:
            words = []
        command = words[0].casefold() if words else ""
        if command in commands:
            try:
                args = self._parse_args(text[len(words[0]) :].strip())
            except ValueError:
                await self.wrapper.post_message(channel, USAGE, thread_ts=event.get("thread_ts") or event.get("ts"))
                return True
            if not files:
                await self.wrapper.post_message(channel, USAGE, thread_ts=event.get("thread_ts") or event.get("ts"))
                return True
            target = commands[command]
        else:
            pending = self._pending.get((channel, user))
            if pending is None:
                return False
            if not files:
                return False
            self._pending.pop((channel, user), None)
            expires_at, target, args = pending
            if expires_at <= time.monotonic():
                return False

        task = asyncio.create_task(
            self._process(
                channel,
                user,
                event.get("thread_ts") or event.get("ts"),
                target,
                args,
                files[0],
            )
        )
        self.wrapper._background_tasks.add(task)
        task.add_done_callback(self.wrapper._background_tasks.discard)
        return True

    async def _process(
        self,
        channel: str,
        user: str,
        thread_ts: Optional[str],
        target: UploadTargetKind,
        args: Dict[str, Any],
        file_info: Dict[str, Any],
    ) -> None:
        """Download, submit, and relay the upload outcome without exposing internals."""
        max_bytes = self.service.max_bytes()

        async def notify(outcome: UploadOutcome) -> None:
            await self.wrapper.post_message(channel, outcome.message, thread_ts=thread_ts)

        if file_info.get("size") is not None and file_info["size"] > max_bytes:
            await self.wrapper.post_message(channel, "This file is too large.", thread_ts=thread_ts)
            return
        try:
            data = await self._download(file_info, max_bytes)
        except ValueError:
            await self.wrapper.post_message(channel, "This file is too large.", thread_ts=thread_ts)
            return
        except Exception:
            self.logger.warning("Slack knowledge upload download failed", exc_info=True)
            await self.wrapper.post_message(channel, "The file could not be downloaded.", thread_ts=thread_ts)
            return
        email = await self._email(user)
        identity = UploaderIdentity(platform="slack", platform_user_id=user, email=email)
        request = UploadRequest(
            target=target,
            identity=identity,
            filename=file_info.get("name") or "document",
            data=data,
            **args,
        )
        outcome = await self.service.submit(request, notify)
        if outcome.status in {UploadStatus.ACCEPTED, UploadStatus.DENIED, UploadStatus.INVALID}:
            await self.wrapper.post_message(channel, outcome.message, thread_ts=thread_ts)

    async def _download(self, file_info: Dict[str, Any], max_bytes: int) -> bytes:
        """Stream a private Slack file into memory while enforcing the byte cap."""
        url = file_info.get("url_private_download") or file_info.get("url_private")
        headers = {"Authorization": f"Bearer {self.wrapper.config.bot_token}"}
        async with ClientSession(timeout=ClientTimeout(total=120)) as session:
            async with session.get(url, headers=headers) as resp:
                resp.raise_for_status()
                data = bytearray()
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise ValueError("too large")
                return bytes(data)

    async def _email(self, user_id: str) -> Optional[str]:
        """Resolve the Slack user's email through the Slack users.info API."""
        data = await self.wrapper._slack_api("users.info", {"user": user_id})
        email = ((data or {}).get("user", {}).get("profile", {}) or {}).get("email", "")
        return email or None
