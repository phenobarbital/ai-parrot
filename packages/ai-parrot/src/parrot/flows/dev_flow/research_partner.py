"""Complementary (collaborative) research partner contracts (FEAT-482).

The proactive dev-flow (`IdeationNode`) and the ops flow (`ResearchNode`)
each dispatch a single Claude research seat. This module defines the
contract layer for an OPT-IN second seat — a read-only, advisory
collaborator that investigates the same request from its own angle and
whose findings the primary seat reads and expands upon.

This module mirrors :class:`AbstractCodeReviewDispatcher` /
:class:`CodeReviewDispatcherFactory`
(``parrot.flows.dev_loop.code_review``), including the ``advisory``
marker, but is deliberately NOT a subclass of them — research is not
review, and the partner never renders a pass/fail verdict.

See ``sdd/specs/devflow-complementary-research.spec.md`` §2 Data Models,
§3 Module 1.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from parrot import conf
from parrot.clients.base import AbstractClient
from parrot.clients.nova.client import NovaClient
from parrot.clients.nova.mantle import BedrockMantleClient
from parrot.flows.dev_loop.catalog import (
    resolve_research_partner_backend,
    validate_research_partner_model,
)
from parrot.flows.dev_loop.session_state import SessionHost
from parrot.tools.repo import ReadOnlyRepoToolkit


class ResearchFinding(BaseModel):
    """One discrete finding from the complementary researcher.

    Attributes:
        id: Stable identifier (e.g. ``"F1"``) that enables attributed
            merge into the primary seat's document.
        title: Short human-readable summary of the finding.
        detail: The finding's full explanation.
        evidence: File:line references or URLs the partner actually read
            while producing this finding.
        confidence: The partner's own confidence in this finding.
    """

    id: str
    title: str
    detail: str
    evidence: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"


class ResearchFindings(BaseModel):
    """Structured output contract for a research partner dispatch."""

    summary: str
    findings: list[ResearchFinding] = Field(default_factory=list)
    options_considered: list[str] = Field(default_factory=list)
    could_not_determine: list[str] = Field(default_factory=list)
    sources_examined: list[str] = Field(default_factory=list)


class ComplementaryFindings(BaseModel):
    """What :class:`ComplementaryResearchCoordinator` hands back to a node.

    Absent (i.e. no complementary research happened, whether because the
    seat is disabled or because it failed) is represented as ``None`` at
    the coordinator boundary — this model is never constructed empty.
    """

    backend: str
    model: str
    findings: ResearchFindings
    document_path: str = ""
    rendered: str
    duration_ms: float
    degraded: bool = False


class AbstractResearchPartner(ABC):
    """Read-only, advisory collaborative researcher.

    Concrete subclasses implement :meth:`research` against a specific
    backend/transport (e.g. Bedrock mantle for ``gpt-5.6-sol``, Bedrock
    Converse for ``nova-2-lite``). The partner never authors or commits
    under ``sdd/`` and is never treated as authoritative — see
    ``advisory``.
    """

    partner_name: str
    advisory: bool = True
    """Findings from a research partner are never authoritative — the
    primary seat reads, attributes, and expands upon them, but is not
    bound by them. Mirrors ``AbstractCodeReviewDispatcher.advisory``
    (``code_review.py:100``)."""

    @abstractmethod
    async def research(
        self,
        *,
        brief: BaseModel,
        question: str,
        cwd: str,
        run_id: str,
        node_id: str,
        session_host: SessionHost | None = None,
    ) -> ResearchFindings:
        """Investigate ``question`` against the repo at ``cwd``.

        Args:
            brief: The originating dev-flow/dev-loop brief (never the
                primary seat's framing or hypotheses — neutrality is a
                contract, see spec §2).
            question: The research question posed to the partner.
            cwd: The repo checkout the partner may read (read-only).
            run_id: The flow run id, for correlating telemetry.
            node_id: The flow node id, for correlating telemetry.
            session_host: The run's ``SessionHost``, if any.

        Returns:
            Validated :class:`ResearchFindings`.
        """


class ResearchPartnerFactory:
    """Factory for creating research partner instances by backend name.

    Mirrors :class:`CodeReviewDispatcherFactory`
    (``code_review.py:164-187``).
    """

    _registry: ClassVar[dict[str, type[AbstractResearchPartner]]] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator to register a research partner implementation."""

        def decorator(klass):
            cls._registry[name] = klass
            return klass

        return decorator

    @classmethod
    def create(cls, name: str, **kwargs) -> AbstractResearchPartner:
        """Create a research partner by backend name.

        Args:
            name: One of the registered backend names (e.g. ``"gpt"``,
                ``"nova"``).
            **kwargs: Forwarded to the registered class's constructor.

        Returns:
            The constructed :class:`AbstractResearchPartner`.

        Raises:
            ValueError: If ``name`` is not registered.
        """
        if name not in cls._registry:
            raise ValueError(f"Unknown research partner backend: {name!r}. " f"Available: {sorted(cls._registry)}")
        return cls._registry[name](**kwargs)


