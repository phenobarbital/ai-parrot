"""Slack Agent Wrapper.

Handles Slack Events API and slash commands with async processing,
signature verification, and event deduplication.
"""
import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from aiohttp import web, ClientSession

from .assistant import SlackAssistantHandler
from .dedup import EventDeduplicator
from .interactive import SlackInteractiveHandler
from .models import SlackAgentConfig
from .security import verify_slack_signature_raw
from ..parser import parse_response, ParsedResponse
from ...models.outputs import OutputMode
from ...memory import InMemoryConversation


def convert_markdown_to_mrkdwn(text: str) -> str:
    """Convert standard Markdown to Slack mrkdwn format.

    Slack's mrkdwn is a subset of Markdown with different syntax:
    - Bold: **text** → *text*
    - Italic: *text* / _text_ → _text_
    - Links: [label](url) → <url|label>
    - Headings: # Heading → *Heading*
    - Bullets: - item / * item → • item
    - Horizontal rules: --- → (removed)
    """
    # Headings: ## Title → *Title*
    text = re.sub(r'^#{1,6}\s+(.+)$', r'*\1*', text, flags=re.MULTILINE)

    # Horizontal rules
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)

    # Bold: **text** or __text__ → *text*
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)
    text = re.sub(r'__(.+?)__', r'*\1*', text)

    # Italic: *text* → _text_  (after bold is handled)
    # Only match single asterisks not preceded/followed by another asterisk
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'_\1_', text)

    # Links: [label](url) → <url|label>
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<\2|\1>', text)

    # Bullet lists: leading '- ' or '* ' → '• '
    text = re.sub(r'^[ \t]*[-*]\s+', '• ', text, flags=re.MULTILINE)

    # Numbered lists: '1. item' → '1. item' (already fine in Slack)

    # Blockquotes: '> text' → Slack doesn't render these, just strip '>'
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)

    return text.strip()


if TYPE_CHECKING:
    from ...bots.abstract import AbstractBot
    from ...memory import ConversationMemory


