import json
import time
from typing import Dict, Any, Optional
from datetime import timedelta

try:
    from navconfig.logging import logging
except ImportError:
    import logging

logger = logging.getLogger(__name__)


class InMemoryStateStore:
    """Simple in-memory key-value store with TTL support.

    Used as a fallback when no persistent store (e.g., Redis) is available.

    .. warning::
        **Memory leak risk** — this store holds all keys in memory indefinitely
        unless they are explicitly deleted or their TTL is checked on access.
        Entries with an ``expire`` value are evicted lazily on ``get()`` and
        swept proactively (via :meth:`_sweep_expired`) whenever the store
        exceeds ``_SWEEP_THRESHOLD`` entries.  For production workloads with
        high message volumes, replace this with a real Redis-backed store.
    """

    _SWEEP_THRESHOLD: int = 1000

    def __init__(self):
        self._data: Dict[str, Any] = {}
        self._expiry: Dict[str, float] = {}

    def _sweep_expired(self) -> None:
        """Remove all expired keys. Called automatically when store grows large."""
        now = time.monotonic()
        expired = [k for k, t in self._expiry.items() if now > t]
        for k in expired:
            self._data.pop(k, None)
            self._expiry.pop(k, None)

    async def set(self, key: str, value: str, expire: int = 0) -> None:
        self._data[key] = value
        if expire > 0:
            self._expiry[key] = time.monotonic() + expire
        if len(self._data) > self._SWEEP_THRESHOLD:
            self._sweep_expired()

    async def get(self, key: str) -> Optional[str]:
        if key in self._expiry and time.monotonic() > self._expiry[key]:
            self._data.pop(key, None)
            self._expiry.pop(key, None)
            return None
        return self._data.get(key)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)
        self._expiry.pop(key, None)


class IntegrationStateManager:
    """
    Manages state for chat integrations (Telegram, MS Teams, Slack, Matrix).
    
    Tracks when a user in a specific chat context is waiting for a handoff response
    (Human-in-the-Loop) rather than starting a new conversation turn.
    """
    
    # Prefix for redis keys
    KEY_PREFIX = "integration:state:"
    
    # Default TTL for waiting on a human response
    DEFAULT_TTL = timedelta(minutes=10)
    
    def __init__(self, store: Any = None):
        """
        Initialize the state manager.

        Args:
            store: Persistent store implementation (e.g., RedisStore).
                   Falls back to an in-memory store if not provided.
        """
        self.store = store or InMemoryStateStore()
        
    def _make_key(self, integration: str, chat_id: str, user_id: str) -> str:
        """Create a unique key for the chat context."""
        return f"{self.KEY_PREFIX}{integration}:{chat_id}:{user_id}"
        
    async def set_suspended_state(
        self, 
        integration_id: str, 
        chat_id: str, 
        user_id: str, 
        session_id: str,
        agent_name: str,
        execution_state: str = "handoff_waiting"
    ) -> bool:
        """
        Mark a user/chat context as suspended, waiting for human input.
        
        Args:
            integration_id: Platform name (e.g., 'telegram', 'msteams')
            chat_id: Chat/Channel ID
            user_id: User ID 
            session_id: The execution session ID to resume later
            agent_name: Name of the agent that was executing
            execution_state: String describing the state
            
        Returns:
            bool: True if successful
        """
        key = self._make_key(integration_id, chat_id, user_id)
        
        data = {
            "session_id": session_id,
            "agent_name": agent_name,
            "state": execution_state
        }
        
        try:
            # Note: TTL handling depends on the store implementation
            # We enforce a TTL of 10 minutes (600 seconds)
            await self.store.set(key, json.dumps(data), expire=int(self.DEFAULT_TTL.total_seconds()))
            logger.debug(
                "Set suspended state for %s:%s:%s -> Session %s",
                integration_id, chat_id, user_id, session_id,
            )
            return True
        except Exception as e:
            logger.error("Failed to set suspended state: %s", e)
            return False
            
    async def get_suspended_session(
        self,
        integration_id: str,
        chat_id: str,
        user_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Check if there's a suspended session for this user/chat context.
        
        Args:
            integration_id: Identifier for the integration (e.g., 'telegram', 'slack')
            chat_id: The chat or channel ID
            user_id: The user ID within the integration
            
        Returns:
            The suspended state dictionary if one exists, None otherwise.
        """
        key = self._make_key(integration_id, chat_id, user_id)
        try:
            state_str = await self.store.get(key)
            if state_str:
                return json.loads(state_str)
        except Exception as e:
            logger.error("Failed to get suspended session from store: %s", e)

        return None
            
    async def clear_suspended_state(
        self, 
        integration_id: str, 
        chat_id: str, 
        user_id: str
    ) -> bool:
        """
        Clear the suspended state for a user context.
        Call this after successfully resuming the agent.
        
        Args:
            integration_id: Platform name
            chat_id: Chat/Channel ID
            user_id: User ID
            
        Returns:
            bool: True if successful
        """
        key = self._make_key(integration_id, chat_id, user_id)
        
        try:
            await self.store.delete(key)
            logger.debug(
                "Cleared suspended state for %s:%s:%s",
                integration_id, chat_id, user_id,
            )
            return True
        except Exception as e:
            logger.error("Failed to clear suspended state: %s", e)
            return False
