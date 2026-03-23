# parrot/advisors/manager.py
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
import json
from redis.asyncio import Redis
from ..conf import REDIS_HISTORY_URL
from .state import SelectionState, SelectionHistory, StateSnapshot, SelectionPhase


class SelectionStateManager:
    """
    Manages selection state with Redis persistence and Memento pattern.

    Responsibilities:
    - CRUD for SelectionState
    - Memento history management (undo/redo)
    - State transitions
    - TTL management
    """

    def __init__(
        self,
        redis_url: str = None,
        key_prefix: str = "product_selection",
        state_ttl: timedelta = timedelta(hours=24),
    ):
        self.redis_url = redis_url or REDIS_HISTORY_URL
        self.key_prefix = key_prefix
        self.state_ttl = state_ttl
        self._redis: Optional[Redis] = None

    async def _get_redis(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(
                self.redis_url,
                decode_responses=True,
                encoding="utf-8"
            )
        return self._redis

    def _state_key(self, session_id: str, user_id: str) -> str:
        return f"{self.key_prefix}:state:{user_id}:{session_id}"

    def _history_key(self, session_id: str, user_id: str) -> str:
        return f"{self.key_prefix}:history:{user_id}:{session_id}"

    # ─────────────────────────────────────────────────────────────────────────
    # State CRUD
    # ─────────────────────────────────────────────────────────────────────────

    async def create_state(
        self,
        session_id: str,
        user_id: str,
        catalog_id: str,
        product_ids: List[str],
        metadata: Dict[str, Any] = None
    ) -> SelectionState:
        """Create a new selection state."""
        state = SelectionState(
            session_id=session_id,
            user_id=user_id,
            catalog_id=catalog_id,
            phase=SelectionPhase.INTAKE,
            all_product_ids=product_ids,
            candidate_ids=product_ids.copy(),
            started_at=datetime.utcnow(),
            metadata=metadata or {}
        )

        await self._save_state(state)

        # Initialize history with first snapshot
        history = SelectionHistory()
        history.push(StateSnapshot.from_state(state, action="started"))
        await self._save_history(session_id, user_id, history)

        return state

    async def get_state(
        self,
        session_id: str,
        user_id: str
    ) -> Optional[SelectionState]:
        """Get current selection state."""
        redis = await self._get_redis()
        data = await redis.get(self._state_key(session_id, user_id))
        if data:
            return SelectionState(**json.loads(data))
        return None

    async def _save_state(self, state: SelectionState) -> None:
        """Save state to Redis."""
        redis = await self._get_redis()
        state.updated_at = datetime.utcnow()
        await redis.setex(
            self._state_key(state.session_id, state.user_id),
            int(self.state_ttl.total_seconds()),
            state.model_dump_json()
        )

    async def _save_history(
        self,
        session_id: str,
        user_id: str,
        history: SelectionHistory
    ) -> None:
        """Save history to Redis."""
        redis = await self._get_redis()
        await redis.setex(
            self._history_key(session_id, user_id),
            int(self.state_ttl.total_seconds()),
            history.model_dump_json()
        )

    async def _get_history(
        self,
        session_id: str,
        user_id: str
    ) -> SelectionHistory:
        """Get history from Redis."""
        redis = await self._get_redis()
        data = await redis.get(self._history_key(session_id, user_id))
        if data:
            return SelectionHistory(**json.loads(data))
        return SelectionHistory()

    # ─────────────────────────────────────────────────────────────────────────
    # State Updates (with Memento)
    # ─────────────────────────────────────────────────────────────────────────

    async def apply_criteria(
        self,
        session_id: str,
        user_id: str,
        criteria_key: str,
        criteria_value: Any,
        question: str = None,
        answer: str = None,
        products_to_keep: List[str] = None
    ) -> Tuple[SelectionState, int]:
        """
        Apply a criterion and filter products.

        Returns:
            Tuple of (updated_state, products_eliminated)
        """
        state = await self.get_state(session_id, user_id)
        if not state:
            raise ValueError("No active selection state")

        # Save snapshot before modification (Memento)
        history = await self._get_history(session_id, user_id)
        history.push(StateSnapshot.from_state(
            state,
            action=f"Applied {criteria_key}={criteria_value}",
            question=question,
            answer=answer
        ))

        # Update criteria
        state.criteria[criteria_key] = criteria_value
        if question:
            state.questions_asked.append(question)

        # Filter products
        original_count = len(state.candidate_ids)
        if products_to_keep is not None:
            eliminated = set(state.candidate_ids) - set(products_to_keep)
            for pid in eliminated:
                state.eliminated[pid] = f"Did not match {criteria_key}={criteria_value}"
            state.candidate_ids = products_to_keep

        # Update phase
        if state.products_remaining <= 1:
            state.phase = SelectionPhase.RECOMMENDATION
        elif state.products_remaining <= 3:
            state.phase = SelectionPhase.COMPARISON
        else:
            state.phase = SelectionPhase.QUESTIONING

        # Save
        await self._save_state(state)
        await self._save_history(session_id, user_id, history)

        return state, original_count - len(state.candidate_ids)

    # ─────────────────────────────────────────────────────────────────────────
    # Memento Operations
    # ─────────────────────────────────────────────────────────────────────────

    async def undo(
        self,
        session_id: str,
        user_id: str
    ) -> Tuple[Optional[SelectionState], Optional[str]]:
        """
        Undo last action.

        Returns:
            Tuple of (restored_state, action_undone) or (None, None) if can't undo
        """
        history = await self._get_history(session_id, user_id)

        if not history.can_undo():
            return None, None

        # Get current action name before undoing
        current_snapshot = history._get_current_snapshot()
        action_undone = current_snapshot.action

        # Undo
        previous = history.undo()
        if previous:
            await self._save_state(previous.state)
            await self._save_history(session_id, user_id, history)
            return previous.state, action_undone

        return None, None

    async def redo(
        self,
        session_id: str,
        user_id: str
    ) -> Tuple[Optional[SelectionState], Optional[str]]:
        """
        Redo previously undone action.

        Returns:
            Tuple of (restored_state, action_redone) or (None, None) if can't redo
        """
        history = await self._get_history(session_id, user_id)

        if not history.can_redo():
            return None, None

        next_snapshot = history.redo()
        if next_snapshot:
            await self._save_state(next_snapshot.state)
            await self._save_history(session_id, user_id, history)
            return next_snapshot.state, next_snapshot.action

        return None, None

    async def get_history_summary(
        self,
        session_id: str,
        user_id: str
    ) -> List[Dict[str, Any]]:
        """Get human-readable history for display."""
        history = await self._get_history(session_id, user_id)
        return history.get_history_summary()

    async def can_undo(self, session_id: str, user_id: str) -> bool:
        """Check if undo is available."""
        history = await self._get_history(session_id, user_id)
        return history.can_undo()

    async def can_redo(self, session_id: str, user_id: str) -> bool:
        """Check if redo is available."""
        history = await self._get_history(session_id, user_id)
        return history.can_redo()

    # ─────────────────────────────────────────────────────────────────────────
    # Cleanup
    # ─────────────────────────────────────────────────────────────────────────

    async def delete_state(self, session_id: str, user_id: str) -> bool:
        """Delete selection state and history."""
        redis = await self._get_redis()
        deleted = await redis.delete(
            self._state_key(session_id, user_id),
            self._history_key(session_id, user_id)
        )
        return deleted > 0

    async def close(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None
