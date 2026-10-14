"""Decision-plane ``AbstractTool`` wrappers (FEAT-578 Module 6).

Mirrors :mod:`parrot.knowledge.wiki.structural.tools` so the decision tools
register alongside the other wiki tools on one ``StdioMCPServer``
(``wiki_decisions_for_symbol``, ``wiki_decision_why``, and — only when
explicitly enabled — ``wiki_decision_generate``).

There is deliberately NO review tool: accepting a candidate is a maintainer
CLI action, never something an agent does on its own (spec §2, AC11).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from parrot.knowledge.wiki.decisions.models import ADR_INVALID_ARGUMENT, DecisionError
from parrot.knowledge.wiki.decisions.operations import (
    DecisionGenerateInput,
    DecisionWhyInput,
    DecisionsForSymbolInput,
    op_decision_generate,
    op_decision_why,
    op_decisions_for_symbol,
)
from parrot.knowledge.wiki.decisions.render import DEFAULT_BUDGET_TOKENS
from parrot.knowledge.wiki.decisions.service import DecisionService
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.knowledge.wiki.structural.service import StructuralService
from parrot.knowledge.wiki.operations import _scoped_store, _unknown_namespace_error
from parrot.tools.abstract import AbstractTool, ToolResult

#: Same wording as ``structural.tools._NAMESPACE_DESC``, minus 'all' — ADR
#: reads target exactly one namespace in v1 (spec §2 Module 6).
_NAMESPACE_DESC = (
    "Federated namespace to read: a namespace name, or 'local' for this "
    "repo's own wiki. 'all' is not supported for decisions."
)

ServiceFactory = Callable[[str | None], DecisionService]


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
        result = await op_decisions_for_symbol(
            None,
            DecisionsForSymbolInput(
                symbol=symbol,
                include_history=include_history,
                limit=limit,
                budget_tokens=budget_tokens,
                namespace=namespace,
            ),
            service_factory=self._service_factory,
        )
        if result.is_error:
            return ToolResult(success=False, status="error", result=None, error=result.text)
        return ToolResult(result=result.text, metadata=result.data)


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
        result = await op_decision_why(
            None,
            DecisionWhyInput(
                question=question,
                include_history=include_history,
                limit=limit,
                budget_tokens=budget_tokens,
                namespace=namespace,
            ),
            service_factory=self._service_factory,
        )
        if result.is_error:
            return ToolResult(success=False, status="error", result=None, error=result.text)
        return ToolResult(result=result.text, metadata=result.data)


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
        result = await op_decision_generate(
            None, DecisionGenerateInput(target=target), service_factory=self._service_factory
        )
        if result.is_error:
            return ToolResult(success=False, status="error", result=None, error=result.text)
        return ToolResult(result=result.data)


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
