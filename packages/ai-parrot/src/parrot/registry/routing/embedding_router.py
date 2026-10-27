"""EmbeddingIntentRouter — deterministic, embedding-based output-mode router.

Pure engine (no agent coupling) for FEAT-224. Encodes a phrase bank keyed by
:class:`~parrot.models.outputs.OutputMode` once via a multilingual
SentenceTransformer (``intfloat/multilingual-e5-small`` by default) and scores a
query by **max cosine** similarity per mode. No cloud LLM, no tokens on the hot
path.

The engine is intentionally synchronous and CPU-bound: callers dispatch
:meth:`EmbeddingIntentRouter.route` via :func:`asyncio.to_thread` so the blocking
``encode()`` never runs on the event loop (see ``IntentRouterMixin``).

Usage::

    from parrot.models.outputs import OutputMode
    from parrot.registry.routing.embedding_router import EmbeddingIntentRouter

    router = EmbeddingIntentRouter(threshold=0.55, margin=0.05)
    router.add_route(OutputMode.STRUCTURED_CHART,
                     ["create a pie chart", "hazme una gráfica de pastel"])
    score = router.route("create a pie chart of Q1 sales")
    # -> RouteScore(mode=OutputMode.STRUCTURED_CHART, score=0.83, ...)

e5 convention: queries (and short reference utterances) are prefixed with
``"query: "``. Swapping the encoder invalidates the tuned ``threshold``/``margin``
because of embedding-space drift.
"""
from __future__ import annotations

from typing import Any, NamedTuple, Optional

import numpy as np

from parrot.models.outputs import OutputMode
from parrot.registry.routing.route_labels import OutputShape, parse_route_label

class RouteScore(NamedTuple):
    """Result of :meth:`EmbeddingIntentRouter.route`.

    Attributes:
        mode: Best-matching :class:`OutputMode`, or ``None`` when the best score
            is below the router's ``threshold`` (abstain).
        score: Max-cosine similarity of the winning mode.
        runner_up: Second-best mode's score (for margin/ambiguity checks);
            ``-1.0`` when there is no runner-up.
        ambiguous: ``True`` when ``score >= threshold`` and
            ``(score - runner_up) < margin`` — i.e. the winner is not clearly
            ahead and a caller may wish to consult an LLM tie-breaker.
        label: Raw winning route label, or ``None`` when the router abstains.
        component: A2UI component parsed from ``label``, or ``None``.
    """

    mode: Optional[OutputMode]
    score: float
    runner_up: float
    ambiguous: bool
    label: Optional[str] = None
    component: Optional[str] = None


