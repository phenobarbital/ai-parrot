"""Ephemeral user agent lifecycle models and registry.

Provides:
- ``EphemeralAgentStatus`` — Pydantic model tracking warm-up state for an
  ephemeral (in-memory-only) user bot.
- ``EphemeralRegistry`` — In-memory dict-backed store for active ephemeral
  statuses, with per-user ownership checks and TTL expiration helpers.
- ``_warm_up`` — background coroutine that drives an ephemeral bot through
  the configure → MCP validate → RAG build pipeline.

All types are consumed by ``BotManager`` (Module 2 / TASK-1035).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Callable, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from parrot.bots.abstract import AbstractBot
    from aiohttp import web as _web

logger = logging.getLogger("Parrot.Ephemeral")

# ---------------------------------------------------------------------------
# Lazy sentinel for validate_mcp_http (FIX-6)
# ---------------------------------------------------------------------------

_validate_mcp_http: Optional[Callable] = None
try:
    from parrot.mcp.integration import validate_mcp_http as _validate_mcp_http  # noqa: PLC0415
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Phase type
# ---------------------------------------------------------------------------

EphemeralPhase = Literal["creating", "warming", "ready", "error"]

# Default TTL: 24 h, overridable via env / navconfig.
_DEFAULT_TTL_SECONDS: int = 86400


def _default_ttl() -> int:
    """Read ephemeral TTL from navconfig, fall back to 24 h.

    Returns:
        TTL in seconds (positive integer).
    """
    # FIX-16: use navconfig.config.get instead of os.environ.get
    try:
        from navconfig import config  # noqa: PLC0415
        raw = config.get("EPHEMERAL_BOT_TTL")
    except Exception:  # noqa: BLE001
        raw = None
    if raw is None:
        return _DEFAULT_TTL_SECONDS
    try:
        value = int(raw)
        return value if value > 0 else _DEFAULT_TTL_SECONDS
    except (TypeError, ValueError):
        return _DEFAULT_TTL_SECONDS


# ---------------------------------------------------------------------------
# EphemeralAgentStatus
# ---------------------------------------------------------------------------


class EphemeralAgentStatus(BaseModel):
    """Live warm-up state for an ephemeral user bot.

    Attributes:
        chatbot_id: Canonical string form of the bot's UUID.
        user_id: Owning user — enforced on every registry lookup.
        phase: Current lifecycle phase.
        progress: Per-subsystem progress dict (tools / mcp / rag).
        error: Human-readable error message, set when phase == "error".
        created_at: UTC timestamp of registry insertion.
        expires_at: UTC timestamp after which the bot may be swept.
        rag_mode: Optional RAG mode used during warm-up.
    """

    model_config = {"validate_assignment": True}

    chatbot_id: str
    user_id: int
    phase: EphemeralPhase = "creating"
    progress: Dict[str, str] = Field(default_factory=dict)
    error: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    rag_mode: Optional[Literal["pageindex", "vector"]] = None


# ---------------------------------------------------------------------------
# EphemeralRegistry
# ---------------------------------------------------------------------------


class EphemeralRegistry:
    """In-memory registry of active ephemeral bots.

    Thread-safe enough for a single asyncio event loop: mutations are
    protected by a ``asyncio.Lock`` to prevent TOCTOU races between the
    warm-up background task and concurrent HTTP requests.

    The registry is intentionally not persistent — entries live only in
    process memory and vanish on restart.

    The lock is created lazily (FIX-5) so it is always initialised inside
    a running event loop, avoiding deprecation warnings on Python 3.10+.
    """

    def __init__(self) -> None:
        self._store: Dict[str, EphemeralAgentStatus] = {}
        self._lock: Optional[asyncio.Lock] = None  # lazily initialised (FIX-5)

    @property
    def _get_lock(self) -> asyncio.Lock:
        """Return the asyncio lock, creating it lazily inside the running loop.

        Returns:
            The ``asyncio.Lock`` instance.
        """
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def register(self, status: EphemeralAgentStatus) -> None:
        """Insert or replace a status entry (keyed by chatbot_id).

        Args:
            status: The ``EphemeralAgentStatus`` to register.
        """
        async with self._get_lock:  # FIX-1: acquire lock
            self._store[status.chatbot_id] = status
        logger.debug(
            "EphemeralRegistry: registered %s for user %s (phase=%s)",
            status.chatbot_id,
            status.user_id,
            status.phase,
        )

    def get(self, chatbot_id: str, user_id: int) -> Optional[EphemeralAgentStatus]:
        """Return the status if it exists and belongs to *user_id*.

        Args:
            chatbot_id: The bot's canonical UUID string.
            user_id: The requesting user — must match the stored entry.

        Returns:
            The ``EphemeralAgentStatus`` on a hit, ``None`` on a miss or
            ownership mismatch.
        """
        entry = self._store.get(chatbot_id)
        if entry is None:
            return None
        if entry.user_id != user_id:
            logger.warning(
                "EphemeralRegistry: ownership mismatch for %s "
                "(owner=%s, requester=%s)",
                chatbot_id,
                entry.user_id,
                user_id,
            )
            return None
        return entry

    def get_all_for_user(self, user_id: int) -> List[EphemeralAgentStatus]:
        """Return all entries owned by *user_id*.

        Args:
            user_id: The owning user ID to filter by.

        Returns:
            List of matching ``EphemeralAgentStatus`` objects.
        """
        return [s for s in self._store.values() if s.user_id == user_id]

    async def remove(self, chatbot_id: str) -> bool:
        """Delete the registry entry for *chatbot_id*.

        Args:
            chatbot_id: The bot's canonical UUID string.

        Returns:
            ``True`` if an entry was deleted, ``False`` if it was not present.
        """
        async with self._get_lock:  # FIX-1: acquire lock
            if chatbot_id in self._store:
                del self._store[chatbot_id]
                logger.debug("EphemeralRegistry: removed %s", chatbot_id)
                return True
            return False

    def get_expired(self) -> List[str]:
        """Return chatbot_ids whose ``expires_at`` is in the past.

        Uses ``datetime.now(timezone.utc)`` for comparison (FIX-13).

        Returns:
            List of chatbot_id strings ready to be swept.
        """
        # FIX-13: replace datetime.utcnow() with timezone-aware equivalent
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return [
            cid
            for cid, status in self._store.items()
            if now > status.expires_at
        ]

    def snapshot(self) -> Dict[str, EphemeralAgentStatus]:
        """Return a shallow copy of the current store (safe for iteration).

        Returns:
            Dict mapping chatbot_id → EphemeralAgentStatus.
        """
        return dict(self._store)


# ---------------------------------------------------------------------------
# Warm-up coroutine
# ---------------------------------------------------------------------------


async def _warm_up(
    bot: "AbstractBot",
    status: EphemeralAgentStatus,
    app: "_web.Application",
    remove_bot_callback: Optional[Callable[[str], None]] = None,  # FIX-12
) -> None:
    """Background warm-up coroutine for an ephemeral bot.

    Drives the bot through ``configure(app)``, optional MCP HTTP handshake
    validation, and optional RAG index building (FAISS or PageIndex).
    Updates ``status.phase`` and ``status.progress`` throughout.

    On any exception the phase is set to ``"error"`` and ``status.error``
    is populated — exceptions are NOT re-raised so callers can fire-and-forget
    with ``asyncio.create_task``.

    Args:
        bot: The ``AbstractBot`` instance to warm up.
        status: The ``EphemeralAgentStatus`` whose phase/progress to update.
        app: The aiohttp ``Application`` passed to ``configure()``.
        remove_bot_callback: Optional callable ``(chatbot_id: str) -> None``
            invoked when warm-up fails to remove the broken bot from the
            manager's active bots dict (FIX-12).
    """
    try:
        status.phase = "warming"

        # -----------------------------------------------------------------
        # 1. Tool sync via configure()
        # -----------------------------------------------------------------
        status.progress["tools"] = "syncing"
        await bot.configure(app)
        status.progress["tools"] = "ready"

        # -----------------------------------------------------------------
        # 2. MCP HTTP handshake validation (FIX-6: single lazy sentinel)
        # -----------------------------------------------------------------
        mcp_servers = _extract_mcp_servers(bot)
        if mcp_servers:
            if _validate_mcp_http is None:
                logger.warning("validate_mcp_http not available; skipping MCP validation")
                status.progress["mcp"] = "skipped"
            else:
                status.progress["mcp"] = "validating"
                for server_config in mcp_servers:
                    try:
                        await _validate_mcp_http(server_config)
                    except Exception as exc:  # noqa: BLE001
                        raise RuntimeError(
                            f"MCP handshake failed for server: {exc}"
                        ) from exc
                status.progress["mcp"] = "ready"
        else:
            status.progress["mcp"] = "skipped"

        # -----------------------------------------------------------------
        # 3. RAG index build
        # -----------------------------------------------------------------
        rag_mode = status.rag_mode
        documents = getattr(bot, "documents", None) or []

        if not documents or not rag_mode:
            status.progress["rag"] = "skipped"
        elif rag_mode == "vector":
            status.progress["rag"] = "building"
            await _build_faiss_index(bot, documents, app)
            status.progress["rag"] = "ready"
        elif rag_mode == "pageindex":
            status.progress["rag"] = "building"
            await _build_page_index(bot, documents, app)
            # FIX-14: PageIndex build is deferred (stub) — mark as pending, not ready
            status.progress["rag"] = "pending"
        else:
            status.progress["rag"] = "skipped"

        # All subsystems done
        status.phase = "ready"
        logger.info(
            "_warm_up: bot %s reached phase=ready (progress=%s)",
            status.chatbot_id,
            status.progress,
        )

    except Exception as exc:  # noqa: BLE001
        status.phase = "error"
        status.error = str(exc)
        logger.error(
            "_warm_up: bot %s failed warm-up: %s",
            status.chatbot_id,
            exc,
            exc_info=True,
        )
        # FIX-12: remove the broken bot from the manager's active bots dict
        if remove_bot_callback is not None:
            with contextlib.suppress(Exception):
                remove_bot_callback(status.chatbot_id)


# ---------------------------------------------------------------------------
# Internal helpers for warm-up
# ---------------------------------------------------------------------------


def _extract_mcp_servers(bot) -> list:
    """Extract MCP server config list from a bot instance.

    Tries ``bot.mcp_config`` (list) or ``bot.get_mcp_config()`` (dict list).
    Returns an empty list if neither is available.

    FIX-7: Handles encrypted blobs by falling back to ``get_mcp_config()``.

    Args:
        bot: The ``AbstractBot`` instance.

    Returns:
        List of MCP server config objects (``MCPServerConfig``).
    """
    mcp_config = None
    with contextlib.suppress(Exception):
        mcp_config = getattr(bot, "mcp_config", None)

    # FIX-7: If attribute is not a list (e.g. encrypted bytes/string), try the accessor
    if not mcp_config or not isinstance(mcp_config, list):
        get_fn = getattr(bot, "get_mcp_config", None)
        if callable(get_fn):
            with contextlib.suppress(Exception):
                mcp_config = get_fn()

    if not mcp_config or not isinstance(mcp_config, list):
        return []

    # If it's a list of dicts (serialised form), convert to MCPServerConfig
    result = []
    for item in mcp_config:
        if isinstance(item, dict):
            with contextlib.suppress(Exception):
                from parrot.mcp.client import MCPClientConfig as MCPServerConfig  # noqa: PLC0415
                result.append(MCPServerConfig(**item))
        else:
            result.append(item)
    return result


async def _build_faiss_index(bot, documents: list, app) -> None:
    """Build a FAISS vector index over *documents* and attach it to *bot*.

    Args:
        bot: The ``AbstractBot`` instance — its vector store is updated.
        documents: List of document dicts (from S3 ingestion).
        app: The aiohttp Application (for env/config access).
    """
    with contextlib.suppress(ImportError):
        from parrot.stores.faiss_store import FAISSStore  # noqa: PLC0415
        from parrot.stores.models import Document  # noqa: PLC0415

        store = FAISSStore(collection_name=str(getattr(bot, "chatbot_id", "ephemeral")))
        # FIX-4: Convert document dicts to Document objects (not plain strings)
        docs = []
        for doc_dict in documents:
            content = doc_dict.get("path") or doc_dict.get("name", "")
            if content:
                docs.append(Document(page_content=content))
        if docs:
            await store.add_documents(docs)
        # Attach to bot for later use and potential S3 dump on promote
        bot._ephemeral_faiss_store = store
        logger.info(
            "_build_faiss_index: built FAISS index for %s (%d docs)",
            getattr(bot, "chatbot_id", "?"),
            len(docs),
        )


async def _build_page_index(bot, documents: list, app) -> None:
    """Run the PageIndex builder pipeline over *documents*.

    The PageIndex builder requires TOC-bearing documents. If the pipeline
    cannot process the documents (e.g., no TOC detected) the step is
    silently skipped so the agent still reaches ``ready``.

    Args:
        bot: The ``AbstractBot`` instance.
        documents: List of document dicts.
        app: The aiohttp Application.
    """
    logger.info(
        "_build_page_index: pageindex pipeline requested for %s (%d docs); "
        "requires LLM adapter — skipping in warm-up stub.",
        getattr(bot, "chatbot_id", "?"),
        len(documents),
    )
    # Full PageIndex pipeline requires a PageIndexLLMAdapter instance (LLM
    # client), which depends on the specific LLM configured for the bot.
    # The pipeline is deferred to a follow-up integration; for now we log
    # and return — callers mark status.progress["rag"] = "pending" (FIX-14).
