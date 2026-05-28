"""
Slack Agents & AI Apps integration for AI-Parrot.

Implements the assistant container experience with split-view panel,
suggested prompts, loading states, thread titles, and streaming.

Part of FEAT-010: Slack Wrapper Integration Enhancements.

Ref: https://api.slack.com/docs/apps/ai
"""
import json
import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from aiohttp import ClientSession

from ..parser import parse_response
from ...models.outputs import OutputMode

if TYPE_CHECKING:
    from .wrapper import SlackAgentWrapper

logger = logging.getLogger("SlackAssistant")


class SlackAssistantHandler:
    """
    Handles Slack's Agents & AI Apps events.

    Provides a native AI assistant experience in Slack with:
    - Split-view panel UI
    - Suggested prompts
    - Loading states with rotating messages
    - Thread titles
    - Chat streaming (when agent supports it)

    Attributes:
        wrapper: The parent SlackAgentWrapper instance.
        config: Slack configuration from the wrapper.

    Example::

        handler = SlackAssistantHandler(wrapper)
        await handler.handle_thread_started(event, payload)
    """

    def __init__(self, wrapper: 'SlackAgentWrapper'):
        """
        Initialize the assistant handler.

        Args:
            wrapper: The SlackAgentWrapper instance to integrate with.
        """
        self.wrapper = wrapper
        self.config = wrapper.config
        self._thread_contexts: Dict[str, Dict[str, Any]] = {}

    @property
    def _headers(self) -> Dict[str, str]:
        """HTTP headers for Slack API calls."""
        return {
            "Authorization": f"Bearer {self.config.bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    # === Event Handlers ===

    async def handle_thread_started(self, event: Dict[str, Any], payload: Dict[str, Any]) -> None:
        """
        Handle assistant_thread_started — user opens assistant container.

        Sends a welcome message and sets suggested prompts for the new thread.

        Args:
            event: The event data containing assistant_thread info.
            payload: The full payload (for additional context if needed).
        """
        assistant_thread = event.get("assistant_thread", {})
        channel = assistant_thread.get("channel_id")
        thread_ts = assistant_thread.get("thread_ts")
        context = assistant_thread.get("context", {})

        if not channel or not thread_ts:
            logger.warning("Missing channel or thread_ts in assistant_thread_started")
            return

        # Store context for potential future use
        self._thread_contexts[thread_ts] = context

        logger.info(
            "Assistant thread started: channel=%s thread_ts=%s",
            channel, thread_ts
        )

        # Send welcome message
        welcome = self.config.welcome_message or "Hi! How can I help you today?"
        await self._post_message(channel, welcome, thread_ts=thread_ts)

        # Set suggested prompts
        prompts = self.config.suggested_prompts or self._default_prompts()
        await self._set_suggested_prompts(channel, thread_ts, prompts)

    async def handle_context_changed(self, event: Dict[str, Any]) -> None:
        """
        Handle assistant_thread_context_changed — user switched channels.

        Updates the stored context for the thread.

        Args:
            event: The event data containing the new context.
        """
        assistant_thread = event.get("assistant_thread", {})
        thread_ts = assistant_thread.get("thread_ts")
        context = assistant_thread.get("context", {})

        if thread_ts:
            self._thread_contexts[thread_ts] = context
            logger.debug("Context updated for thread %s: %s", thread_ts, context)

    async def handle_user_message(self, event: Dict[str, Any]) -> None:
        """
        Handle message.im in an assistant thread.

        Processes the user's message, sets loading status, generates response,
        and sends it back with optional streaming.

        Args:
            event: The message event data.
        """
        channel = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")
        text = (event.get("text") or "").strip()
        user = event.get("user") or "unknown"
        team = event.get("team")

        if not channel or not text:
            return

        session_id = f"assistant:{channel}:{user}"

        logger.info(
            "Assistant message: channel=%s user=%s text=%s",
            channel, user, text[:50]
        )

        # 1. Set thread title (auto-generated from first message)
        title = text[:100] + ("..." if len(text) > 100 else "")
        await self._set_title(channel, thread_ts, title)

        # 2. Set loading status
        await self._set_status(
            channel, thread_ts,
            status="is thinking...",
            loading_messages=[
                "Analyzing your question...",
                "Consulting the knowledge base...",
                "Preparing a thoughtful response...",
            ],
        )

        # 3. Process with agent
        memory = self.wrapper._get_or_create_memory(session_id)
        try:
            # Check if streaming is available
            if hasattr(self.wrapper.agent, 'ask_stream') and team:
                await self._stream_response(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=text,
                    user=user,
                    team=team,
                    memory=memory,
                    session_id=session_id,
                )
            else:
                # Non-streaming response
                response = await self.wrapper.agent.ask(
                    text,
                    memory=memory,
                    output_mode=OutputMode.SLACK,
                    session_id=session_id,
                    user_id=user,
                )
                parsed = parse_response(response)
                blocks = self.wrapper._build_blocks(parsed)

                # Add feedback buttons
                from .interactive import build_feedback_blocks
                blocks.extend(build_feedback_blocks())

                await self._post_message(
                    channel,
                    parsed.text or "Done.",
                    blocks=blocks,
                    thread_ts=thread_ts,
                )

        except Exception as exc:
            logger.error("Assistant response error: %s", exc, exc_info=True)
            await self._clear_status(channel, thread_ts)
            await self._post_message(
                channel,
                "Sorry, I encountered an error. Please try again.",
                thread_ts=thread_ts,
            )

    async def _stream_response(
        self,
        channel: str,
        thread_ts: str,
        text: str,
        user: str,
        team: str,
        memory: Any,
        session_id: str,
    ) -> None:
        """
        Stream response using Slack's chat_stream API.

        Args:
            channel: Slack channel ID.
            thread_ts: Thread timestamp.
            text: User's message text.
            user: Slack user ID.
            team: Slack team ID.
            memory: Conversation memory.
            session_id: Session identifier.
        """
        try:
            from slack_sdk.web.async_client import AsyncWebClient
        except ImportError:
            logger.warning("slack-sdk not installed, falling back to non-streaming")
            response = await self.wrapper.agent.ask(
                text, memory=memory, output_mode=OutputMode.SLACK,
                session_id=session_id, user_id=user,
            )
            parsed = parse_response(response)
            blocks = self.wrapper._build_blocks(parsed)
            await self._post_message(channel, parsed.text or "Done.", blocks=blocks, thread_ts=thread_ts)
            return

        client = AsyncWebClient(token=self.config.bot_token)

        try:
            streamer = client.chat_stream(
                channel=channel,
                thread_ts=thread_ts,
                recipient_team_id=team,
                recipient_user_id=user,
            )

            async for chunk in self.wrapper.agent.ask_stream(
                text,
                memory=memory,
                output_mode=OutputMode.SLACK,
                session_id=session_id,
                user_id=user,
            ):
                content = getattr(chunk, 'content', chunk) if not isinstance(chunk, str) else chunk
                if content:
                    streamer.append(markdown_text=str(content))

            # Add feedback buttons at the end
            from .interactive import build_feedback_blocks
            streamer.stop(blocks=build_feedback_blocks())

        except Exception as exc:
            logger.error("Streaming error: %s", exc, exc_info=True)
            try:
                streamer.stop(markdown_text="\n\n:warning: An error occurred during generation.")
            except Exception:
                pass
            # Fall back to error message
            await self._clear_status(channel, thread_ts)
            await self._post_message(
                channel,
                "Sorry, I encountered an error while streaming the response.",
                thread_ts=thread_ts,
            )

    # === Slack API helpers ===

    async def _set_status(
        self,
        channel: str,
        thread_ts: str,
        status: str,
        loading_messages: Optional[List[str]] = None,
    ) -> None:
        """
        Set assistant loading status.

        Args:
            channel: Slack channel ID.
            thread_ts: Thread timestamp.
            status: Status text to display.
            loading_messages: Optional list of rotating loading messages.
        """
        payload: Dict[str, Any] = {
            "channel_id": channel,
            "thread_ts": thread_ts,
            "status": status,
        }
        if loading_messages:
            payload["loading_messages"] = loading_messages

        async with ClientSession() as session:
            async with session.post(
                "https://slack.com/api/assistant.threads.setStatus",
                headers=self._headers,
                data=json.dumps(payload),
            ) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    logger.debug("setStatus failed: %s", data.get("error"))

    async def _clear_status(self, channel: str, thread_ts: str) -> None:
        """
        Clear assistant status.

        Args:
            channel: Slack channel ID.
            thread_ts: Thread timestamp.
        """
        await self._set_status(channel, thread_ts, status="")

    async def _set_title(self, channel: str, thread_ts: str, title: str) -> None:
        """
        Set assistant thread title.

        Args:
            channel: Slack channel ID.
            thread_ts: Thread timestamp.
            title: Title text (max 100 characters recommended).
        """
        async with ClientSession() as session:
            async with session.post(
                "https://slack.com/api/assistant.threads.setTitle",
                headers=self._headers,
                data=json.dumps({
                    "channel_id": channel,
                    "thread_ts": thread_ts,
                    "title": title[:255],  # Slack limit
                }),
            ) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    logger.debug("setTitle failed: %s", data.get("error"))

    async def _set_suggested_prompts(
        self,
        channel: str,
        thread_ts: str,
        prompts: List[Dict[str, str]],
    ) -> None:
        """
        Set suggested prompts for assistant thread.

        Args:
            channel: Slack channel ID.
            thread_ts: Thread timestamp.
            prompts: List of prompt dictionaries with "title" and "message" keys.
        """
        async with ClientSession() as session:
            async with session.post(
                "https://slack.com/api/assistant.threads.setSuggestedPrompts",
                headers=self._headers,
                data=json.dumps({
                    "channel_id": channel,
                    "thread_ts": thread_ts,
                    "prompts": prompts,
                }),
            ) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    logger.debug("setSuggestedPrompts failed: %s", data.get("error"))

    async def _post_message(
        self,
        channel: str,
        text: str,
        blocks: Optional[List[Dict[str, Any]]] = None,
        thread_ts: Optional[str] = None,
    ) -> None:
        """
        Post message to channel/thread.

        Args:
            channel: Slack channel ID.
            text: Message text (fallback).
            blocks: Optional Block Kit blocks.
            thread_ts: Optional thread timestamp for replies.
        """
        payload: Dict[str, Any] = {"channel": channel, "text": text}
        if blocks:
            payload["blocks"] = blocks
        if thread_ts:
            payload["thread_ts"] = thread_ts

        async with ClientSession() as session:
            async with session.post(
                "https://slack.com/api/chat.postMessage",
                headers=self._headers,
                data=json.dumps(payload),
            ) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    logger.warning("postMessage failed: %s", data.get("error"))

    def _default_prompts(self) -> List[Dict[str, str]]:
        """Return default suggested prompts."""
        return [
            {
                "title": "Summarize this channel",
                "message": "Summarize the recent discussion in this channel",
            },
            {
                "title": "Help me draft a message",
                "message": "Help me draft a professional message about",
            },
            {
                "title": "Explain a concept",
                "message": "Can you explain the following concept:",
            },
        ]

    def get_thread_context(self, thread_ts: str) -> Optional[Dict[str, Any]]:
        """
        Get stored context for a thread.

        Args:
            thread_ts: Thread timestamp.

        Returns:
            Context dictionary if available, None otherwise.
        """
        return self._thread_contexts.get(thread_ts)
