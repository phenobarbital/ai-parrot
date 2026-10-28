"""Suggestion engine: lane gating, guards, dedupe and caps (FEAT-752)."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from navconfig.logging import logging

from parrot.models.outputs import OutputMode
from parrot.models.suggestions import Suggestion, SuggestionSource
from parrot.outputs.formats import get_renderer

from .protocol import LANES, SuggestionContext, SuggestionProvider


def renderer_available(mode: "OutputMode | str | None") -> bool:
    """True when ``mode`` is None or ``get_renderer(OutputMode(mode))`` succeeds."""
    if mode is None:
        return True
    try:
        get_renderer(OutputMode(mode))
    except ValueError:
        return False
    return True


class SuggestionEngine:
    """Runs providers lane by lane; never raises; returns ``(suggestions, metadata)``."""

    def __init__(
        self,
        *,
        max_suggestions: int = 6,
        max_llm_suggestions: int = 4,
        timeout_s: float = 4.0,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """Caps and per-provider timeout. ``timeout_s`` applies to every provider, not only the LLM lane."""
        self.max_suggestions = max_suggestions
        self.max_llm_suggestions = max_llm_suggestions
        self.timeout_s = timeout_s
        self.logger = logger or logging.getLogger(__name__)
        self._providers: list[SuggestionProvider] = []

    def register(self, provider: SuggestionProvider, *, prepend: bool = False) -> None:
        """Append (or prepend) a provider; a duplicate ``name`` replaces the previous registration."""
        self._providers = [p for p in self._providers if p.name != provider.name]
        if prepend:
            self._providers.insert(0, provider)
        else:
            self._providers.append(provider)

    @property
    def providers(self) -> tuple[SuggestionProvider, ...]:
        """Registration order sorted by lane (skill, deterministic, llm); stable within a lane."""
        return tuple(sorted(self._providers, key=lambda p: LANES.index(p.lane)))

    async def collect(
        self, ctx: SuggestionContext, *, lanes: frozenset[str]
    ) -> tuple[list[Suggestion], dict[str, Any]]:
        """Run providers whose lane is in ``lanes``; guard, post-process and account. Never raises."""
        meta: dict[str, Any] = {
            "enabled_lanes": [lane for lane in LANES if lane in lanes],
            "count": 0,
            "providers": {},
            "llm": None,
        }
        collected: list[Suggestion] = []
        try:
            for provider in self.providers:
                if provider.lane not in lanes:
                    meta["providers"][provider.name] = {"status": "skipped", "count": 0, "elapsed_ms": 0.0}
                    continue
                chips, status, elapsed_ms = await self._run_provider(provider, ctx)
                meta["providers"][provider.name] = {"status": status, "count": len(chips), "elapsed_ms": elapsed_ms}
                collected.extend(chips)
                if status == "ok" and provider.lane == "llm" and meta["llm"] is None:
                    meta["llm"] = self._provider_cost(provider, ctx)
            collected = self._post_process(collected)
        except Exception as exc:  # defensive: collect must never raise
            self.logger.warning("Suggestion engine failed: %s", exc)
            collected = []
        meta["count"] = len(collected)
        return collected, meta

    @staticmethod
    def _provider_cost(provider: SuggestionProvider, ctx: SuggestionContext) -> Optional[dict[str, Any]]:
        """Cost record of the call that just ran for ``ctx``.

        A provider that declares ``per_call_cost = True`` reports it through ``ctx.scratch["llm_cost"]`` (safe under
        concurrency: one context per turn). Other providers fall back to the ``last_cost`` attribute, which is
        instance state shared by every request on the bot and can therefore race.
        """
        if getattr(provider, "per_call_cost", False):
            return ctx.scratch.get("llm_cost")
        return getattr(provider, "last_cost", None)

    async def _run_provider(
        self, provider: SuggestionProvider, ctx: SuggestionContext
    ) -> tuple[list[Suggestion], str, float]:
        """Run one provider under the timeout; return ``(chips, status, elapsed_ms)`` and never raise."""
        started = time.perf_counter()
        status = "ok"
        chips: list[Suggestion] = []
        try:
            chips = list(await asyncio.wait_for(provider.suggest(ctx), self.timeout_s) or [])
        except asyncio.TimeoutError:
            self.logger.warning("Suggestion provider %r timed out after %ss", provider.name, self.timeout_s)
            status = "timeout"
        except Exception as exc:
            self.logger.warning("Suggestion provider %r failed: %s", provider.name, exc)
            status = "error"
        return chips, status, round((time.perf_counter() - started) * 1000, 3)

    def _post_process(self, chips: list[Suggestion]) -> list[Suggestion]:
        """Renderer check, dedupe by label, llm cap, then total cap — in that order."""
        available = [c for c in chips if renderer_available(c.output_mode)]
        seen: set[str] = set()
        unique: list[Suggestion] = []
        for chip in available:
            key = chip.label.casefold()
            if key in seen:
                continue
            seen.add(key)
            unique.append(chip)
        llm_value = SuggestionSource.LLM.value
        capped: list[Suggestion] = []
        llm_seen = 0
        for chip in unique:
            if chip.source == llm_value:
                if llm_seen >= self.max_llm_suggestions:
                    continue
                llm_seen += 1
            capped.append(chip)
        return capped[: self.max_suggestions]
