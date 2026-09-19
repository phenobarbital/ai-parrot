"""``DecisionToolkit`` — agent-facing surface over ``DecisionService``.

Mirrors :class:`~parrot.knowledge.wiki.structural.toolkit.CodeStructuralToolkit`:
resolve (or accept) a root, config and store, then expose public async
methods that ``AbstractToolkit`` converts into tools.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from parrot.knowledge.wiki.decisions.service import DecisionService
from parrot.knowledge.wiki.project import (
    WikiProjectConfig,
    find_project_root,
    load_effective_config,
    sqlite_policy_from_config,
)
from parrot.knowledge.wiki.store import BaseWikiStore, create_wiki_store
from parrot.tools.toolkit import AbstractToolkit


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
