"""LegacyPipelineGuardrail — wraps a bot's `PromptPipeline` as an INPUT TRANSFORM guardrail.

Lets existing `PromptPipeline` middleware registrations
(`bots/search.py`'s competitor-query pivot, `skills/mixin.py`'s
skill-trigger middleware) keep applying unchanged now that the INPUT
seam runs through the unified `GuardrailPipeline` (FEAT-396, TASK-2028).
See ``sdd/specs/guardrails-infrastructure.spec.md`` §3 Module 2.
"""
import logging
from collections.abc import Callable
from typing import Any, ClassVar

from ..base import (
    Guardrail,
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
    GuardrailStage,
)

logger = logging.getLogger(__name__)


class LegacyPipelineGuardrail(Guardrail):
    """Adapts a `PromptPipeline` (`bots/middleware.py:23`) into the INPUT stage.

    Resolves the pipeline **dynamically**, via ``get_pipeline()``, on every
    ``check()`` call rather than snapshotting it once at construction. This
    is deliberate: `AbstractBot.__init__` registers exactly one instance of
    this guardrail unconditionally (even when ``self._prompt_pipeline`` is
    still ``None``), because both existing registration sites mutate
    ``self._prompt_pipeline`` *after* `__init__` runs
    (`bots/search.py:_setup_competitor_pipeline`, called from
    `WebSearchAgent.__init__` after `super().__init__()`; `skills/mixin.py`'s
    `_ensure_skill_file_registry`, called on first tool setup). A one-time
    snapshot at `__init__` would miss both.

    A no-op (PASS) whenever the resolved pipeline is ``None`` or has no
    middlewares — matches the legacy `if self.prompt_pipeline and
    self._prompt_pipeline.has_middlewares:` gate exactly.
    """
    name = "legacy_prompt_pipeline"
    stages: ClassVar[set] = {GuardrailStage.INPUT}
    priority = 150  # transformer band
    on_error = "fail_open"

    def __init__(self, get_pipeline: Callable[[], Any | None]) -> None:
        """Initialize the guardrail.

        Args:
            get_pipeline: Zero-argument callable returning the bot's
                current `PromptPipeline` (or ``None``). Typically
                ``lambda: self._prompt_pipeline`` bound to the owning bot.
        """
        self._get_pipeline = get_pipeline

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        pipeline = self._get_pipeline()
        if pipeline is None or not pipeline.has_middlewares:
            return GuardrailResult(action=GuardrailAction.PASS)

        # `PromptPipeline.apply()` already swallows per-middleware exceptions
        # internally (`middleware.py:42-45`), so this call cannot raise.
        transformed = await pipeline.apply(
            content,
            context={
                "agent_name": ctx.agent_name,
                "user_id": ctx.user_id,
                "session_id": ctx.session_id,
                "method": ctx.method,
            },
        )
        if transformed == content:
            return GuardrailResult(action=GuardrailAction.PASS)
        return GuardrailResult(action=GuardrailAction.TRANSFORM, content=transformed)
