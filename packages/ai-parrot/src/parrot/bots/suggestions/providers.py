"""Built-in deterministic suggestion providers (FEAT-752)."""

from __future__ import annotations

from typing import Any, ClassVar, Optional, Sequence

from navconfig.logging import logging

from parrot.models.outputs import OutputMode
from parrot.models.responses import AIMessage
from parrot.models.suggestions import Suggestion, SuggestionKind, SuggestionSource
from parrot.skills.tenancy import current_turn_skill

from .engine import renderer_available
from .protocol import SuggestionContext

logger = logging.getLogger(__name__)


def has_tabular_data(response: AIMessage) -> bool:
    """True for a non-empty list of dicts in ``response.data`` or a non-empty DataFrame-like object."""
    data = getattr(response, "data", None)
    if data is None:
        return False
    if isinstance(data, list):
        return bool(data) and all(isinstance(item, dict) for item in data)
    if hasattr(data, "to_dict") and hasattr(data, "to_string"):
        return not bool(getattr(data, "empty", False))
    return False


def _as_mode(value: Any) -> Optional[OutputMode]:
    """Coerce ``value`` to an :class:`OutputMode`, or ``None`` when it is not a valid mode."""
    try:
        return OutputMode(value)
    except ValueError:
        return None


class SkillSuggestionProvider:
    """lane="skill". Emits the turn skill's declared chips (FEAT-752, spec rev 0.2)."""

    name = "skill"
    lane = "skill"

    def __init__(self, bot: Any) -> None:
        self.bot = bot

    async def suggest(self, ctx: SuggestionContext) -> Sequence[Suggestion]:
        """Map the turn skill's ``suggestions`` 1:1; an invalid ``output_mode`` drops only that chip."""
        skill = current_turn_skill()
        if skill is None or not getattr(skill, "suggestions", None):
            return []
        chips: list[Suggestion] = []
        for declared in skill.suggestions:
            mode: Optional[OutputMode] = None
            if declared.output_mode is not None:
                mode = _as_mode(declared.output_mode)
                if mode is None:
                    logger.warning(
                        "Skill %r suggestion %r has unknown output_mode %r; dropped",
                        skill.name,
                        declared.label,
                        declared.output_mode,
                    )
                    continue
            try:
                chips.append(
                    Suggestion(
                        label=declared.label,
                        prompt=declared.prompt,
                        output_mode=mode,
                        kind=SuggestionKind.PRESENTATION if mode is not None else SuggestionKind.FOLLOWUP,
                        source=SuggestionSource.SKILL,
                    )
                )
            except ValueError as exc:
                logger.warning("Skill %r suggestion %r is invalid: %s", skill.name, declared.label, exc)
        return chips


class PresentationSuggestionProvider:
    """lane="deterministic". Offers "View as table / chart / KPI" for modes the server can render."""

    name = "presentation"
    lane = "deterministic"
    DEFAULT_MODES: ClassVar[tuple[tuple[OutputMode, str, str], ...]] = (
        (OutputMode.STRUCTURED_TABLE, "View as table", "Show the previous answer as a table"),
        (OutputMode.STRUCTURED_CHART, "View as chart", "Show the previous answer as a chart"),
        (OutputMode.CARD, "View as KPI", "Show the headline figure of the previous answer as a KPI card"),
    )

    def __init__(self, bot: Any, *, modes: Optional[Sequence[OutputMode]] = None) -> None:
        self.bot = bot
        self._modes = modes

    def _allowed_modes(self) -> Optional[set[OutputMode]]:
        """Resolve the allowed modes: constructor > ``bot.presentation_modes`` > ``None`` (all defaults)."""
        configured = self._modes
        if configured is None:
            configured = getattr(self.bot, "presentation_modes", None)
        if configured is None:
            return None
        return {mode for mode in (_as_mode(m) for m in configured) if mode is not None}

    async def suggest(self, ctx: SuggestionContext) -> Sequence[Suggestion]:
        """Return one chip per renderable mode that is not already the current mode."""
        if not has_tabular_data(ctx.response):
            return []
        allowed = self._allowed_modes()
        current = {_as_mode(ctx.output_mode), _as_mode(getattr(ctx.response, "output_mode", None))}
        chips: list[Suggestion] = []
        for mode, label, prompt in self.DEFAULT_MODES:
            if allowed is not None and mode not in allowed:
                continue
            if mode in current or not renderer_available(mode):
                continue
            chips.append(
                Suggestion(
                    label=label,
                    prompt=prompt,
                    output_mode=mode,
                    kind=SuggestionKind.PRESENTATION,
                    source=SuggestionSource.PROVIDER,
                )
            )
        return chips


class ExplainSuggestionProvider:
    """lane="deterministic". One "Explain this" action chip for data answers on bots that support followup."""

    name = "explain"
    lane = "deterministic"

    def __init__(self, bot: Any) -> None:
        self.bot = bot

    async def suggest(self, ctx: SuggestionContext) -> Sequence[Suggestion]:
        """Emit the explain chip only for tabular answers on a bot with a callable ``followup``."""
        if not has_tabular_data(ctx.response) or not callable(getattr(self.bot, "followup", None)):
            return []
        return [
            Suggestion(
                label="Explain this",
                prompt="Explain this answer",
                kind=SuggestionKind.ACTION,
                action="explain",
                source=SuggestionSource.PROVIDER,
            )
        ]
