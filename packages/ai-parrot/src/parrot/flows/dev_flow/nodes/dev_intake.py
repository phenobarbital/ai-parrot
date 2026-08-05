"""DevIntakeNode — first node of the dev-flow graph (FEAT-412).

Validates the user-selected :data:`DevFlowBrief` and returns it so the
topology's CEL edge predicates can route on ``result.kind``:

* ``"enhancement"`` / ``"new_feature"`` → ``dev_flow.ideation`` (the request
  is natural language; the SDD document does not exist yet).
* ``"feature"`` → ``dev_loop.planner`` (an SDD brainstorm/proposal/spec was
  supplied; ideation is skipped entirely).

There is deliberately **no LLM intent classification** here (spec §1
Non-Goals / §8): the user picks the intent in the UI, and this node only
*validates* the typed brief — exactly the relationship
``IntentClassifierNode`` has to ``WorkBrief``, whose pattern this node
mirrors (ctx-or-JSON-prompt loading, lazy Redis, one
``flow.intake_validated`` event, return-the-brief-for-routing).

No allowlist/path-traversal guards apply: those are
``WorkBrief.acceptance_criteria``-specific and neither
:class:`DevRequestBrief` nor :class:`FeatureBrief` carries acceptance
criteria. A ``FeatureBrief``'s own constructor validates ``document_path``
readability eagerly, so an invalid brief fails inside :meth:`_load_brief` —
before this node returns and before any dispatch.
"""

from __future__ import annotations

import json
import time
from typing import Any

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.dev_flow.models import DevRequestBrief, parse_dev_brief
from parrot.flows.dev_loop.models import FeatureBrief
from parrot.flows.dev_loop.nodes.base import DevLoopNode, register_dev_loop_node


@register_dev_loop_node("dev_flow.dev_intake")
class DevIntakeNode(DevLoopNode):
    """Validates a :data:`DevFlowBrief` and routes by ``kind``.

    Args:
        redis_url: Redis URL used to publish ``flow.intake_validated``. The
            connection is lazy: the node is safe to construct without a live
            Redis instance — the publish happens on first :meth:`execute`.
        name: Node identifier, defaults to ``"dev_intake"``.
    """

    def __init__(
        self,
        *,
        redis_url: str,
        name: str = "dev_intake",
    ) -> None:
        super().__init__(node_id=name)
        object.__setattr__(self, "_redis_url", redis_url)
        object.__setattr__(self, "_redis", None)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        ctx: FlowContext | dict[str, Any],
        deps: DependencyResults | None = None,
        **kwargs: Any,
    ) -> DevRequestBrief | FeatureBrief:
        """Validate the dev-flow brief and emit the intake event.

        Args:
            ctx: Flow context (``FlowContext`` or plain dict in tests). The
                shared state must contain ``"run_id"`` for the event stream
                key and may contain ``"dev_brief"`` or ``"feature_brief"``
                (an instance or a dict); the context's ``initial_task`` is
                used as a JSON fallback when neither is present.
            deps: Dependency results (unused — this is the entry node).
            **kwargs: Extra execution context (ignored).

        Returns:
            The validated :class:`DevRequestBrief` or :class:`FeatureBrief`.
            The topology's conditional edges read ``result.kind`` to route
            to ``ideation`` or straight to ``planner``.

        Raises:
            ValueError: When no brief source is available, when ``kind`` is
                absent/unknown, or when the loaded brief fails validation
                (e.g. an unreadable ``FeatureBrief.document_path`` —
                ``pydantic.ValidationError`` subclasses ``ValueError``) —
                always BEFORE this node returns.
        """
        shared = self.shared_state(ctx)
        brief = self._load_brief(self.initial_prompt(ctx), shared)

        # Always publish the canonical dev-flow key.
        shared["dev_brief"] = brief

        if isinstance(brief, FeatureBrief):
            # The document already exists → hand it straight to PlannerNode
            # under the exact key it reads. IdeationNode never runs.
            shared["feature_brief"] = brief
            self.logger.info(
                "Dev intake validated: kind=feature, document_kind=%s, "
                "document_path=%s",
                brief.document_kind, brief.document_path,
            )
        else:
            self.logger.info(
                "Dev intake validated: kind=%s, title=%s",
                brief.kind, brief.title,
            )

        run_id = shared.get("run_id", "")
        if run_id:
            await self._emit_validated_event(run_id, brief)
        return brief

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_brief(
        self, prompt: str, ctx: dict[str, Any]
    ) -> DevRequestBrief | FeatureBrief:
        """Load a :class:`DevRequestBrief` or :class:`FeatureBrief`.

        Resolution order:

        1. ``ctx["dev_brief"]`` — the canonical dev-flow key (what
           ``DevFlowRunner`` seeds).
        2. ``ctx["feature_brief"]`` — a caller that already has a
           ``FeatureBrief`` in hand.
        3. ``prompt`` — JSON string fallback, routed through
           :func:`parse_dev_brief`.

        Args:
            prompt: Raw JSON string representing a brief.
            ctx: Flow shared-state dictionary.

        Returns:
            A validated brief instance.

        Raises:
            ValueError: When no source is available, when ``kind`` is missing
                or not one of the three dev-flow kinds, or when the brief
                fails model validation.
        """
        candidate = ctx.get("dev_brief") or ctx.get("feature_brief")
        if isinstance(candidate, (DevRequestBrief, FeatureBrief)):
            return candidate
        if isinstance(candidate, dict):
            return parse_dev_brief(candidate)
        if prompt:
            return parse_dev_brief(json.loads(prompt))
        raise ValueError(
            "DevIntakeNode requires ctx['dev_brief'], ctx['feature_brief'], "
            "or a JSON prompt."
        )

    async def _emit_validated_event(
        self, run_id: str, brief: DevRequestBrief | FeatureBrief
    ) -> None:
        """XADD one ``flow.intake_validated`` event to the flow stream.

        Args:
            run_id: Identifies the Redis stream key ``flow:{run_id}:flow``.
            brief: The validated brief whose metadata goes into the payload.
                The payload shape is per-kind: a document-based
                ``FeatureBrief`` reports its document, a natural-language
                ``DevRequestBrief`` reports its title.
        """
        try:
            redis_client = await self._ensure_redis()
        except Exception as exc:  # noqa: BLE001 — telemetry must never break a run
            self.logger.warning(
                "Redis unavailable, dropping flow.intake_validated event: %s",
                exc,
            )
            return

        if isinstance(brief, FeatureBrief):
            event_payload: dict[str, Any] = {
                "kind": "feature",
                "document_kind": brief.document_kind,
                "document_path": brief.document_path,
                "jira_issue_key": brief.jira_issue_key,
            }
        else:
            event_payload = {
                "kind": brief.kind,
                "title": brief.title,
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
        except Exception as exc:  # noqa: BLE001 — telemetry must never break a run
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


__all__ = ["DevIntakeNode"]
