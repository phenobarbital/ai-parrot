"""SecretsGuardrail — wraps `OutputScrubber` (FEAT-252) as a guardrail.

Encapsulates the existing secret/PII-adjacent redaction engine
(`parrot.security.redaction.OutputScrubber`) as a pluggable TOOL_OUTPUT/
OUTPUT `Guardrail`, so it can be ordered, combined with future guardrails
(PII, groundedness, moderation), and driven by the unified
``guardrails=[...]``/``enable_redaction`` config surface instead of being
called ad hoc at four separate seams. See
``sdd/specs/guardrails-infrastructure.spec.md`` §3 Module 3 (FEAT-396).

Note on ``scrub()``: `OutputScrubber.scrub(value: Any) -> Any` natively
handles str/dict/list/tuple (recursive structure traversal) — a wider
contract than `Guardrail.check(content: str, ...) -> GuardrailResult`
(whose `content`/`GuardrailResult.content` are Pydantic-typed as `str`).
Callers with non-string payloads that still need OutputScrubber's native
Any-typed traversal (e.g. the FEAT-252 tool hook's `ToolResult.result`/
`.metadata` fields, which are frequently dict/list) use `scrub()` directly
rather than the string-only `check()`/pipeline path — see
`tools/abstract.py`'s `_default_secrets_guardrail()`.
"""
import logging
from typing import Any, ClassVar

from parrot.security.redaction import OutputScrubber, ScrubPolicy, _already_scrubbed

from ..base import (
    Guardrail,
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
    GuardrailStage,
)

logger = logging.getLogger(__name__)


class SecretsGuardrail(Guardrail):
    """TOOL_OUTPUT/OUTPUT guardrail wrapping `OutputScrubber`.

    Always runs first within its stages (priority 10, sanitizer band) —
    other transformers (e.g. a future PII guardrail) must never scan
    already-``***REDACTED***`` text.

    Attributes:
        policy: The `ScrubPolicy` forwarded to the wrapped `OutputScrubber`.
    """
    name = "secrets"
    stages: ClassVar[set] = {GuardrailStage.TOOL_OUTPUT, GuardrailStage.OUTPUT}
    priority = 10  # sanitizer band — always first
    on_error = "fail_open"  # mirrors the FEAT-252 non-fatal scrub contract

    def __init__(
        self,
        policy: ScrubPolicy | None = None,
        tool_name: str = "unknown",
        **kwargs: Any,
    ) -> None:
        """Initialize the guardrail.

        Args:
            policy: Scrub policy forwarded to `OutputScrubber`. Defaults to
                `ScrubPolicy()`.
            tool_name: Default audit-log tool-name hint, overridable per call.
            **kwargs: Accepted and ignored, for forward-compat with extra
                policy keys passed via `guardrails=[{"name": ..., ...}]`.
        """
        self.policy = policy or ScrubPolicy()
        self.logger = logging.getLogger(__name__)
        self._scrubber = OutputScrubber(self.policy, tool_name=tool_name)

    def scrub(self, value: Any, tool_name: str | None = None) -> Any:
        """Recursively scrub any value (str/dict/list/tuple), as-is from FEAT-252.

        Direct, Any-typed escape hatch for callers that cannot express their
        payload as `Guardrail.check(content: str, ...)` — see module
        docstring. Not part of the `Guardrail` ABC.

        Args:
            value: The value to scrub.
            tool_name: Overrides the instance-level tool-name audit hint.

        Returns:
            A sanitized copy of ``value``.
        """
        return self._scrubber.scrub(value, tool_name=tool_name)

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        """Scrub string content for the standard Guardrail/Pipeline flow.

        Args:
            content: The text content to scrub.
            ctx: Call context. ``ctx.tool_name`` (TOOL_OUTPUT) is used as
                the audit-log tool-name hint when present.

        Returns:
            PASS if nothing changed (including already-scrubbed content,
            per idempotency); otherwise TRANSFORM with the scrubbed text.
        """
        if _already_scrubbed(content):
            return GuardrailResult(action=GuardrailAction.PASS)

        tool_name = ctx.tool_name or ctx.agent_name
        scrubbed = self._scrubber.scrub(content, tool_name=tool_name)
        if scrubbed == content:
            return GuardrailResult(action=GuardrailAction.PASS)
        return GuardrailResult(action=GuardrailAction.TRANSFORM, content=scrubbed)
