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

from typing import NamedTuple, Optional

import numpy as np

from parrot.models.outputs import OutputMode


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
    """

    mode: Optional[OutputMode]
    score: float
    runner_up: float
    ambiguous: bool


class EmbeddingIntentRouter:
    """Deterministic, embedding-based output-mode router. No cloud LLM.

    Encodes a phrase bank (``dict[OutputMode, list[str]]``) once and scores
    queries by max-cosine similarity per mode. The encoder is lazy-loaded at
    most once and reused across all routes/queries.
    """

    def __init__(
        self,
        model: str = "intfloat/multilingual-e5-small",
        threshold: float = 0.85,
        margin: float = 0.05,
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
        """
        self._model_name = model
        self.threshold = threshold
        self.margin = margin
        self._encoder = None  # lazy — loaded at most once
        self._routes: dict[OutputMode, np.ndarray] = {}

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

    def add_route(self, mode: OutputMode, utterances: list[str]) -> None:
        """Encode and store reference utterances for an output mode.

        Encoding happens at configuration time (once per route); ``route()``
        never re-encodes the bank.

        Args:
            mode: The :class:`OutputMode` these utterances map to.
            utterances: Reference phrases for the mode (ES/EN supported).
        """
        if not utterances:
            return
        enc = self._ensure_encoder()
        texts = [f"query: {u}" for u in utterances]  # e5 prefix convention
        emb = enc.encode(texts, normalize_embeddings=True)
        self._routes[mode] = np.asarray(emb)

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
        if not self._routes:
            return RouteScore(None, -1.0, -1.0, False)
        enc = self._ensure_encoder()
        q = np.asarray(
            enc.encode([f"query: {query}"], normalize_embeddings=True)
        )[0]
        # Cosine == dot product on normalized vectors; max over each mode's bank.
        scored = sorted(
            ((m, float(np.max(emb @ q))) for m, emb in self._routes.items()),
            key=lambda kv: kv[1],
            reverse=True,
        )
        best_mode, best = scored[0]
        runner_up = scored[1][1] if len(scored) > 1 else -1.0
        if best < self.threshold:
            return RouteScore(None, best, runner_up, False)
        ambiguous = (best - runner_up) < self.margin
        return RouteScore(best_mode, best, runner_up, ambiguous)
