"""Decision plane tools and toolkit (moved from parrot.knowledge.wiki.decisions — FEAT-540 M3)."""

from __future__ import annotations

from collections.abc import Callable
from parrot.knowledge.wiki.decisions.models import (
    ADR_INVALID_ARGUMENT,
    DecisionError,
)
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
from parrot.knowledge.wiki.operations import (
    _scoped_store,
    _unknown_namespace_error,
)
from parrot.knowledge.wiki.project import (
    WikiProjectConfig,
    find_project_root,
    load_effective_config,
    sqlite_policy_from_config,
)
from parrot.knowledge.wiki.store import (
    BaseWikiStore,
    create_wiki_store,
)
from parrot.knowledge.wiki.structural.service import StructuralService
from parrot.tools.abstract import (
    AbstractTool,
    ToolResult,
)
from parrot.tools.toolkit import AbstractToolkit
from pathlib import Path
from typing import Any

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


class DecisionToolkit(AbstractToolkit):
    """Query the codebase's architectural decisions: symbol lookup and cited why.

    Tool prefix: ``"decision"`` — methods are exposed as
    ``decision_for_symbol`` and ``decision_why``. Candidate generation is
    explicit opt-in via ``include_generation=True`` and still requires
    ``generation_enabled`` in the project config. Review is never exposed
    (spec §2, AC11).
    """

    tool_prefix: str = "decision"

    def __init__(
        self,
        root: Path | None = None,
        store: BaseWikiStore | None = None,
        config: WikiProjectConfig | None = None,
        include_generation: bool = False,
        **kwargs: Any,
    ) -> None:
        """Resolve root/config/store, then build one shared service.

        Args:
            root: Wiki project root. Defaults to :func:`find_project_root`
                from the current working directory.
            store: Pre-built retrieval plane. When omitted, one is built
                from ``config`` the same way ``wikitoolkit``'s CLI does.
            config: Effective project configuration. Defaults to
                :func:`load_effective_config` for ``root``.
            include_generation: Reserved for a future opt-in generation
                tool. This toolkit never exposes review — accepting a
                candidate is a maintainer CLI action only (spec §2, AC11).
            **kwargs: Forwarded to :class:`AbstractToolkit`.

        Raises:
            ValueError: When ``root`` is omitted and no project root can
                be found from the current working directory.
        """
        super().__init__(**kwargs)
        resolved_root = root or find_project_root()
        if resolved_root is None:
            raise ValueError(
                "DecisionToolkit: no wiki project root found — pass "
                "root= explicitly, or run inside a repo with "
                ".parrot/wiki.json or a .git root."
            )
        self._root = resolved_root
        self._config = config or load_effective_config(resolved_root).config
        self._store = store if store is not None else self._build_store()
        self._include_generation = include_generation
        self._service = DecisionService(self._store, self._root, self._config.decisions)

    def _build_store(self) -> BaseWikiStore:
        """Build the retrieval-plane store from ``self._config`` (no store given)."""
        storage = self._config.storage_path(self._root)
        if self._config.backend == "arangodb":
            from parrot.knowledge.wiki.project import resolve_arango_params

            return create_wiki_store(
                storage,
                wiki_name=self._config.wiki_name,
                backend="arangodb",
                arango_params=resolve_arango_params(self._config),
                database=self._config.arango_database or "",
                text_analyzer=self._config.arango_text_analyzer,
            )
        storage.mkdir(parents=True, exist_ok=True)
        return create_wiki_store(
            storage,
            wiki_name=self._config.wiki_name,
            backend=self._config.backend,
            sqlite_policy=sqlite_policy_from_config(self._config),
        )

    async def for_symbol(self, symbol: str, include_history: bool = False, limit: int = 10) -> dict[str, Any]:
        """Find the architectural decisions that apply to a symbol.

        Returns two separate groups: ``documented`` (real ADRs, with their
        declared lifecycle status) and ``candidates`` (INFERRED hypotheses
        that no maintainer has accepted). Every hit carries its origin,
        status, freshness and at least one source citation.

        Args:
            symbol: A ``sym:<rel>#<qualname>`` id, or an exact symbol name.
                An ambiguous name returns ``status='ambiguous'`` with the
                candidate ids rather than guessing.
            include_history: Also return rejected, deprecated and superseded
                records.
            limit: Maximum hits across both groups.

        Returns:
            A ``DecisionDossier`` as a JSON-safe dict.

        Raises:
            DecisionError: With a stable ``ADR_*`` code.
        """
        dossier = await self._service.for_symbol(symbol, include_history=include_history, limit=limit)
        return dossier.model_dump(mode="json")

    async def why(self, question: str, include_history: bool = False, limit: int = 10) -> dict[str, Any]:
        """Answer a 'why is it built this way' question with cited decisions.

        Documented decisions rank above inferred candidates and the two
        groups are never merged. Citations prove what the code does; a
        candidate's ``hypotheses`` are reasoning, not history.

        Args:
            question: Natural language; it need not name a symbol.
            include_history: Also return rejected/deprecated/superseded records.
            limit: Maximum hits across both groups.

        Returns:
            A ``DecisionDossier`` as a JSON-safe dict.

        Raises:
            DecisionError: With a stable ``ADR_*`` code.
        """
        dossier = await self._service.why(question, include_history=include_history, limit=limit)
        return dossier.model_dump(mode="json")
