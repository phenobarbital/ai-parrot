"""Deterministic follow-up chips from the stashed MetricMatch (FEAT-756 G7, FEAT-752 provider)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal, Sequence

from parrot.metrics.context import current_metric_match
from parrot.models.suggestions import Suggestion, SuggestionKind, SuggestionSource

if TYPE_CHECKING:
    from parrot.bots.suggestions.protocol import SuggestionContext

_LOGGER = logging.getLogger(__name__)
_SHAPES = ("KPICard", "Chart", "DataTable")


class MetricSuggestionProvider:
    """Chips: "vs previous period", "by <dimension>" (≤3), "as <other shape>"."""

    name: str = "metrics"
    lane: Literal["skill", "deterministic", "llm"] = "deterministic"

    def __init__(self, *, max_chips: int = 5) -> None:
        self.max_chips = max_chips

    async def suggest(self, ctx: "SuggestionContext") -> Sequence[Suggestion]:
        match = current_metric_match()
        if match is None:
            return []
        try:
            chips = []

            # Add "vs previous period" chip if comparison is enabled
            if match.metric.comparison.mode != "none":
                prompt = f"Compare {match.metric.name} vs previous period"
                label = "vs previous period"
                if len(label) > 40:
                    label = label[:37] + "..."
                chips.append(
                    Suggestion(
                        label=label,
                        prompt=prompt,
                        output_mode=None,
                        kind=SuggestionKind.FOLLOWUP,
                        source=SuggestionSource.PROVIDER,
                        action=None,
                    )
                )

            # Add dimension chips (max 3)
            for dimension in match.metric.dimensions[:3]:
                prompt = f"Show {match.metric.name} by {dimension.label or dimension.name}"
                label = f"by {dimension.label or dimension.name}"
                if len(label) > 40:
                    label = label[:37] + "..."
                chips.append(
                    Suggestion(
                        label=label,
                        prompt=prompt,
                        output_mode=None,
                        kind=SuggestionKind.FOLLOWUP,
                        source=SuggestionSource.PROVIDER,
                        action=None,
                    )
                )

            # Add presentation chips for other shapes
            current_shape = match.metric.default_shape.component
            for shape in _SHAPES:
                if shape != current_shape:
                    prompt = f"Show {match.metric.name} as a {shape.lower()}"
                    label = f"as {shape}"
                    if len(label) > 40:
                        label = label[:37] + "..."
                    chips.append(
                        Suggestion(
                            label=label,
                            prompt=prompt,
                            output_mode=None,
                            kind=SuggestionKind.PRESENTATION,
                            source=SuggestionSource.PROVIDER,
                            action=None,
                        )
                    )

            # Return up to max_chips
            return chips[: self.max_chips]
        except Exception as exc:
            _LOGGER.warning("metric suggestions failed: %s", exc)
            return []