def resolve_backend_model(backend: str) -> str:
    """Return the configured model id for ``backend`` (``"gpt"``/``"nova"``).

    The single source of truth for this two-branch mapping — shared by
    :meth:`BedrockResearchPartner._build_client` and
    :class:`~parrot.flows.dev_flow.complementary_research.
    ComplementaryResearchCoordinator._resolve_model_for_backend` (which
    needs to know the model actually used to stamp
    ``ComplementaryFindings.model``, without importing a private method
    off a partner instance). Extracted here, rather than duplicated in
    both call sites, per code review.

    Args:
        backend: ``"gpt"`` or ``"nova"``.

    Returns:
        ``conf.DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL`` for ``"gpt"``,
        otherwise ``conf.DEV_FLOW_RESEARCH_PARTNER_NOVA_MODEL``.
    """
    if backend == "gpt":
        return conf.DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL
    return conf.DEV_FLOW_RESEARCH_PARTNER_NOVA_MODEL


@ResearchPartnerFactory.register("gpt")
@ResearchPartnerFactory.register("nova")
class BedrockResearchPartner(AbstractResearchPartner):
    """One implementation covering both research-partner backends.

    ``gpt`` (default) and ``nova`` both reach AWS Bedrock on the same
    ``AWS_NOVA_API_KEY`` credential and share one call shape —
    ``ask(use_tools=True, structured_output=ResearchFindings)`` — because
    :class:`~parrot.clients.nova.mantle.BedrockMantleClient` and
    :class:`~parrot.clients.nova.client.NovaClient` are both
    :class:`~parrot.clients.base.AbstractClient` subclasses sharing one
    tool registry and one ``_execute_tool`` path. No per-transport tool
    adapter exists, or should exist, here.

    This class MAY raise on any failure (bad credentials, Bedrock outage,
    unparseable structured output) — :class:`ComplementaryResearchCoordinator`
    (a later task) is the soft-degradation boundary, not this class.
    """

    partner_name = "bedrock-research-partner"

    def __init__(self, *, backend: str | None = None, model: str | None = None) -> None:
        """Initialize the partner for a resolved backend.

        Args:
            backend: ``"gpt"`` or ``"nova"``. When omitted, resolved via
                :func:`resolve_research_partner_backend` (empty/disabled
                is rejected — a coordinator must never construct this
                class for a disabled seat).
            model: FEAT-486 — explicit model id override for this seat.
                ``None`` (default) resolves ``resolve_backend_model(backend)``
                exactly as before, so every pre-FEAT-486 construction path
                is byte-identical. A supplied model is still run through
                :func:`validate_research_partner_model` in
                :meth:`_build_client`, so the Anthropic family guard cannot
                be bypassed by injecting one here.

        Raises:
            ValueError: If the resolved backend is empty (disabled) or
                not one of ``"gpt"``/``"nova"``.
        """
        self.logger = logging.getLogger(__name__)
        self.backend = backend if backend is not None else resolve_research_partner_backend()
        self.model = model or ""
        if self.backend not in ("gpt", "nova"):
            raise ValueError(
                f"BedrockResearchPartner requires an enabled backend "
                f"('gpt' or 'nova'); got {self.backend!r} — the "
                "research-partner seat is disabled or misconfigured."
            )

    def _build_client(self) -> AbstractClient:
        """Construct the backend-appropriate client, model pre-configured.

        Defense-in-depth: re-validates the resolved model against the
        Anthropic family guard (:func:`validate_research_partner_model`)
        even though :func:`resolve_research_partner_backend` already does
        so — that resolver is bypassed entirely when this class is
        constructed directly with an explicit ``backend=`` (e.g. by a
        future caller that doesn't go through the config-driven path), so
        the guard must not depend on the resolver having run first.

        Returns:
            A :class:`BedrockMantleClient` (``"gpt"``) or
            :class:`NovaClient` (``"nova"``) — both share the same
            ``AWS_NOVA_API_KEY`` credential; no ``OPENAI_API_KEY`` is
            read, and no Codex CLI is involved.
        """
        # FEAT-486: an explicit `model=` wins over the conf mapping; the
        # family guard below runs either way, so an injected model is no
        # less validated than a configured one.
        model = self.model or resolve_backend_model(self.backend)
        validate_research_partner_model(model)
        if self.backend == "gpt":
            return BedrockMantleClient(model=model)
        return NovaClient(model=model)

    def _reasoning_kwargs(self) -> dict[str, Any]:
        """Return the backend-appropriate reasoning knob only.

        ``thinking_budget`` is a Converse-only ``BedrockConverseBase.ask()``
        parameter — passing it to :class:`BedrockMantleClient` (which
        inherits :meth:`OpenAIBaseClient.ask` unchanged) would raise a
        ``TypeError``, since that signature has no such parameter. The
        mantle path has no OpenAI-shaped ``effort``/``reasoning_effort``
        parameter to forward it through either (see this module's
        docstring note on ``DEV_FLOW_RESEARCH_PARTNER_EFFORT`` — reserved,
        not yet wired; see TASK-2631 completion note for the full
        rationale). Returning ``{}`` for ``"gpt"`` keeps that path
        strictly additive rather than guessing an unsupported kwarg.

        Returns:
            ``{"thinking_budget": N}`` for ``"nova"``; ``{}`` for ``"gpt"``.
        """
        if self.backend == "nova":
            return {"thinking_budget": conf.DEV_FLOW_RESEARCH_PARTNER_THINKING_BUDGET}
        # Code-review follow-up: an operator who explicitly changed EFFORT
        # away from its documented default would reasonably expect it to
        # do something. Since it currently doesn't (see the docstring
        # above), warn once per call rather than silently ignoring an
        # operator's explicit configuration.
        if conf.DEV_FLOW_RESEARCH_PARTNER_EFFORT != "high":
            self.logger.warning(
                "DEV_FLOW_RESEARCH_PARTNER_EFFORT=%r is set but has no "
                "effect on the 'gpt' (bedrock-mantle) backend — "
                "BedrockMantleClient has no effort/reasoning_effort "
                "parameter to forward it through today.",
                conf.DEV_FLOW_RESEARCH_PARTNER_EFFORT,
            )
        return {}

    @staticmethod
    def _build_prompt(*, brief: BaseModel, question: str, cwd: str) -> str:
        """Build the neutral prompt: brief, repo root, question — nothing else.

        Deliberately excludes the primary Claude seat's framing,
        hypotheses, or preferred conclusion (spec §2 "Why the partner is
        prompted neutrally") — supplying them would produce ratification
        of the primary seat's read, not an independent second opinion.

        Args:
            brief: The originating dev-flow/dev-loop brief.
            question: The research question posed to the partner.
            cwd: The repo checkout root the partner may read.

        Returns:
            The complete prompt text.
        """
        return (
            "You are an independent research partner investigating a "
            "software development request in parallel with another "
            "researcher who works separately from you. Answer strictly "
            "from your own reading of the repository — you do not see "
            "the other researcher's findings, framing, or conclusions.\n\n"
            f"Repository root: {cwd}\n\n"
            f"Request brief (JSON):\n{brief.model_dump_json(indent=2)}\n\n"
            f"Research question:\n{question}\n"
        )

    async def research(
        self,
        *,
        brief: BaseModel,
        question: str,
        cwd: str,
        run_id: str,
        node_id: str,
        session_host: SessionHost | None = None,
    ) -> ResearchFindings:
        """Investigate ``question`` against the repo at ``cwd``.

        Issues exactly one ``ask(use_tools=True,
        structured_output=ResearchFindings)`` call against the resolved
        backend's client, with FEAT-484's :class:`ReadOnlyRepoToolkit`
        (and no other tool) registered.

        Args:
            brief: The originating dev-flow/dev-loop brief.
            question: The research question posed to the partner.
            cwd: The repo checkout the partner may read (read-only).
            run_id: The flow run id — logged for correlation only; no
                per-run node wiring happens in this class.
            node_id: The flow node id — logged for correlation only.
            session_host: Unused by this implementation (accepted for ABC
                compatibility).

        Returns:
            Validated :class:`ResearchFindings`.

        Raises:
            ValueError: If the client returns no parseable
                ``ResearchFindings`` (unstructured/failed output). Any
                other exception raised by the underlying client (auth,
                network, Bedrock outage) propagates unchanged — this
                class is not the soft-degradation boundary.
        """
        self.logger.info(
            "%s research partner (%s) starting: run_id=%s node_id=%s",
            self.partner_name,
            self.backend,
            run_id,
            node_id,
        )
        client = self._build_client()
        toolkit = ReadOnlyRepoToolkit(
            repo_root=Path(cwd),
            enable_web_search=conf.DEV_FLOW_RESEARCH_PARTNER_WEB_SEARCH,
        )
        client.register_tools(toolkit.get_tools())

        prompt = self._build_prompt(brief=brief, question=question, cwd=cwd)
        message = await client.ask(
            prompt,
            use_tools=True,
            structured_output=ResearchFindings,
            max_tokens=conf.DEV_FLOW_RESEARCH_PARTNER_MAX_TOKENS,
            **self._reasoning_kwargs(),
        )

        findings = message.structured_output
        if isinstance(findings, ResearchFindings):
            return findings
        if isinstance(findings, dict):
            return ResearchFindings.model_validate(findings)
        raise ValueError(
            f"{self.backend} research partner returned no valid "
            f"ResearchFindings (got {type(findings).__name__}); "
            "structured-output parsing likely failed."
        )


__all__ = [
    "AbstractResearchPartner",
    "BedrockResearchPartner",
    "ComplementaryFindings",
    "ResearchFinding",
    "ResearchFindings",
    "ResearchPartnerFactory",
    "resolve_backend_model",
]
