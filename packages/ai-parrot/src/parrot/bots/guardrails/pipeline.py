"""Guardrail pipeline — priority-ordered execution engine.

``GuardrailPipeline`` runs the guardrails registered for a single stage
(INPUT, TOOL_OUTPUT, OUTPUT, OUTPUT_STREAM) in priority order, applying
BLOCK short-circuit, TRANSFORM chaining, FLAG accumulation, per-guardrail
error contracts, and telemetry recording. See
``sdd/specs/guardrails-infrastructure.spec.md`` §2/§3 Module 1 (FEAT-396).

Note on idempotency: earlier revisions of this module memoized outcomes in
a pipeline-level ``(stage, content)`` cache, generalizing the
``_already_scrubbed`` precedent (`security/redaction.py:122`) from "one
guardrail's own content-marker check" to "skip re-invoking every guardrail
for repeat input." That generalization was incorrect and has been removed
(FEAT-396 code review, post-TASK-2030): guardrails with side effects beyond
their return value — `PromptInjectionGuardrail`'s `SecurityEventLogger`
audit trail, `LegacyPipelineGuardrail`'s wrapped LLM call
(`bots/search.py`'s competitor-query pivot) — would silently stop firing on
the second occurrence of identical content, which is a correctness and
security regression, not an optimization. Per-guardrail idempotency (e.g.
`SecretsGuardrail` checking `_already_scrubbed` before re-scrubbing) is the
correct place for this concern — each guardrail knows whether its own
`check()` is safe to skip on already-processed content; the pipeline does
not.

Note on telemetry: this module never imports the FEAT-176 lifecycle-events
system directly (not part of this task's verified Codebase Contract, and
wiring a specific observer is bot-level concern, out of scope here). Instead
``GuardrailPipeline`` accepts an optional ``on_telemetry`` callback so a
caller (e.g. the bot-wiring task that constructs pipelines) can forward
each ``GuardrailTelemetryEntry`` to FEAT-176 observers, or anywhere else,
without this module depending on that subsystem.
"""
import logging
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from .base import Guardrail, GuardrailAction, GuardrailContext, GuardrailStage


class GuardrailTelemetryEntry(BaseModel):
    """One guardrail's execution record for a single pipeline run.

    Attributes:
        name: The guardrail's ``name``.
        stage: The stage this run executed at.
        action: The verdict produced (or the effective verdict after error
            handling, e.g. BLOCK for a `fail_closed` exception).
        duration_ms: Wall-clock time spent in this guardrail's ``check()``.

    Telemetry never carries content — only name/stage/action/duration, per
    spec §2.
    """
    name: str
    stage: GuardrailStage
    action: GuardrailAction
    duration_ms: float


class PipelineOutcome(BaseModel):
    """Result of running a ``GuardrailPipeline`` once.

    Attributes:
        content: The final (possibly transformed) content. ``None`` when
            ``blocked`` is True — BLOCK discards prior TRANSFORMs in favor
            of a canned response the caller constructs; the offending
            content is never carried in the outcome.
        blocked: Whether a guardrail issued (or errored into) a BLOCK.
        reason: The BLOCK category label, populated when ``blocked`` is
            True. Never the offending content.
        flag_reports: FLAG reports keyed by guardrail name.
        telemetry: One entry per guardrail actually executed, in
            execution order.
    """
    content: str | None = None
    blocked: bool = False
    reason: str | None = None
    flag_reports: dict[str, dict[str, Any]] = Field(default_factory=dict)
    telemetry: list[GuardrailTelemetryEntry] = Field(default_factory=list)


