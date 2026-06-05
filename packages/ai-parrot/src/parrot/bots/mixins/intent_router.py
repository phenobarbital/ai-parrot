"""IntentRouterMixin — pre-RAG query routing for AI-Parrot bots.

Intercepts ``conversation()`` calls and routes the user query to the most
appropriate strategy (dataset query, vector search, tool call, graph traversal,
free LLM, etc.) before delegating to the base ``conversation()`` implementation.

Usage::

    class MyAgent(IntentRouterMixin, BasicAgent):
        pass

    agent = MyAgent(...)
    await agent.configure_router(config, registry)
    result = await agent.conversation("What were our Q1 sales?")

MRO note: ``IntentRouterMixin`` MUST appear before the concrete bot class in
the inheritance list so its ``conversation()`` method is called first.

Cross-feature dependency: The LLM routing path uses ``self.invoke()``
(FEAT-069). If invoke() is not available, the mixin falls back gracefully to
FREE_LLM.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from parrot.registry.routing.llm_helper import extract_json_from_response  # FEAT-111
from parrot.registry.capabilities.models import (
    IntentRouterConfig,
    RoutingDecision,
    RoutingTrace,
    RoutingType,
    RouterCandidate,
    TraceEntry,
)
from parrot.registry.capabilities.registry import CapabilityRegistry
from parrot.models.outputs import OutputMode  # FEAT-224 (output-mode routing)
from parrot.registry.routing.embedding_router import (  # FEAT-224
    EmbeddingIntentRouter,
    RouteScore,
)

# Lazy import guard — ContextEnvelope and EnrichedContext are only available when
# the knowledge.ontology package is installed.  We do a try/except at module level
# so that the router still works in environments without ontology dependencies.
try:
    from parrot.knowledge.ontology.schema import ContextEnvelope, EnrichedContext
    _CONTEXT_ENVELOPE_AVAILABLE = True
except ImportError:
    ContextEnvelope = None  # type: ignore[assignment,misc]
    EnrichedContext = None  # type: ignore[assignment,misc]
    _CONTEXT_ENVELOPE_AVAILABLE = False

# Fast-path keyword map: if any keyword appears in the query (case-insensitive),
# the corresponding strategy is returned immediately without an LLM call.
_KEYWORD_STRATEGY_MAP: dict[str, RoutingType] = {
    # ── Vector search ────────────────────────────────────────────────────
    "search for": RoutingType.VECTOR_SEARCH,
    "find documents": RoutingType.VECTOR_SEARCH,
    "search documents": RoutingType.VECTOR_SEARCH,
    # ── Dataset ──────────────────────────────────────────────────────────
    "run query": RoutingType.DATASET,
    "show data": RoutingType.DATASET,
    "get data": RoutingType.DATASET,
    "dataset": RoutingType.DATASET,
    # ── Tool call / Product comparison ───────────────────────────────────
    "compare": RoutingType.TOOL_CALL,
    "comparison": RoutingType.TOOL_CALL,
    "difference between": RoutingType.TOOL_CALL,
    "differences between": RoutingType.TOOL_CALL,
    "differ from": RoutingType.TOOL_CALL,
    " vs ": RoutingType.TOOL_CALL,
    "versus": RoutingType.TOOL_CALL,
    "side by side": RoutingType.TOOL_CALL,
    "head to head": RoutingType.TOOL_CALL,
    "which is better": RoutingType.TOOL_CALL,
    "which one is better": RoutingType.TOOL_CALL,
    "pros and cons": RoutingType.TOOL_CALL,
    "how does it differ": RoutingType.TOOL_CALL,
    "what sets apart": RoutingType.TOOL_CALL,
    "what's the difference": RoutingType.TOOL_CALL,
    "what is the difference": RoutingType.TOOL_CALL,
    # ── Graph / PageIndex ────────────────────────────────────────────────
    "graph": RoutingType.GRAPH_PAGEINDEX,
    "ontology": RoutingType.GRAPH_PAGEINDEX,
    "relationships": RoutingType.GRAPH_PAGEINDEX,
    # FAQ / company / policy / info queries — best served by PageIndex
    "faq": RoutingType.GRAPH_PAGEINDEX,
    "frequently asked": RoutingType.GRAPH_PAGEINDEX,
    "installation": RoutingType.GRAPH_PAGEINDEX,
    "how to install": RoutingType.GRAPH_PAGEINDEX,
    "delivery": RoutingType.GRAPH_PAGEINDEX,
    "shipping": RoutingType.GRAPH_PAGEINDEX,
    "warranty": RoutingType.GRAPH_PAGEINDEX,
    "guarantee": RoutingType.GRAPH_PAGEINDEX,
    "return policy": RoutingType.GRAPH_PAGEINDEX,
    "refund": RoutingType.GRAPH_PAGEINDEX,
    "company info": RoutingType.GRAPH_PAGEINDEX,
    "about us": RoutingType.GRAPH_PAGEINDEX,
    "about the company": RoutingType.GRAPH_PAGEINDEX,
    "contact": RoutingType.GRAPH_PAGEINDEX,
    "opening hours": RoutingType.GRAPH_PAGEINDEX,
    "payment method": RoutingType.GRAPH_PAGEINDEX,
    "payment options": RoutingType.GRAPH_PAGEINDEX,
    "terms and conditions": RoutingType.GRAPH_PAGEINDEX,
    "privacy policy": RoutingType.GRAPH_PAGEINDEX,
}

# Strategy display labels used in exhaustive mode synthesis context.
_STRATEGY_LABELS: dict[RoutingType, str] = {
    RoutingType.GRAPH_PAGEINDEX: "Graph context",
    RoutingType.DATASET: "Dataset context",
    RoutingType.VECTOR_SEARCH: "Vector search context",
    RoutingType.TOOL_CALL: "Tool result",
    RoutingType.FREE_LLM: "LLM context",
    RoutingType.MULTI_HOP: "Multi-hop context",
}


class IntentRouterMixin:
    """Mixin that adds intent-based routing to any Bot or Agent.

    Must be placed before the concrete bot class in the MRO::

        class MyAgent(IntentRouterMixin, BasicAgent): ...

    The mixin's ``conversation()`` intercepts calls when active and routes
    through strategy discovery → candidate retrieval → decision → execution.

    When inactive (``configure_router()`` not called), the mixin is a
    zero-overhead no-op pass-through.
    """

    _router_active: bool = False
    _router_config: Optional[IntentRouterConfig] = None
    _capability_registry: Optional[CapabilityRegistry] = None

    def __init__(self, **kwargs: Any) -> None:
        """Cooperative __init__ for MRO compatibility.

        Args:
            **kwargs: Passed to the next class in MRO.
        """
        self._router_active = False
        self._router_config = None
        self._capability_registry = None
        # FEAT-224: output-mode router (separate, optional second concern).
        self._output_router: Optional[EmbeddingIntentRouter] = None
        super().__init__(**kwargs)  # type: ignore[call-arg]

    # ── Public API ────────────────────────────────────────────────────────────

    def configure_router(
        self,
        config: IntentRouterConfig,
        registry: CapabilityRegistry,
    ) -> None:
        """Activate the intent router with the given config and registry.

        Args:
            config: Router configuration (thresholds, timeouts, mode).
            registry: The capability registry for candidate retrieval.
        """
        self._router_config = config
        self._capability_registry = registry
        self._router_active = True
        logger = getattr(self, "logger", logging.getLogger(__name__))
        logger.info("Intent router configured and active.")

    # ── FEAT-224: output-mode routing (CONFIGURE + REQUEST) ────────────────────

    def configure_output_router(self, config: IntentRouterConfig) -> None:
        """Build the deterministic output-mode router once (CONFIGURE phase).

        Loads the embedding encoder and encodes the phrase bank exactly once.
        A no-op unless ``config.enable_output_mode_routing`` is True, so existing
        retrieval-routing configs are unaffected.

        Args:
            config: Router configuration carrying the output-mode fields
                (``embedding_model``, ``output_mode_routes``,
                ``output_mode_threshold``, ``discrepancy_margin``).
        """
        logger = getattr(self, "logger", logging.getLogger(__name__))
        if not config.enable_output_mode_routing:
            return
        router = EmbeddingIntentRouter(
            config.embedding_model,
            config.output_mode_threshold,
            config.discrepancy_margin,
        )
        for mode_value, utterances in config.output_mode_routes.items():
            try:
                router.add_route(OutputMode(mode_value), utterances)
            except ValueError:
                logger.warning(
                    "Unknown OutputMode in output_mode_routes: %s", mode_value
                )
        self._output_router = router
        logger.info(
            "Output-mode router configured (%d routes, threshold=%.2f).",
            len(config.output_mode_routes),
            config.output_mode_threshold,
        )

    async def _resolve_output_mode(
        self,
        query: str,
        ctx: Any,
    ) -> "Optional[OutputMode]":
        """Resolve an OutputMode for ``query`` (REQUEST phase, FEAT-224).

        Threshold + margin policy:
          * no router / abstain (best < threshold) -> chain ``super()``.
          * clear winner -> the embedding mode (no LLM call).
          * ambiguous (best >= threshold and gap < margin) -> bounded LLM
            tie-breaker among the close candidates; fall back to the embedding
            winner if the LLM is unavailable / invalid.

        Mirrors the resolved mode's score onto ``ctx.intent_score``; the base
        call site mirrors ``ctx.output_mode``. The blocking ``route()`` runs off
        the event loop via :func:`asyncio.to_thread`.
        """
        router = getattr(self, "_output_router", None)
        if router is None:
            return await super()._resolve_output_mode(query, ctx)  # type: ignore[misc]

        rs: RouteScore = await asyncio.to_thread(router.route, query)
        if rs.mode is None:
            # Below threshold -> abstain, cooperate with the rest of the MRO.
            return await super()._resolve_output_mode(query, ctx)  # type: ignore[misc]

        chosen = rs.mode
        if rs.ambiguous:
            # Assemble the close-candidate set off the event loop (re-uses the
            # warm encoder); only modes within ``margin`` of the winner.
            scores = await asyncio.to_thread(router.route_scores, query)
            candidates = [
                m for m, sc in scores if (rs.score - sc) < router.margin
            ]
            llm_choice = await self._llm_disambiguate_output_mode(query, candidates)
            if llm_choice is not None:
                chosen = llm_choice

        if ctx is not None:
            ctx.intent_score = rs.score
        return chosen

    async def _llm_disambiguate_output_mode(
        self,
        query: str,
        candidates: "list[OutputMode]",
    ) -> "Optional[OutputMode]":
        """Bounded LLM tie-breaker over the close candidate modes (FEAT-224).

        Consulted ONLY on genuine ambiguity. Uses ``self.invoke()`` (FEAT-069)
        and abstains (returns ``None``) when invoke is unavailable, times out, or
        returns a value that is not one of the close candidates.

        Args:
            query: The user query.
            candidates: The close candidate modes (winner + any within margin).

        Returns:
            A candidate :class:`OutputMode`, or ``None`` to abstain to the
            embedding winner.
        """
        invoke = getattr(self, "invoke", None)
        if invoke is None or not candidates:
            return None

        logger = getattr(self, "logger", logging.getLogger(__name__))
        candidate_values = [m.value for m in candidates]
        prompt = (
            "You pick the single best OUTPUT MODE for rendering an answer.\n"
            f"User query: {query}\n"
            f"Candidate output modes: {', '.join(candidate_values)}\n"
            'Respond with JSON only: {"output_mode": "<one of the candidates>"}'
        )
        timeout = (
            getattr(self._router_config, "strategy_timeout_s", 30.0)
            if self._router_config is not None
            else 30.0
        )
        try:
            raw = await asyncio.wait_for(invoke(prompt), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Output-mode LLM tie-breaker timed out; abstaining.")
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Output-mode LLM tie-breaker failed: %s", exc)
            return None

        parsed = extract_json_from_response(raw)
        if not parsed:
            return None
        try:
            mode = OutputMode(parsed.get("output_mode"))
        except ValueError:
            return None
        # Only accept a value that is one of the close candidates.
        return mode if mode in candidates else None

    async def conversation(self, prompt: str, **kwargs: Any) -> Any:
        """Intercept conversation to route via intent router when active.

        When ``_router_active`` is False, delegates directly to
        ``super().conversation()`` with no overhead.

        Args:
            prompt: The user's question or message.
            **kwargs: Forwarded to ``super().conversation()``.

        Returns:
            AIMessage from the base conversation method.
        """
        if not self._router_active:
            return await super().conversation(prompt, **kwargs)  # type: ignore[misc]

        context, decision, trace = await self._route(prompt)

        # HITL: return clarifying question directly as a plain string response.
        if decision and decision.routing_type == RoutingType.HITL:
            return self._build_hitl_question(prompt, decision.candidates)

        # Inject routing artefacts as kwargs for AbstractBot to consume.
        if context:
            kwargs["injected_context"] = context
        if decision:
            kwargs["routing_decision"] = decision
        if trace:
            kwargs["routing_trace"] = trace

        return await super().conversation(prompt, **kwargs)  # type: ignore[misc]

    # ── Core Routing ──────────────────────────────────────────────────────────

    async def _route(
        self, prompt: str
    ) -> tuple[Optional[str], Optional[RoutingDecision], Optional[RoutingTrace]]:
        """Main routing logic: discover → candidate search → decide → execute.

        Returns:
            Tuple of (context_string, RoutingDecision, RoutingTrace).
            Any element may be None if not applicable.
        """
        start = time.monotonic()
        trace = RoutingTrace(mode="exhaustive" if self._router_config.exhaustive_mode else "normal")

        strategies = self._discover_strategies(prompt)
        if not strategies:
            trace.elapsed_ms = (time.monotonic() - start) * 1000
            return None, None, trace

        # Retrieve registry candidates
        candidates: list[RouterCandidate] = []
        if self._capability_registry:
            try:
                candidates = await self._capability_registry.search(
                    prompt, top_k=self._router_config.max_cascades + 2
                )
            except Exception as exc:  # noqa: BLE001
                _logger = getattr(self, "logger", logging.getLogger(__name__))
                _logger.warning("Registry search failed: %s", exc)

        # Try fast path first (keyword scan)
        decision = self._fast_path(prompt, strategies, candidates)

        # Fall back to LLM path via invoke()
        if not decision:
            decision = await self._llm_route(prompt, strategies, candidates)

        if not decision:
            # No decision available — use FREE_LLM directly
            decision = RoutingDecision(
                routing_type=RoutingType.FREE_LLM,
                confidence=0.5,
                reasoning="No routing decision available; falling back to FREE_LLM.",
            )

        # HITL check: low confidence → return clarifying question
        if decision.confidence < self._router_config.hitl_threshold:
            decision = RoutingDecision(
                routing_type=RoutingType.HITL,
                confidence=decision.confidence,
                reasoning=decision.reasoning,
                candidates=decision.candidates,
                cascades=decision.cascades,
            )
            trace.elapsed_ms = (time.monotonic() - start) * 1000
            return None, decision, trace

        # Execute strategy (exhaustive or cascade)
        if self._router_config.exhaustive_mode:
            context, trace = await self._execute_exhaustive(strategies, prompt, candidates)
        else:
            context, trace = await self._execute_with_cascade(decision, prompt)

        trace.elapsed_ms = (time.monotonic() - start) * 1000

        # No strategy produced context → use fallback prompt
        if not context and self._router_config.confidence_threshold > 0:
            context = await self._build_fallback_prompt(prompt, trace)
            decision = RoutingDecision(
                routing_type=RoutingType.FALLBACK,
                confidence=decision.confidence,
                reasoning="All strategies exhausted; using LLM fallback with trace context.",
            )

        return context, decision, trace

    # ── Strategy Discovery ────────────────────────────────────────────────────

    def _discover_strategies(self, prompt: str) -> list[RoutingType]:  # noqa: ARG002
        """Auto-detect available routing strategies from agent configuration.

        Inspects the agent's attributes to determine which strategies are
        available without requiring explicit configuration.

        Args:
            prompt: The user prompt (unused — reserved for future context).

        Returns:
            List of available RoutingType values.
        """
        available: set[RoutingType] = set()

        # Graph / PageIndex
        if getattr(self, "_ont_graph_store", None) or getattr(self, "graph_store", None):
            available.add(RoutingType.GRAPH_PAGEINDEX)
        if getattr(self, "_pageindex_retriever", None) or getattr(
            self, "pageindex_retriever", None
        ):
            available.add(RoutingType.GRAPH_PAGEINDEX)

        # Vector search
        if getattr(self, "_vector_store", None) or getattr(self, "vector_store", None):
            available.add(RoutingType.VECTOR_SEARCH)
        if getattr(self, "_use_vector", False):
            available.add(RoutingType.VECTOR_SEARCH)

        # Dataset
        if getattr(self, "dataset_manager", None):
            available.add(RoutingType.DATASET)

        # Tool call
        tool_manager = getattr(self, "tool_manager", None)
        if tool_manager is not None:
            try:
                if tool_manager.tool_count() > 0:
                    available.add(RoutingType.TOOL_CALL)
            except Exception:  # noqa: BLE001
                pass
        if getattr(self, "tools", None):
            available.add(RoutingType.TOOL_CALL)

        # Always available
        available.add(RoutingType.FREE_LLM)
        if self._router_config and self._router_config.exhaustive_mode is False:
            available.add(RoutingType.FALLBACK)
        else:
            available.add(RoutingType.FALLBACK)
        if self._router_config and getattr(self._router_config, "hitl_threshold", None) is not None:
            available.add(RoutingType.HITL)

        return list(available)

    # ── Fast Path ─────────────────────────────────────────────────────────────

    def _fast_path(
        self,
        prompt: str,
        strategies: list[RoutingType],
        candidates: list[RouterCandidate],  # noqa: ARG002
    ) -> Optional[RoutingDecision]:
        """Keyword-based fast routing (no LLM call, ~0ms).

        Merges the built-in ``_KEYWORD_STRATEGY_MAP`` with any
        ``custom_keywords`` from the router config.  Custom keywords take
        precedence over built-in ones.

        Args:
            prompt: The user query.
            strategies: Available strategies from _discover_strategies().
            candidates: Registry candidates (unused in fast path).

        Returns:
            RoutingDecision if a keyword matched, None otherwise.
        """
        # Build the effective keyword map (custom overrides built-in)
        effective_map: dict[str, RoutingType] = dict(_KEYWORD_STRATEGY_MAP)
        if self._router_config and self._router_config.custom_keywords:
            for kw, rt_value in self._router_config.custom_keywords.items():
                try:
                    effective_map[kw.lower()] = RoutingType(rt_value)
                except ValueError:
                    pass  # skip invalid RoutingType values

        prompt_lower = prompt.lower()
        for keyword, routing_type in effective_map.items():
            if keyword in prompt_lower and routing_type in strategies:
                return RoutingDecision(
                    routing_type=routing_type,
                    confidence=0.95,
                    reasoning=f"Fast path: keyword '{keyword}' matched.",
                )
        return None

    # ── LLM Path ──────────────────────────────────────────────────────────────

    async def _llm_route(
        self,
        prompt: str,
        strategies: list[RoutingType],
        candidates: list[RouterCandidate],
    ) -> Optional[RoutingDecision]:
        """LLM-based routing via ``self.invoke()`` (FEAT-069).

        Builds a structured prompt with available strategies and registry
        candidates, then calls ``invoke()`` to get a ``RoutingDecision``.

        Falls back to FREE_LLM if ``invoke()`` is not available or raises.

        Args:
            prompt: The user query.
            strategies: Available strategies.
            candidates: Registry candidates with similarity scores.

        Returns:
            RoutingDecision from LLM, or None if unavailable.
        """
        invoke = getattr(self, "invoke", None)
        if invoke is None:
            return None

        strategy_names = ", ".join(s.value for s in strategies)
        candidate_info = ""
        if candidates:
            lines = [
                f"  - {c.entry.name} ({c.entry.resource_type.value}, score={c.score:.2f}): "
                f"{c.entry.description[:80]}"
                for c in candidates[:5]
            ]
            candidate_info = "\n" + "\n".join(lines)

        routing_prompt = (
            f"You are an intent router. Given the user query and available strategies, "
            f"select the best routing strategy.\n\n"
            f"User query: {prompt}\n\n"
            f"Available strategies: {strategy_names}\n"
            f"Registry candidates:{candidate_info if candidate_info else ' (none)'}\n\n"
            f"Respond with JSON: "
            f'{{\"routing_type\": \"<strategy>\", \"confidence\": <0.0-1.0>, '
            f'\"reasoning\": \"<brief explanation>\", '
            f'\"cascades\": [\"<fallback1>\", \"<fallback2>\"]}}'
        )

        try:
            raw_response = await asyncio.wait_for(
                invoke(routing_prompt),
                timeout=self._router_config.strategy_timeout_s,
            )
            # Parse the LLM response into a RoutingDecision
            return self._parse_invoke_response(raw_response, strategies)
        except asyncio.TimeoutError:
            _logger = getattr(self, "logger", logging.getLogger(__name__))
            _logger.warning("LLM routing path timed out")
        except Exception as exc:  # noqa: BLE001
            _logger = getattr(self, "logger", logging.getLogger(__name__))
            _logger.warning("LLM routing path failed: %s", exc)

        return None

    def _parse_invoke_response(
        self,
        response: Any,
        available_strategies: list[RoutingType],
    ) -> Optional[RoutingDecision]:
        """Parse the invoke() response into a RoutingDecision.

        JSON extraction is delegated to
        :func:`parrot.registry.routing.llm_helper.extract_json_from_response`
        (introduced by FEAT-111 / TASK-787).  Enum-validation and
        ``RoutingDecision`` assembly remain here.

        Args:
            response: Raw response from invoke() (AIMessage or similar).
            available_strategies: Strategies to validate against.

        Returns:
            RoutingDecision or None if parsing fails.
        """
        try:
            parsed = extract_json_from_response(response)
            if parsed is None:
                return None

            routing_type_str = parsed.get("routing_type", "free_llm")
            try:
                routing_type = RoutingType(routing_type_str)
            except ValueError:
                routing_type = RoutingType.FREE_LLM

            if routing_type not in available_strategies:
                routing_type = RoutingType.FREE_LLM

            cascades: list[RoutingType] = []
            for c in parsed.get("cascades", []):
                try:
                    cascade_type = RoutingType(c)
                    if cascade_type in available_strategies:
                        cascades.append(cascade_type)
                except ValueError:
                    pass

            return RoutingDecision(
                routing_type=routing_type,
                confidence=float(parsed.get("confidence", 0.5)),
                reasoning=str(parsed.get("reasoning", "")),
                cascades=cascades,
            )
        except Exception:  # noqa: BLE001
            return None

    # ── Strategy Execution ────────────────────────────────────────────────────

    async def _execute_with_cascade(
        self,
        decision: RoutingDecision,
        prompt: str,
    ) -> tuple[Optional[str], RoutingTrace]:
        """Execute primary strategy, then cascades until context is produced.

        Args:
            decision: The routing decision with primary + cascades.
            prompt: The user query.

        Returns:
            Tuple of (context, RoutingTrace).
        """
        trace = RoutingTrace(mode="normal")
        candidates = getattr(decision, "candidates", [])

        all_strategies = [decision.routing_type] + list(decision.cascades)
        max_steps = 1 + min(len(decision.cascades), self._router_config.max_cascades)

        for strategy in all_strategies[:max_steps]:
            context = await self._execute_strategy(strategy, prompt, candidates)
            produced = bool(context)
            trace.entries.append(
                TraceEntry(
                    routing_type=strategy,
                    produced_context=produced,
                    context_snippet=context[:200] if context else None,
                    elapsed_ms=0.0,
                )
            )
            if produced:
                return context, trace

        return None, trace

    async def _execute_exhaustive(
        self,
        strategies: list[RoutingType],
        prompt: str,
        candidates: list[RouterCandidate],
    ) -> tuple[str, RoutingTrace]:
        """Run all strategies and concatenate non-empty results with labels.

        Args:
            strategies: All available strategies to run.
            prompt: The user query.
            candidates: Registry candidates for context.

        Returns:
            Tuple of (concatenated_context, RoutingTrace).
        """
        trace = RoutingTrace(mode="exhaustive")
        parts: list[str] = []

        # Exclude meta-strategies from exhaustive execution
        exec_strategies = [
            s
            for s in strategies
            if s not in (RoutingType.HITL, RoutingType.FALLBACK)
        ]

        for strategy in exec_strategies:
            entry_start = time.monotonic()
            try:
                context = await asyncio.wait_for(
                    self._execute_strategy(strategy, prompt, candidates),
                    timeout=self._router_config.strategy_timeout_s,
                )
            except asyncio.TimeoutError:
                context = None
            except Exception as exc:  # noqa: BLE001
                _logger = getattr(self, "logger", logging.getLogger(__name__))
                _logger.warning("Strategy %s failed: %s", strategy.value, exc)
                context = None
            elapsed = (time.monotonic() - entry_start) * 1000
            produced = bool(context)

            trace.entries.append(
                TraceEntry(
                    routing_type=strategy,
                    produced_context=produced,
                    context_snippet=context[:200] if context else None,
                    elapsed_ms=elapsed,
                )
            )

            if produced and context:
                label = _STRATEGY_LABELS.get(strategy, strategy.value.replace("_", " ").title())
                parts.append(f"### {label}\n{context}")

        return "\n\n".join(parts), trace

    async def _execute_strategy(
        self,
        strategy: RoutingType,
        prompt: str,
        candidates: list[RouterCandidate],
    ) -> Optional[str]:
        """Dispatch to the appropriate strategy runner with timeout.

        Args:
            strategy: The routing strategy to execute.
            prompt: The user query.
            candidates: Registry candidates for context.

        Returns:
            Context string produced by the strategy, or None.
        """
        runner_map: dict[RoutingType, Any] = {
            RoutingType.GRAPH_PAGEINDEX: self._run_graph_pageindex,
            RoutingType.DATASET: self._run_dataset_query,
            RoutingType.VECTOR_SEARCH: self._run_vector_search,
            RoutingType.TOOL_CALL: self._run_tool_call,
            RoutingType.FREE_LLM: self._run_free_llm,
            RoutingType.MULTI_HOP: self._run_multi_hop,
        }
        runner = runner_map.get(strategy)
        if runner is None:
            return None

        try:
            return await asyncio.wait_for(
                runner(prompt, candidates),
                timeout=self._router_config.strategy_timeout_s,
            )
        except asyncio.TimeoutError:
            _logger = getattr(self, "logger", logging.getLogger(__name__))
            _logger.warning("Strategy %s timed out", strategy.value)
            return None
        except Exception as exc:  # noqa: BLE001
            _logger = getattr(self, "logger", logging.getLogger(__name__))
            _logger.warning("Strategy %s error: %s", strategy.value, exc)
            return None

    # ── Strategy Runners ──────────────────────────────────────────────────────

    async def _run_graph_pageindex(
        self,
        prompt: str,
        candidates: list[RouterCandidate],  # noqa: ARG002
    ) -> Optional[str]:
        """Run graph / pageindex strategy.

        Uses OntologyRAGMixin.ontology_process() when available, or queries
        graph_store / _ont_graph_store directly.

        When ``ontology_process`` returns a ``ContextEnvelope`` the response
        is branched on ``envelope.state``:

        - ``"ok"`` with populated ``context.graph_context`` or
          ``context.vector_context`` → format with provenance and return.
        - ``"ok"`` with empty/None context → fall back to unscoped PageIndex
          retriever (if available).
        - ``"ambiguous"``, ``"denied"``, ``"entity_not_found"``,
          ``"auth_required"``, ``"render_error"``, ``"tool_failed"`` →
          format the state information and return (do NOT call PageIndex).
        - ``"disabled"`` / ``"not_configured"`` → continue to direct graph /
          PageIndex fallback paths below.
        - Anything that is not a ``ContextEnvelope`` (legacy behaviour) →
          ``str(result)`` fallback.

        Args:
            prompt: The user query.
            candidates: Registry candidates (unused — graph uses query directly).

        Returns:
            Context string from graph traversal, or None.
        """
        _logger = getattr(self, "logger", logging.getLogger(__name__))

        # Try OntologyRAGMixin integration
        ontology_process = getattr(self, "ontology_process", None)
        if ontology_process:
            perm_ctx = (
                self._get_permission_context()
                if hasattr(self, "_get_permission_context")
                else {}
            )
            tenant_id = getattr(self, "_tenant_id", "default")
            try:
                result = await ontology_process(
                    prompt, user_context=perm_ctx, tenant_id=tenant_id,
                )

                # --- ContextEnvelope branch logic (FEAT-159) ---
                if _CONTEXT_ENVELOPE_AVAILABLE and isinstance(result, ContextEnvelope):
                    envelope: ContextEnvelope = result

                    if envelope.state == "ok":
                        ctx = envelope.context
                        has_graph = bool(ctx is not None and ctx.graph_context)
                        has_vector = bool(ctx is not None and ctx.vector_context)
                        # tool_result is populated when a tool_call post-action
                        # succeeded; even if graph/vector context is empty the
                        # tool result is meaningful and must not be discarded.
                        has_tool = bool(envelope.tool_result)

                        if has_graph or has_vector or has_tool:
                            # Format with provenance label
                            return self._format_envelope_context(envelope)

                        # Context is empty / None → fall through to unscoped PageIndex
                        _logger.debug(
                            "ontology_process ok but empty context; falling back to PageIndex"
                        )

                    elif envelope.state in ("disabled", "not_configured"):
                        # Silently fall through to the non-ontology paths below
                        pass

                    else:
                        # Non-ok, non-disabled state (ambiguous, denied, auth_required, …)
                        # → format and return without calling PageIndex
                        return self._format_non_ok_envelope(envelope)

                elif result:
                    # Legacy: ontology_process returned something non-envelope
                    return str(result)

            except Exception as exc:  # noqa: BLE001
                _logger.warning("ontology_process failed: %s", exc)

        # Try direct graph store query
        for attr in ("_ont_graph_store", "graph_store"):
            store = getattr(self, attr, None)
            if store:
                query_fn = getattr(store, "query", None)
                if query_fn:
                    try:
                        result = await query_fn(prompt)
                        if result:
                            return str(result)
                    except Exception:  # noqa: BLE001
                        pass

        # Try PageIndexRetriever (lazy import)
        retriever = getattr(self, "_pageindex_retriever", None) or getattr(
            self, "pageindex_retriever", None
        )
        if retriever:
            try:
                result = await retriever.retrieve(prompt)
                if result:
                    return str(result)
            except Exception:  # noqa: BLE001
                pass

        return None

    def _format_envelope_context(self, envelope: "ContextEnvelope") -> str:
        """Format the enriched context from a ``state="ok"`` ContextEnvelope.

        Includes a provenance prefix derived from ``context.source`` so that
        downstream LLM prompts can reason about *where* the context came from.

        Args:
            envelope: A ContextEnvelope in ``state="ok"`` with non-empty context.

        Returns:
            Formatted context string including the provenance label.
        """
        ctx = envelope.context
        if ctx is None:
            return ""

        parts: list[str] = []
        source_label = ctx.source or "ontology"
        parts.append(f"[Source: {source_label}]")

        if ctx.graph_context:
            parts.append("Graph context:")
            for item in ctx.graph_context[:10]:  # cap at 10 items
                parts.append(f"  {item}")

        if ctx.vector_context:
            parts.append("Vector context:")
            for item in ctx.vector_context[:10]:
                parts.append(f"  {item}")

        if ctx.tool_hint:
            parts.append(f"Tool hint: {ctx.tool_hint}")

        if envelope.tool_result:
            parts.append(f"Tool result: {envelope.tool_result}")

        return "\n".join(parts)

    @staticmethod
    def _format_non_ok_envelope(envelope: "ContextEnvelope") -> str:
        """Format a non-ok ContextEnvelope into a human-readable string.

        Used so that the chat layer can surface actionable messages for
        ambiguous, denied, or auth-required states.

        Args:
            envelope: A ContextEnvelope in a non-ok state.

        Returns:
            Formatted string describing the pipeline state.
        """
        state = envelope.state

        if state == "ambiguous":
            cl = envelope.clarification or {}
            mention = cl.get("mention", "")
            candidates = cl.get("candidates", [])
            cand_names = [c.get("name", str(c)) for c in candidates[:5]]
            return (
                f"Ambiguous reference '{mention}'. "
                f"Did you mean: {', '.join(cand_names)}?"
            )

        if state == "denied":
            reason = envelope.denial_reason or "Access denied."
            return f"Access denied: {reason}"

        if state == "entity_not_found":
            return envelope.error or "Entity not found."

        if state == "auth_required":
            ap = envelope.auth_prompt or {}
            provider = ap.get("provider", "unknown provider")
            auth_url = ap.get("auth_url", "")
            return (
                f"Authorization required for {provider}. "
                f"Please authenticate at: {auth_url}"
            )

        if state in ("render_error", "tool_failed"):
            return envelope.error or f"Pipeline error: {state}"

        # Catch-all for any unexpected non-ok states
        return f"Pipeline returned state: {state}"

    async def _run_dataset_query(
        self,
        prompt: str,
        candidates: list[RouterCandidate],  # noqa: ARG002
    ) -> Optional[str]:
        """Run dataset strategy via DatasetManager.

        Args:
            prompt: The user query.
            candidates: Registry candidates (unused — dataset uses query directly).

        Returns:
            Context string from dataset query, or None.
        """
        dm = getattr(self, "dataset_manager", None)
        if not dm:
            return None
        try:
            result = await dm.query(prompt)
            if result:
                return str(result)
        except AttributeError:
            pass
        except Exception as exc:  # noqa: BLE001
            _logger = getattr(self, "logger", logging.getLogger(__name__))
            _logger.debug("Dataset query failed: %s", exc)
        return None

    async def _run_vector_search(
        self,
        prompt: str,
        candidates: list[RouterCandidate],  # noqa: ARG002
    ) -> Optional[str]:
        """Run vector search strategy.

        Delegates to ``_build_vector_context()`` if available, or queries
        the vector store directly.

        Args:
            prompt: The user query.
            candidates: Registry candidates (unused).

        Returns:
            Context string from vector search, or None.
        """
        build_vector = getattr(self, "_build_vector_context", None)
        if build_vector:
            try:
                context, _ = await build_vector(prompt, use_vectors=True)
                if context:
                    return context
            except Exception:  # noqa: BLE001
                pass

        for attr in ("_vector_store", "vector_store"):
            store = getattr(self, attr, None)
            if store:
                search_fn = getattr(store, "search", None)
                if search_fn:
                    try:
                        results = await search_fn(prompt)
                        if results:
                            return "\n".join(
                                r.get("content", str(r)) if isinstance(r, dict) else str(r)
                                for r in results
                            )
                    except Exception:  # noqa: BLE001
                        pass
        return None

    async def _run_tool_call(
        self,
        prompt: str,
        candidates: list[RouterCandidate],  # noqa: ARG002
    ) -> Optional[str]:
        """Run tool call strategy.

        When a PageIndex retriever is available, retrieves contextual
        information first so the LLM has supporting knowledge before
        deciding which tool (if any) to invoke.  This prevents the LLM
        from calling product-lookup tools for non-product queries (e.g.
        "installation process").

        Args:
            prompt: The user query.
            candidates: Registry candidates (unused).

        Returns:
            Context string from PageIndex (if available), or None.
        """
        tool_manager = getattr(self, "tool_manager", None)
        if tool_manager is None:
            tools = getattr(self, "tools", None)
            if not tools:
                return None

        # Enrich the tool-call path with PageIndex context so the LLM can
        # answer informational queries without misusing product tools.
        retriever = getattr(self, "_pageindex_retriever", None) or getattr(
            self, "pageindex_retriever", None
        )
        if retriever:
            try:
                context = await retriever.retrieve(prompt)
                if context:
                    return context
            except Exception:  # noqa: BLE001
                pass

        return None

    async def _run_free_llm(
        self,
        prompt: str,  # noqa: ARG002
        candidates: list[RouterCandidate],  # noqa: ARG002
    ) -> Optional[str]:
        """Run free LLM strategy (no context injection).

        This strategy returns None so the base conversation() runs without
        any injected_context, allowing the LLM to answer from its training data.

        Args:
            prompt: The user query (unused).
            candidates: Registry candidates (unused).

        Returns:
            Always None — the base bot handles this natively.
        """
        return None

    async def _run_multi_hop(
        self,
        prompt: str,
        candidates: list[RouterCandidate],
    ) -> Optional[str]:
        """Run multi-hop strategy: chain graph + vector search concurrently.

        Args:
            prompt: The user query.
            candidates: Registry candidates.

        Returns:
            Concatenated context from both strategies, or None.
        """
        results = await asyncio.gather(
            self._run_graph_pageindex(prompt, candidates),
            self._run_vector_search(prompt, candidates),
            return_exceptions=True,
        )
        parts = [r for r in results if isinstance(r, str) and r]
        return "\n\n".join(parts) if parts else None

    # ── Fallback / HITL ───────────────────────────────────────────────────────

    async def _build_fallback_prompt(
        self,
        prompt: str,
        trace: RoutingTrace,
    ) -> str:
        """Build an enriched prompt for the LLM fallback strategy.

        Includes a summary of what was tried and failed so the LLM can
        provide a contextually aware answer from its training data.

        Args:
            prompt: The original user query.
            trace: Routing trace recording all attempted strategies.

        Returns:
            Enriched prompt string for the fallback LLM call.
        """
        tried = ", ".join(
            e.routing_type.value
            for e in trace.entries
            if not e.produced_context
        )
        if tried:
            summary = (
                f"[Routing note: The following strategies were tried but produced no results: "
                f"{tried}. Please answer from general knowledge.]\n\n"
            )
        else:
            summary = ""
        return f"{summary}{prompt}"

    def _build_hitl_question(
        self,
        prompt: str,
        candidates: list[RouterCandidate],
    ) -> str:
        """Build a clarifying question as a normal response.

        No agent suspension — the clarification is returned as a plain
        response. The user's reply continues naturally via conversation history.

        Args:
            prompt: The original user query.
            candidates: Top registry candidates (used for options hint).

        Returns:
            Clarifying question string.
        """
        if candidates:
            options = ", ".join(
                f"'{c.entry.name}'" for c in candidates[:3]
            )
            return (
                f"I need a bit more context to answer your question accurately. "
                f"Your query '{prompt}' could refer to: {options}. "
                f"Could you clarify which one you mean, or provide more details?"
            )
        return (
            f"I need a bit more context to answer '{prompt}' accurately. "
            f"Could you provide more details about what you're looking for?"
        )
