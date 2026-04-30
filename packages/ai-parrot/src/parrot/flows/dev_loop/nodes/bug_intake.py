"""BugIntakeNode — bug-specific intake hook for the dev-loop flow.

FEAT-132 scope-down: universal validation (allowlist heads, path-traversal)
has moved to :class:`IntentClassifierNode`, which runs before this node on
the bug path. ``BugIntakeNode`` is now a thin extension hook reserved for
future bug-only enrichment (severity classification, stack-trace parsing,
etc.). For v1 it re-emits ``flow.bug_brief_validated`` so existing
downstream observers keep working, and returns the brief unchanged.

This node deliberately does NOT call the dispatcher; the most
expensive thing it does is one ``XADD`` to the flow event stream.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict

from parrot.bots.flow.node import Node
from parrot.flows.dev_loop.models import BugBrief


class BugIntakeNode(Node):
    """Bug-specific intake hook — emits ``flow.bug_brief_validated`` event.

    FEAT-132 scope-down: universal validation now lives in
    :class:`IntentClassifierNode` (which runs before this node on the
    bug path). ``BugIntakeNode`` acts as an extension point for future
    bug-only enrichment without requiring the flow topology to change.

    Args:
        redis_url: Redis URL used to publish ``flow.bug_brief_validated``.
            The connection is lazy: the node is safe to construct without
            a live Redis. The actual publish happens on first ``execute``.
        name: Node id, defaults to ``"bug_intake"``.
    """

    def __init__(
        self,
        *,
        redis_url: str,
        name: str = "bug_intake",
    ) -> None:
        super().__init__()
        self._name = name
        self._init_node(name)
        self._redis_url = redis_url
        self._redis: Any = None
        self.logger = logging.getLogger(__name__)

    @property
    def name(self) -> str:
        """Node identifier used by the flow router."""
        return self._name

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(self, prompt: str, ctx: Dict[str, Any]) -> BugBrief:
        """Bug-specific intake hook (post FEAT-132 scope-down).

        Universal validation now happens in :class:`IntentClassifierNode`
        which runs before this node on the bug path. This node remains as
        an extension point for bug-only enrichment (severity classification,
        stack-trace parsing, etc.); for v1 it just re-emits
        ``flow.bug_brief_validated`` for downstream observers that already
        subscribe to that event.

        Args:
            prompt: Optional JSON string containing a serialized BugBrief.
                Used as a fallback when ``ctx["bug_brief"]`` is absent.
            ctx: Flow context. Must contain ``"run_id"`` for the event
                stream key. May contain ``"bug_brief"`` (a ``BugBrief``
                instance or a dict).

        Returns:
            The :class:`BugBrief` instance (already validated upstream).
        """
        brief = self._load_brief(prompt, ctx)
        run_id = ctx.get("run_id", "")
        if run_id:
            await self._emit_validated_event(run_id, brief)
        ctx["bug_brief"] = brief
        return brief

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_brief(self, prompt: str, ctx: Dict[str, Any]) -> BugBrief:
        """Load a :class:`BugBrief` from context or JSON prompt.

        Args:
            prompt: Raw JSON string representing a ``BugBrief``.
            ctx: Flow context dictionary.

        Returns:
            A validated :class:`BugBrief` instance.

        Raises:
            ValueError: When no source is available.
        """
        candidate = ctx.get("bug_brief")
        if isinstance(candidate, BugBrief):
            return candidate
        if isinstance(candidate, dict):
            return BugBrief.model_validate(candidate)
        if prompt:
            return BugBrief.model_validate_json(prompt)
        raise ValueError(
            "BugIntakeNode requires ctx['bug_brief'] or a JSON prompt."
        )

    async def _emit_validated_event(self, run_id: str, brief: BugBrief) -> None:
        """XADD one ``flow.bug_brief_validated`` event to the flow stream.

        Args:
            run_id: Identifies the Redis stream key ``flow:{run_id}:flow``.
            brief: The validated brief whose metadata is included in the
                event payload.
        """
        try:
            redis_client = await self._ensure_redis()
        except Exception as exc:  # pragma: no cover - degraded path
            self.logger.warning(
                "Redis unavailable, dropping bug_brief_validated event: %s",
                exc,
            )
            return
        event_payload = {
            "summary": brief.summary,
            "n_criteria": len(brief.acceptance_criteria),
            "affected_component": brief.affected_component,
        }
        envelope = {
            "kind": "flow.bug_brief_validated",
            "ts": time.time(),
            "run_id": run_id,
            "node_id": self.name,
            "payload": event_payload,
        }
        fields = {"event": json.dumps(envelope)}
        try:
            await redis_client.xadd(
                f"flow:{run_id}:flow", fields, maxlen=10_000, approximate=True
            )
        except Exception as exc:  # pragma: no cover
            self.logger.warning(
                "Failed to XADD flow.bug_brief_validated: %s", exc
            )

    async def _ensure_redis(self) -> Any:
        """Return a cached async Redis client, creating it on first call.

        Returns:
            A live ``redis.asyncio`` client instance.
        """
        if self._redis is not None:
            return self._redis
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(
            self._redis_url, decode_responses=True
        )
        return self._redis

    async def close(self) -> None:
        """Release the Redis client connection pool."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None


__all__ = ["BugIntakeNode"]
