"""IntentClassifierNode — first node of the dev-loop flow (FEAT-132).

Absorbs the universal validation logic previously in ``BugIntakeNode``
(allowlist heads, path-traversal checks on FlowtaskCriterion).

After validation it emits a ``flow.intake_validated`` event to Redis
and returns the ``WorkBrief`` so that the flow factory's
``on_condition`` predicates can route on ``result.kind``.

Both ``ctx['bug_brief']`` (legacy key) and ``ctx['work_brief']`` (forward-
compat) are populated so Development / QA / Failure nodes that already
read ``bug_brief`` keep working without modification.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict

from parrot.bots.flow.node import Node
from parrot.conf import ACCEPTANCE_CRITERION_ALLOWLIST
from parrot.flows.dev_loop.models import (
    FlowtaskCriterion,
    ShellCriterion,
    WorkBrief,
)


class IntentClassifierNode(Node):
    """Validates a :class:`WorkBrief` and routes by ``kind``.

    This is the first node in the FEAT-132 flow topology. It replaces
    the universal validation that previously ran inside ``BugIntakeNode``
    so that non-bug kinds (enhancement, new_feature) also receive the
    allowlist / path-traversal guards before reaching ``ResearchNode``.

    Args:
        redis_url: Redis URL used to publish ``flow.intake_validated``.
            The connection is lazy: the node is safe to construct without
            a live Redis instance. The publish happens on first ``execute``.
        name: Node identifier, defaults to ``"intent_classifier"``.
    """

    def __init__(
        self,
        *,
        redis_url: str,
        name: str = "intent_classifier",
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

    async def execute(self, prompt: str, ctx: Dict[str, Any]) -> WorkBrief:
        """Validate the :class:`WorkBrief` and emit the intake event.

        Args:
            prompt: Optional JSON string containing a serialised
                ``WorkBrief``. Used as a fallback when neither
                ``ctx["work_brief"]`` nor ``ctx["bug_brief"]`` is present.
            ctx: Flow context. Must contain ``"run_id"`` for the event
                stream key. May contain ``"work_brief"`` or ``"bug_brief"``
                (a ``WorkBrief`` instance or a dict).

        Returns:
            The validated :class:`WorkBrief` instance.  The flow
            factory's ``on_condition`` predicate reads ``result.kind``
            to route either to ``BugIntakeNode`` (``kind="bug"``) or
            directly to ``ResearchNode`` (all other kinds).

        Raises:
            ValueError: When any :class:`ShellCriterion` command head
                is not in the allowlist or any :class:`FlowtaskCriterion`
                ``task_path`` is absolute or contains a ``..`` segment.
        """
        brief = self._load_brief(prompt, ctx)
        self._validate(brief)
        run_id = ctx.get("run_id", "")
        if run_id:
            await self._emit_validated_event(run_id, brief)
        ctx["bug_brief"] = brief    # legacy key — Development/QA/Failure read this
        ctx["work_brief"] = brief   # forward-compat name
        self.logger.info(
            "Intake validated: kind=%s, criteria=%d, component=%s",
            brief.kind,
            len(brief.acceptance_criteria),
            brief.affected_component,
        )
        return brief

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_brief(self, prompt: str, ctx: Dict[str, Any]) -> WorkBrief:
        """Load a ``WorkBrief`` from context or JSON prompt.

        Resolution order:
        1. ``ctx["work_brief"]`` — new canonical key (FEAT-132 callers).
        2. ``ctx["bug_brief"]`` — legacy key (FEAT-129 callers).
        3. ``prompt`` — JSON string fallback.

        Args:
            prompt: Raw JSON string representing a ``WorkBrief``.
            ctx: Flow context dictionary.

        Returns:
            A validated :class:`WorkBrief` instance.

        Raises:
            ValueError: When no source is available.
        """
        # New key takes precedence.
        candidate = ctx.get("work_brief") or ctx.get("bug_brief")
        if isinstance(candidate, WorkBrief):
            return candidate
        if isinstance(candidate, dict):
            return WorkBrief.model_validate(candidate)
        if prompt:
            return WorkBrief.model_validate_json(prompt)
        raise ValueError(
            "IntentClassifierNode requires ctx['work_brief'], "
            "ctx['bug_brief'], or a JSON prompt."
        )

    def _validate(self, brief: WorkBrief) -> None:
        """Apply allowlist + path-traversal guards to each criterion.

        Args:
            brief: The :class:`WorkBrief` to validate.

        Raises:
            ValueError: On disallowed shell head or unsafe task path.
        """
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

    async def _emit_validated_event(
        self, run_id: str, brief: WorkBrief
    ) -> None:
        """XADD one ``flow.intake_validated`` event to the flow stream.

        Args:
            run_id: Identifies the Redis stream key ``flow:{run_id}:flow``.
            brief: The validated brief whose metadata is included in the
                event payload.
        """
        try:
            redis_client = await self._ensure_redis()
        except Exception as exc:  # pragma: no cover - degraded path
            self.logger.warning(
                "Redis unavailable, dropping flow.intake_validated event: %s",
                exc,
            )
            return
        event_payload = {
            "kind": brief.kind,
            "n_criteria": len(brief.acceptance_criteria),
            "affected_component": brief.affected_component,
            "summary": brief.summary,
        }
        envelope = {
            "kind": "flow.intake_validated",
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
                "Failed to XADD flow.intake_validated: %s", exc
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


__all__ = ["IntentClassifierNode"]
