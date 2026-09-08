from typing import Dict, List, Optional, Any, TYPE_CHECKING
import asyncio
import json
import aiofiles
from pathlib import Path
from .abstract import ConversationMemory, ConversationHistory, ConversationTurn
from .compaction.omission import FileOmissionStore, OmissionStore

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .compaction.tokens import TokenCounter


class FileConversationMemory(ConversationMemory):
    """File-based implementation of conversation memory."""

    def __init__(
        self,
        base_path: str = "./conversations",
        *,
        token_counter: Optional["TokenCounter"] = None,
        omission_store: Optional[OmissionStore] = None,
        normalize: bool = True,
    ) -> None:
        """Initialize the store.

        Args:
            base_path: Root directory for conversation history files.
            token_counter: Stage 0.5 counter override (see
                :class:`~parrot.memory.abstract.ConversationMemory`).
            omission_store: Omission-store override; defaults to a
                :class:`FileOmissionStore` sharing ``base_path``.
            normalize: Disables Stage 0 for this instance when ``False``.
        """
        self.base_path = Path(base_path)
        super().__init__(
            token_counter=token_counter,
            omission_store=omission_store or FileOmissionStore(self.base_path),
            normalize=normalize,
        )
        self.base_path.mkdir(exist_ok=True)
        self._lock = asyncio.Lock()

    def _get_file_path(self, user_id: str, session_id: str, chatbot_id: Optional[str] = None) -> Path:
        """Get file path for a conversation history."""
        user_dir = self.base_path / str(user_id)
        if chatbot_id:
            user_dir = user_dir / str(chatbot_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir / f"{session_id}.json"

    async def create_history(
        self, user_id: str, session_id: str, metadata: Optional[Dict[str, Any]] = None, chatbot_id: Optional[str] = None
    ) -> ConversationHistory:
        """Create a new conversation history."""
        async with self._lock:
            history = ConversationHistory(
                session_id=session_id, user_id=user_id, chatbot_id=chatbot_id, metadata=metadata or {}
            )

            file_path = self._get_file_path(user_id, session_id, chatbot_id)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(history.to_dict(), f, indent=2, ensure_ascii=False, default=str)

            return history

    async def get_history(
        self, user_id: str, session_id: str, chatbot_id: Optional[str] = None
    ) -> Optional[ConversationHistory]:
        """Get a conversation history, re-keying a legacy record if needed.

        FEAT-524 unified the storage path to ``{user}/{chatbot}/{session}.json``.
        Histories written before that live at ``{user}/{session}.json``. When
        ``chatbot_id`` is given and the segmented path holds nothing, the legacy
        path is read once, copied to the segmented path and returned. The legacy
        file is deliberately **left in place** so a rollback still finds it.

        Args:
            user_id: Owner of the conversation.
            session_id: Conversation session.
            chatbot_id: Agent path segment. Falsy means "read the legacy path
                directly" — no re-key is attempted.

        Returns:
            The history, or ``None`` when neither path holds one.
        """
        # One lock acquisition for read-and-maybe-copy: ``self._lock`` is a
        # plain asyncio.Lock (not reentrant), so calling update_history() from
        # in here would deadlock. The write is inlined via _write_history().
        async with self._lock:
            history = await self._read_history(user_id, session_id, chatbot_id)
            if history is not None or not chatbot_id:
                return history

            legacy = await self._read_history(user_id, session_id, None)
            if legacy is None:
                return None

            legacy.chatbot_id = str(chatbot_id)
            await self._write_history(legacy)
            self.logger.info("Re-keyed legacy conversation %s/%s under chatbot %s", user_id, session_id, chatbot_id)
            return legacy

    async def _read_history(
        self, user_id: str, session_id: str, chatbot_id: Optional[str] = None
    ) -> Optional[ConversationHistory]:
        """Read exactly one path, without fallback. Caller must hold ``_lock``.

        Args:
            user_id: Owner of the conversation.
            session_id: Conversation session.
            chatbot_id: Agent path segment; ``None`` reads the legacy path.

        Returns:
            The deserialized history, or ``None`` if the file is absent or
            cannot be parsed.
        """
        file_path = self._get_file_path(user_id, session_id, chatbot_id)
        if not file_path.exists():
            return None

        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                content = await f.read()
            data = json.loads(content)
            return ConversationHistory.from_dict(data)
        except (TypeError, KeyError, ValueError):
            return None

    async def _write_history(self, history: ConversationHistory) -> None:
        """Write a history to its own path. Caller must hold ``_lock``.

        Args:
            history: The history to persist; its ``chatbot_id`` selects the path.
        """
        file_path = self._get_file_path(history.user_id, history.session_id, history.chatbot_id)
        async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(history.to_dict(), indent=2, ensure_ascii=False, default=str))

    async def update_history(self, history: ConversationHistory) -> None:
        """Update a conversation history."""
        async with self._lock:
            await self._write_history(history)

    async def _store_turn(
        self,
        user_id: str,
        session_id: str,
        turn: ConversationTurn,
        chatbot_id: Optional[str] = None,
        *,
        compaction_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append ``turn``, set ``metadata['compaction']`` when given, and rewrite the file once."""
        history = await self.get_history(user_id, session_id, chatbot_id)
        if history:
            history.add_turn(turn)
            if compaction_state is not None:
                history.metadata["compaction"] = compaction_state
            await self.update_history(history)

    async def clear_history(self, user_id: str, session_id: str, chatbot_id: Optional[str] = None) -> None:
        """Clear a conversation history."""
        history = await self.get_history(user_id, session_id, chatbot_id)
        if history:
            history.clear_turns()
            await self.update_history(history)
        await self.omission_store.clear(self.omission_key(user_id, session_id, chatbot_id))

    async def list_sessions(self, user_id: str, chatbot_id: Optional[str] = None) -> List[str]:
        """List all session IDs for a user."""
        async with self._lock:
            base_user_dir = self.base_path / str(user_id)
            if not base_user_dir.exists():
                return []

            sessions: List[str] = []
            seen = set()
            if chatbot_id is None:
                for file_path in base_user_dir.glob("*.json"):
                    if file_path.stem not in seen:
                        seen.add(file_path.stem)
                        sessions.append(file_path.stem)
                for subdir in base_user_dir.iterdir():
                    if subdir.is_dir():
                        for file_path in subdir.glob("*.json"):
                            if file_path.stem not in seen:
                                seen.add(file_path.stem)
                                sessions.append(file_path.stem)
            else:
                chatbot_dir = base_user_dir / str(chatbot_id)
                if chatbot_dir.exists():
                    for file_path in chatbot_dir.glob("*.json"):
                        if file_path.stem not in seen:
                            seen.add(file_path.stem)
                            sessions.append(file_path.stem)

            return sessions

    async def delete_history(self, user_id: str, session_id: str, chatbot_id: Optional[str] = None) -> bool:
        """Delete a conversation history entirely."""
        await self.omission_store.clear(self.omission_key(user_id, session_id, chatbot_id))
        async with self._lock:
            file_path = self._get_file_path(user_id, session_id, chatbot_id)
            if file_path.exists():
                file_path.unlink()
                return True
            return False