class SlackAgentWrapper:
    """Wrap an AI-Parrot agent for Slack Events and slash commands.

    Features:
    - HMAC-SHA256 signature verification
    - Event deduplication to prevent duplicate processing
    - Async background processing (returns HTTP 200 immediately)
    - Concurrency limiting via semaphore
    - Retry header detection (ignores Slack retries)
    """

    def __init__(
        self,
        agent: 'AbstractBot',
        config: SlackAgentConfig,
        app: web.Application,
    ):
        """Initialize the Slack wrapper.

        Args:
            agent: The AI-Parrot agent to wrap.
            config: Slack configuration including tokens and settings.
            app: The aiohttp application to register routes on.
        """
        self.agent = agent
        self.config = config
        self.app = app
        self.logger = logging.getLogger(f"SlackWrapper.{config.name}")
        self.conversations: Dict[str, 'ConversationMemory'] = {}

        # Event deduplication (prevents duplicate processing on Slack retries)
        self._dedup = EventDeduplicator(ttl_seconds=300)

        # Concurrency limiting
        self._concurrency_semaphore = asyncio.Semaphore(config.max_concurrent_requests)

        # Background tasks tracking (for graceful shutdown)
        self._background_tasks: set[asyncio.Task] = set()

        # Route setup
        safe_id = self.config.chatbot_id.replace(" ", "_").lower()
        self.events_route = config.webhook_path or f"/api/slack/{safe_id}/events"
        self.commands_route = f"/api/slack/{safe_id}/commands"
        self.interactive_route = f"/api/slack/{safe_id}/interactive"

        app.router.add_post(self.events_route, self._handle_events)
        app.router.add_post(self.commands_route, self._handle_command)

        # Interactive handler (Block Kit buttons, modals, etc.)
        self._interactive_handler = SlackInteractiveHandler(self)
        app.router.add_post(self.interactive_route, self._interactive_handler.handle)

        # Assistant handler (Agents & AI Apps)
        self._assistant_handler: Optional[SlackAssistantHandler] = None
        if config.enable_assistant:
            self._assistant_handler = SlackAssistantHandler(self)

        # Exclude from auth middleware
        if auth := app.get("auth"):
            auth.add_exclude_list(self.events_route)
            auth.add_exclude_list(self.commands_route)
            auth.add_exclude_list(self.interactive_route)

    async def start(self) -> None:
        """Start the deduplication cleanup task."""
        await self._dedup.start()
        self.logger.info("SlackWrapper started for %s", self.config.name)

    async def stop(self) -> None:
        """Stop background tasks and cleanup."""
        await self._dedup.stop()
        # Cancel any pending background tasks
        for task in self._background_tasks:
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()
        self.logger.info("SlackWrapper stopped for %s", self.config.name)

    def _get_or_create_memory(self, session_id: str) -> 'ConversationMemory':
        """Get or create conversation memory for a session."""
        if session_id not in self.conversations:
            self.conversations[session_id] = InMemoryConversation()
        return self.conversations[session_id]

    def _is_authorized(self, channel_id: str) -> bool:
        """Check if a channel is authorized for this bot."""
        if self.config.allowed_channel_ids is None:
            return True
        return channel_id in self.config.allowed_channel_ids

    async def _handle_events(self, request: web.Request) -> web.Response:
        """Handle Slack Events API requests.

        This method returns HTTP 200 immediately and processes in background.
        """
        # 1. Reject Slack retries immediately
        retry_num = request.headers.get("X-Slack-Retry-Num")
        if retry_num:
            self.logger.debug(
                "Ignoring Slack retry #%s (reason: %s)",
                retry_num,
                request.headers.get("X-Slack-Retry-Reason", "unknown"),
            )
            return web.json_response({"ok": True})

        # 2. Read raw body ONCE (needed for signature verification + JSON parsing)
        raw_body = await request.read()

        # 3. Verify signature BEFORE any processing
        if not verify_slack_signature_raw(
            raw_body, request.headers, self.config.signing_secret
        ):
            self.logger.warning("Slack signature verification failed")
            return web.Response(status=401, text="Unauthorized")

        # 4. Parse JSON
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            self.logger.warning("Invalid JSON in Slack request: %s", exc)
            return web.Response(status=400, text="Invalid JSON")

        # 5. URL verification challenge (Slack setup)
        if payload.get("type") == "url_verification":
            return web.json_response({"challenge": payload.get("challenge")})

        # 6. Deduplicate by event_id
        event_id = payload.get("event_id")
        if self._dedup.is_duplicate(event_id):
            self.logger.debug("Duplicate event ignored: %s", event_id)
            return web.json_response({"ok": True})

        # 7. Extract event and validate
        event = payload.get("event", {})
        event_type = event.get("type")

        # 8. Handle Agents & AI Apps events if assistant mode is enabled
        if self._assistant_handler:
            if event_type == "assistant_thread_started":
                task = asyncio.create_task(
                    self._assistant_handler.handle_thread_started(event, payload)
                )
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
                return web.json_response({"ok": True})

            if event_type == "assistant_thread_context_changed":
                task = asyncio.create_task(
                    self._assistant_handler.handle_context_changed(event)
                )
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
                return web.json_response({"ok": True})

            # Handle DM messages in assistant mode
            if event_type == "message" and event.get("channel_type") == "im":
                # Skip bot messages
                if not event.get("subtype") and not event.get("bot_id"):
                    task = asyncio.create_task(
                        self._assistant_handler.handle_user_message(event)
                    )
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)
                    return web.json_response({"ok": True})

        # 9. Standard event handling
        if event_type not in {"app_mention", "message"}:
            return web.json_response({"ok": True})

        # Ignore bot messages (including our own)
        if event.get("subtype") == "bot_message" or event.get("bot_id"):
            return web.json_response({"ok": True})

        channel = event.get("channel")
        if not channel or not self._is_authorized(channel):
            return web.json_response({"ok": True})

        text = (event.get("text") or "").strip()
        user = event.get("user") or "unknown"
        thread_ts = event.get("thread_ts") or event.get("ts")
        session_id = f"{channel}:{user}"
        files = event.get("files")

        # 8. Process in background — return 200 immediately
        task = asyncio.create_task(
            self._safe_answer(
                channel=channel,
                user=user,
                text=text,
                thread_ts=thread_ts,
                session_id=session_id,
                files=files,
            )
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        return web.json_response({"ok": True})

    async def _handle_command(self, request: web.Request) -> web.Response:
        """Handle Slack slash commands."""
        data = await request.post()
        channel = data.get("channel_id", "")
        user = data.get("user_id", "unknown")
        text = (data.get("text") or "").strip()

        if not channel or not self._is_authorized(channel):
            return web.json_response({
                "response_type": "ephemeral",
                "text": "Unauthorized channel."
            })

        if text.lower() in {"help", "/help"}:
            return web.json_response({
                "response_type": "ephemeral",
                "text": self._help_text()
            })
        if text.lower() in {"clear", "/clear"}:
            self.conversations.pop(f"{channel}:{user}", None)
            return web.json_response({
                "response_type": "ephemeral",
                "text": "Conversation cleared."
            })
        if text.lower() in {"commands", "/commands"}:
            return web.json_response({
                "response_type": "ephemeral",
                "text": "Available commands: help, clear, commands"
            })

        # Process in background
        task = asyncio.create_task(
            self._safe_answer(
                channel=channel,
                user=user,
                text=text,
                thread_ts=None,
                session_id=f"{channel}:{user}",
            )
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        return web.json_response({
            "response_type": "ephemeral",
            "text": "Processing..."
        })

    async def _safe_answer(
        self,
        channel: str,
        user: str,
        text: str,
        thread_ts: Optional[str],
        session_id: str,
        files: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Wrapper for _answer with error handling, timeout, and concurrency limit.

        Args:
            channel: Slack channel ID.
            user: Slack user ID.
            text: Message text from user.
            thread_ts: Thread timestamp for replies.
            session_id: Session identifier for conversation memory.
            files: Optional list of file attachments (for future use).
        """
        async with self._concurrency_semaphore:
            try:
                await asyncio.wait_for(
                    self._answer(
                        channel=channel,
                        user=user,
                        text=text,
                        thread_ts=thread_ts,
                        session_id=session_id,
                        files=files,
                    ),
                    timeout=120.0,
                )
            except asyncio.TimeoutError:
                self.logger.error("Slack answer timed out after 120s")
                await self._post_message(
                    channel,
                    "The request took too long. Please try again.",
                    thread_ts=thread_ts,
                )
            except asyncio.CancelledError:
                # Task was cancelled (e.g., during shutdown)
                self.logger.debug("Slack answer task cancelled")
                raise
            except Exception as exc:
                self.logger.error(
                    "Unhandled error in Slack answer: %s", exc, exc_info=True
                )
                try:
                    await self._post_message(
                        channel,
                        "Sorry, an unexpected error occurred.",
                        thread_ts=thread_ts,
                    )
                except Exception:
                    self.logger.error("Failed to send error message to Slack")

    async def _answer(
        self,
        channel: str,
        user: str,
        text: str,
        thread_ts: Optional[str],
        session_id: str,
        files: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Process user message and send response.

        Args:
            channel: Slack channel ID.
            user: Slack user ID.
            text: Message text from user.
            thread_ts: Thread timestamp for replies.
            session_id: Session identifier for conversation memory.
            files: Optional list of file attachments (for future use).
        """
        memory = self._get_or_create_memory(session_id)

        # Send typing indicator to show we're processing.
        # Track the ts so we can delete the indicator after responding.
        typing_ts: Optional[str] = None
        if self.config.enable_assistant and thread_ts:
            # Use Agents & AI Apps status for assistant mode
            await self._set_assistant_status(
                channel,
                thread_ts,
                status="is thinking...",
                loading_messages=[
                    "Analyzing your question...",
                    "Consulting the knowledge base...",
                    "Preparing a response...",
                ],
            )
        else:
            typing_ts = await self._send_typing_indicator(channel, user, thread_ts)

        try:
            response = await self.agent.ask(
                text,
                memory=memory,
                output_mode=OutputMode.SLACK,
                session_id=session_id,
                user_id=user,
            )
        except Exception as exc:
            self.logger.error(
                "Error generating Slack response: %s", exc, exc_info=True
            )
            await self._post_message(
                channel,
                "Sorry, I encountered an error while processing your request.",
                thread_ts=thread_ts,
            )
            return

        # Delete typing indicator before posting response (DM mode)
        if typing_ts:
            await self._delete_message(channel, typing_ts)

        parsed = parse_response(response)
        blocks = self._build_blocks(parsed)
        fallback = parsed.text or "Done."
        await self._post_message(channel, fallback, blocks=blocks, thread_ts=thread_ts)

    @staticmethod
    def _build_blocks(parsed: ParsedResponse) -> List[Dict[str, Any]]:
        """Build Slack Block Kit blocks from parsed response."""
        blocks: List[Dict[str, Any]] = []

        if parsed.text:
            mrkdwn_text = convert_markdown_to_mrkdwn(parsed.text)
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": mrkdwn_text[:3000]}
            })

        if parsed.has_code and parsed.code:
            lang = parsed.code_language or ""
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"```{lang}\n{parsed.code}\n```"[:3000]}
            })

        if parsed.has_table and parsed.table_markdown:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"```\n{parsed.table_markdown}\n```"[:3000]}
            })

        for img in parsed.images:
            image_url = str(img)
            if image_url.startswith("http://") or image_url.startswith("https://"):
                blocks.append({
                    "type": "image",
                    "image_url": image_url,
                    "alt_text": img.name,
                })
            else:
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"Image generated: `{img}`"}]
                })

        return blocks or [{"type": "section", "text": {"type": "mrkdwn", "text": "No content."}}]

    def _help_text(self) -> str:
        """Return help text for slash commands."""
        return (
            "Use `/ask <question>` (or configured slash command) to query the agent.\n"
            "Commands: help, clear, commands"
        )

    async def _post_message(
        self,
        channel: str,
        text: str,
        blocks: Optional[List[Dict[str, Any]]] = None,
        thread_ts: Optional[str] = None,
    ) -> None:
        """Send a message to Slack.

        Args:
            channel: Channel ID to post to.
            text: Fallback text for notifications.
            blocks: Optional Block Kit blocks.
            thread_ts: Optional thread timestamp for replies.
        """
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
            async with session.post(
                "https://slack.com/api/chat.postMessage",
                headers=headers,
                data=json.dumps(payload),
            ) as resp:
                if resp.status >= 400:
                    self.logger.error(
                        "Slack API error: status=%s body=%s",
                        resp.status,
                        await resp.text(),
                    )

    async def _send_typing_indicator(
        self,
        channel: str,
        user: str,
        thread_ts: Optional[str] = None,
    ) -> Optional[str]:
        """Send a 'thinking' indicator visible to the user.

        In direct-message channels (channel ID starts with 'D'),
        ``chat.postEphemeral`` is not supported, so we post a regular
        message and return its timestamp so the caller can delete it
        once the real response is ready.

        In public/private channels we use ``chat.postEphemeral`` instead
        (no need to clean it up — it disappears automatically).

        Args:
            channel: Slack channel ID.
            user: Slack user ID.
            thread_ts: Optional thread timestamp.

        Returns:
            The message timestamp if a deletable message was posted,
            None otherwise.
        """
        if not self.config.bot_token:
            return None

        headers = {
            "Authorization": f"Bearer {self.config.bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        is_dm = channel.startswith("D")

        try:
            async with ClientSession() as session:
                if is_dm:
                    # Ephemeral messages are not supported in DMs.
                    # Post a regular message and return its ts for later deletion.
                    payload: Dict[str, Any] = {
                        "channel": channel,
                        "text": ":hourglass_flowing_sand: _Thinking..._",
                    }
                    if thread_ts:
                        payload["thread_ts"] = thread_ts
                    async with session.post(
                        "https://slack.com/api/chat.postMessage",
                        headers=headers,
                        data=json.dumps(payload),
                    ) as resp:
                        data = await resp.json()
                        if data.get("ok"):
                            return data.get("ts")  # caller will delete this
                        self.logger.debug(
                            "Failed to send DM typing indicator: %s",
                            data.get("error", "unknown"),
                        )
                        return None
                else:
                    # Public / private channel — use ephemeral (auto-dismisses).
                    payload = {
                        "channel": channel,
                        "user": user,
                        "text": ":hourglass_flowing_sand: Thinking...",
                    }
                    if thread_ts:
                        payload["thread_ts"] = thread_ts
                    async with session.post(
                        "https://slack.com/api/chat.postEphemeral",
                        headers=headers,
                        data=json.dumps(payload),
                    ) as resp:
                        data = await resp.json()
                        if not data.get("ok"):
                            self.logger.debug(
                                "Failed to send typing indicator: %s",
                                data.get("error", "unknown"),
                            )
                        return None  # ephemeral — no ts to track
        except Exception as exc:
            # Don't let typing indicator errors break the flow
            self.logger.debug("Error sending typing indicator: %s", exc)
            return None

    async def _delete_message(
        self,
        channel: str,
        ts: str,
    ) -> None:
        """Delete a previously posted message (used to clean up typing indicators).

        Args:
            channel: Slack channel ID.
            ts: Timestamp of the message to delete.
        """
        if not self.config.bot_token:
            return

        payload: Dict[str, Any] = {"channel": channel, "ts": ts}
        headers = {
            "Authorization": f"Bearer {self.config.bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        try:
            async with ClientSession() as session:
                async with session.post(
                    "https://slack.com/api/chat.delete",
                    headers=headers,
                    data=json.dumps(payload),
                ) as resp:
                    data = await resp.json()
                    if not data.get("ok"):
                        self.logger.debug(
                            "Failed to delete typing indicator: %s",
                            data.get("error", "unknown"),
                        )
        except Exception as exc:
            self.logger.debug("Error deleting typing indicator: %s", exc)

    async def _set_assistant_status(
        self,
        channel: str,
        thread_ts: str,
        status: str = "is thinking...",
        loading_messages: Optional[List[str]] = None,
    ) -> None:
        """Set assistant status in Slack AI container.

        Requires Agents & AI Apps feature and assistant:write scope.

        Args:
            channel: Slack channel ID.
            thread_ts: Thread timestamp.
            status: Status text to display.
            loading_messages: Optional list of rotating loading messages.
        """
        if not self.config.bot_token:
            return

        payload: Dict[str, Any] = {
            "channel_id": channel,
            "thread_ts": thread_ts,
            "status": status,
        }
        if loading_messages:
            payload["loading_messages"] = loading_messages

        headers = {
            "Authorization": f"Bearer {self.config.bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        try:
            async with ClientSession() as session:
                async with session.post(
                    "https://slack.com/api/assistant.threads.setStatus",
                    headers=headers,
                    data=json.dumps(payload),
                ) as resp:
                    data = await resp.json()
                    if not data.get("ok"):
                        self.logger.debug(
                            "Failed to set assistant status: %s",
                            data.get("error", "unknown"),
                        )
        except Exception as exc:
            # Don't let assistant status errors break the flow
            self.logger.debug("Error setting assistant status: %s", exc)

    async def _clear_assistant_status(
        self,
        channel: str,
        thread_ts: str,
    ) -> None:
        """Clear assistant status (sets empty status).

        Args:
            channel: Slack channel ID.
            thread_ts: Thread timestamp.
        """
        await self._set_assistant_status(channel, thread_ts, status="")
