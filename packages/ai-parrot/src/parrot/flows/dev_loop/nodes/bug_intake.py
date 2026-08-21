"""BugIntakeNode — bug-specific intake hook for the dev-loop flow.

FEAT-132 scope-down moved universal validation (allowlist heads,
path-traversal) to :class:`IntentClassifierNode`, which runs before this
node on the bug path. What is left here is the bug-only enrichment the node
was reserved for: parse the stack trace, classify severity, and — when a
replication target is configured — reproduce the failure against a real
environment and document what was actually observed.

Enrichment is additive and best-effort. Without a replication target, or
when the brief carries no trace, the node behaves exactly as before:
re-emit ``flow.bug_brief_validated`` and return the brief. A bug report
that cannot be enriched still has to reach Research.

The point of reproducing is evidence over narration. A brief that says
"returns 500" sends Research looking; one that carries the observed status,
the response body, the culprit frame and a regression test that currently
fails tells it where to look and how the fix will be judged.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional, Union

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.dev_loop.models import BugBrief
from parrot.flows.dev_loop.nodes.base import DevLoopNode, register_dev_loop_node
from parrot.flows.dev_loop.replication import (
    ReplicationResult,
    ReplicationTarget,
    StackTrace,
    classify_severity,
    extract_endpoint,
    parse_stack_trace,
    proposed_regression_test,
    replicate_endpoint,
)


@register_dev_loop_node("dev_loop.bug_intake")
class BugIntakeNode(DevLoopNode):
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
        replication_target: Environment to reproduce the failure against
            (dev, staging). ``None`` skips reproduction and the node only
            parses what the report already carries. The target is an
            environment on purpose: reproducing where the 500 actually
            happens beats standing up the service and its database locally
            for every bug.
        replicate: Set ``False`` to parse and classify but never issue a
            request — for a bug whose endpoint must not be touched again.
    """

    def __init__(
        self,
        *,
        redis_url: str,
        name: str = "bug_intake",
        replication_target: Optional[ReplicationTarget] = None,
        replicate: bool = True,
    ) -> None:
        super().__init__(node_id=name)
        object.__setattr__(self, "_redis_url", redis_url)
        object.__setattr__(self, "_redis", None)
        object.__setattr__(self, "_replication_target", replication_target)
        object.__setattr__(self, "_replicate", replicate)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        ctx: Union[FlowContext, Dict[str, Any]],
        deps: Optional[DependencyResults] = None,
        **kwargs: Any,
    ) -> BugBrief:
        """Bug-specific intake hook (post FEAT-132 scope-down).

        Universal validation now happens in :class:`IntentClassifierNode`
        which runs before this node on the bug path. This node remains as
        an extension point for bug-only enrichment (severity classification,
        stack-trace parsing, etc.); for v1 it just re-emits
        ``flow.bug_brief_validated`` for downstream observers that already
        subscribe to that event.

        Args:
            ctx: Flow context (``FlowContext`` or plain dict in tests). The
                shared state must contain ``"run_id"`` for the event stream
                key and may contain ``"bug_brief"`` (a ``BugBrief`` instance
                or a dict); the context's ``initial_task`` is used as a JSON
                fallback.
            deps: Dependency results (unused).
            **kwargs: Extra execution context (ignored).

        Returns:
            The :class:`BugBrief` instance (already validated upstream).
        """
        shared = self.shared_state(ctx)
        brief = self._load_brief(self.initial_prompt(ctx), shared)
        findings = await self._enrich(brief)
        if findings:
            # The findings also travel in shared state, unflattened, so
            # downstream nodes can use the parsed pieces instead of
            # re-parsing the prose we appended to the description.
            shared["bug_findings"] = findings
        if run_id := shared.get("run_id", ""):
            await self._emit_validated_event(run_id, brief)
        shared["bug_brief"] = brief
        return brief

    # ------------------------------------------------------------------
    # Enrichment
    # ------------------------------------------------------------------

    async def _enrich(self, brief: BugBrief) -> Dict[str, Any]:
        """Parse, reproduce and document — mutating ``brief`` in place.

        Best-effort throughout: anything that cannot be determined is left
        out rather than guessed, and no failure here stops the brief from
        reaching Research.

        Args:
            brief: The validated brief, enriched in place.

        Returns:
            The structured findings (also stored in shared state), empty
            when there was nothing to add.
        """
        trace = self._parse_reported_trace(brief)
        replication = await self._reproduce(brief)
        severity = classify_severity(trace, replication)

        findings: Dict[str, Any] = {"severity": severity}
        notes = [f"severidad observada: {severity}"]

        if trace is not None and (trace.frames or trace.exception_type):
            findings["trace"] = {
                "language": trace.language,
                "exception_type": trace.exception_type,
                "message": trace.message,
                "culprit": (
                    {
                        "file": trace.culprit.file,
                        "line": trace.culprit.line,
                        "function": trace.culprit.function,
                    }
                    if trace.culprit is not None
                    else None
                ),
            }
            notes.append(f"trace reportado: {trace.summary()}")

        if replication is not None:
            findings["replication"] = {
                "attempted": replication.attempted,
                "reproduced": replication.reproduced,
                "target": replication.target,
                "url": replication.url,
                "method": replication.method,
                "status": replication.status,
                "error": replication.error,
            }
            notes.append(f"reproduccion: {replication.summary()}")
            if replication.reproduced and replication.body_excerpt:
                # The observed body is stronger evidence than the pasted
                # excerpt, so it becomes a log source of its own.
                brief.log_sources.append(
                    _inline_source(
                        f"--- Respuesta observada en {replication.target} "
                        f"({replication.status}) ---\n"
                        f"{replication.body_excerpt}"
                    )
                )
            observed = replication.trace
            if observed is not None:
                findings["observed_trace"] = observed.summary()
                notes.append(f"trace observado: {observed.summary()}")

        test = (
            proposed_regression_test(replication, replication.trace or trace)
            if replication is not None
            else None
        )
        if test is not None:
            findings["regression_test"] = test
            notes.append(
                f"test de regresion propuesto: {test['path']} "
                f"(criterio: {test['command']})"
            )
            self._add_acceptance_command(brief, test["command"])

        if notes:
            brief.description = (
                f"{brief.description}\n\n"
                f"--- Intake automatico ---\n"
                + "\n".join(f"- {note}" for note in notes)
            ).strip()
        return findings

    def _parse_reported_trace(self, brief: BugBrief) -> Optional[StackTrace]:
        """Parse the stack trace the reporter pasted, if any.

        Only ``inline`` sources are read: the remote kinds are fetched by
        ``ResearchNode`` later, and this node must not do network I/O for
        logs it was not given.

        Args:
            brief: The brief to read.

        Returns:
            The parsed trace, or ``None`` when there is no inline source.
        """
        for source in brief.log_sources:
            if getattr(source, "kind", None) != "inline":
                continue
            trace = parse_stack_trace(getattr(source, "locator", ""))
            if trace.frames or trace.exception_type:
                return trace
        return None

    async def _reproduce(self, brief: BugBrief) -> Optional[ReplicationResult]:
        """Reproduce the failure against the configured environment.

        Args:
            brief: The brief, read for the endpoint to hit.

        Returns:
            The result, or ``None`` when reproduction is off, no target is
            configured, or no endpoint could be read from the report.
        """
        if not self._replicate or self._replication_target is None:
            return None
        method, path = extract_endpoint(f"{brief.summary}\n{brief.description}")
        if not path:
            return ReplicationResult(
                attempted=False,
                target=self._replication_target.name,
                error="el reporte no nombra ninguna ruta reproducible",
            )
        return await replicate_endpoint(self._replication_target, method, path)

    @staticmethod
    def _add_acceptance_command(brief: BugBrief, command: str) -> None:
        """Add the regression test as an acceptance criterion.

        QA runs every criterion, so this is what turns "the bug is fixed"
        from a judgement call into something checkable: a fix that does not
        make the reproduction pass is not a fix.

        It is *added*, not substituted — the reporter's own criteria stay,
        and this raises the bar rather than replacing it. (It could not
        substitute anyway: ``acceptance_criteria`` must be non-empty for the
        brief to validate, so the list is never empty by the time this runs.)
        Re-running intake is idempotent: an identical command is not added
        twice.

        Args:
            brief: The brief to extend in place.
            command: The shell command that runs the regression test.
        """
        from parrot.flows.dev_loop.models import ShellCriterion

        existing = {
            getattr(criterion, "command", None)
            for criterion in brief.acceptance_criteria
        }
        if command in existing:
            return
        brief.acceptance_criteria.append(
            ShellCriterion(name="regression", command=command)
        )

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


def _inline_source(text: str) -> Any:
    """Build an ``inline`` LogSource carrying ``text``.

    Imported lazily so this module keeps its light import surface.

    Args:
        text: The log/trace content itself.

    Returns:
        A ``LogSource`` with ``kind="inline"``.
    """
    from parrot.flows.dev_loop.models import LogSource

    return LogSource(kind="inline", locator=text)
