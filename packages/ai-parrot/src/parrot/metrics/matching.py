"""Phrase to metric-id matching with lexical and embedding lanes (FEAT-756 M3)."""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Mapping, Sequence

from parrot.metrics.models import DimensionSpec, PeriodPreset

_LOGGER = logging.getLogger(__name__)


def normalize(text: str) -> str:
    """Casefold text, strip accents and punctuation, and collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    unaccented = "".join(character for character in decomposed if not unicodedata.combining(character))
    without_punctuation = "".join(character if character.isalnum() else " " for character in unaccented)
    return " ".join(without_punctuation.split())


class MetricMatcher:
    """Resolve a phrase to a metric id, trying lexical aliases before embeddings."""

    def __init__(
        self,
        *,
        embedding_model: str = "intfloat/multilingual-e5-small",
        threshold: float = 0.85,
        margin: float = 0.05,
        enable_embeddings: bool = True,
        encoder: Any | None = None,
    ) -> None:
        """Initialize a matcher using the shared intent-router calibration defaults.

        Args:
            embedding_model: Sentence-transformer model used by the embedding lane.
            threshold: Minimum embedding score accepted as a match.
            margin: Score separation below which a match is ambiguous.
            enable_embeddings: Whether unmatched questions may use embeddings.
            encoder: Optional encoder injected into the embedding router.
        """
        self.embedding_model = embedding_model
        self.threshold = threshold
        self.margin = margin
        self.enable_embeddings = enable_embeddings
        self._encoder = encoder
        self._terms: dict[str, list[str]] = {}
        self._bank: dict[str, list[str]] = {}
        self._router: Any | None = None

    def configure(self, bank: Mapping[str, Sequence[str]]) -> None:
        """Store a metric phrase bank while deferring all embedding work."""
        self._bank = {metric_id: list(terms) for metric_id, terms in bank.items()}
        self._terms = {
            metric_id: list(dict.fromkeys(term for value in terms if (term := normalize(value))))
            for metric_id, terms in self._bank.items()
        }
        self._router = None

    def _ensure_router(self) -> Any:
        """Build and populate the embedding router on first embedding-lane use."""
        if self._router is None:
            from parrot.registry.routing.embedding_router import EmbeddingIntentRouter

            router = EmbeddingIntentRouter(
                self.embedding_model,
                self.threshold,
                self.margin,
                encoder=self._encoder,
            )
            for metric_id, utterances in self._bank.items():
                router.add_route(metric_id, list(utterances))
            self._router = router
        return self._router

    def match(self, question: str) -> tuple[str, float, str, bool] | None:
        """Return ``(metric_id, score, lane, ambiguous)`` or ``None``.

        This method is CPU-bound when it reaches the embedding lane; async
        callers should invoke it with :func:`asyncio.to_thread`.
        """
        normalized_question = normalize(question)
        tokens = normalized_question.split()
        if len(tokens) < 2:
            return None

        exact_ids = [metric_id for metric_id, terms in self._terms.items() if normalized_question in terms]
        if exact_ids:
            return exact_ids[0], 1.0, "alias", len(exact_ids) > 1

        contained: list[tuple[int, str, str]] = []
        for metric_id, terms in self._terms.items():
            for term in terms:
                if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", normalized_question):
                    contained.append((len(term), metric_id, term))
        if contained:
            longest = max(length for length, _, _ in contained)
            winners = list(dict.fromkeys(metric_id for length, metric_id, _ in contained if length == longest))
            return winners[0], 0.95, "alias", len(winners) > 1

        if not self.enable_embeddings or len(tokens) < 3 or not self._bank:
            return None

        try:
            scores = self._ensure_router().route_label_scores(question)
        except Exception:
            _LOGGER.warning("Metric embedding match failed", exc_info=True)
            return None
        if not scores:
            return None
        best_label, best_score = scores[0]
        if best_score < self.threshold:
            return None
        runner_up = scores[1][1] if len(scores) > 1 else -1.0
        ambiguous = (best_score - runner_up) < self.margin
        return best_label, best_score, "embedding", ambiguous

    @staticmethod
    def parse_period(question: str) -> PeriodPreset | None:
        """Parse a supported English or Spanish period preset from a question."""
        normalized_question = normalize(question)
        lexicon: tuple[tuple[PeriodPreset, tuple[str, ...]], ...] = (
            ("last_90d", ("last 90 days", "ultimos 90 dias")),
            ("last_30d", ("last 30 days", "ultimos 30 dias")),
            ("last_7d", ("last 7 days", "ultimos 7 dias")),
            ("last_month", ("last month", "el mes pasado", "mes pasado")),
            ("this_month", ("this month", "este mes")),
            ("last_week", ("last week", "semana pasada")),
            ("this_week", ("this week", "esta semana")),
            ("last_year", ("last year", "ano pasado")),
            ("this_year", ("this year", "este ano")),
            ("ytd", ("year to date", "en lo que va del ano", "ytd")),
            ("mtd", ("month to date", "mtd")),
            ("qtd", ("qtd",)),
            ("yesterday", ("yesterday", "ayer")),
            ("today", ("today", "hoy")),
        )
        matches = {
            preset
            for preset, phrases in lexicon
            if any(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", normalized_question) for phrase in phrases)
        }
        return next(iter(matches)) if len(matches) == 1 else None

    @staticmethod
    def parse_dimension(question: str, dimensions: Sequence[DimensionSpec]) -> str | None:
        """Parse ``by``/``por`` followed by a dimension name or alias."""
        match = re.search(r"\b(?:by|por)\s+(.+)$", normalize(question))
        if match is None:
            return None
        requested = match.group(1)
        candidates: list[tuple[int, str]] = []
        for dimension in dimensions:
            for value in (dimension.name, *dimension.aliases):
                term = normalize(value)
                if term and re.match(rf"{re.escape(term)}(?:\s|$)", requested):
                    candidates.append((len(term), dimension.name))
        if not candidates:
            return None
        longest = max(length for length, _ in candidates)
        return next(name for length, name in candidates if length == longest)
