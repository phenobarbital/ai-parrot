"""ModerationGuardrail — reference interface + stub backend.

Proves the unified guardrails infrastructure supports content moderation
as a first-class, pluggable stage (INPUT + OUTPUT) — but ships NO real
classification logic. ``StubModerationBackend`` always allows everything
(``classify()`` returns ``{}``); it exists only to prove the
``ModerationGuardrail``/``ModerationBackend`` interface works end-to-end.

**Concrete backends (OpenAI moderation API, local classifiers, keyword
lists) are explicit follow-up features, out of scope for this task and
this feature (FEAT-396) entirely.** Implement `ModerationBackend` and pass
an instance via ``ModerationGuardrail(backend=...)`` (or register a new
named factory) to add one.

See ``sdd/specs/guardrails-infrastructure.spec.md`` §3 Module 4.
"""
import logging
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel, Field

from ..base import (
    Guardrail,
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
    GuardrailStage,
)

logger = logging.getLogger(__name__)


class ModerationPolicy(BaseModel):
    """Configuration for `ModerationGuardrail`.

    Attributes:
        categories: Moderation categories to check (keys expected in a
            backend's `classify()` result). Categories a backend returns
            but that are NOT listed here are ignored.
        threshold: Score (0.0-1.0) at or above which a category triggers
            ``action``.
        action: ``"flag"`` (default, observe-only — FLAG verdict) or
            ``"block"`` (BLOCK verdict, also selects ``on_error="fail_closed"``).
    """
    categories: list[str] = Field(default_factory=list)
    threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    action: str = Field(default="flag", pattern="^(flag|block)$")


class ModerationBackend(Protocol):
    """Protocol a concrete moderation backend must implement.

    Follow-up features (not part of FEAT-396) implement this against a
    real classifier/API; `ModerationGuardrail` is backend-agnostic.
    """

    async def classify(self, text: str) -> dict[str, float]:
        """Return a ``{category: score}`` mapping for ``text``.

        Args:
            text: The content to classify.

        Returns:
            Scores (0.0-1.0) per category. An empty dict means "nothing
            flagged" (the `StubModerationBackend` always returns this).
        """
        ...


class StubModerationBackend:
    """Allow-all reference backend (FEAT-396 default).

    Exists solely to prove the `ModerationGuardrail`/`ModerationBackend`
    interface is wired correctly end-to-end — NOT a real moderation
    implementation. Logs the call shape (text length only, never the
    content itself) so the seam is observable in tests/telemetry.
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    async def classify(self, text: str) -> dict[str, float]:
        """Always return ``{}`` (nothing flagged).

        Args:
            text: The content that would be classified by a real backend.

        Returns:
            An empty dict.
        """
        self.logger.debug(
            "StubModerationBackend.classify called (len=%d) — allow-all stub, "
            "no real classification performed",
            len(text or ""),
        )
        return {}


class ModerationGuardrail(Guardrail):
    """INPUT + OUTPUT guardrail applying a `ModerationPolicy` via a pluggable backend.

    Attributes:
        policy: The `ModerationPolicy` in effect.
        backend: The `ModerationBackend` used to classify content.
    """
    name = "moderation"
    stages: ClassVar[set] = {GuardrailStage.INPUT, GuardrailStage.OUTPUT}
    priority = 50  # sanitizer band, after prompt injection (priority 10)

    def __init__(
        self,
        policy: ModerationPolicy | None = None,
        backend: ModerationBackend | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the guardrail.

        Args:
            policy: Moderation policy. Defaults to `ModerationPolicy()`
                (empty categories, ``action="flag"`` — effectively a no-op
                until categories are configured).
            backend: The classifier backend. Defaults to
                `StubModerationBackend` (allow-all).
            **kwargs: Accepted and ignored, for forward-compat with extra
                policy keys passed via `guardrails=[{"name": ..., ...}]`.
        """
        self.policy = policy or ModerationPolicy()
        self.backend = backend or StubModerationBackend()
        self.on_error = "fail_closed" if self.policy.action == "block" else "fail_open"
        self.logger = logging.getLogger(__name__)

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        """Classify ``content`` and apply the policy's threshold/action.

        Args:
            content: The text to moderate.
            ctx: Call context (unused by the stub backend; available for
                real backends needing agent/session identity).

        Returns:
            PASS if no configured category meets/exceeds the threshold;
            otherwise FLAG (report = triggered category → score) or BLOCK
            (reason = category label only, never content), per
            ``policy.action``.
        """
        scores = await self.backend.classify(content)
        triggered = {
            category: score
            for category, score in scores.items()
            if category in self.policy.categories and score >= self.policy.threshold
        }

        if not triggered:
            return GuardrailResult(action=GuardrailAction.PASS)

        if self.policy.action == "block":
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                reason=f"moderation:{','.join(sorted(triggered))}",
            )

        return GuardrailResult(action=GuardrailAction.FLAG, report=triggered)