class GuardrailPipeline:
    """Priority-ordered execution engine for a single guardrail stage.

    Guardrails are executed in ascending ``priority`` order (default bands:
    sanitizers 0-99, transformers 100-199, observers 200+; see
    ``Guardrail`` docstring). A BLOCK verdict short-circuits the chain and
    discards any TRANSFORMs already applied. FLAG reports accumulate under
    each guardrail's name. Per-guardrail exceptions honor ``on_error``:
    ``fail_open`` logs a warning and treats the guardrail as PASS;
    ``fail_closed`` converts the exception into a BLOCK.

    Empty pipelines (``not has_guardrails``) short-circuit ``run()`` with
    zero overhead — no loop, no telemetry, content returned unchanged.
    """

    def __init__(self, on_telemetry: Callable[[GuardrailTelemetryEntry], None] | None = None) -> None:
        """Initialize an empty pipeline.

        Args:
            on_telemetry: Optional callback invoked with each
                ``GuardrailTelemetryEntry`` as it is recorded. Exceptions
                raised by the callback are logged and swallowed — telemetry
                must never break a guardrail run.
        """
        self._guardrails: list[Guardrail] = []
        self._on_telemetry = on_telemetry
        self.logger = logging.getLogger(__name__)

    def add(self, guardrail: Guardrail) -> None:
        """Register a guardrail, keeping the list sorted by priority.

        Args:
            guardrail: The guardrail instance to add.
        """
        self._guardrails.append(guardrail)
        self._guardrails.sort(key=lambda g: g.priority)

    @property
    def has_guardrails(self) -> bool:
        """Whether any guardrail is registered on this pipeline."""
        return bool(self._guardrails)

    @property
    def guardrails(self) -> tuple[Guardrail, ...]:
        """The registered guardrails, in execution (priority) order.

        Read-only view for callers that need Any-typed access a guardrail
        may expose beyond the string-only `check()` contract (e.g. a
        `scrub(value, tool_name)` escape hatch — see `tools/abstract.py`'s
        TOOL_OUTPUT hook, which needs this for non-string `ToolResult`
        fields that cannot be expressed as `Guardrail.check(content: str)`).
        """
        return tuple(self._guardrails)

    async def run(self, content: str, ctx: GuardrailContext) -> PipelineOutcome:
        """Execute all registered guardrails against ``content``.

        Args:
            content: The text content to check.
            ctx: Contextual information for this call (also carries the
                stage — must match the stage this pipeline is used for).

        Returns:
            A ``PipelineOutcome`` describing the final content (or block).
        """
        if not self.has_guardrails:
            return PipelineOutcome(content=content, blocked=False)

        working_content = content
        blocked = False
        reason: str | None = None
        flag_reports: dict[str, dict[str, Any]] = {}
        telemetry: list[GuardrailTelemetryEntry] = []

        for guardrail in self._guardrails:
            start = time.perf_counter()
            try:
                result = await guardrail.check(working_content, ctx)
            except Exception as exc:  # noqa: BLE001 - guardrail error contract, see on_error
                duration_ms = (time.perf_counter() - start) * 1000
                if guardrail.on_error == "fail_closed":
                    self.logger.error(
                        "Guardrail '%s' raised %s; on_error=fail_closed -> blocking",
                        guardrail.name, type(exc).__name__,
                    )
                    self._record(telemetry, guardrail.name, ctx.stage, GuardrailAction.BLOCK, duration_ms)
                    blocked = True
                    reason = f"guardrail_error:{guardrail.name}"
                    break
                self.logger.warning(
                    "Guardrail '%s' raised %s; on_error=fail_open -> continuing",
                    guardrail.name, type(exc).__name__,
                )
                self._record(telemetry, guardrail.name, ctx.stage, GuardrailAction.PASS, duration_ms)
                continue

            duration_ms = (time.perf_counter() - start) * 1000
            self._record(telemetry, guardrail.name, ctx.stage, result.action, duration_ms)

            if result.action == GuardrailAction.BLOCK:
                blocked = True
                reason = result.reason
                # A blocking guardrail may still attach a non-content report
                # (e.g. a threat count) — surfaced the same way a FLAG's
                # report would be, so seam code can reconstruct compat
                # metadata (FEAT-396 TASK-2028) without leaking content.
                if result.report:
                    flag_reports[guardrail.name] = result.report
                break
            elif result.action == GuardrailAction.TRANSFORM:
                if result.content is not None:
                    working_content = result.content
            elif result.action == GuardrailAction.FLAG:
                flag_reports[guardrail.name] = result.report or {}
            # PASS: no-op, working_content unchanged

        return PipelineOutcome(
            content=None if blocked else working_content,
            blocked=blocked,
            reason=reason,
            flag_reports=flag_reports,
            telemetry=telemetry,
        )

    def _record(
        self,
        telemetry: list[GuardrailTelemetryEntry],
        name: str,
        stage: GuardrailStage,
        action: GuardrailAction,
        duration_ms: float,
    ) -> None:
        """Append a telemetry entry and forward it to ``on_telemetry``."""
        entry = GuardrailTelemetryEntry(name=name, stage=stage, action=action, duration_ms=duration_ms)
        telemetry.append(entry)
        if self._on_telemetry is not None:
            try:
                self._on_telemetry(entry)
            except Exception:
                self.logger.debug("on_telemetry callback raised", exc_info=True)