class EmbeddingIntentRouter:
    """Deterministic, embedding-based output-mode router. No cloud LLM.

    Encodes a phrase bank (``dict[str, list[str]]``) once and scores
    queries by max-cosine similarity per mode. The encoder is lazy-loaded at
    most once and reused across all routes/queries.
    """

    def __init__(
        self,
        model: str = "intfloat/multilingual-e5-small",
        threshold: float = 0.85,
        margin: float = 0.05,
        *,
        encoder: Any | None = None,
    ) -> None:
        """Initialize the router.

        Args:
            model: SentenceTransformer model id (multilingual e5 by default).
            threshold: Minimum max-cosine to accept a route; below -> abstain.
                Calibrated for ``multilingual-e5-small``, whose cosine scores
                cluster high (empirically: on-topic matches ~0.92–0.95,
                off-topic ~0.77–0.82). The default ``0.85`` separates those
                cleanly; **swapping the encoder invalidates this value** and
                requires a re-sweep (embedding-space drift).
            margin: If ``(best - second) < margin`` the result is flagged
                ``ambiguous`` for an optional caller-side tie-breaker.
            encoder: An optional shared SentenceTransformer-compatible encoder.
        """
        self._model_name = model
        self.threshold = threshold
        self.margin = margin
        self._encoder = encoder  # lazy — loaded at most once when not supplied
        self._routes: dict[str, np.ndarray] = {}

    def _ensure_encoder(self):
        """Lazily load the SentenceTransformer encoder (once).

        Uses the project ``lazy_import`` helper so a missing optional
        ``sentence-transformers`` install raises an actionable error pointing at
        the ``embeddings`` extra, matching ``memory/episodic/embedding.py``.
        """
        if self._encoder is None:
            from parrot._imports import lazy_import

            _st = lazy_import(
                "sentence_transformers",
                package_name="sentence-transformers",
                extra="embeddings",
            )
            self._encoder = _st.SentenceTransformer(self._model_name)
        return self._encoder

    def add_route(self, label: OutputMode | str, utterances: list[str]) -> None:
        """Encode and store reference utterances under ``label``.

        Encoding happens at configuration time (once per route); ``route()``
        never re-encodes the bank.

        Args:
            label: An :class:`OutputMode` or a composite route label.
            utterances: Reference phrases for the mode (ES/EN supported).
        """
        if not utterances:
            return
        key = label.value if isinstance(label, OutputMode) else str(label)
        enc = self._ensure_encoder()
        texts = [f"query: {u}" for u in utterances]  # e5 prefix convention
        emb = enc.encode(texts, normalize_embeddings=True)
        self._routes[key] = np.asarray(emb)

    def route_label_scores(self, query: str) -> list[tuple[str, float]]:
        """Return every label's max-cosine score, sorted descending.

        CPU-bound and synchronous — dispatch via ``asyncio.to_thread`` from
        async callers. Unlike :meth:`route`, no thresholding is applied.

        Args:
            query: The raw user query (the ``"query: "`` prefix is added here).

        Returns:
            A list of ``(label, score)`` pairs sorted by score desc; empty when
            no routes are configured.
        """
        if not self._routes:
            return []
        enc = self._ensure_encoder()
        q = np.asarray(enc.encode([f"query: {query}"], normalize_embeddings=True))[0]
        return sorted(
            ((label, float(np.max(emb @ q))) for label, emb in self._routes.items()),
            key=lambda kv: kv[1],
            reverse=True,
        )

    def route_scores(self, query: str) -> list[tuple[OutputMode, float]]:
        """Return every parseable mode's max-cosine score, sorted descending.

        CPU-bound and synchronous — dispatch via ``asyncio.to_thread`` from
        async callers. Unlike :meth:`route`, no thresholding is applied; this is
        used to assemble the close-candidate set for an LLM tie-breaker.

        Args:
            query: The raw user query (the ``"query: "`` prefix is added here).

        Returns:
            A list of ``(OutputMode, score)`` pairs sorted by score desc; empty
            when no routes are configured.
        """
        scores: list[tuple[OutputMode, float]] = []
        for label, score in self.route_label_scores(query):
            try:
                shape = parse_route_label(label)
            except ValueError:
                continue
            scores.append((shape.mode, score))
        return scores

    def route(self, query: str) -> RouteScore:
        """Score ``query`` against the phrase bank and return a RouteScore.

        CPU-bound and synchronous by design — dispatch via ``asyncio.to_thread``
        from async callers.

        Args:
            query: The raw user query (the ``"query: "`` prefix is added here).

        Returns:
            A :class:`RouteScore`. ``mode is None`` when the best score is below
            ``threshold`` (abstain) or when no routes are configured.
        """
        scored = self.route_label_scores(query)
        if not scored:
            return RouteScore(None, -1.0, -1.0, False)
        best_label, best = scored[0]
        runner_up = scored[1][1] if len(scored) > 1 else -1.0
        if best < self.threshold:
            return RouteScore(None, best, runner_up, False)
        ambiguous = (best - runner_up) < self.margin
        shape: OutputShape = parse_route_label(best_label)
        return RouteScore(shape.mode, best, runner_up, ambiguous, best_label, shape.component)
