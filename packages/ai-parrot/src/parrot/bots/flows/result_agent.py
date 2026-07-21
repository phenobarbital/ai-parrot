"""ResultAgent — Registered Agent for Crew Infographic Rendering (FEAT-308).

Spec: ``sdd/specs/agentcrew-node-infographic.spec.md`` §3 Module 3.

An internal ``Agent`` subclass, registered as ``"result-agent"`` in the
``AgentRegistry``, that carries an ``InfographicToolkit``. It receives a
crew's synthesis ``summary`` and the deterministic tab blocks (built by
:mod:`parrot.bots.flows.crew.result_infographic`), LLM-authors the Tab 1
(Executive Summary & Insights) blocks from the summary, merges them with the
deterministic blocks, and renders the merged block list through the
``crew_report`` template.

Codebase Contract corrections (verified against the real registry / toolkit
implementations on 2026-07-14):
    - ``@register_agent(...)`` (``agent_registry.register_bot_decorator``) is
      **keyword-only** (``def register_bot_decorator(self, *, name=None,
      ...)``, registry/registry.py:1205-1216). ``@register_agent("result-agent")``
      (positional, as shown in the spec's own §2 pseudo-code) raises
      ``TypeError``; the correct form is ``@register_agent(name="result-agent")``.
    - ``AgentRegistry`` has **no** ``.get(name)`` method. The verified
      lookup API is ``get_metadata(name) -> Optional[BotMetadata]``, whose
      ``.factory`` attribute holds the registered class
      (registry/registry.py:513-514, :43-63).
    - ``InfographicToolkit.__init__`` requires ``artifact_store: ArtifactStore``
      as a mandatory keyword-only argument (infographic_toolkit.py:134-141);
      there is no zero-arg constructor. Building the real ``ArtifactStore``
      (``build_conversation_backend()`` + ``.initialize()``) is async, but
      ``agent_tools()`` is called synchronously from ``BasicAgent.__init__``
      (agent.py:110). ``_LazyArtifactStore`` below defers the real backend
      construction to the first actual ``save_artifact()`` call (inside the
      async ``render()`` path), so ``ResultAgent()`` can be constructed
      without requiring a caller-supplied ``ArtifactStore``.
    - Default LLM: ``BasicAgent.__init__`` already falls back to
      ``GoogleGenAIClient()`` (whose ``_default_model`` is
      ``GoogleModel.GEMINI_FLASH_LATEST``) when no ``llm`` is supplied
      (agent.py:104-108) — no hardcoded model-id string is needed here,
      resolving the spec's §8 open question.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from parrot.registry import register_agent
from parrot.bots.agent import Agent
from parrot.tools.abstract import AbstractTool
from parrot.tools.infographic_toolkit import InfographicToolkit, InfographicRenderResult
from parrot.storage.artifacts import ArtifactStore
from parrot.bots.flows.crew.result_infographic import merge_tab1_blocks

logger = logging.getLogger(__name__)

# SummaryBlock.content max_length (parrot/models/infographic.py:365-377).
_SUMMARY_BLOCK_MAX_LENGTH = 2000


class _LazyArtifactStore:
    """Deferred-init ``ArtifactStore`` proxy.

    ``InfographicToolkit`` requires a real ``ArtifactStore`` at construction
    time, but building one (``build_conversation_backend()`` +
    ``.initialize()`` + ``build_overflow_store()``) is async. This proxy
    lets ``ResultAgent.agent_tools()`` construct the toolkit synchronously
    while deferring the actual backend construction to the first
    ``save_artifact()`` call, which happens inside the async ``render()``
    path. Uses env-configured defaults (``PARROT_STORAGE_BACKEND``,
    ``PARROT_OVERFLOW_STORE``), the same ones the app's own startup wiring
    uses (see ``manager.py::on_startup``).
    """

    def __init__(self) -> None:
        self._store: Optional[ArtifactStore] = None
        self._lock = asyncio.Lock()

    async def _ensure_store(self) -> ArtifactStore:
        if self._store is None:
            async with self._lock:
                if self._store is None:
                    # Local imports: avoid pulling storage backends into
                    # every import of this module (parity with the app's own
                    # lazy backend construction pattern).
                    from parrot.storage.backends import (
                        build_conversation_backend,
                        build_overflow_store,
                    )
                    backend = await build_conversation_backend()
                    await backend.initialize()
                    overflow = build_overflow_store()
                    self._store = ArtifactStore(dynamodb=backend, s3_overflow=overflow)
        return self._store

    async def save_artifact(self, user_id: str, agent_id: str, session_id: str, artifact: Any) -> None:
        store = await self._ensure_store()
        await store.save_artifact(user_id, agent_id, session_id, artifact)

    async def get_artifact(self, *args: Any, **kwargs: Any) -> Any:
        store = await self._ensure_store()
        return await store.get_artifact(*args, **kwargs)

    async def get_public_url(self, *args: Any, **kwargs: Any) -> Any:
        store = await self._ensure_store()
        return await store.get_public_url(*args, **kwargs)


@register_agent(name="result-agent")
class ResultAgent(Agent):
    """Internal agent that renders a crew's ExecutionMemory into a crew_report infographic."""

    agent_id: str = "result-agent"

    def __init__(
        self,
        *args: Any,
        artifact_store: Optional[ArtifactStore] = None,
        **kwargs: Any,
    ) -> None:
        """Initialise the ResultAgent.

        Args:
            *args: Forwarded to :class:`~parrot.bots.agent.Agent`.
            artifact_store: Optional pre-built ``ArtifactStore``. Defaults to
                a lazily-initialised store (see ``_LazyArtifactStore``) when
                not supplied.
            **kwargs: Forwarded to :class:`~parrot.bots.agent.Agent`. If no
                ``llm`` is given, the base class falls back to Gemini Flash
                (``GoogleGenAIClient``).
        """
        self._artifact_store = artifact_store or _LazyArtifactStore()
        self._toolkit: Optional[InfographicToolkit] = None
        kwargs.setdefault("name", "ResultAgent")
        kwargs.setdefault("agent_id", "result-agent")
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(__name__)

    def agent_tools(self) -> List[AbstractTool]:
        """Return the tools used by this agent.

        Returns:
            Tools generated by ``InfographicToolkit``.
        """
        self._toolkit = InfographicToolkit(artifact_store=self._artifact_store)
        return self._toolkit.get_tools()

    async def generate_infographic(
        self,
        summary: str,
        deterministic_blocks: List[Dict[str, Any]],
        crew_name: str = "AgentCrew",
        theme: str = "light",
    ) -> InfographicRenderResult:
        """LLM-author Tab 1 and render the merged crew_report infographic.

        Args:
            summary: The crew's existing synthesis summary (SynthesisMixin
                output) — reused as the Tab 1 seed; no second synthesis pass.
            deterministic_blocks: The ``[title, tab_view]`` block list from
                :func:`~parrot.bots.flows.crew.result_infographic.build_deterministic_tabs`.
            crew_name: Crew name, used in the Tab 1 authoring prompt.
            theme: Infographic theme (default ``"light"``).

        Returns:
            The rendered ``InfographicRenderResult``.
        """
        tab1_blocks = await self._author_tab1_blocks(summary, crew_name)
        merged_blocks = merge_tab1_blocks(tab1_blocks, deterministic_blocks)

        if self._toolkit is None:
            # Defensive: agent_tools() always runs during __init__, but guard
            # against direct instantiation edge cases.
            self._toolkit = InfographicToolkit(artifact_store=self._artifact_store)

        return await self._toolkit.render(
            template_name="crew_report",
            theme=theme,
            mode="deterministic",
            data_variables=[],
            blocks=merged_blocks,
        )

    async def _author_tab1_blocks(self, summary: str, crew_name: str) -> List[Dict[str, Any]]:
        """LLM-author the Executive Summary & Insights tab from ``summary``.

        Reuses the crew's existing synthesis output — this is NOT a second
        synthesis pass, just a re-framing of it into the Tab 1 block. Falls
        back to the raw ``summary`` text (graceful degradation) if the LLM
        call raises.

        Args:
            summary: The crew's synthesis summary.
            crew_name: Crew name for the authoring prompt.

        Returns:
            A one-item list containing a ``SummaryBlock``-shaped dict.
        """
        prompt = (
            "You are drafting the 'Executive Summary & Insights' tab of a "
            f"crew execution report for '{crew_name}'. Using ONLY the "
            "summary below (do not invent new facts), write a concise "
            "executive summary highlighting the key insights.\n\n"
            f"Summary:\n{summary}\n"
        )
        try:
            ai_message = await self.ask(prompt, use_tools=False, use_conversation_history=False)
            content = getattr(ai_message, "response", None) or str(getattr(ai_message, "output", "")) or summary
        except Exception:  # noqa: BLE001 — graceful degradation per spec G7
            self.logger.warning(
                "ResultAgent: Tab 1 LLM authoring failed; falling back to raw summary.",
                exc_info=True,
            )
            content = summary or "No summary available."

        if not content:
            content = "No summary available."

        return [{"type": "summary", "content": content[:_SUMMARY_BLOCK_MAX_LENGTH]}]
