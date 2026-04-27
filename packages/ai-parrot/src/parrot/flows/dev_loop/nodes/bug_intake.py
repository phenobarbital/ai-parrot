"""BugIntakeNode — first node of the dev-loop flow.

Pure AI-Parrot validation. Loads the incoming :class:`BugBrief`,
sanity-checks every acceptance criterion against the
``ACCEPTANCE_CRITERION_ALLOWLIST``, emits a
``flow.bug_brief_validated`` event, and returns the brief for the
downstream nodes to consume.

This node deliberately does NOT call the dispatcher; the most
expensive thing it does is one ``XADD`` to the flow event stream.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from parrot.bots.flow.node import Node
from parrot.conf import ACCEPTANCE_CRITERION_ALLOWLIST
from parrot.flows.dev_loop.models import (
    BugBrief,
    FlowtaskCriterion,
    ShellCriterion,
)


class BugIntakeNode(Node):
    """First node — validates a :class:`BugBrief` and emits a flow event.

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
        return self._name

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(self, prompt: str, ctx: Dict[str, Any]) -> BugBrief:
        """Validate and pass through the :class:`BugBrief`.

        Args:
            prompt: Optional JSON string containing a serialized BugBrief.
                Used as a fallback when ``ctx["bug_brief"]`` is absent.
            ctx: Flow context. Must contain ``"run_id"`` for the event
                stream key. May contain ``"bug_brief"`` (a ``BugBrief``
                instance or a dict).

        Returns:
            The validated :class:`BugBrief` instance.

        Raises:
            ValueError: When any :class:`ShellCriterion` command head is
                not in the allowlist or any :class:`FlowtaskCriterion`
                ``task_path`` is absolute or contains a ``..`` segment.
        """
        brief = self._load_brief(prompt, ctx)
        self._validate(brief)
        run_id = ctx.get("run_id", "")
        if run_id:
            await self._emit_validated_event(run_id, brief)
        ctx["bug_brief"] = brief
        return brief

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_brief(self, prompt: str, ctx: Dict[str, Any]) -> BugBrief:
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

    def _validate(self, brief: BugBrief) -> None:
        for crit in brief.acceptance_criteria:
            if isinstance(crit, ShellCriterion):
                tokens = crit.command.split(maxsplit=1)
                head = tokens[0] if tokens else ""
                if head not in ACCEPTANCE_CRITERION_ALLOWLIST:
                    raise ValueError(
                        f"Shell command head {head!r} not in allowlist "
                        f"{sorted(ACCEPTANCE_CRITERION_ALLOWLIST)}"
                    )
            elif isinstance(crit, FlowtaskCriterion):
                path = crit.task_path
                if path.startswith("/") or ".." in path.split("/"):
                    raise ValueError(
                        f"Invalid relative task_path: {path!r}"
                    )

    async def _emit_validated_event(self, run_id: str, brief: BugBrief) -> None:
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
        if self._redis is not None:
            return self._redis
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(
            self._redis_url, decode_responses=True
        )
        return self._redis


__all__ = ["BugIntakeNode"]
