"""StoreRouter core orchestrator (FEAT-111 Module 7).

Integrates all sub-modules (cache, rules, ontology, LLM helper) into the
end-to-end store-routing decision + execution pipeline.

Usage::

    from parrot.registry.routing import StoreRouter, StoreRouterConfig

    router = StoreRouter(config)
    decision = await router.route("what is an endcap?", [StoreType.PGVECTOR])
    results  = await router.execute(decision, query, stores_dict)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Optional

from parrot.registry.routing.cache import DecisionCache, build_cache_key
from parrot.registry.routing.llm_helper import run_llm_ranking
from parrot.registry.routing.models import (
    StoreFallbackPolicy,
    StoreRoutingDecision,
    StoreRouterConfig,
    StoreScore,
)
from parrot.registry.routing.ontology_signal import OntologyPreAnnotator
from parrot.registry.routing.rules import DEFAULT_STORE_RULES, apply_rules
from parrot.stores.abstract import AbstractStore
from parrot.tools.multistoresearch import MultiStoreSearchTool, StoreType

_logger = logging.getLogger(__name__)


class NoSuitableStoreError(RuntimeError):
    """Raised by ``StoreRouter.execute`` when ``fallback_policy=RAISE``
    and no store scored above the confidence floor."""


class StoreRouter:
    """Store-level router activated via ``AbstractBot.configure_store_router()``.

    Orchestration order within :meth:`route`:

    1. LRU cache lookup.
    2. Ontology pre-annotation (when ``enable_ontology_signal=True``).
    3. Fast-path rules evaluation.
    4. Margin check → LLM path (when margin is too narrow and ``invoke_fn``
       is provided).
    5. Confidence floor filtering.
    6. Decision assembly + cache write.

    :meth:`execute` drives retrieval according to the decision's
    ``rankings`` and ``StoreFallbackPolicy``.

    Args:
        config: Full router configuration.
        ontology_resolver: Optional resolver passed through to
            :class:`~parrot.registry.routing.OntologyPreAnnotator`.
    """

    def __init__(
        self,
        config: StoreRouterConfig,
        ontology_resolver: Optional[Any] = None,
    ) -> None:
        self._config = config
        self._cache = DecisionCache(config.cache_size)
        self._annotator = OntologyPreAnnotator(ontology_resolver)
        self.logger = _logger

    # ------------------------------------------------------------------
    # Route
    # ------------------------------------------------------------------

    async def route(
        self,
        query: str,
        available_stores: list[StoreType],
        invoke_fn: Optional[Callable] = None,
    ) -> StoreRoutingDecision:
        """Produce a :class:`StoreRoutingDecision` for *query*.

        Args:
            query: User query string.
            available_stores: Stores configured on the calling bot.
            invoke_fn: Async callable used for the LLM fallback path
                (usually ``bot.invoke``).  ``None`` disables the LLM path.

        Returns:
            A fully-assembled :class:`StoreRoutingDecision`.
        """
        t_start = time.monotonic()

        # ── 1. Cache lookup ───────────────────────────────────────────────
        fingerprint = tuple(sorted(s.value for s in available_stores))
        cache_key = build_cache_key(query, fingerprint)

        cached = await self._cache.get(cache_key)
        if cached is not None:
            self.logger.debug("StoreRouter: cache hit for query '%s...'", query[:60])
            # Return a copy with the cache_hit flag set.
            return StoreRoutingDecision(
                rankings=cached.rankings,
                fallback_used=cached.fallback_used,
                cache_hit=True,
                ontology_annotations=cached.ontology_annotations,
                path="cache",
                elapsed_ms=(time.monotonic() - t_start) * 1_000,
            )

        # ── 2. Ontology annotation ────────────────────────────────────────
        annotations: dict = {}
        if self._config.enable_ontology_signal:
            try:
                annotations = await self._annotator.annotate(query)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("StoreRouter: ontology annotation failed: %s", exc)

        # ── 3. Fast-path rules ────────────────────────────────────────────
        merged_rules = list(DEFAULT_STORE_RULES) + list(self._config.custom_rules)
        fast_scores = apply_rules(query, merged_rules, available_stores, annotations or None)

        # Track the routing path.  "fast" unless LLM is successfully used.
        path = "fast"
        final_scores = fast_scores

        # ── 4. Margin check / empty fast-path → LLM path ─────────────────
        # Trigger LLM when:
        #   a) Fast-path is empty (no heuristic match → uncertain), or
        #   b) Fast-path produces ≥2 results with a tight margin.
        should_try_llm = (
            invoke_fn is not None
            and (len(fast_scores) == 0 or self._should_try_llm(fast_scores))
        )
        if should_try_llm:
            llm_scores = await self._llm_path(query, available_stores, annotations, invoke_fn)
            if llm_scores is not None:
                final_scores = _merge_scores(fast_scores, llm_scores)
                path = "llm"
            # If LLM timed out or failed, keep fast_scores; path stays "fast".

        # ── 5. Confidence floor ───────────────────────────────────────────
        floor = self._config.confidence_floor
        filtered = [s for s in final_scores if s.confidence >= floor]
        filtered.sort(key=lambda s: s.confidence, reverse=True)

        # fallback_used=True means execute() should apply the StoreFallbackPolicy.
        # We intentionally preserve the path ("fast"/"llm") so the caller knows
        # which decision route was taken, regardless of whether results exist.
        fallback_used = len(filtered) == 0

        # ── 6. Assemble decision + cache ──────────────────────────────────
        elapsed_ms = (time.monotonic() - t_start) * 1_000
        decision = StoreRoutingDecision(
            rankings=filtered,
            fallback_used=fallback_used,
            cache_hit=False,
            ontology_annotations=annotations or None,
            path=path,
            elapsed_ms=elapsed_ms,
        )

        await self._cache.put(cache_key, decision)
        self.logger.info(
            "StoreRouter: query='%s...' path=%s stores=%s elapsed_ms=%.1f",
            query[:60],
            path,
            [s.store.value for s in filtered[:3]],
            elapsed_ms,
        )
        return decision

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        decision: StoreRoutingDecision,
        query: str,
        stores: dict[StoreType, "AbstractStore"],
        multistore_tool: Optional["MultiStoreSearchTool"] = None,
        **search_kwargs: Any,
    ) -> list:
        """Execute retrieval according to *decision*.

        Args:
            decision: The routing decision from :meth:`route`.
            query: The user query (forwarded to ``similarity_search``).
            stores: Dict of available :class:`~parrot.stores.abstract.AbstractStore`
                instances keyed by :class:`~parrot.tools.multistoresearch.StoreType`.
            multistore_tool: Optional :class:`~parrot.tools.multistoresearch.MultiStoreSearchTool`
                instance used when ``fallback_policy=FAN_OUT``.
            **search_kwargs: Extra keyword arguments forwarded to
                ``similarity_search`` (e.g. ``limit``, ``score_threshold``).

        Returns:
            List of results (may be empty).  Deduplication is the caller's
            responsibility.
        """
        if decision.fallback_used or not decision.rankings:
            return await self._execute_fallback(
                query, stores, multistore_tool, **search_kwargs
            )

        # Normal path: query top-N stores concurrently.
        top_n = min(self._config.top_n, len(decision.rankings))
        top_stores = [r.store for r in decision.rankings[:top_n]]

        tasks = []
        store_types = []
        for st in top_stores:
            store = stores.get(st)
            if store is None:
                self.logger.debug("StoreRouter: store %s not in stores dict — skip", st)
                continue
            tasks.append(store.similarity_search(query, **search_kwargs))
            store_types.append(st)

        if not tasks:
            return []

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        results = []
        for st, raw in zip(store_types, raw_results):
            if isinstance(raw, Exception):
                self.logger.warning(
                    "StoreRouter: similarity_search on %s failed: %s", st, raw
                )
                continue
            results.extend(raw)
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _should_try_llm(self, fast_scores: list[StoreScore]) -> bool:
        """Return True when the margin between top-1 and top-2 is too narrow."""
        if len(fast_scores) < 2:
            # Only one (or zero) candidates — no ambiguity.
            return False
        top1 = fast_scores[0].confidence
        top2 = fast_scores[1].confidence
        return (top1 - top2) < self._config.margin_threshold

    async def _llm_path(
        self,
        query: str,
        available_stores: list[StoreType],
        annotations: dict,
        invoke_fn: Callable,
    ) -> Optional[list[StoreScore]]:
        """Call the LLM for a ranking and parse the result."""
        store_list = ", ".join(s.value for s in available_stores)
        ann_str = str(annotations) if annotations else "none"
        prompt = (
            f"You are a retrieval router. Available stores: {store_list}.\n"
            f"Query: \"{query}\"\n"
            f"Ontology annotations: {ann_str}\n"
            "Respond with JSON: "
            '{"rankings": [{"store": "<name>", "confidence": <0-1>, "reason": "<short>"}]}'
        )

        parsed = await run_llm_ranking(invoke_fn, prompt, self._config.llm_timeout_s)
        if parsed is None:
            return None

        rankings_raw = parsed.get("rankings", [])
        if not isinstance(rankings_raw, list):
            return None

        available_values = {s.value: s for s in available_stores}
        scores = []
        for entry in rankings_raw:
            if not isinstance(entry, dict):
                continue
            store_val = entry.get("store", "")
            store_type = available_values.get(store_val)
            if store_type is None:
                continue
            try:
                confidence = float(entry.get("confidence", 0.5))
                confidence = max(0.0, min(1.0, confidence))
            except (TypeError, ValueError):
                confidence = 0.5
            reason = str(entry.get("reason", "llm"))
            scores.append(StoreScore(store=store_type, confidence=confidence, reason=reason))

        return scores if scores else None

    async def _execute_fallback(
        self,
        query: str,
        stores: dict[StoreType, AbstractStore],
        multistore_tool: Optional[MultiStoreSearchTool],
        **search_kwargs: Any,
    ) -> list:
        """Execute the configured ``StoreFallbackPolicy``."""
        policy = self._config.fallback_policy

        if policy == StoreFallbackPolicy.FAN_OUT:
            if multistore_tool is not None:
                return await multistore_tool._execute(query, **search_kwargs)
            # No multistore tool — parallel fan-out across all stores.
            if not stores:
                return []
            tasks = [
                store.similarity_search(query, **search_kwargs)
                for store in stores.values()
            ]
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)
            results = []
            for raw in raw_results:
                if isinstance(raw, Exception):
                    self.logger.warning("StoreRouter FAN_OUT: store search failed: %s", raw)
                    continue
                results.extend(raw)
            return results

        elif policy == StoreFallbackPolicy.FIRST_AVAILABLE:
            if not stores:
                return []
            first_store = next(iter(stores.values()))
            try:
                return await first_store.similarity_search(query, **search_kwargs)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("StoreRouter FIRST_AVAILABLE failed: %s", exc)
                return []

        elif policy == StoreFallbackPolicy.EMPTY:
            return []

        elif policy == StoreFallbackPolicy.RAISE:
            raise NoSuitableStoreError(
                f"No suitable store found for query: {query!r}"
            )

        # Unknown policy — log and return empty.
        self.logger.warning("StoreRouter: unknown fallback policy %r — returning []", policy)
        return []


# ------------------------------------------------------------------
# Score merging helper (LLM path)
# ------------------------------------------------------------------

def _merge_scores(
    fast: list[StoreScore],
    llm: list[StoreScore],
) -> list[StoreScore]:
    """Merge fast-path and LLM scores via a 0.5/0.5 weighted average.

    Stores present in only one list use their sole score directly.  Result
    is sorted descending by confidence.
    """
    fast_by_store = {s.store: s for s in fast}
    llm_by_store  = {s.store: s for s in llm}

    all_stores = set(fast_by_store) | set(llm_by_store)
    merged = []
    for st in all_stores:
        f = fast_by_store.get(st)
        l = llm_by_store.get(st)
        if f and l:
            conf = 0.5 * f.confidence + 0.5 * l.confidence
            reason = f"{f.reason}; {l.reason}"
        elif f:
            conf = f.confidence
            reason = f.reason
        else:
            assert l is not None
            conf = l.confidence
            reason = l.reason
        merged.append(StoreScore(store=st, confidence=conf, reason=reason))

    merged.sort(key=lambda s: s.confidence, reverse=True)
    return merged
