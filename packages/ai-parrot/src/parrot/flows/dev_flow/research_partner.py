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

from abc import ABC, abstractmethod
from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from parrot.flows.dev_loop.session_state import SessionHost


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
            raise ValueError(
                f"Unknown research partner backend: {name!r}. "
                f"Available: {sorted(cls._registry)}"
            )
        return cls._registry[name](**kwargs)


__all__ = [
    "AbstractResearchPartner",
    "ComplementaryFindings",
    "ResearchFinding",
    "ResearchFindings",
    "ResearchPartnerFactory",
]
