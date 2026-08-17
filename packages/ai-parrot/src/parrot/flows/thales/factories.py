"""Research agent & node factories for the "Thales" research flow (FEAT-425).

Module 2: builds the per-run research agents for the three v1 sources —
web search, deep research, arxiv — registers them in an ephemeral per-run
:class:`~parrot.registry.registry.AgentRegistry` so
``AgentsFlow.from_definition`` (TASK-2231) can resolve them, and normalizes
each source's raw output (plus grounding/groundedness metadata) into
``Finding``/``SourceClaim`` lists (spec §2 Overview, §6 Codebase Contract).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Optional

from parrot_tools.arxiv_tool import ArxivTool

from parrot.bots.agent import Agent
from parrot.bots.search import WebSearchAgent
from parrot.clients.factory import LLMFactory
from parrot.flows.thales.models import Finding, ResearchAngle, SourceClaim, ThalesConfig
from parrot.models.responses import AIMessage
from parrot.registry.registry import AgentRegistry

#: Default LLM used by the deep-research node when the caller does not
#: override it. Google is the default client per spec §2.
DEFAULT_DEEP_RESEARCH_LLM = "google:gemini-3-flash"


# ---------------------------------------------------------------------------
# Agent builders
# ---------------------------------------------------------------------------


def _web_agent_kwargs() -> dict[str, Any]:
    """Constructor kwargs shared by every per-angle web-search agent."""
    return {
        "use_builtin_search": True,
        "contrastive_search": True,
        "enable_groundedness": True,
    }


def _arxiv_agent_kwargs() -> dict[str, Any]:
    """Constructor kwargs shared by every per-angle arxiv research agent."""
    return {
        "tools": [ArxivTool()],
        "enable_groundedness": True,
    }


def build_web_agent(angle: ResearchAngle, config: ThalesConfig) -> WebSearchAgent:
    """Build a per-angle web-search research agent.

    Args:
        angle: The research angle this agent investigates.
        config: The run's :class:`ThalesConfig`.

    Returns:
        A :class:`WebSearchAgent` using Gemini's built-in search
        (``use_builtin_search=True``), contrastive search, and
        groundedness scoring — required for anti-hallucination provenance
        (spec G2/G3).
    """
    return WebSearchAgent(
        name=f"thales-web-{angle.angle_id}",
        agent_id=f"thales-web-{angle.angle_id}",
        **_web_agent_kwargs(),
    )


def build_arxiv_agent(angle: ResearchAngle, config: ThalesConfig) -> Agent:
    """Build a per-angle arxiv research agent.

    Args:
        angle: The research angle this agent investigates.
        config: The run's :class:`ThalesConfig`.

    Returns:
        An :class:`Agent` carrying :class:`ArxivTool` with groundedness
        scoring enabled.
    """
    return Agent(
        name=f"thales-arxiv-{angle.angle_id}",
        agent_id=f"thales-arxiv-{angle.angle_id}",
        **_arxiv_agent_kwargs(),
    )


def build_deep_research_caller(
    config: ThalesConfig,
    *,
    llm: str = DEFAULT_DEEP_RESEARCH_LLM,
) -> Callable[[str], Awaitable[AIMessage]]:
    """Build an async callable wrapping a client's ``ask(deep_research=True)``.

    ``deep_research`` is a cross-provider flag on the ``AbstractClient.ask()``
    contract (``clients/base.py:1631``): Google routes to the background
    Deep Research interactions agent, Anthropic applies an enhanced research
    system prompt, OpenAI resolves to deep-research models, and Bedrock
    **logs and ignores** the flag — degrading to a plain ask rather than
    raising. The returned callable never special-cases any provider: every
    client's ``ask()`` implementation accepts the flag.

    Args:
        config: The run's :class:`ThalesConfig` (reserved for future
            per-run client overrides).
        llm: The ``"provider:model"`` string identifying the client to use.
            Defaults to Google, per spec ("Default client: Google").

    Returns:
        An async callable ``(prompt: str) -> AIMessage``.
    """
    client = LLMFactory.create(llm=llm)

    async def _call(prompt: str) -> AIMessage:
        return await client.ask(prompt, deep_research=True)

    return _call


def build_agent_registry(
    angles: list[ResearchAngle],
    config: ThalesConfig,
) -> AgentRegistry:
    """Build an ephemeral per-run ``AgentRegistry`` holding all research agents.

    Registers one agent per ``(angle, source)`` pair (for the agent-backed
    sources — ``web`` and ``arxiv``; deep research has no agent of its own,
    see :func:`build_deep_research_caller`) under a deterministic name
    (``thales-<source>-<angle_id>``) as a singleton, so downstream
    flow-definition assembly (TASK-2231) can eagerly resolve them via
    ``AgentsFlow.from_definition(agent_registry=...)``.

    Args:
        angles: All research angles for this run.
        config: The run's :class:`ThalesConfig`; ``config.sources`` selects
            which per-angle agents get registered.

    Returns:
        A populated, ephemeral ``AgentRegistry`` (not yet eagerly resolved
        — left to the caller / TASK-2231).
    """
    registry = AgentRegistry()
    for angle in angles:
        if "web" in config.sources:
            registry.register(
                name=f"thales-web-{angle.angle_id}",
                factory=WebSearchAgent,
                singleton=True,
                startup_config={
                    "agent_id": f"thales-web-{angle.angle_id}",
                    **_web_agent_kwargs(),
                },
            )
        if "arxiv" in config.sources:
            registry.register(
                name=f"thales-arxiv-{angle.angle_id}",
                factory=Agent,
                singleton=True,
                startup_config={
                    "agent_id": f"thales-arxiv-{angle.angle_id}",
                    **_arxiv_agent_kwargs(),
                },
            )
    return registry


# ---------------------------------------------------------------------------
# Output normalizers — raw source output -> list[Finding]
# ---------------------------------------------------------------------------


def _cap_paragraphs(text: str, max_paragraphs: int) -> str:
    """Cap ``text`` to at most ``max_paragraphs`` double-newline-separated paragraphs."""
    if not text:
        return text
    parts = [p for p in text.split("\n\n") if p.strip()]
    if len(parts) <= max_paragraphs:
        return text
    return "\n\n".join(parts[:max_paragraphs])


def extract_groundedness_report(message: AIMessage) -> Optional[dict[str, Any]]:
    """Extract the ``GroundednessReport`` dump from an ``AIMessage``, if present.

    Per contract, the report lands at
    ``AIMessage.metadata["guardrails"]["groundedness"]`` (FLAG-only guardrail
    output) — never at the top level of ``metadata``.

    Args:
        message: The agent/tool response to inspect.

    Returns:
        The report dict, or ``None`` when no groundedness scoring ran.
    """
    guardrails = (message.metadata or {}).get("guardrails")
    if not guardrails:
        return None
    return guardrails.get("groundedness")


def _extract_grounding_sources(message: AIMessage) -> list[dict[str, Any]]:
    """Best-effort extraction of individual grounding sources from metadata.

    Provider-native grounding (Gemini built-in search / Deep Research) does
    not expose a single stable, parsed per-source citation list through
    ``AIMessage`` today — this reads the common candidate metadata keys
    defensively and returns ``[]`` when none are present, in which case the
    caller falls back to one aggregate claim for the whole response.
    """
    metadata = message.metadata or {}
    for key in ("grounding_sources", "citations", "sources", "search_results"):
        value = metadata.get(key)
        if isinstance(value, list) and value:
            return [item for item in value if isinstance(item, dict)]
    return []


def websearch_to_findings(
    message: AIMessage,
    *,
    accessed_date: str,
    config: ThalesConfig,
) -> list[Finding]:
    """Normalize a ``WebSearchAgent.ask()`` response into ``Finding``s.

    Gemini's built-in search yields no ``ToolCall.result`` evidence for the
    deterministic groundedness scorer, so claims are labeled
    ``"provider_grounding"`` (resolved in brainstorm).

    Args:
        message: The agent's response.
        accessed_date: ISO date this source was retrieved. Never invented
            by this function — the caller supplies the run date.
        config: The run's :class:`ThalesConfig` (paragraph cap).

    Returns:
        A list with a single :class:`Finding`, or ``[]`` when the response
        carries no text.
    """
    text = message.response or (message.output if isinstance(message.output, str) else "")
    if not text:
        return []
    text = _cap_paragraphs(text, config.max_paragraphs_per_finding)

    sources = _extract_grounding_sources(message)
    if sources:
        claims = [
            SourceClaim(
                url=source.get("url", ""),
                title=source.get("title"),
                publisher=source.get("publisher") or source.get("source"),
                published_date=source.get("published_date"),
                accessed_date=accessed_date,
                source_tool="web_search",
                verification="provider_grounding",
            )
            for source in sources
        ]
    else:
        claims = [
            SourceClaim(
                url=(message.metadata or {}).get("url", ""),
                accessed_date=accessed_date,
                source_tool="web_search",
                verification="provider_grounding",
            )
        ]
    return [Finding(text=text, claims=claims)]


def deep_research_to_findings(
    message: AIMessage,
    *,
    accessed_date: str,
    config: ThalesConfig,
) -> list[Finding]:
    """Normalize a deep-research ``ask()`` response into ``Finding``s.

    Deep Research is provider-native background research (Google) or an
    enhanced system prompt (Anthropic/OpenAI) — it yields no
    ``ToolCall.result`` evidence, so claims are labeled
    ``"provider_grounding"`` (resolved in brainstorm), same as built-in
    search.

    Args:
        message: The deep-research caller's response
            (see :func:`build_deep_research_caller`).
        accessed_date: ISO date this source was retrieved.
        config: The run's :class:`ThalesConfig` (paragraph cap).

    Returns:
        A list with a single :class:`Finding`, or ``[]`` when the response
        carries no text.
    """
    text = message.response or (message.output if isinstance(message.output, str) else "")
    if not text:
        return []
    text = _cap_paragraphs(text, config.max_paragraphs_per_finding)

    sources = _extract_grounding_sources(message)
    if sources:
        claims = [
            SourceClaim(
                url=source.get("url", ""),
                title=source.get("title"),
                publisher=source.get("publisher") or source.get("source"),
                published_date=source.get("published_date"),
                accessed_date=accessed_date,
                source_tool="deep_research",
                verification="provider_grounding",
            )
            for source in sources
        ]
    else:
        claims = [
            SourceClaim(
                url=(message.metadata or {}).get("url", ""),
                accessed_date=accessed_date,
                source_tool="deep_research",
                verification="provider_grounding",
            )
        ]
    return [Finding(text=text, claims=claims)]


def arxiv_to_findings(
    execute_result: dict[str, Any],
    *,
    accessed_date: str,
    config: ThalesConfig,
    groundedness_report: Optional[dict[str, Any]] = None,
) -> list[Finding]:
    """Normalize an ``ArxivTool._execute()`` result dict into ``Finding``s.

    Each returned paper maps 1:1 onto one ``Finding``/``SourceClaim`` pair:
    ``title``/``authors``/``published``/``pdf_url``/``journal_ref`` carry
    over directly; ``published`` is never invented — papers without a
    publication date keep ``published_date=None``.

    Args:
        execute_result: The dict returned by ``ArxivTool._execute()``
            (keys: ``"query"``, ``"count"``, ``"papers"``, ``"message"``).
        accessed_date: ISO date this source was retrieved.
        config: The run's :class:`ThalesConfig` (paragraph cap).
        groundedness_report: Optional ``GroundednessReport`` dump (see
            :func:`extract_groundedness_report`). When present, claims are
            labeled ``"groundedness"``; otherwise ``"unverified"`` (tool
            calls carry real ``ToolCall.result`` evidence, so this is never
            ``"provider_grounding"``).

    Returns:
        One :class:`Finding` per paper in ``execute_result["papers"]``.
    """
    verification = "groundedness" if groundedness_report else "unverified"
    findings: list[Finding] = []
    for paper in execute_result.get("papers", []):
        text = _cap_paragraphs(paper.get("summary", ""), config.max_paragraphs_per_finding)
        claim = SourceClaim(
            url=paper.get("pdf_url", ""),
            title=paper.get("title"),
            authors=list(paper.get("authors") or []),
            publisher=paper.get("journal_ref"),
            published_date=paper.get("published"),
            accessed_date=accessed_date,
            source_tool="arxiv_search",
            verification=verification,
        )
        findings.append(Finding(text=text, claims=[claim]))
    return findings
