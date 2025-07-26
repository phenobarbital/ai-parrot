from typing import Dict, List, Optional, Any
import asyncio
import aiofiles
from pathlib import Path
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa
from .abstract import ConversationMemory, ConversationHistory, ConversationTurn


class FileConversationMemory(ConversationMemory):
    """File-based implementation of conversation memory."""

    def __init__(self, base_path: str = "./conversations"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(exist_ok=True)
        self._lock = asyncio.Lock()

    def _get_file_path(self, user_id: str, session_id: str) -> Path:
        """Get file path for a conversation history."""
        user_dir = self.base_path / user_id
        user_dir.mkdir(exist_ok=True)
        return user_dir / f"{session_id}.json"

    async def create_history(
        self,
        user_id: str,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ConversationHistory:
        """Create a new conversation history."""
        async with self._lock:
            history = ConversationHistory(
                session_id=session_id,
                user_id=user_id,
                metadata=metadata or {}
            )

            file_path = self._get_file_path(user_id, session_id)
            with open(file_path, 'w', encoding='utf-8') as f:
                json_encoder(history.to_dict(), f, indent=2, ensure_ascii=False)

            return history

    async def get_history(self, user_id: str, session_id: str) -> Optional[ConversationHistory]:
        """Get a conversation history."""
        async with self._lock:
            file_path = self._get_file_path(user_id, session_id)
            if not file_path.exists():
                return None

            try:
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                    data = await json_decoder(f)
                return ConversationHistory.from_dict(data)
            except (TypeError, KeyError, ValueError):
                return None

    async def update_history(self, history: ConversationHistory) -> None:
        """Update a conversation history."""
        async with self._lock:
            file_path = self._get_file_path(history.user_id, history.session_id)
            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                await json_encoder(history.to_dict(), f, indent=2, ensure_ascii=False)

    async def add_turn(self, user_id: str, session_id: str, turn: ConversationTurn) -> None:
        """Add a turn to the conversation."""
        history = await self.get_history(user_id, session_id)
        if history:
            history.add_turn(turn)
            await self.update_history(history)

    async def clear_history(self, user_id: str, session_id: str) -> None:
        """Clear a conversation history."""
        history = await self.get_history(user_id, session_id)
        if history:
            history.clear_turns()
            await self.update_history(history)

    async def list_sessions(self, user_id: str) -> List[str]:
        """List all session IDs for a user."""
        async with self._lock:
            user_dir = self.base_path / user_id
            if not user_dir.exists():
                return []

            sessions = []
            for file_path in user_dir.glob("*.json"):
                sessions.append(file_path.stem)
            return sessions

    async def delete_history(self, user_id: str, session_id: str) -> bool:
        """Delete a conversation history entirely."""
        async with self._lock:
            file_path = self._get_file_path(user_id, session_id)
            if file_path.exists():
                file_path.unlink()
                return True
            return False
