"""Decision-plane ``AbstractTool`` wrappers (FEAT-578 Module 6).

Mirrors :mod:`parrot.knowledge.wiki.structural.tools` so the decision tools
register alongside the other wiki tools on one ``StdioMCPServer``
(``wiki_decisions_for_symbol``, ``wiki_decision_why``, and — only when
explicitly enabled — ``wiki_decision_generate``).

There is deliberately NO review tool: accepting a candidate is a maintainer
CLI action, never something an agent does on its own (spec §2, AC11).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.context import truncate_to_tokens
from parrot.knowledge.wiki.decisions.models import ADR_INVALID_ARGUMENT, DecisionDossier, DecisionError
from parrot.knowledge.wiki.decisions.render import DEFAULT_BUDGET_TOKENS, render_dossier_text
from parrot.knowledge.wiki.decisions.service import DecisionService
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import BaseWikiStore, estimate_tokens
from parrot.knowledge.wiki.structural.service import StructuralService
from parrot.knowledge.wiki.tools import _scoped_store, _unknown_namespace_error
from parrot.tools.abstract import AbstractTool, ToolResult

#: Same wording as ``structural.tools._NAMESPACE_DESC``, minus 'all' — ADR
#: reads target exactly one namespace in v1 (spec §2 Module 6).
_NAMESPACE_DESC = (
    "Federated namespace to read: a namespace name, or 'local' for this "
    "repo's own wiki. 'all' is not supported for decisions."
)

ServiceFactory = Callable[[str | None], DecisionService]


class DecisionsForSymbolInput(BaseModel):
    """Arguments for ``wiki_decisions_for_symbol`` / ``decision_for_symbol``."""

    symbol: str = Field(..., description="A sym:<rel>#<qualname> id, or an exact symbol name")
    include_history: bool = Field(default=False, description="Include rejected/deprecated/superseded records")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum hits across both groups")
    budget_tokens: int = Field(default=DEFAULT_BUDGET_TOKENS, ge=256, description="Estimated output budget")
    namespace: str | None = Field(default=None, description=_NAMESPACE_DESC)


class DecisionWhyInput(BaseModel):
    """Arguments for ``wiki_decision_why`` / ``decision_why``."""

    question: str = Field(..., description="Natural-language question, optionally naming a symbol")
    include_history: bool = Field(default=False, description="Include rejected/deprecated/superseded records")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum hits across both groups")
    budget_tokens: int = Field(default=DEFAULT_BUDGET_TOKENS, ge=256, description="Estimated output budget")
    namespace: str | None = Field(default=None, description=_NAMESPACE_DESC)


class DecisionGenerateInput(BaseModel):
    """Arguments for ``wiki_decision_generate``."""

    target: str = Field(..., description="One sym: id or one repository-relative file path")


def _dossier_result(dossier: DecisionDossier, budget_tokens: int) -> ToolResult:
    """Render a dossier as a ToolResult, labels intact.

    The text body always carries the origin/status/freshness labels and the
    candidate group heading, so a model reading only the text cannot mistake
    a candidate for documented history (AC3, AC9).

    The machine-readable JSON tail is reserved its own token budget and is
    NEVER passed through ``truncate_to_tokens`` itself — truncating the
    combined text+JSON blob as one string can cut the JSON mid-object,
    corrupting it into something that no longer parses (AC9: adapters must
    preserve service semantics under output budgets). Only the human-
    readable prose is subject to character-level truncation; the JSON tail
    is always appended whole.
    """
    tail = json.dumps(dossier.model_dump(mode="json"))
    text_budget = budget_tokens - estimate_tokens(tail)
    if text_budget <= 0:
        # The JSON tail alone already meets or exceeds the budget; there is
        # no room left for prose, but the tail must still be emitted whole.
        body, body_truncated = "", True
    else:
        body, body_truncated = truncate_to_tokens(render_dossier_text(dossier), text_budget)
    text = f"{body}\n\n{tail}"
    return ToolResult(
        result=text, metadata={"status": dossier.status, "truncated": dossier.truncated or body_truncated}
    )


def _error_result(exc: DecisionError) -> ToolResult:
    """Render a DecisionError as a failed ToolResult with its stable code."""
    return ToolResult(success=False, status="error", result=None, error=f"{exc.code}: {exc.message}")


class WikiDecisionsForSymbolTool(AbstractTool):
    """Find the architectural decisions that apply to a symbol, with citations.
    Returns documented ADRs and, separately, labeled inferred candidates."""

    name = "wiki_decisions_for_symbol"
    description = (
        "Find architectural decisions (ADRs) that apply to a function, class "
        "or method, with source citations. Documented decisions and inferred "
        "candidates are returned as separate, explicitly labeled groups — a "
        "candidate is a hypothesis, not accepted history."
    )
    args_schema = DecisionsForSymbolInput

    def __init__(self, service_factory: ServiceFactory):
        super().__init__(name=self.name, description=self.description)
        self._service_factory = service_factory

    async def _execute(
        self,
        symbol: str,
        include_history: bool = False,
        limit: int = 10,
        budget_tokens: int = DEFAULT_BUDGET_TOKENS,
        namespace: str | None = None,
    ) -> ToolResult:
        try:
            service = self._service_factory(namespace)
        except ValueError as exc:
            return ToolResult(success=False, status="error", result=None, error=str(exc))
        except DecisionError as exc:
            return _error_result(exc)
        try:
            dossier = await service.for_symbol(
                symbol, include_history=include_history, limit=limit, budget_tokens=budget_tokens
            )
        except DecisionError as exc:
            return _error_result(exc)
        return _dossier_result(dossier, budget_tokens)


class WikiDecisionWhyTool(AbstractTool):
    """Answer "why is this built this way?" with cited decision excerpts."""

    name = "wiki_decision_why"
    description = (
        "Answer a 'why' question about the codebase with cited decision "
        "excerpts and supporting code. Documented decisions rank above "
        "inferred candidates, which are returned in their own labeled group."
    )
    args_schema = DecisionWhyInput

    def __init__(self, service_factory: ServiceFactory):
        super().__init__(name=self.name, description=self.description)
        self._service_factory = service_factory

    async def _execute(
        self,
        question: str,
        include_history: bool = False,
        limit: int = 10,
        budget_tokens: int = DEFAULT_BUDGET_TOKENS,
        namespace: str | None = None,
    ) -> ToolResult:
        try:
            service = self._service_factory(namespace)
        except ValueError as exc:
            return ToolResult(success=False, status="error", result=None, error=str(exc))
        except DecisionError as exc:
            return _error_result(exc)
        try:
            dossier = await service.why(
                question, include_history=include_history, limit=limit, budget_tokens=budget_tokens
            )
        except DecisionError as exc:
            return _error_result(exc)
        return _dossier_result(dossier, budget_tokens)


class WikiDecisionGenerateTool(AbstractTool):
    """Generate labeled candidate rationale for an undocumented symbol or file.

    Registered ONLY when generation is enabled and a local writable project is
    available. It creates UNREVIEWED candidates — it cannot accept anything.
    """

    name = "wiki_decision_generate"
    description = (
        "Generate explicitly labeled CANDIDATE rationale for a symbol or file "
        "that has no documented decision. Candidates are inferred, unreviewed "
        "hypotheses and are never accepted history; a maintainer accepts them "
        "separately through the CLI."
    )
    args_schema = DecisionGenerateInput

    def __init__(self, service_factory: ServiceFactory):
        super().__init__(name=self.name, description=self.description)
        self._service_factory = service_factory

    async def _execute(self, target: str) -> ToolResult:
        try:
            service = self._service_factory(None)
        except (ValueError, DecisionError) as exc:
            return ToolResult(success=False, status="error", result=None, error=str(exc))
        try:
            result = await service.generate(target)
        except DecisionError as exc:
            return _error_result(exc)
        return ToolResult(result=result.model_dump(mode="json"))


def create_decision_tools(
    store: BaseWikiStore,
    root: Path | None,
    config: WikiProjectConfig,
) -> list[AbstractTool]:
    """Create namespace-aware read tools and explicitly enabled generation tools.

    The two read tools are always returned. ``wiki_decision_generate`` is
    appended ONLY when ``config.decisions.generation_enabled`` is true AND a
    local writable ``root`` exists (spec §2 Module 6). No review tool is ever
    created (AC11).
    """
    decisions_config = config.decisions
    local_structural = StructuralService(store, root, config) if root is not None else None

    def service_factory(namespace: str | None) -> DecisionService:
        if namespace == "all":
            raise DecisionError(ADR_INVALID_ARGUMENT, "namespace='all' is not supported for decisions")
        # `namespace` defaults to "local" (never passed through as `None`):
        # `_scoped_store(store, None)` no-ops and returns `store` UNCHANGED,
        # which — when `store` is a `FederatedWikiStore` (the MCP server
        # wraps it in one before this factory ever runs) — is the whole
        # broadcasting federation, not the local plane. Spec §2 Module 6
        # requires why/lookup to target exactly one namespace per call,
        # `local` by default; only an explicit selector should narrow to a
        # named foreign namespace.
        effective_ns = namespace or "local"
        try:
            scoped = _scoped_store(store, effective_ns)
        except KeyError:
            raise ValueError(_unknown_namespace_error(store, str(namespace))) from None
        if effective_ns == "local":
            return DecisionService(scoped, root, decisions_config, structural=local_structural)
        # A foreign/federated namespace has no local evidence root of its
        # own — freshness answers 'unverified' and generation/sync refuse,
        # per spec §2 Module 6 ("cannot generate or sync local code").
        return DecisionService(scoped, None, decisions_config, structural=None)

    tools: list[AbstractTool] = [
        WikiDecisionsForSymbolTool(service_factory),
        WikiDecisionWhyTool(service_factory),
    ]
    if decisions_config.generation_enabled and root is not None:
        tools.append(WikiDecisionGenerateTool(service_factory))
    return tools
