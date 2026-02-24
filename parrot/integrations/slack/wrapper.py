"""Slack Agent Wrapper."""
import json
import logging
from typing import Dict, Any, TYPE_CHECKING

from aiohttp import web, ClientSession

from .models import SlackAgentConfig
from ..parser import parse_response, ParsedResponse
from ...models.outputs import OutputMode
from ...memory import InMemoryConversation

if TYPE_CHECKING:
    from ...bots.abstract import AbstractBot
    from ...memory import ConversationMemory


class SlackAgentWrapper:
    """Wrap an AI-Parrot agent for Slack Events and slash commands."""

    def __init__(self, agent: 'AbstractBot', config: SlackAgentConfig, app: web.Application):
        self.agent = agent
        self.config = config
        self.app = app
        self.logger = logging.getLogger(f"SlackWrapper.{config.name}")
        self.conversations: Dict[str, 'ConversationMemory'] = {}

        safe_id = self.config.chatbot_id.replace(" ", "_").lower()
        self.events_route = config.webhook_path or f"/api/slack/{safe_id}/events"
        self.commands_route = f"/api/slack/{safe_id}/commands"

        app.router.add_post(self.events_route, self._handle_events)
        app.router.add_post(self.commands_route, self._handle_command)

        if auth := app.get("auth"):
            auth.add_exclude_list(self.events_route)
            auth.add_exclude_list(self.commands_route)

    def _get_or_create_memory(self, session_id: str) -> 'ConversationMemory':
        if session_id not in self.conversations:
            self.conversations[session_id] = InMemoryConversation()
        return self.conversations[session_id]

    def _is_authorized(self, channel_id: str) -> bool:
        if self.config.allowed_channel_ids is None:
            return True
        return channel_id in self.config.allowed_channel_ids

    async def _handle_events(self, request: web.Request) -> web.Response:
        payload = await request.json()
        if payload.get("type") == "url_verification":
            return web.json_response({"challenge": payload.get("challenge")})

        event = payload.get("event", {})
        if event.get("type") not in {"app_mention", "message"}:
            return web.json_response({"ok": True})
        if event.get("subtype") == "bot_message":
            return web.json_response({"ok": True})

        channel = event.get("channel")
        if not channel or not self._is_authorized(channel):
            return web.json_response({"ok": True})

        text = (event.get("text") or "").strip()
        user = event.get("user") or "unknown"
        thread_ts = event.get("thread_ts") or event.get("ts")
        session_id = f"{channel}:{user}"
        await self._answer(channel=channel, user=user, text=text, thread_ts=thread_ts, session_id=session_id)
        return web.json_response({"ok": True})

    async def _handle_command(self, request: web.Request) -> web.Response:
        data = await request.post()
        channel = data.get("channel_id", "")
        user = data.get("user_id", "unknown")
        text = (data.get("text") or "").strip()

        if not channel or not self._is_authorized(channel):
            return web.json_response({"response_type": "ephemeral", "text": "Unauthorized channel."})

        if text.lower() in {"help", "/help"}:
            return web.json_response({"response_type": "ephemeral", "text": self._help_text()})
        if text.lower() in {"clear", "/clear"}:
            self.conversations.pop(f"{channel}:{user}", None)
            return web.json_response({"response_type": "ephemeral", "text": "Conversation cleared."})
        if text.lower() in {"commands", "/commands"}:
            return web.json_response({"response_type": "ephemeral", "text": "Available commands: help, clear, commands"})

        await self._answer(channel=channel, user=user, text=text, thread_ts=None, session_id=f"{channel}:{user}")
        return web.json_response({"response_type": "ephemeral", "text": "Processing..."})

    async def _answer(self, channel: str, user: str, text: str, thread_ts: str | None, session_id: str) -> None:
        memory = self._get_or_create_memory(session_id)
        try:
            response = await self.agent.ask(
                text,
                memory=memory,
                output_mode=OutputMode.SLACK,
                session_id=session_id,
                user_id=user,
            )
        except Exception as exc:
            self.logger.error("Error generating Slack response: %s", exc, exc_info=True)
            await self._post_message(channel, "Sorry, I encountered an error while processing your request.", thread_ts=thread_ts)
            return

        parsed = parse_response(response)
        blocks = self._build_blocks(parsed)
        fallback = parsed.text or "Done."
        await self._post_message(channel, fallback, blocks=blocks, thread_ts=thread_ts)

    @staticmethod
    def _build_blocks(parsed: ParsedResponse) -> list[Dict[str, Any]]:
        blocks: list[Dict[str, Any]] = []
        if parsed.text:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": parsed.text[:3000]}})

        if parsed.has_code and parsed.code:
            lang = parsed.code_language or ""
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"```{lang}\n{parsed.code}\n```"[:3000]}})

        if parsed.has_table and parsed.table_markdown:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"```\n{parsed.table_markdown}\n```"[:3000]}})

        for img in parsed.images:
            image_url = str(img)
            if image_url.startswith("http://") or image_url.startswith("https://"):
                blocks.append(
                    {
                        "type": "image",
                        "image_url": image_url,
                        "alt_text": img.name,
                    }
                )
            else:
                blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"Image generated: `{img}`"}]})

        return blocks or [{"type": "section", "text": {"type": "mrkdwn", "text": "No content."}}]

    def _help_text(self) -> str:
        return "Use `/ask <question>` (or configured slash command) to query the agent.\nCommands: help, clear, commands"

    async def _post_message(
        self,
        channel: str,
        text: str,
        blocks: list[Dict[str, Any]] | None = None,
        thread_ts: str | None = None,
    ) -> None:
        if not self.config.bot_token:
            self.logger.warning("Slack bot token is not configured; cannot send message")
            return

        payload: Dict[str, Any] = {"channel": channel, "text": text}
        if blocks:
            payload["blocks"] = blocks
        if thread_ts:
            payload["thread_ts"] = thread_ts

        headers = {
            "Authorization": f"Bearer {self.config.bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        async with ClientSession() as session:
            async with session.post("https://slack.com/api/chat.postMessage", headers=headers, data=json.dumps(payload)) as resp:
                if resp.status >= 400:
                    self.logger.error("Slack API error: status=%s body=%s", resp.status, await resp.text())

