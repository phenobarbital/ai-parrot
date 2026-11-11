"""PageIndex tools over the Bookstore library (project + global) with Bookstore's write policy (FEAT-876).

:class:`LibraryPageIndexToolkit` serves the full ``pageindex_*`` tool surface (same names, parameters and
docstrings as :class:`~parrot.knowledge.pageindex.toolkit.PageIndexToolkit`) over every resolved library
scope. Each call is routed to the scope that owns the target tree and checked against the policy table of the
FEAT-876 spec (§2):

====================  ===========================================  ==========================
Target tree           Structural ops                               Node ops
====================  ===========================================  ==========================
catalogued book       denied                                       denied
notebook              ``rename_tree`` / ``delete_tree`` denied     allowed
uncatalogued (free)   allowed                                      allowed
====================  ===========================================  ==========================

A tree is classified by name **and** catalog: ``_library_notes``, or ``<X>_notes`` where ``X`` is a catalogued
book, is a notebook even before Bookstore lazily registers its row (design-research S2). The facade reads the
catalog but never writes ``library.db``.
"""

from __future__ import annotations

import functools
import inspect
import logging
from pathlib import Path
from typing import Any, Callable, Optional

from parrot.knowledge.pageindex.store import JSONTreeStore
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit, PageIndexWriteDenied
from parrot.tools.toolkit import AbstractToolkit

from .config import resolve_locations
from .library import LIBRARY_NOTEBOOK, NOTEBOOK_SUFFIX, Bookstore, _is_reserved_tree_name
from .models import BookCard

logger = logging.getLogger(__name__)

_STRUCTURAL_DENIED_FOR_NOTES = frozenset({"rename_tree", "delete_tree"})

#: Single-tree PageIndex tools that only read; delegated after routing, never authorized.
_READ_DELEGATES: tuple[str, ...] = (
    "get_tree",
    "get_generation",
    "list_documents",
    "outline",
    "read_pages",
    "read_segments",
    "agentic_retrieve",
)
#: Single-tree PageIndex tools that write; ``_authorize(tree_name, op)`` runs before delegating.
_WRITE_DELEGATES: tuple[str, ...] = (
    "delete_tree",
    "vacuum_tree",
    "optimize",
    "index_segments",
    "insert_markdown",
    "insert_ebook",
    "insert_content",
    "import_file",
    "import_pdf",
    "import_folder",
    "tag_node",
    "add_node",
    "update_node",
    "update_node_content",
    "delete_node",
)


def _bound_parts(parts: list[str], limit: Optional[int]) -> str:
    """Join retrieve sections and bound the text to ``limit`` characters.

    Keeps whole sections while they fit; when the first section alone exceeds the bound it is cut at the last
    paragraph break before the bound (never inside its ``## title`` line). A trailer names what was dropped.

    Args:
        parts: ``"## title\\nbody"`` sections in rank order.
        limit: Maximum characters, or ``None`` for unbounded.

    Returns:
        The joined (possibly truncated) text.
    """
    joined = "\n\n".join(parts)
    if limit is None or len(joined) <= limit:
        return joined
    kept_parts: list[str] = []
    for part in parts:
        if len("\n\n".join([*kept_parts, part])) > limit:
            break
        kept_parts.append(part)
    first_cut = not kept_parts
    if kept_parts:
        kept = "\n\n".join(kept_parts)
        dropped_parts = len(parts) - len(kept_parts)
    else:
        first = parts[0]
        title_end = first.find("\n")
        title_end = len(first) if title_end == -1 else title_end
        cut = first.rfind("\n\n", title_end, max(limit, title_end))
        kept = first[:cut] if cut != -1 else first[: max(limit, title_end)]
        dropped_parts = len(parts) - 1
    dropped_chars = len(joined) - len(kept)
    if not first_cut:
        where = f"in {dropped_parts} further sections"
    elif dropped_parts:
        where = f"in this section and {dropped_parts} further sections"
    else:
        where = "in this section"
    return f"{kept}\n\n[truncated: {dropped_chars} more characters {where} — lower top_k or narrow the query]"


