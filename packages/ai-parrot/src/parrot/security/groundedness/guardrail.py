"""``GroundednessGuardrail`` — FLAG-only OUTPUT-stage plugin (FEAT-398 Module 3).

Wires the deterministic groundedness scorer (Modules 1-2:
``extract_atoms`` / ``EvidenceIndex`` / ``GroundednessScorer``) into the
unified guardrails infrastructure (FEAT-396) as an *observer* guardrail: it
never transforms, masks, or blocks the response — it only scores the
agent's final answer against the turn's own tool-call evidence and attaches
the resulting :class:`~parrot.security.groundedness.policy.GroundednessReport`
to ``AIMessage.metadata["guardrails"]["groundedness"]`` via the standard
FLAG-report mechanism (``GuardrailPipeline.run`` keys ``flag_reports`` by
``Guardrail.name`` — see ``bots/guardrails/pipeline.py``).

See ``sdd/specs/deterministic-groundedness-scoring.spec.md`` §3 Module 3
(v0.2 guardrails repositioning) for the full design.
"""
from __future__ import annotations

import logging
from typing import Any, ClassVar

from parrot.bots.guardrails import (
    Guardrail,
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
    GuardrailStage,
)
from parrot.models.basic import ToolCall

from .evidence import EvidenceIndex
from .policy import GroundednessPolicy, GroundednessReport
from .scorer import GroundednessScorer

logger = logging.getLogger(__name__)


class GroundednessGuardrail(Guardrail):
    """OUTPUT-stage observer guardrail scoring answers against tool evidence.

    Always returns ``GuardrailAction.FLAG`` on success (or ``PASS`` if
    scoring itself raises) — never ``TRANSFORM``/``BLOCK`` — so the
    response text delivered to the caller is guaranteed byte-identical
    whether groundedness scoring is enabled or not (spec §5 scoring-only
    invariant).

    Attributes:
        policy: The active :class:`GroundednessPolicy`.
        scorer: The :class:`GroundednessScorer` built from ``policy``.
    """

    name = "groundedness"
    # Observer band (200+): runs after every sanitizer/transformer and only
    # annotates — see the `Guardrail` ABC docstring's priority bands, which
    # cites "groundedness scoring" as the 200+ example.
    stages: ClassVar[set] = {GuardrailStage.OUTPUT}
    priority = 200

    def __init__(self, policy: GroundednessPolicy | None = None, **kwargs: Any) -> None:
        """Initialize the guardrail.

        Args:
            policy: The scoring policy. Defaults to ``GroundednessPolicy()``.
            **kwargs: Accepted and ignored, for forward-compat with extra
                policy keys passed via ``guardrails=[{"name": ..., ...}]``.
        """
        self.policy = policy or GroundednessPolicy()
        self.scorer = GroundednessScorer(self.policy)
        self.logger = logging.getLogger(__name__)

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        """Score ``content`` (the agent's final answer) against tool evidence.

        Builds the turn's :class:`EvidenceIndex` from the outgoing
        ``AIMessage`` carried on ``ctx.extras["ai_message"]`` (populated by
        ``AbstractBot._run_output_pipeline`` — the only OUTPUT-stage
        ``GuardrailContext`` construction site), scores ``content`` against
        it, and returns a FLAG result carrying the serialized report. Any
        exception is caught and logged — the guardrail degrades to PASS
        (no report) rather than failing the turn (spec §3 Module 3
        non-fatal contract, mirrors ``security/redaction.py``'s scrubber
        failure contract).

        Args:
            content: The agent's final answer text for this turn.
            ctx: Call context. ``ctx.extras["ai_message"]`` carries the
                outgoing ``AIMessage`` (source of ``tool_calls`` and the
                original ``input`` prompt) when available; its absence is
                tolerated (treated as a turn with no tool evidence).

        Returns:
            FLAG with the serialized ``GroundednessReport`` in ``report``
            on success; PASS (no report) if scoring raised.
        """
        try:
            ai_message = ctx.extras.get("ai_message")
            tool_calls: list[ToolCall] = list(getattr(ai_message, "tool_calls", None) or [])
            user_prompt = getattr(ai_message, "input", None)

            evidence = EvidenceIndex.from_tool_calls(
                tool_calls, self.policy, user_prompt=user_prompt,
            )
            report: GroundednessReport = self.scorer.score(content, evidence)
        except Exception:  # non-fatal scoring contract (spec §3 Module 3)
            self.logger.warning(
                "GroundednessGuardrail scoring failed for agent=%s; "
                "turn completes without a groundedness report",
                ctx.agent_name, exc_info=True,
            )
            return GuardrailResult(action=GuardrailAction.PASS)

        # Telemetry: score + per-verdict counts only. Atom raw values (which
        # may embed emails, ids, or other sensitive figures echoed in the
        # answer) never leave the process through this log line (spec §3
        # Module 3 / §5 AC — "telemetry carries score + counts, never atom
        # values").
        self.logger.info(
            "groundedness: agent=%s score=%.3f total_atoms=%d supported=%d "
            "contradicted=%d unsupported=%d no_evidence=%s no_factual_content=%s",
            ctx.agent_name, report.score, report.total_atoms,
            len(report.supported), len(report.contradicted), len(report.unsupported),
            report.no_evidence, report.no_factual_content,
        )
        if report.score < self.policy.min_alert_score:
            self.logger.info(
                "groundedness: agent=%s turn score %.3f below min_alert_score %.3f",
                ctx.agent_name, report.score, self.policy.min_alert_score,
            )

        return GuardrailResult(action=GuardrailAction.FLAG, report=report.model_dump())
