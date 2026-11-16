"""Episodic recall visibility of one request.

One policy, shared by automatic recall (``UnifiedMemoryManager``) and by the agent-facing
tools (``EpisodicMemoryToolkit``): a request recalls its own episodes plus the agent-level
ones, and never another user's.
"""

from __future__ import annotations

from typing import Any

from .models import MemoryNamespace

_NARROWING_DIMENSIONS = ("room_id", "crew_id", "model_id")


def recall_scopes(scope: Any) -> list[tuple[MemoryNamespace, tuple[str, ...]]]:
    """Return the namespace filters that make up one request's episodic recall visibility.

    - an identified user: that user's episodes in every session;
    - an anonymous request with a session: that session's episodes that carry no user;
    - always: agent-level episodes, recorded with neither a user nor a session (explicit
      lessons and episodes written before request scoping existed).

    Set room, crew and model dimensions keep narrowing every filter.

    Args:
        scope: Request identity exposing ``tenant_id``, ``agent_id`` and the optional dimensions
            (a ``MemoryRequestScope``).

    Returns:
        ``(namespace, null_dimensions)`` pairs for ``EpisodicMemoryStore.recall_similar``.
    """
    exact = MemoryNamespace(
        tenant_id=scope.tenant_id,
        agent_id=scope.agent_id,
        model_id=scope.model_id,
        user_id=scope.user_id,
        session_id=scope.session_id,
        room_id=scope.room_id,
        crew_id=scope.crew_id,
    )
    scopes: list[tuple[MemoryNamespace, tuple[str, ...]]] = []
    if scope.user_id is not None:
        scopes.append((exact.model_copy(update={"session_id": None}), ()))
    elif scope.session_id is not None:
        scopes.append((exact, ("user_id",)))
    agent_level = exact.model_copy(update={"user_id": None, "session_id": None})
    scopes.append((agent_level, ("user_id", "session_id")))
    return scopes


def visible_to_scope(episode: Any, scope: Any) -> bool:
    """Apply the visibility of :func:`recall_scopes` to one returned episode.

    Callers re-check every episode a backend returns, so a backend that ignores a filter
    cannot widen recall.

    Args:
        episode: A stored episode (``EpisodicMemory`` or a search result).
        scope: Request identity, as in :func:`recall_scopes`.

    Returns:
        True when the request may read the episode.
    """
    if (episode.tenant_id, episode.agent_id) != (scope.tenant_id, scope.agent_id):
        return False
    for dimension in _NARROWING_DIMENSIONS:
        wanted = getattr(scope, dimension)
        if wanted is not None and getattr(episode, dimension) != wanted:
            return False
    if episode.user_id is None and episode.session_id is None:
        return True
    if scope.user_id is not None:
        return episode.user_id == scope.user_id
    return episode.user_id is None and scope.session_id is not None and episode.session_id == scope.session_id
