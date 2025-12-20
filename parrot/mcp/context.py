"""
MCP Context Module.

Provides ReadonlyContext for context-aware tool access and MCPSessionManager
for session lifecycle management with retry logic.
"""
import asyncio
import logging
from functools import wraps
from typing import Dict, List, Any, Optional, Callable, TypeVar, Awaitable

from pydantic import BaseModel, ConfigDict


class ReadonlyContext(BaseModel):
    """Immutable context passed to tool operations.

    This context provides information about the agent, user, and organizational
    context for tool execution. It enables:
    - Tool filtering based on user roles/scopes
    - Dynamic header generation
    - Multi-tenant isolation
    - Rate limiting by user/organization

    Example:
        >>> ctx = ReadonlyContext(
        ...     agent_id="hr-agent",
        ...     user_id="user-123",
        ...     organization_id="acme-corp",
        ...     roles=["admin", "hr"],
        ...     scopes=["read:employees", "write:employees"]
        ... )
        >>> # Context is immutable
        >>> ctx.user_id = "other"  # Raises ValidationError
    """
    agent_id: str
    user_id: Optional[str] = None
    organization_id: Optional[str] = None
    roles: List[str] = []
    scopes: List[str] = []
    conversation_id: Optional[str] = None
    metadata: Dict[str, Any] = {}

    model_config = ConfigDict(frozen=True)


class TransientMCPError(Exception):
    """Transient MCP errors that should be retried.

    Use this for errors like connection timeouts, temporary server unavailability,
    rate limiting, etc. The retry_on_errors decorator will automatically retry
    operations that raise this exception.
    """
    pass


F = TypeVar('F', bound=Callable[..., Awaitable[Any]])


def retry_on_errors(max_retries: int = 3, base_wait: float = 2.0) -> Callable[[F], F]:
    """Decorator for automatic retry on transient errors with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        base_wait: Base wait time in seconds for exponential backoff (default: 2.0)

    Returns:
        Decorated async function with retry logic

    Example:
        >>> @retry_on_errors(max_retries=3)
        ... async def get_tools(self):
        ...     # This will auto-retry on TransientMCPError
        ...     return await self._session.list_tools()
    """
    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            logger = logging.getLogger("MCPRetry")
            last_error = None

            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except TransientMCPError as e:
                    last_error = e
                    if attempt == max_retries - 1:
                        raise

                    wait_time = base_wait ** attempt
                    logger.warning(
                        f"Transient error on attempt {attempt + 1}/{max_retries}, "
                        f"retrying in {wait_time:.1f}s: {e}"
                    )
                    await asyncio.sleep(wait_time)

            # Should not reach here, but just in case
            if last_error:
                raise last_error

        return wrapper  # type: ignore
    return decorator


class MCPSessionManager:
    """Manages session lifecycle and retry logic for MCP connections.

    Features:
    - Session caching keyed by headers (for multi-user scenarios)
    - Automatic retry with exponential backoff on transient failures
    - Configurable max retries

    Example:
        >>> manager = MCPSessionManager(config, max_retries=3)
        >>> session = await manager.create_session(headers={"X-User-ID": "123"})
        >>> # Session is cached - same headers return same session
        >>> same_session = await manager.create_session(headers={"X-User-ID": "123"})
    """

    def __init__(
        self,
        config: Any,  # MCPClientConfig - avoid circular import
        max_retries: int = 3,
        base_wait: float = 2.0
    ):
        self.config = config
        self.max_retries = max_retries
        self.base_wait = base_wait
        self.sessions: Dict[int, Any] = {}
        self.logger = logging.getLogger(f"MCPSessionManager.{getattr(config, 'name', 'unknown')}")

    def _session_key(self, headers: Optional[Dict[str, str]] = None) -> int:
        """Generate cache key from headers."""
        if not headers:
            return 0
        return hash(tuple(sorted(headers.items())))

    async def create_session(
        self,
        headers: Optional[Dict[str, str]] = None,
        force_new: bool = False
    ) -> Any:
        """Create or retrieve cached session with retry.

        Args:
            headers: Optional headers that affect session identity
            force_new: If True, create new session even if cached

        Returns:
            MCP session object
        """
        session_key = self._session_key(headers)

        if not force_new and session_key in self.sessions:
            session = self.sessions[session_key]
            # Verify session is still valid
            if await self._is_session_valid(session):
                return session
            else:
                self.logger.debug("Cached session invalid, creating new one")
                del self.sessions[session_key]

        session = await self._create_session_with_retry(headers)
        self.sessions[session_key] = session
        return session

    async def _create_session_with_retry(
        self,
        headers: Optional[Dict[str, str]]
    ) -> Any:
        """Create session with exponential backoff."""
        last_error = None

        for attempt in range(self.max_retries):
            try:
                return await self._do_create_session(headers)
            except (TransientMCPError, ConnectionError, asyncio.TimeoutError) as e:
                last_error = e
                if attempt == self.max_retries - 1:
                    raise TransientMCPError(
                        f"Session creation failed after {self.max_retries} attempts: {e}"
                    ) from e

                wait_time = self.base_wait ** attempt
                self.logger.warning(
                    f"Session creation failed (attempt {attempt + 1}/{self.max_retries}), "
                    f"retrying in {wait_time:.1f}s: {e}"
                )
                await asyncio.sleep(wait_time)

        # Should not reach here
        if last_error:
            raise last_error

    async def _do_create_session(self, headers: Optional[Dict[str, str]]) -> Any:
        """Override this method to implement actual session creation.

        Subclasses should implement the actual transport-specific session
        creation logic here.

        Args:
            headers: Optional headers for the session

        Returns:
            Created session object
        """
        raise NotImplementedError("Subclasses must implement _do_create_session")

    async def _is_session_valid(self, session: Any) -> bool:
        """Check if a cached session is still valid.

        Override this in subclasses for transport-specific validation.
        Default implementation returns True (assume sessions are valid).
        """
        return True

    async def invalidate_session(self, headers: Optional[Dict[str, str]] = None) -> None:
        """Invalidate a cached session."""
        session_key = self._session_key(headers)
        if session_key in self.sessions:
            session = self.sessions.pop(session_key)
            await self._close_session(session)

    async def invalidate_all(self) -> None:
        """Invalidate all cached sessions."""
        for session in self.sessions.values():
            await self._close_session(session)
        self.sessions.clear()

    async def _close_session(self, session: Any) -> None:
        """Close a session. Override for transport-specific cleanup."""
        if hasattr(session, 'disconnect'):
            try:
                await session.disconnect()
            except Exception as e:
                self.logger.debug(f"Error closing session: {e}")
        elif hasattr(session, 'close'):
            try:
                await session.close()
            except Exception as e:
                self.logger.debug(f"Error closing session: {e}")
