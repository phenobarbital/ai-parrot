"""LLM-based debug reranker implementation.

This module provides ``LLMReranker``, a debug/fallback reranker that uses any
``AbstractClient`` to score ``(query, document)`` pairs via a structured-output
prompt.

**NOT intended for production hot-path use.**  It exists so engineers can
sanity-check ``LocalCrossEncoderReranker`` rankings against a strong reference
LLM (e.g. GPT-4, Claude) without external reranking services.

Throughput characteristics:

- Scores each document independently using the LLM's ``invoke()`` method.
- Uses ``asyncio.gather()`` to score documents concurrently.
- No batching, no caching — this is a debug tool only.

Example:
    >>> from parrot.rerankers import LLMReranker
    >>> reranker = LLMReranker(client=my_llm_client)
    >>> results = await reranker.rerank("my query", documents, top_n=5)
"""

import asyncio
import logging
import time
from typing import Optional

from parrot.clients.base import AbstractClient
from parrot.rerankers.abstract import AbstractReranker
from parrot.rerankers.models import RerankedDocument
from parrot.stores.models import SearchResult

_SCORE_PROMPT_TEMPLATE = """\
Rate the relevance of the following passage to the query on a scale of 0.0 to 1.0.

Query: {query}
Passage: {passage}

Respond with ONLY a single floating-point number between 0.0 and 1.0.
Do not include any explanation, units, or other text.\
"""


class LLMReranker(AbstractReranker):
    """Debug reranker that uses an LLM to score query-passage pairs.

    This reranker calls the LLM once per document to obtain a relevance score
    in the range ``[0.0, 1.0]``.  Documents are scored concurrently via
    ``asyncio.gather()``.  Results are sorted in descending order by score.

    On any failure (LLM error, parse error), the reranker logs a WARNING and
    returns the original ordering with ``rerank_score=float('nan')``.

    Args:
        client: Any concrete ``AbstractClient`` subclass (OpenAI, Anthropic, etc.).
        model_name: Optional display name for ``rerank_model`` in the output.
            Defaults to ``"llm-reranker"``.
        **kwargs: Reserved for future extension.

    Example:
        >>> reranker = LLMReranker(client=openai_client)
        >>> results = await reranker.rerank("What is ML?", documents, top_n=3)
    """

    def __init__(
        self,
        client: AbstractClient,
        model_name: str = "llm-reranker",
        **kwargs,
    ) -> None:
        """Initialise the LLMReranker.

        Args:
            client: An ``AbstractClient`` instance used to call the LLM.
            model_name: Label used in the ``rerank_model`` field of each
                ``RerankedDocument``.  Defaults to ``"llm-reranker"``.
            **kwargs: Reserved for future extension.
        """
        self.client = client
        self.model_name = model_name
        self.logger = logging.getLogger(__name__)

    async def rerank(
        self,
        query: str,
        documents: list[SearchResult],
        top_n: Optional[int] = None,
    ) -> list[RerankedDocument]:
        """Score ``(query, document)`` pairs via LLM and return sorted results.

        Each document is scored independently with a single LLM call.  All
        calls are issued concurrently via ``asyncio.gather()``.

        Args:
            query: User query text.
            documents: Candidate documents from upstream retrieval.
            top_n: If set, return only the top N results.  ``None`` returns all.

        Returns:
            ``RerankedDocument`` list sorted by descending ``rerank_score``.
            On failure, returns the original ordering with ``rerank_score=NaN``.
        """
        if not documents:
            return []

        t0 = time.monotonic()

        try:
            scores = await asyncio.gather(
                *[self._score_document(query, doc) for doc in documents]
            )
        except Exception as exc:
            self.logger.warning(
                "LLMReranker batch failed; returning original order. Error: %s",
                exc,
            )
            return self._fallback_result(documents)

        latency_ms = (time.monotonic() - t0) * 1000.0

        # Sort descending by score
        scored = sorted(
            enumerate(zip(scores, documents)),
            key=lambda x: x[1][0],
            reverse=True,
        )

        results = [
            RerankedDocument(
                document=doc,
                rerank_score=float(score),
                rerank_rank=new_rank,
                original_rank=orig_rank,
                rerank_model=self.model_name,
                rerank_latency_ms=latency_ms,
            )
            for new_rank, (orig_rank, (score, doc)) in enumerate(scored)
        ]

        if top_n is not None:
            results = results[:top_n]

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _score_document(
        self,
        query: str,
        document: SearchResult,
    ) -> float:
        """Ask the LLM to score one (query, passage) pair.

        Parse failures (non-numeric LLM response) are handled gracefully by
        returning ``0.0``.  LLM invocation errors are **not** caught here —
        they propagate to the ``asyncio.gather()`` in ``rerank()``, which
        triggers the full-batch NaN fallback.

        Args:
            query: User query text.
            document: A single candidate document.

        Returns:
            Relevance score in ``[0.0, 1.0]`` on success, or ``0.0`` on
            parse failure.

        Raises:
            Exception: Any exception raised by the underlying LLM call
                (propagated to allow ``rerank()`` to trigger the NaN fallback).
        """
        prompt = _SCORE_PROMPT_TEMPLATE.format(
            query=query,
            passage=document.content,
        )
        response = await self.client.invoke(
            prompt,
            max_tokens=16,
            temperature=0.0,
        )
        # InvokeResult may be a string or structured object
        raw = response
        if hasattr(response, "content"):
            raw = response.content
        elif hasattr(response, "text"):
            raw = response.text

        try:
            score = float(str(raw).strip())
        except (ValueError, TypeError):
            self.logger.warning(
                "LLMReranker: could not parse score from LLM response for "
                "document id=%s (got %r); assigning 0.0",
                document.id,
                raw,
            )
            return 0.0

        # Clamp to [0, 1]
        return max(0.0, min(1.0, score))

    def _fallback_result(self, documents: list[SearchResult]) -> list[RerankedDocument]:
        """Return documents in original order with NaN scores.

        Args:
            documents: Original retrieval results.

        Returns:
            ``RerankedDocument`` list preserving original order with NaN scores.
        """
        nan = float("nan")
        return [
            RerankedDocument(
                document=doc,
                rerank_score=nan,
                rerank_rank=i,
                original_rank=i,
                rerank_model=self.model_name,
            )
            for i, doc in enumerate(documents)
        ]
