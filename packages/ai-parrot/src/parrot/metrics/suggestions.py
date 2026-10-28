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

    async def suggest(self, ctx: SuggestionContext) -> Sequence[Suggestion]:
        match = current_metric_match()
        if match is None:
            return []
        try:
            chips: list[Suggestion] = []
            metric = match.metric

            # 1. "vs previous period" chip (if comparison is enabled)
            if metric.comparison.mode != "none":
                chips.append(
                    Suggestion(
                        label="vs previous period",
                        prompt=f"Show {metric.name} vs previous period",
                        kind=SuggestionKind.FOLLOWUP,
                        source=SuggestionSource.PROVIDER,
                    )
                )

            # 2. "by <dimension>" chips (up to 3)
            for dimension in metric.dimensions[:3]:
                label = dimension.label or dimension.name
                chips.append(
                    Suggestion(
                        label=f"by {label}",
                        prompt=f"Show {metric.name} by {label}",
                        kind=SuggestionKind.FOLLOWUP,
                        source=SuggestionSource.PROVIDER,
                    )
                )

            # 3. "as <other shape>" chips (exclude current default)
            current_shape = metric.default_shape.component
            for shape in _SHAPES:
                if shape != current_shape:
                    chips.append(
                        Suggestion(
                            label=f"as {shape}",
                            prompt=f"Show {metric.name} as a {shape.lower()}",
                            kind=SuggestionKind.PRESENTATION,
                            source=SuggestionSource.PROVIDER,
                        )
                    )

            # Cap at max_chips
            return chips[: self.max_chips]

        except Exception as exc:
            _LOGGER.warning("metric suggestions failed: %s", exc)
            return []
