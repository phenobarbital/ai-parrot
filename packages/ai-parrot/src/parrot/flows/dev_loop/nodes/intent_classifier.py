"""IntentClassifierNode — first node of the dev-loop flow (FEAT-132).

Absorbs the universal validation logic previously in ``BugIntakeNode``
(allowlist heads, path-traversal checks on FlowtaskCriterion).

After validation it emits a ``flow.intake_validated`` event to Redis
and returns the validated brief so that the flow factory's
``on_condition`` predicates can route on ``result.kind``.

Both ``ctx['bug_brief']`` (legacy key) and ``ctx['work_brief']`` (forward-
compat) are populated for a ``WorkBrief`` so Development / QA / Failure
nodes that already read ``bug_brief`` keep working without modification.

FEAT-378: the loader also accepts the discriminated ``Brief = WorkBrief |
FeatureBrief`` union (``parse_brief``, TASK-1918). A validated
:class:`FeatureBrief` is published to ``ctx['feature_brief']`` and
returned as-is — no allowlist/path-traversal validation applies to it
(those guards are ``WorkBrief.acceptance_criteria``-specific;
``FeatureBrief`` carries no acceptance criteria at all). Its own
constructor already validates ``document_path`` readability
(TASK-1918's ``_document_path_must_be_readable`` field validator) — any
invalid ``FeatureBrief`` therefore fails during :meth:`_load_brief`,
i.e. before this node returns and before any downstream dispatch.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional, Union

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
from parrot.conf import ACCEPTANCE_CRITERION_ALLOWLIST
from parrot.flows.dev_loop.models import (
    FeatureBrief,
    FlowtaskCriterion,
    ShellCriterion,
    WorkBrief,
    parse_brief,
)
from parrot.flows.dev_loop.nodes.base import DevLoopNode, register_dev_loop_node


@register_dev_loop_node("dev_loop.intent_classifier")
class IntentClassifierNode(DevLoopNode):
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
        super().__init__(node_id=name)
        object.__setattr__(self, "_redis_url", redis_url)
        object.__setattr__(self, "_redis", None)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        ctx: Union[FlowContext, Dict[str, Any]],
        deps: Optional[DependencyResults] = None,
        **kwargs: Any,
    ) -> Union[WorkBrief, FeatureBrief]:
        """Validate the brief and emit the intake event.

        Args:
            ctx: Flow context (``FlowContext`` or plain dict in tests). The
                shared state must contain ``"run_id"`` for the event stream
                key and may contain ``"work_brief"``, ``"bug_brief"``, or
                ``"feature_brief"`` (an instance or a dict); the context's
                ``initial_task`` is used as a JSON fallback when none of
                those keys are present.
            deps: Dependency results (unused — this is the entry node).
            **kwargs: Extra execution context (ignored).

        Returns:
            The validated :class:`WorkBrief` or :class:`FeatureBrief`
            instance. The flow factory's conditional edge predicates read
            ``result.kind`` to route: a ``WorkBrief`` to ``BugIntakeNode``
            (``kind="bug"``) or directly to ``ResearchNode`` (all other
            ``WorkKind`` values); a ``FeatureBrief`` (``kind="feature"``,
            FEAT-378) to ``PlannerNode``.

        Raises:
            ValueError: When any :class:`ShellCriterion` command head
                is not in the allowlist, any :class:`FlowtaskCriterion`
                ``task_path`` is absolute or contains a ``..`` segment
                (``WorkBrief`` path), or the loaded brief fails
                :func:`parse_brief`'s validation (e.g. an unreadable
                ``FeatureBrief.document_path`` — ``pydantic.ValidationError``
                is a ``ValueError`` subclass) — always BEFORE any dispatch.
        """
        shared = self.shared_state(ctx)
        brief = self._load_brief(self.initial_prompt(ctx), shared)

        if isinstance(brief, FeatureBrief):
            run_id = shared.get("run_id", "")
            if run_id:
                await self._emit_validated_event_feature(run_id, brief)
            shared["feature_brief"] = brief
            self.logger.info(
                "Intake validated: kind=feature, document_kind=%s, "
                "document_path=%s",
                brief.document_kind, brief.document_path,
            )
            return brief

        self._validate(brief)
        run_id = shared.get("run_id", "")
        if run_id:
            await self._emit_validated_event(run_id, brief)
        shared["bug_brief"] = brief    # legacy key — Development/QA/Failure read this
        shared["work_brief"] = brief   # forward-compat name
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

    def _load_brief(
        self, prompt: str, ctx: Dict[str, Any]
    ) -> Union[WorkBrief, FeatureBrief]:
        """Load a ``WorkBrief`` or :class:`FeatureBrief` from context or JSON prompt.

        Resolution order:
        1. ``ctx["work_brief"]`` — new canonical key (FEAT-132 callers).
        2. ``ctx["bug_brief"]`` — legacy key (FEAT-129 callers).
        3. ``ctx["feature_brief"]`` — FEAT-378 callers.
        4. ``prompt`` — JSON string fallback, routed through
           :func:`parse_brief` (``kind: "feature"`` → ``FeatureBrief``,
           anything else/absent → ``WorkBrief``, zero behavior change for
           pre-FEAT-378 callers).

        Args:
            prompt: Raw JSON string representing a brief.
            ctx: Flow context dictionary.

        Returns:
            A validated :class:`WorkBrief` or :class:`FeatureBrief` instance.

        Raises:
            ValueError: When no source is available, or the loaded brief
                fails validation (``pydantic.ValidationError`` subclasses
                ``ValueError``).
        """
        # New keys take precedence, in declaration order above.
        candidate = ctx.get("work_brief") or ctx.get("bug_brief") or ctx.get("feature_brief")
        if isinstance(candidate, (WorkBrief, FeatureBrief)):
            return candidate
        if isinstance(candidate, dict):
            return parse_brief(candidate)
        if prompt:
            return parse_brief(json.loads(prompt))
        raise ValueError(
            "IntentClassifierNode requires ctx['work_brief'], "
            "ctx['bug_brief'], ctx['feature_brief'], or a JSON prompt."
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

    async def _emit_validated_event_feature(
        self, run_id: str, brief: FeatureBrief
    ) -> None:
        """XADD one ``flow.intake_validated`` event for a :class:`FeatureBrief` (FEAT-378).

        Args:
            run_id: Identifies the Redis stream key ``flow:{run_id}:flow``.
            brief: The validated ``FeatureBrief`` whose metadata is
                included in the event payload.
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
            "kind": "feature",
            "document_kind": brief.document_kind,
            "document_path": brief.document_path,
            "jira_issue_key": brief.jira_issue_key,
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

    async def close(self) -> None:
        """Release the Redis client connection pool."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None


__all__ = ["IntentClassifierNode"]