class LibraryPageIndexToolkit(AbstractToolkit):
    """pageindex_* tools over the project + global libraries, with Bookstore's write policy.

    Args:
        project_root: Directory the project library is resolved from (``resolve_locations(cwd=...)``);
            ``None`` uses the process CWD. ``PARROT_LIBRARY_DIR`` / ``PARROT_HOME`` apply as usual.
        llm_client: Optional :class:`~parrot.clients.base.AbstractClient` (what ``parrot mcp-local`` passes
            when the section has ``llm:``); wrapped into a PageIndex LLM adapter. ``None`` = no LLM: search and
            retrieve run BM25-only.
        lightweight_model: Optional cheap model id (same provider as ``llm_client``).
        max_result_chars: Upper bound on the text :meth:`retrieve` returns; ``None`` = unbounded.
        **kwargs: Forwarded to :class:`AbstractToolkit`.
    """

    name = "pageindex-library"
    tool_prefix = "pageindex"
    llm_dependent_tools: frozenset[str] = PageIndexToolkit.llm_dependent_tools

    def __init__(
        self,
        project_root: Optional[str | Path] = None,
        llm_client: Optional[Any] = None,
        lightweight_model: Optional[str] = None,
        max_result_chars: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.logger = logger
        adapter = None
        if llm_client is not None:
            # Same construction as bookstore/_llm.resolve_adapter (the bookstore CLI and MCP server path).
            from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter

            adapter = PageIndexLLMAdapter(llm_client, model=getattr(llm_client, "model", None))
        cwd = Path(project_root).expanduser() if project_root is not None else None
        self._store = Bookstore(resolve_locations(cwd), adapter=adapter, lightweight_model=lightweight_model)
        self._max_result_chars = max_result_chars

    # ------------------------------------------------------------------
    # Routing and policy
    # ------------------------------------------------------------------
    def _scopes(self) -> list[str]:
        """Scopes in precedence order (project first)."""
        return [loc.scope for loc in self._store.locations]

    def _tree_exists(self, scope: str, tree_name: str) -> bool:
        """Whether ``tree_name`` is on disk in ``scope`` (never creates the trees directory)."""
        trees_dir = self._store._location(scope).trees_dir
        if not trees_dir.is_dir():
            return False
        return JSONTreeStore(trees_dir).exists(tree_name)

    def _tree_names(self, scope: str) -> list[str]:
        """Non-reserved tree names on disk in ``scope``."""
        trees_dir = self._store._location(scope).trees_dir
        if not trees_dir.is_dir():
            return []
        return [name for name in JSONTreeStore(trees_dir).list_names() if not _is_reserved_tree_name(name)]

    def _cards(self, scope: str) -> list[BookCard]:
        """Every catalog row of ``scope`` (books and notebooks); ``[]`` when the scope has no ``library.db``.

        Read-only: a missing catalog is never created here.
        """
        if not self._store._location(scope).exists():
            return []
        return self._store._catalog(scope).list_cards(kind=None)

    @staticmethod
    def _kind_of(card: BookCard) -> str:
        return "notes" if card.kind == "notes" else "book"

    def _catalogued_book_scope(self, book_id: str, cards: dict[str, list[BookCard]]) -> Optional[str]:
        """First scope (project first) where ``book_id`` is a catalogued book."""
        for scope in self._scopes():
            for card in cards[scope]:
                if card.kind == "book" and (card.book_id == book_id or card.tree_name == book_id):
                    return scope
        return None

    def _classify(self, tree_name: str) -> tuple[str, Optional[BookCard], str]:
        """``(scope, card, kind)`` for ``tree_name`` (see :meth:`_resolve`)."""
        scopes = self._scopes()
        cards = {scope: self._cards(scope) for scope in scopes}
        # 1. A catalogued row decides (project first).
        for scope in scopes:
            for card in cards[scope]:
                if card.tree_name == tree_name:
                    return scope, card.model_copy(update={"scope": scope}), self._kind_of(card)
        # 2. Name rule (S2): notebooks are notebooks before their row exists.
        if tree_name == LIBRARY_NOTEBOOK:
            holders = [scope for scope in scopes if self._tree_exists(scope, tree_name)]
            return (holders[0] if holders else scopes[0]), None, "notes"
        if tree_name.endswith(NOTEBOOK_SUFFIX) and len(tree_name) > len(NOTEBOOK_SUFFIX):
            book_scope = self._catalogued_book_scope(tree_name[: -len(NOTEBOOK_SUFFIX)], cards)
            if book_scope is not None:
                return book_scope, None, "notes"
        # 3. Free tree: where it exists (project first), else the first scope.
        for scope in scopes:
            if self._tree_exists(scope, tree_name):
                return scope, None, "free"
        return scopes[0], None, "free"

    def _resolve(self, tree_name: str) -> tuple[str, Optional[BookCard], str, PageIndexToolkit]:
        """``(scope, card, kind, toolkit)`` with ``kind`` in ``{book, notes, free}`` (spec §2, S2)."""
        scope, card, kind = self._classify(tree_name)
        return scope, card, kind, self._store._toolkit(scope)

    def _authorize(self, tree_name: str, op: str) -> None:
        """Apply the policy table; raise PageIndexWriteDenied with a ``<id>_notes`` hint for books."""
        if isinstance(tree_name, str) and _is_reserved_tree_name(tree_name):
            raise PageIndexWriteDenied(f"{tree_name!r} is a reserved Bookstore tree name: {op} is not allowed")
        scope, card, kind = self._classify(tree_name)
        if kind == "book":
            book_id = card.book_id if card is not None else tree_name
            raise PageIndexWriteDenied(
                f"{tree_name!r} is a Bookstore book (read-only evidence). "
                f"Write notes in {book_id + NOTEBOOK_SUFFIX!r} instead."
            )
        if kind == "notes" and op in _STRUCTURAL_DENIED_FOR_NOTES:
            raise PageIndexWriteDenied(f"{tree_name!r} is a Bookstore notebook: {op} is not allowed")

    async def _toolkit_for(self, tree_name: str) -> PageIndexToolkit:
        """The ready (reserved-tree-swept) toolkit of the scope that owns ``tree_name``."""
        scope, _, _ = self._classify(tree_name)
        return await self._store._ready_toolkit(scope)

    # ------------------------------------------------------------------
    # Routed tools
    # ------------------------------------------------------------------
    async def list_trees(self) -> list[str]:
        """List all PageIndex tree names available in the library (project and global)."""
        names: set[str] = set()
        for scope in self._scopes():
            names.update(self._tree_names(scope))
        return sorted(names)

    async def list_library_trees(self) -> list[dict[str, Any]]:
        """List library trees with their scope and kind (book, notes or free)."""
        scopes = self._scopes()
        cards = {scope: self._cards(scope) for scope in scopes}
        listing: list[dict[str, Any]] = []
        for scope in scopes:
            by_tree = {card.tree_name: card for card in cards[scope]}
            for tree_name in self._tree_names(scope):
                card = by_tree.get(tree_name)
                if card is not None:
                    kind = self._kind_of(card)
                elif tree_name == LIBRARY_NOTEBOOK:
                    kind = "notes"
                elif (
                    tree_name.endswith(NOTEBOOK_SUFFIX)
                    and len(tree_name) > len(NOTEBOOK_SUFFIX)
                    and self._catalogued_book_scope(tree_name[: -len(NOTEBOOK_SUFFIX)], cards) is not None
                ):
                    kind = "notes"
                else:
                    kind = "free"
                listing.append({"tree_name": tree_name, "scope": scope, "kind": kind})
        return listing

    async def create_tree(
        self, tree_name: str, doc_name: Optional[str] = None, scope: str = "project"
    ) -> dict[str, Any]:
        """Create an empty tree in the project (default) or global library.

        Args:
            tree_name: Unique name for the tree (filesystem-safe).
            doc_name: Optional display name for the tree's root document.
            scope: Library scope to create the tree in: ``"project"`` (default) or ``"global"``.
        """
        if scope not in self._scopes():
            raise ValueError(f"Unknown library scope {scope!r}; available: {self._scopes()}")
        self._authorize(tree_name, "create_tree")
        owner_scope, card, kind = self._classify(tree_name)
        # A book notebook (or any catalogued notebook) lives in its owner's scope; only the per-scope
        # ``_library_notes`` may be created in either scope.
        if kind == "notes" and tree_name != LIBRARY_NOTEBOOK and owner_scope != scope:
            raise PageIndexWriteDenied(
                f"{tree_name!r} is a Bookstore notebook of the {owner_scope} library; create it with scope={owner_scope!r}"
            )
        toolkit = await self._store._ready_toolkit(scope)
        return await toolkit.create_tree(tree_name, doc_name)

    async def rename_tree(self, src: str, dst: str, *, overwrite: bool = False) -> dict[str, Any]:
        """Rename a tree inside one library scope."""
        self._authorize(src, "rename_tree")
        self._authorize(dst, "rename_tree")
        src_scope, _, _ = self._classify(src)
        holders = [scope for scope in self._scopes() if self._tree_exists(scope, dst)]
        if holders and src_scope not in holders:
            raise PageIndexWriteDenied(
                f"cannot rename {src!r} ({src_scope} library) onto {dst!r} ({holders[0]} library): "
                "both trees must be in the same library scope"
            )
        toolkit = await self._store._ready_toolkit(src_scope)
        return await toolkit.rename_tree(src, dst, overwrite=overwrite)

    async def search(
        self,
        tree_name: str,
        query: str,
        top_k: int = 10,
        use_bm25: bool = True,
        use_llm_walk: Optional[bool] = None,
        rerank: bool = False,
        categories: Optional[list[str]] = None,
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Hybrid search over a tree.

        Returns ordered candidates, each ``{node_id, title, summary, score, source}``.
        ``source`` is one of ``"bm25"``, ``"llm"``, ``"fused"``, ``"reranked"``.

        Args:
            use_llm_walk: Run the LLM tree walk; defaults to whether this server has an LLM configured.
            categories: When set, candidates whose node does NOT carry
                **all** of the listed categories are filtered out
                (AND-semantics).
            metadata_filter: When set, candidates whose node metadata
                does not have ``metadata[k] == v`` for every ``(k, v)``
                in the dict are filtered out (equality-only).
        """
        if use_llm_walk is None:
            use_llm_walk = self._store.has_llm
        toolkit = await self._toolkit_for(tree_name)
        return await toolkit.search(
            tree_name,
            query,
            top_k=top_k,
            use_bm25=use_bm25,
            use_llm_walk=use_llm_walk,
            rerank=rerank,
            categories=categories,
            metadata_filter=metadata_filter,
        )

    async def retrieve(
        self,
        tree_name: str,
        query: str,
        top_k: int = 5,
    ) -> str:
        """Hybrid search + per-node markdown aggregation.

        Loads each result's markdown from :class:`NodeContentStore`. Falls
        back to summary text only when the content sidecar is missing
        (e.g. a tree imported before this feature).
        """
        scope, _, _ = self._classify(tree_name)
        toolkit = await self._store._ready_toolkit(scope)
        # BM25 (+ the LLM walk only when a real model is configured: Bookstore's toolkits carry a
        # _NullAdapter otherwise, which would make PageIndex's own retrieve attempt the walk and fail).
        candidates = await toolkit.search(
            tree_name,
            query,
            top_k=top_k,
            use_bm25=True,
            use_llm_walk=self._store.has_llm,
            rerank=False,
        )
        if not candidates:
            return ""
        content = self._store._content_store(scope)
        parts: list[str] = []
        for cand in candidates:
            title = cand.get("title") or "Section"
            body = content.load_current(tree_name, cand["node_id"])
            if not body:
                body = cand.get("summary") or ""
            if body:
                parts.append(f"## {title}\n{body}")
        return _bound_parts(parts, self._max_result_chars)

    async def search_documents_scoped(
        self,
        tree_names: list[str],
        query: str,
        include_tree_context: bool = False,
        max_trees: int = 10,
    ) -> dict[str, Any]:
        """Run an LLM tree-walk against a SUBSET of trees in one call.

        Trees are grouped by library scope and each group is searched by
        that scope's PageIndex toolkit; results keep the input order.
        Missing tree names are skipped. Returns ``{"status": "empty", ...}``
        when the input is empty or every name is missing.

        Args:
            tree_names: Tree names to search. Order is preserved.
            query: Free-form natural-language query.
            include_tree_context: When ``True``, each result entry
                carries the per-tree ``tree_context`` blob.
            max_trees: Hard cap on the number of trees searched
                (default and max: 10).

        Returns:
            ``{"status": "ok"|"empty", "scoped_results": [...]}`` with one
            ``{tree_name, doc_name, node_list, thinking, context[, tree_context]}``
            entry per searched tree.
        """
        if not tree_names:
            return {"status": "empty", "scoped_results": []}
        effective = list(tree_names[:max_trees])
        groups: dict[str, list[str]] = {}
        for tree_name in effective:
            scope, _, _ = self._classify(tree_name)
            groups.setdefault(scope, []).append(tree_name)
        merged: list[dict[str, Any]] = []
        for scope, names in groups.items():
            toolkit = await self._store._ready_toolkit(scope)
            result = await toolkit.search_documents_scoped(
                names, query, include_tree_context=include_tree_context, max_trees=max_trees
            )
            merged.extend(result.get("scoped_results") or [])
        order = {name: index for index, name in enumerate(effective)}
        merged.sort(key=lambda entry: order.get(entry.get("tree_name"), len(order)))
        if not merged:
            return {"status": "empty", "scoped_results": []}
        return {"status": "ok", "scoped_results": merged}


def _make_delegator(name: str, write: bool) -> Callable[..., Any]:
    """Build a routed delegator with ``PageIndexToolkit.<name>``'s signature and docstring.

    Args:
        name: Unprefixed PageIndex tool name.
        write: Whether the tool mutates its tree (``_authorize`` runs first).

    Returns:
        The ``async def`` to install on :class:`LibraryPageIndexToolkit`.
    """
    target = getattr(PageIndexToolkit, name)
    signature = inspect.signature(target)

    @functools.wraps(target)
    async def delegator(self: LibraryPageIndexToolkit, *args: Any, **kwargs: Any) -> Any:
        bound = signature.bind(self, *args, **kwargs)
        tree_name = bound.arguments["tree_name"]
        # optimize(apply=False) only plans — a read.
        if write and (name != "optimize" or bound.arguments.get("apply", False)):
            self._authorize(tree_name, name)
        toolkit = await self._toolkit_for(tree_name)
        return await getattr(toolkit, name)(*bound.args[1:], **bound.kwargs)

    return delegator


for _name in _READ_DELEGATES:
    setattr(LibraryPageIndexToolkit, _name, _make_delegator(_name, write=False))
for _name in _WRITE_DELEGATES:
    setattr(LibraryPageIndexToolkit, _name, _make_delegator(_name, write=True))
del _name
