"""Agent-facing toolkit for PageIndex.

This toolkit lets an Agent manage one or more named PageIndex trees:
search them (hybrid BM25 + LLM-walk), retrieve aggregated text,
insert new pages from raw content (Two-Step Chain-of-Thought ingest),
and import whole folders preserving directory structure.

Per-tree storage is split into two artefacts:

    <storage_dir>/<tree_name>.json   — lean ToC tree (titles, summaries,
                                       categories, metadata)
    <storage_dir>/<tree_name>/       — sidecar markdown, one .md per node,
                                       served by NodeContentStore

This matches the upstream PageIndex contract: vectorless retrieval over
a hierarchical index, with bodies fetched on demand by node_id.
"""

from __future__ import annotations

import asyncio
import copy
import fnmatch
import logging
import random
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, TypeVar

from parrot.tools.toolkit import AbstractToolkit
from .builder import build_page_index
from .content_store import NodeContentStore
from .embedding_store import NodeEmbeddingStore
from .generation import StaleGenerationError, WriteTransaction, generation_of
from .hybrid_search import HybridPageIndexSearch
from .ingest import IngestedMarkdown, TwoStepIngester
from .llm_adapter import PageIndexLLMAdapter
from .md_builder import md_to_tree
from .retriever import PageIndexRetriever
from .locks import lock_path, tree_lock
from .store import JSONTreeStore
from .tree_ops import (
    delete_node as _delete_node,
    make_folder_node,
    splice_subtree,
)
from .utils import find_node_by_id, structure_to_list
from parrot.knowledge.okf.utils import flatten_concept_id_for_filename
from parrot.knowledge.pageindex.okf.projection import _strip_frontmatter

logger = logging.getLogger("parrot.knowledge.pageindex.toolkit")

_MAX_TREES_HARD_CAP = 10
REPLACED_MARKER = "--replaced-"
_REPLACED_MARKER = REPLACED_MARKER  # backwards-compatible alias
T = TypeVar("T")
_OPEN_TXNS: ContextVar[Optional[dict[tuple[int, str], WriteTransaction]]] = ContextVar(
    "pageindex_open_txns", default=None
)


class PageIndexToolkit(AbstractToolkit):
    """Toolkit exposing search / retrieve / insert tools over PageIndex trees.

    Args:
        adapter: Heavy LLM adapter. Used for Step-2 markdown generation,
            tree-walk search, and node summarisation via :func:`md_to_tree`.
        storage_dir: Filesystem directory where each tree is persisted as
            ``<tree_name>.json``.
        reranker: Optional :class:`AbstractReranker` instance applied to
            the fused candidate set when ``rerank=True`` is requested.
        lightweight_model: Model id used for the cheaper helper calls —
            Step-1 Chain-of-Thought analysis during text ingest, and during
            ``import_pdf``: TOC-page detection, per-node summaries, doc
            description, title verification, and TOC accuracy checks. A
            second :class:`PageIndexLLMAdapter` is built with this model,
            sharing the same underlying client; ``adapter`` is never
            mutated.
        model: Optional override for the model passed to
            :class:`PageIndexRetriever`. Defaults to ``adapter.model``.
        default_bm25_k: Number of BM25 candidates fetched per query.
        folder_concurrency: Maximum concurrent file ingests during
            ``import_folder``.
        embedding_model: Sentence-Transformers model identifier for
            dense node embeddings (FEAT-237).  Defaults to the
            ``EMBEDDING_DEFAULT_MODEL`` config value when embedding is
            enabled.
        embedding_dimension: Dimensionality of the embedding vectors.
            Must match the selected model's output (or MRL truncation dim).
        embedding_backend: Optional runtime backend for
            ``SentenceTransformerModel`` — ``"onnx"``, ``"openvino"``, or
            ``None`` (default torch).
        use_vec_rank: Enable Phase A dense cosine-similarity ranking signal.
        use_embedding_walk: Enable Phase B embedding-guided beam walk.
    """

    name = "pageindex"
    tool_prefix = "pageindex"

    def __init__(
        self,
        adapter: PageIndexLLMAdapter,
        storage_dir: str | Path,
        reranker: Optional[Any] = None,
        lightweight_model: Optional[str] = None,
        model: Optional[str] = None,
        default_bm25_k: int = 20,
        folder_concurrency: int = 4,
        content_cache_size: int = 256,
        embedding_model: Optional[str] = None,
        embedding_dimension: int = 256,
        embedding_backend: Optional[str] = None,
        use_vec_rank: bool = False,
        use_embedding_walk: bool = False,
        generation_grace_s: int = 3600,
        lock_timeout_s: float = 30.0,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._adapter = adapter
        self._storage_dir = Path(storage_dir)
        self._generation_grace_s = generation_grace_s
        self._lock_timeout_s = lock_timeout_s
        self._light_adapter: Optional[PageIndexLLMAdapter] = (
            PageIndexLLMAdapter(client=adapter.client, model=lightweight_model) if lightweight_model else None
        )
        self._store = JSONTreeStore(storage_dir)
        self._content_store = NodeContentStore(storage_dir, cache_size=content_cache_size)
        self._reranker = reranker
        self._model = model or adapter.model
        self._default_bm25_k = default_bm25_k
        self._folder_concurrency = max(1, folder_concurrency)
        self._use_vec_rank = use_vec_rank
        self._use_embedding_walk = use_embedding_walk

        # ---- Embedding store (FEAT-237) ---------------------------------
        # Constructed only when at least one embedding feature is enabled.
        # When both are False, behaviour is identical to pre-FEAT-237.
        self._embedding_store: Optional[NodeEmbeddingStore] = None
        self._embed_fn = None
        if use_vec_rank or use_embedding_walk:
            from parrot.conf import EMBEDDING_DEFAULT_MODEL
            from parrot.embeddings.registry import EmbeddingRegistry

            emb_model_name = embedding_model or EMBEDDING_DEFAULT_MODEL
            self._embedding_store = NodeEmbeddingStore(
                storage_dir=storage_dir,
                model_id=emb_model_name,
                dimension=embedding_dimension,
            )
            _backend = embedding_backend  # closure captures value

            def _make_embed_fn(name: str, backend: Optional[str]):
                """Return a lazy-loading sync embed function."""
                _raw_model = None

                def _embed(texts: list[str]):
                    nonlocal _raw_model
                    if _raw_model is None:
                        registry = EmbeddingRegistry.instance()
                        kw = {}
                        if backend is not None:
                            kw["backend"] = backend
                        wrapper = registry.get_or_create_sync(name, "huggingface", **kw)
                        _raw_model = wrapper.model  # underlying SentenceTransformer
                    import numpy as _np

                    result = _raw_model.encode(texts, convert_to_numpy=True)
                    return _np.asarray(result, dtype=_np.float32)

                return _embed

            self._embed_fn = _make_embed_fn(emb_model_name, _backend)

        self._trees: dict[str, dict[str, Any]] = {}
        # FEAT-647: on-disk signature (st_mtime_ns, st_size) of each cached tree,
        # so trees rewritten by another toolkit/process are reloaded on read.
        self._tree_sigs: dict[str, tuple[int, int]] = {}
        self._search: dict[str, HybridPageIndexSearch] = {}

        # OKF integration (FEAT-238) — optional per-tree OKF toolkits.
        # Populated via set_okf_toolkit() or lazily by _get_or_build_okf_toolkit().
        self._okf_toolkits: dict[str, Any] = {}

    # ---- internal helpers ----------------------------------------------

    @asynccontextmanager
    async def _write(self, tree_name: str) -> AsyncIterator[WriteTransaction]:
        """Open (or join) the copy-on-write transaction for ``tree_name``; publish on clean outermost exit."""
        open_txns = _OPEN_TXNS.get() or {}
        key = (id(self), tree_name)
        if key in open_txns:
            yield open_txns[key]
            return
        base = self._load_tree(tree_name)
        txn = WriteTransaction(
            tree_name=tree_name,
            base_tree=base,
            base_signature=self._tree_sigs.get(tree_name),
            store=self._store,
            content_store=self._content_store,
            storage_dir=self._storage_dir,
            lock_timeout_s=self._lock_timeout_s,
            grace_s=self._generation_grace_s,
            projector=self._project_okf_sidecars_for,
        )
        if generation_of(base) is None:
            self._migrate_legacy_bodies(tree_name, txn)
        token = _OPEN_TXNS.set({**open_txns, key: txn})
        try:
            yield txn
        finally:
            _OPEN_TXNS.reset(token)
        if txn.noop:
            return
        await txn.publish()
        self._after_publish(tree_name, txn)

    def _after_publish(self, tree_name: str, txn: WriteTransaction) -> None:
        """Swap in-process state to the generation ``txn`` just published (spec §2 step 7)."""
        generation = generation_of(txn.tree)
        if generation is None:
            raise RuntimeError("published tree is missing generation metadata")
        self._trees[tree_name] = txn.tree
        self._tree_sigs[tree_name] = txn.published_signature
        self._search.pop(tree_name, None)
        self._content_store._cache_evict_tree(tree_name)
        self._okf_toolkits.pop(tree_name, None)
        if self._embedding_store is not None:
            keep = {generation.id}
            if txn.base_generation is not None:
                keep.add(txn.base_generation.id)
            self._embedding_store.prune_tree_matrices(tree_name, keep=keep)

    def _drop_cached(self, tree_name: str) -> None:
        """Forget every in-process view of ``tree_name`` so the next write re-snapshots the live generation."""
        self._trees.pop(tree_name, None)
        self._tree_sigs.pop(tree_name, None)
        self._search.pop(tree_name, None)
        self._content_store._cache_evict_tree(tree_name)
        self._okf_toolkits.pop(tree_name, None)

    async def _mutate(
        self,
        tree_name: str,
        apply: Callable[[WriteTransaction], Awaitable[T]],
        *,
        attempts: int = 3,
    ) -> T:
        """Run ``apply`` in a transaction; retry on StaleGenerationError when not joined."""
        key = (id(self), tree_name)
        if key in (_OPEN_TXNS.get() or {}):
            async with self._write(tree_name) as txn:
                result = await apply(txn)
                # A joined mutator is one step of a larger write: its "nothing changed"
                # must never suppress the owner's publication.
                txn.noop = False
                return result

        for attempt in range(max(1, attempts)):
            try:
                async with self._write(tree_name) as txn:
                    result = await apply(txn)
                return result
            except StaleGenerationError:
                self._drop_cached(tree_name)
                if attempt + 1 >= max(1, attempts):
                    raise
                # Jittered backoff so contending writers do not all re-snapshot in lockstep.
                await asyncio.sleep(random.uniform(0.005, 0.03) * (attempt + 1))
        raise RuntimeError("unreachable")

    def _migrate_legacy_bodies(self, tree_name: str, txn: WriteTransaction) -> None:
        """Stage every legacy body of a pre-FEAT-831 tree so its first publish assigns ``body_ref``."""
        for node in structure_to_list(txn.tree.get("structure", [])):
            if node.get("body_ref"):
                continue
            body = self._legacy_body(tree_name, node)
            if body is not None:
                txn.set_body(node, body)

    def _legacy_body(self, tree_name: str, node: dict[str, Any]) -> Optional[str]:
        """Return a pre-FEAT-831 node's body, in the same order ``NodeContentStore.load_node`` resolves it.

        The OKF flat-concept sidecar wins (frontmatter stripped), then ``<node_id>.md``.
        """
        concept_id = node.get("concept_id")
        if isinstance(concept_id, str) and concept_id:
            flat_body = self._content_store.load(tree_name, flatten_concept_id_for_filename(concept_id))
            if flat_body is not None:
                return _strip_frontmatter(flat_body)
        node_id = node.get("node_id")
        return self._content_store.load(tree_name, node_id) if isinstance(node_id, str) and node_id else None

    def _ingester(self) -> TwoStepIngester:
        return TwoStepIngester(
            adapter=self._adapter,
            lightweight_adapter=self._light_adapter,
        )

    def _load_tree(self, tree_name: str) -> dict[str, Any]:
        cached = self._trees.get(tree_name)
        if cached is not None:
            if self._store.signature(tree_name) == self._tree_sigs.get(tree_name):
                return cached
            logger.debug("PageIndex tree %r changed on disk; reloading", tree_name)
            self._trees.pop(tree_name, None)
            self._search.pop(tree_name, None)
            self._content_store._cache_evict_tree(tree_name)
            self._okf_toolkits.pop(tree_name, None)
            self._tree_sigs.pop(tree_name, None)
        if not self._store.exists(tree_name):
            raise KeyError(f"Tree {tree_name!r} does not exist")
        tree = self._store.load(tree_name)
        self._trees[tree_name] = tree
        signature = self._store.signature(tree_name)
        if signature is not None:
            self._tree_sigs[tree_name] = signature
        return tree

    def _search_for(self, tree_name: str) -> HybridPageIndexSearch:
        tree = self._load_tree(tree_name)
        engine = self._search.get(tree_name)
        generation_id = (tree.get("generation") or {}).get("id", 0)
        if engine is None or engine.generation_id != generation_id:
            engine = HybridPageIndexSearch(
                tree=tree,
                adapter=self._adapter,
                reranker=self._reranker,
                model=self._model,
                default_bm25_k=self._default_bm25_k,
                content_loader=self._content_store.loader_for(tree_name, tree),
                embedding_store=self._embedding_store,
                embed_fn=self._embed_fn,
                use_vec_rank=self._use_vec_rank,
                use_embedding_walk=self._use_embedding_walk,
                tree_name=tree_name,
                generation_id=generation_id,
            )
            self._search[tree_name] = engine
        return engine

    def _project_okf_sidecars(self, tree_name: str, tree: dict[str, Any]) -> bool:
        """Trigger OKF sidecar projection if the tree is OKF-enriched.

        A tree is considered OKF-enriched when at least one node carries
        **both** a ``concept_id`` AND a ``type`` field — i.e. it has been
        through at least one ``okf_migrate`` pass or a T3 classification.
        Trees that only have ``concept_id`` (auto-assigned by
        ``splice_subtree``) but no ``type`` are NOT projected so that
        pre-migration trees keep their plain ``node_id.md`` sidecar layout.

        Args:
            tree_name: PageIndex tree name.
            tree: The current in-memory tree dict.
        """
        structure = tree.get("structure")
        if not structure:
            return False
        nodes = structure_to_list(structure)
        # Require at least one node with BOTH concept_id AND type to trigger
        # projection.  This preserves backward compatibility for trees that
        # received auto-assigned concept_ids from splice_subtree but were not
        # run through okf_migrate / T3 classification.
        if not any(n.get("concept_id") and n.get("type") for n in nodes):
            return False
        from parrot.knowledge.pageindex.okf.projection import project_sidecars

        project_sidecars(tree, tree_name, self._content_store)
        return True

    def _project_okf_sidecars_for(self, tree: dict[str, Any], tree_name: str) -> bool:
        """Adapt the transaction projector contract to the toolkit helper."""
        return self._project_okf_sidecars(tree_name, tree)

    async def _run_t3_classification(
        self,
        tree: dict[str, Any],
        original_id_to_node: dict[str, dict[str, Any]],
    ) -> None:
        """Classify the OKF ``type`` for newly spliced nodes (T3 step).

        T3 classification only runs when the tree is **OKF-enriched** — i.e.
        at least one existing node already carries a ``type`` field,
        indicating the tree has been through ``okf_migrate`` at least once.
        This preserves backward compatibility: fresh trees that have not been
        OKF-migrated are left untouched.

        Only nodes that are missing a ``type`` field are classified — existing
        types are preserved.

        Falls back to ``ConceptType.SECTION`` when:
        - the OKF subpackage is not installed;
        - the tree has no prior OKF enrichment;
        - the LLM adapter call fails.

        This method never raises — failures are logged and silently ignored so
        the ingest pipeline always completes.

        Args:
            tree: Full in-memory tree dict (concept_ids already assigned).
            original_id_to_node: Map of pre-splice ``node_id`` → node-dict
                reference (unused directly; kept for signature stability).
        """
        try:
            from parrot.knowledge.pageindex.okf.ontology import ConceptType
            from parrot.knowledge.pageindex.utils import structure_to_list
        except ImportError:
            return

        structure = tree.get("structure") or []
        all_nodes = structure_to_list(structure)

        # Gate: only proceed if the tree already has some OKF-typed nodes.
        # This ensures we don't silently enrich fresh non-migrated trees.
        if not any(n.get("type") for n in all_nodes):
            return

        nodes_to_classify = [n for n in all_nodes if not n.get("type")]
        if not nodes_to_classify:
            return

        cache: dict[str, str] = {}
        for node in nodes_to_classify:
            try:
                if self._adapter is not None:
                    from parrot.knowledge.pageindex.okf.migrate import _classify_type

                    result: str = await _classify_type(node, self._adapter, cache, force_reclassify=False)
                    node["type"] = result
                else:
                    node["type"] = ConceptType.SECTION.value
            except Exception:
                logger.debug(
                    "T3 classification failed for node %r — falling back to Section",
                    node.get("node_id") or node.get("concept_id"),
                )
                node["type"] = ConceptType.SECTION.value

    def set_okf_toolkit(self, tree_name: str, okf_toolkit: Any) -> None:
        """Register an :class:`~parrot.knowledge.pageindex.okf.tools.OKFToolkit`
        for ``tree_name`` so OKF read tools appear in :meth:`get_tools`.

        Args:
            tree_name: The PageIndex tree this toolkit is scoped to.
            okf_toolkit: An ``OKFToolkit`` instance bound to the enriched tree.
        """
        self._okf_toolkits[tree_name] = okf_toolkit

    def get_tools(
        self,
        permission_context: Any = None,
        resolver: Any = None,
    ) -> list:
        """Return all tools, including OKF read tools for enriched trees.

        Extends the base ``AbstractToolkit.get_tools()`` with any
        ``OKFToolkit`` tools registered via :meth:`set_okf_toolkit`.

        Args:
            permission_context: Passed through to super (unused, compat).
            resolver: Passed through to super (unused, compat).

        Returns:
            Combined list of toolkit tools + OKF read tools.
        """
        base_tools = super().get_tools(permission_context, resolver)
        okf_tools: list = []
        for okf_tk in self._okf_toolkits.values():
            try:
                okf_tools.extend(okf_tk.get_tools())
            except Exception:
                logger.debug("Failed to collect OKF tools from toolkit %r", okf_tk)
        return base_tools + okf_tools

    # ---- tool methods --------------------------------------------------

    async def list_trees(self) -> list[str]:
        """List all PageIndex tree names available in the storage directory."""
        return self._store.list_names()

    async def create_tree(
        self,
        tree_name: str,
        doc_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new empty PageIndex tree.

        Args:
            tree_name: Unique name for the tree (filesystem-safe).
            doc_name: Optional display name for the tree's root document.
        """
        tree = {"doc_name": doc_name or tree_name, "structure": []}
        txn = WriteTransaction(
            tree_name=tree_name,
            base_tree=tree,
            base_signature=None,
            store=self._store,
            content_store=self._content_store,
            storage_dir=self._storage_dir,
            lock_timeout_s=self._lock_timeout_s,
            grace_s=self._generation_grace_s,
            projector=self._project_okf_sidecars_for,
        )
        # The existence check and the stale-directory cleanup must be atomic with
        # the publication: outside the lock a concurrent creator's bodies/ could be
        # wiped between the check and the delete.
        async with tree_lock(self._storage_dir, tree_name, timeout=self._lock_timeout_s):
            if self._store.exists(tree_name):
                raise ValueError(f"Tree {tree_name!r} already exists")
            # Defensive: a stale content directory from a previous tree with the
            # same name would silently feed wrong sidecars into retrieval.
            self._content_store.delete_tree(tree_name)
            await txn.publish_locked()
        self._after_publish(tree_name, txn)
        return {"tree_name": tree_name, "doc_name": tree["doc_name"]}

    async def delete_tree(self, tree_name: str) -> dict[str, Any]:
        """Delete a tree JSON and every sidecar markdown file for it."""
        async with tree_lock(self._storage_dir, tree_name, timeout=self._lock_timeout_s):
            tree_removed = self._store.delete(tree_name)
            sidecars_removed = self._content_store.delete_tree(tree_name)
            if self._embedding_store is not None:
                self._embedding_store.invalidate_tree(tree_name)
        self._trees.pop(tree_name, None)
        self._search.pop(tree_name, None)
        self._tree_sigs.pop(tree_name, None)
        self._content_store._cache_evict_tree(tree_name)
        self._okf_toolkits.pop(tree_name, None)
        lock_path(self._storage_dir, tree_name).unlink(missing_ok=True)
        return {
            "tree_name": tree_name,
            "tree_removed": tree_removed,
            "sidecars_removed": sidecars_removed,
        }

    async def rename_tree(
        self,
        src: str,
        dst: str,
        *,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Rename a tree and its sidecars, optionally replacing the destination.

        Args:
            src: Existing filesystem-safe tree name.
            dst: New filesystem-safe tree name, distinct from ``src``.
            overwrite: Replace an existing destination when true.

        Returns:
            Source, destination and whether a destination was replaced.

        Raises:
            KeyError: Source tree does not exist.
            ValueError: Invalid names, identical names, an open write, or a
                destination collision without overwrite.
        """
        self._store._validate_name(src)
        self._store._validate_name(dst)
        if src == dst:
            raise ValueError("src and dst must differ")
        open_txns = _OPEN_TXNS.get() or {}
        if (id(self), src) in open_txns or (id(self), dst) in open_txns:
            raise ValueError("Cannot rename a tree participating in an open write")
        if not self._store.exists(src):
            raise KeyError(f"Tree {src!r} does not exist")

        async with tree_lock(self._storage_dir, src, timeout=self._lock_timeout_s):
            src_tree = self._store.load(src)
            for attempt in range(3):
                # ``dst`` is not locked until publish: re-evaluate it on every attempt so
                # a concurrent writer to ``dst`` is retried, not surfaced as a stale error.
                replaced = self._store.exists(dst)
                if replaced and not overwrite:
                    raise ValueError(f"Tree {dst!r} already exists")
                dst_base = (
                    self._store.load(dst) if replaced else {"doc_name": src_tree.get("doc_name", dst), "structure": []}
                )
                txn = WriteTransaction(
                    tree_name=dst,
                    base_tree=dst_base,
                    base_signature=self._store.signature(dst),
                    store=self._store,
                    content_store=self._content_store,
                    storage_dir=self._storage_dir,
                    lock_timeout_s=self._lock_timeout_s,
                    grace_s=self._generation_grace_s,
                    projector=self._project_okf_sidecars_for,
                )
                txn.tree = copy.deepcopy(src_tree)
                for node in structure_to_list(txn.tree.get("structure", [])):
                    body_ref = node.get("body_ref")
                    if isinstance(body_ref, str) and body_ref:
                        body = self._content_store.load_body(src, body_ref)
                    else:
                        body = self._legacy_body(src, node)
                    if body is not None:
                        txn.set_body(node, body)
                try:
                    report = await txn.publish()
                    break
                except StaleGenerationError:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(random.uniform(0.005, 0.03) * (attempt + 1))
            self._after_publish(dst, txn)

            self._store.delete(src)
            self._content_store.delete_tree(src)
            if self._embedding_store is not None:
                self._embedding_store.invalidate_tree(src)
            self._trees.pop(src, None)
            self._search.pop(src, None)
            self._tree_sigs.pop(src, None)
            self._content_store._cache_evict_tree(src)
            self._okf_toolkits.pop(src, None)
            lock_path(self._storage_dir, src).unlink(missing_ok=True)

        return {"src": src, "dst": dst, "replaced": replaced, "generation": report.generation}

    async def get_tree(self, tree_name: str) -> dict[str, Any]:
        """Return the full tree dict for ``tree_name``."""
        return self._load_tree(tree_name)

    async def get_generation(self, tree_name: str) -> dict[str, Any]:
        """Return the live generation: tree name, id, publish time, and parent generation."""
        generation = generation_of(self._load_tree(tree_name))
        return {
            "tree_name": tree_name,
            "id": generation.id if generation else None,
            "published_at": generation.published_at if generation else None,
            "parent": generation.parent if generation else None,
        }

    async def vacuum_tree(self, tree_name: str, max_age_s: Optional[int] = None) -> dict[str, Any]:
        """Remove old files unreferenced by the live generation of a tree.

        Only files older than the generation grace period are removed unless
        ``max_age_s`` supplies a different age.
        """
        async with tree_lock(self._storage_dir, tree_name, timeout=self._lock_timeout_s):
            tree = self._store.load(tree_name)
            removed = self._content_store.sweep_unreferenced(
                tree_name,
                tree,
                max_age_s=self._generation_grace_s if max_age_s is None else max_age_s,
            )
            if self._embedding_store is not None:
                generation = generation_of(tree)
                self._embedding_store.prune_tree_matrices(tree_name, keep={generation.id} if generation else set())
        return {"tree_name": tree_name, "removed": removed}

    async def search(
        self,
        tree_name: str,
        query: str,
        top_k: int = 10,
        use_bm25: bool = True,
        use_llm_walk: bool = True,
        rerank: bool = False,
        categories: Optional[list[str]] = None,
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Hybrid search over a tree.

        Returns ordered candidates, each ``{node_id, title, summary, score, source}``.
        ``source`` is one of ``"bm25"``, ``"llm"``, ``"fused"``, ``"reranked"``.

        Args:
            categories: When set, candidates whose node does NOT carry
                **all** of the listed categories are filtered out
                (AND-semantics).
            metadata_filter: When set, candidates whose node metadata
                does not have ``metadata[k] == v`` for every ``(k, v)``
                in the dict are filtered out (equality-only).
        """
        engine = self._search_for(tree_name)
        # Over-fetch slightly when filtering so we still return ``top_k``
        # results after the post-filter where possible. The engine itself
        # caps to its own internal bm25 budget.
        fetch_k = top_k
        if categories or metadata_filter:
            fetch_k = max(top_k * 4, top_k)
        results = await engine.search(
            query=query,
            top_k=fetch_k,
            use_bm25=use_bm25,
            use_llm_walk=use_llm_walk,
            rerank=rerank,
            use_vec=self._use_vec_rank,
        )
        if categories or metadata_filter:
            results = self._apply_filters(tree_name, results, categories, metadata_filter)
        return results[:top_k]

    def _apply_filters(
        self,
        tree_name: str,
        results: list[dict[str, Any]],
        categories: Optional[list[str]],
        metadata_filter: Optional[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        tree = self._trees.get(tree_name) or self._store.load(tree_name)
        structure = tree.get("structure", [])
        required_categories = set(categories or [])
        filtered: list[dict[str, Any]] = []
        for cand in results:
            node = find_node_by_id(structure, cand["node_id"]) or {}
            if required_categories:
                node_cats = set(node.get("categories") or [])
                if not required_categories.issubset(node_cats):
                    continue
            if metadata_filter:
                node_meta = node.get("metadata") or {}
                if not all(node_meta.get(k) == v for k, v in metadata_filter.items()):
                    continue
            filtered.append(cand)
        return filtered

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
        candidates = await self.search(
            tree_name=tree_name,
            query=query,
            top_k=top_k,
            use_bm25=True,
            use_llm_walk=True,
            rerank=False,
        )
        if not candidates:
            return ""
        tree = self._load_tree(tree_name)
        structure = tree.get("structure", [])
        parts: list[str] = []
        for cand in candidates:
            node = find_node_by_id(structure, cand["node_id"])
            if not node:
                continue
            title = node.get("title") or "Section"
            body = self._content_store.load_node(tree_name, node)
            if not body:
                body = node.get("text") or node.get("summary") or node.get("prefix_summary") or ""
            if body:
                parts.append(f"## {title}\n{body}")
        return "\n\n".join(parts)

    async def search_documents_scoped(
        self,
        tree_names: list[str],
        query: str,
        include_tree_context: bool = False,
        max_trees: int = _MAX_TREES_HARD_CAP,
    ) -> dict[str, Any]:
        """Run an LLM tree-walk against a SUBSET of trees in one call.

        Iterates over ``tree_names``, runs :class:`PageIndexRetriever`
        per tree (LLM-walk only — no BM25), and assembles a per-tree
        ``context`` string from sidecar markdown loaded via
        :class:`NodeContentStore`. Falls back to summaries when a node
        has no sidecar (e.g. legacy tree).

        Designed for the ontology routing pattern: a graph query
        produces a list of ``Document.pageindex_tree_id`` values, this
        method searches just those trees, the agent grounds its answer
        in the merged result.

        Missing tree names are skipped with a WARNING log. Returns
        ``{"status": "empty", ...}`` when the input is empty or every
        name is missing.

        Args:
            tree_names: Tree names to search. Order is preserved.
            query: Free-form natural-language query.
            include_tree_context: When ``True``, each result entry
                carries the per-tree ``tree_context`` blob from
                :meth:`PageIndexRetriever.get_tree_context`.
            max_trees: Hard cap on the number of trees searched
                (default and max: 10). Names past the cap are dropped
                with a DEBUG log.

        Returns:
            ``{"status": "ok"|"empty", "scoped_results": [...]}``.
            Each entry has::

                {
                    "tree_name": str,
                    "doc_name":  str | None,
                    "node_list": list[str],
                    "thinking":  str,
                    "context":   str,
                    # only when include_tree_context=True:
                    "tree_context": str,
                }
        """
        if not tree_names:
            return {"status": "empty", "scoped_results": []}

        effective = tree_names[:max_trees]
        if len(tree_names) > max_trees:
            logger.debug(
                "search_documents_scoped: capping tree_names from %d to %d",
                len(tree_names),
                max_trees,
            )

        scoped_results: list[dict[str, Any]] = []

        for tree_name in effective:
            if not self._store.exists(tree_name):
                logger.warning(
                    "search_documents_scoped: tree %r not found — skipping",
                    tree_name,
                )
                continue

            tree = self._load_tree(tree_name)
            retriever = PageIndexRetriever(
                tree=tree,
                adapter=self._adapter,
                model=self._model,
            )
            search_result = await retriever.search(query)

            context_parts: list[str] = []
            structure = tree.get("structure", [])
            for node_id in search_result.node_list or []:
                node = find_node_by_id(structure, node_id)
                if not node:
                    continue
                title = node.get("title") or "Section"
                body = self._content_store.load_node(tree_name, node)
                if not body:
                    body = node.get("summary") or node.get("prefix_summary") or ""
                if body:
                    context_parts.append(f"## {title}\n{body}")

            entry: dict[str, Any] = {
                "tree_name": tree_name,
                "doc_name": tree.get("doc_name"),
                "node_list": list(search_result.node_list or []),
                "thinking": search_result.thinking,
                "context": "\n\n".join(context_parts),
            }
            if include_tree_context:
                entry["tree_context"] = retriever.get_tree_context(
                    include_summaries=True,
                )
            scoped_results.append(entry)

        if not scoped_results:
            return {"status": "empty", "scoped_results": []}
        return {"status": "ok", "scoped_results": scoped_results}

    async def tag_node(
        self,
        tree_name: str,
        node_id: str,
        categories: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Add or merge ``categories`` / ``metadata`` tags on a node.

        Categories are merged as a set (sorted on persist); metadata as
        a shallow dict (later writes win on overlapping keys). The tree
        is persisted and the BM25 index is marked dirty so the next
        search picks up the change.

        Args:
            tree_name: Tree containing the node.
            node_id: Node id to tag.
            categories: Categories to add to the node. Free-form strings.
            metadata: Arbitrary key/value pairs to merge into the node's
                metadata. Equality-match only for v1 — range queries
                and wildcards are out of scope.

        Returns:
            ``{tree_name, node_id, categories, metadata}`` with the
            post-merge values.
        """
        async def apply(txn: WriteTransaction) -> tuple[list[str], dict[str, Any]]:
            node = find_node_by_id(txn.tree.get("structure", []), node_id)
            if node is None:
                raise KeyError(f"node_id {node_id!r} not found in tree {tree_name!r}")
            before = (node.get("categories"), node.get("metadata"))
            if categories:
                existing = set(node.get("categories") or [])
                existing.update(str(category) for category in categories)
                node["categories"] = sorted(existing)
            if metadata:
                existing_meta = dict(node.get("metadata") or {})
                existing_meta.update(metadata)
                node["metadata"] = existing_meta
            if not node.get("categories"):
                node.pop("categories", None)
            if not node.get("metadata"):
                node.pop("metadata", None)
            if (node.get("categories"), node.get("metadata")) == before:
                txn.noop = True  # tags already present: do not mint an empty generation
            return list(node.get("categories") or []), dict(node.get("metadata") or {})

        merged_categories, merged_metadata = await self._mutate(tree_name, apply)
        return {
            "tree_name": tree_name,
            "node_id": node_id,
            "categories": merged_categories,
            "metadata": merged_metadata,
        }

    async def insert_markdown(
        self,
        tree_name: str,
        markdown: str,
        parent_node_id: Optional[str] = None,
        doc_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """Parse ``markdown`` into a PageIndex subtree and splice it in.

        Lean-tree semantics: the ToC keeps titles, summaries, and metadata;
        the per-node markdown body is moved to :class:`NodeContentStore`
        keyed by ``node_id``. This matches the PageIndex contract — the
        persisted JSON does NOT carry inline ``text`` fields.

        ``parent_node_id=None`` appends at the tree root.

        After splicing, the T3 OKF type-classification step is run for any
        node that is missing a ``type`` field.  The step falls back to
        ``ConceptType.SECTION`` when no LLM adapter is available, so it
        never blocks ingest.
        """
        subtree = await md_to_tree(
            md_text=markdown,
            adapter=self._adapter,
            doc_name=doc_name or "ingested.md",
        )
        # Build-time scratch fields that should never reach disk.
        node_markdown = _pop_node_field(subtree, "text")
        _strip_keys_in_place(subtree, ("token_count", "line_num"))
        async def apply(txn: WriteTransaction) -> list[str]:
            fresh = copy.deepcopy(subtree)
            original_id_to_node = _capture_node_id_object_map(fresh)
            new_ids = splice_subtree(txn.tree, fresh, parent_node_id=parent_node_id)
            self._stage_node_markdown(txn, original_id_to_node, node_markdown)
            await self._run_t3_classification(txn.tree, original_id_to_node)
            return new_ids

        new_ids = await self._mutate(tree_name, apply)
        return {"tree_name": tree_name, "new_node_ids": new_ids}

    async def insert_ebook(
        self,
        tree_name: str,
        sections: list[dict[str, Any]],
        parent_node_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Persist source ebook sections with their exact TOC relationships.

        Unlike Markdown ingestion this does not infer parents from headings,
        thin small nodes, or rewrite source content through an LLM.
        """
        from parrot.loaders.ebook import EbookSection
        from .ebook import ebook_tree

        records = [EbookSection.model_validate(section) for section in sections]
        subtree = ebook_tree(records)
        node_markdown = _pop_node_field(subtree, "text")
        async def apply(txn: WriteTransaction) -> list[str]:
            fresh = copy.deepcopy(subtree)
            original_id_to_node = _capture_node_id_object_map(fresh)
            new_ids = splice_subtree(txn.tree, fresh, parent_node_id=parent_node_id)
            self._stage_node_markdown(txn, original_id_to_node, node_markdown)
            await self._run_t3_classification(txn.tree, original_id_to_node)
            return new_ids

        new_ids = await self._mutate(tree_name, apply)
        return {
            "tree_name": tree_name,
            "new_node_ids": new_ids,
            "title": records[0].title if records else "",
            "summary": "",
        }

    async def insert_content(
        self,
        tree_name: str,
        content: str,
        parent_node_id: Optional[str] = None,
        hint: Optional[str] = None,
    ) -> dict[str, Any]:
        """Two-Step CoT ingest of raw content into the tree.

        Step 1 analyses the content with the lightweight model; Step 2
        generates clean markdown which is then parsed via
        :func:`md_to_tree` and spliced under ``parent_node_id``.
        """
        ingested: IngestedMarkdown = await self._ingester().ingest(content, hint=hint)
        result = await self.insert_markdown(
            tree_name=tree_name,
            markdown=ingested.markdown,
            parent_node_id=parent_node_id,
            doc_name=ingested.title,
        )
        result["title"] = ingested.title
        result["summary"] = ingested.summary
        return result

    async def import_file(
        self,
        tree_name: str,
        file_path: str,
        parent_node_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Read a text file and ingest it via :meth:`insert_content`."""
        path = Path(file_path)
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{file_path!r} is not a UTF-8 text file") from exc
        return await self.insert_content(
            tree_name=tree_name,
            content=content,
            parent_node_id=parent_node_id,
            hint=f"Source filename: {path.name}",
        )

    async def import_pdf(
        self,
        tree_name: str,
        pdf_path: str,
        parent_node_id: Optional[str] = None,
        with_summaries: bool = True,
        with_doc_description: bool = False,
    ) -> dict[str, Any]:
        """Build a PageIndex subtree from a PDF and splice it into ``tree_name``.

        Args:
            tree_name: Existing tree to insert into.
            pdf_path: Path to the source PDF on disk.
            parent_node_id: Insert under this node id, or at root if ``None``.
            with_summaries: When ``True``, generate per-node LLM summaries.
            with_doc_description: When ``True``, also generate a one-sentence
                top-level document description.

        Returns:
            ``{tree_name, new_node_ids, doc_name, doc_description?, pages}``
        """
        if not Path(pdf_path).is_file():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        subtree = await build_page_index(
            doc=pdf_path,
            adapter=self._adapter,
            options={
                "if_add_node_summary": "yes" if with_summaries else "no",
                "if_add_doc_description": "yes" if with_doc_description else "no",
                "if_add_node_id": "yes",
            },
            light_adapter=self._light_adapter,
        )
        # ``build_page_index`` returns per-node markdown keyed by the
        # build-time node ids. Splicing renumbers ids tree-wide, so we
        # capture object references BEFORE the splice to recover the
        # new ids afterwards.
        node_markdown = dict(subtree.pop("_node_markdown", {}) or {})
        async def apply(txn: WriteTransaction) -> list[str]:
            fresh = copy.deepcopy(subtree)
            original_id_to_node = _capture_node_id_object_map(fresh)
            new_ids = splice_subtree(txn.tree, fresh, parent_node_id=parent_node_id)
            self._stage_node_markdown(txn, original_id_to_node, node_markdown)
            await self._run_t3_classification(txn.tree, original_id_to_node)
            return new_ids

        new_ids = await self._mutate(tree_name, apply)
        return {
            "tree_name": tree_name,
            "new_node_ids": new_ids,
            "doc_name": subtree.get("doc_name"),
            "doc_description": subtree.get("doc_description"),
        }

    def _stage_node_markdown(
        self,
        txn: WriteTransaction,
        original_id_to_node: dict[str, dict[str, Any]],
        node_markdown: dict[str, str],
    ) -> None:
        """Stage per-node markdown as immutable blobs after a splice into ``txn.tree``."""
        for original_id, markdown in (node_markdown or {}).items():
            node = original_id_to_node.get(original_id)
            if node is not None:
                txn.set_body(node, markdown or "")

    async def import_folder(
        self,
        tree_name: str,
        folder_path: str,
        recursive: bool = True,
        glob_pattern: str = "*",
        parent_node_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Recursively import all matching files from ``folder_path``.

        Directories become synthetic inner nodes that mirror the source
        layout; files are ingested concurrently (capped by
        ``folder_concurrency``). Binary files that are not UTF-8 decodable
        are skipped with a WARNING log line.
        """
        root = Path(folder_path)
        if not root.is_dir():
            raise NotADirectoryError(f"{folder_path!r} is not a directory")

        sem = asyncio.Semaphore(self._folder_concurrency)
        imported: list[str] = []
        skipped: list[str] = []

        async def _ingest_file(path: Path, parent_id: Optional[str]) -> None:
            async with sem:
                try:
                    content = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    logger.warning("Skipping non-text file: %s", path)
                    skipped.append(str(path))
                    return
                try:
                    await self.insert_content(
                        tree_name=tree_name,
                        content=content,
                        parent_node_id=parent_id,
                        hint=f"Source filename: {path.name}",
                    )
                    imported.append(str(path))
                except Exception as exc:
                    logger.warning("Failed to ingest %s: %s", path, exc)
                    skipped.append(str(path))

        async def _process_dir(
            txn: WriteTransaction,
            dir_path: Path,
            parent_id: Optional[str],
        ) -> None:
            files = [
                p
                for p in sorted(dir_path.iterdir())
                if p.is_file() and not p.name.startswith(".") and fnmatch.fnmatch(p.name, glob_pattern)
            ]
            subdirs = (
                [p for p in sorted(dir_path.iterdir()) if p.is_dir() and not p.name.startswith(".")]
                if recursive
                else []
            )
            if files:
                await asyncio.gather(*[_ingest_file(f, parent_id) for f in files])
            for sub in subdirs:
                folder_node = make_folder_node(sub.name)
                splice_subtree(txn.tree, folder_node, parent_node_id=parent_id)
                new_parent_id = folder_node.get("node_id")
                await _process_dir(txn, sub, new_parent_id)

        # The whole import is one transaction (and one LLM bill). A concurrent
        # publication makes it stale at the end, so re-run it a bounded number of
        # times rather than silently discarding all the work.
        attempts = 3
        for attempt in range(attempts):
            imported.clear()
            skipped.clear()
            try:
                async with self._write(tree_name) as txn:
                    await _process_dir(txn, root, parent_node_id)
                break
            except StaleGenerationError:
                self._drop_cached(tree_name)
                if attempt + 1 >= attempts:
                    raise
                await asyncio.sleep(random.uniform(0.005, 0.03) * (attempt + 1))

        return {
            "tree_name": tree_name,
            "imported": imported,
            "skipped": skipped,
        }

    async def delete_node(
        self,
        tree_name: str,
        node_id: str,
    ) -> dict[str, Any]:
        """Delete a node and all its descendants from the tree.

        Referenced body blobs are deliberately retained for the generation
        sweep so readers holding an earlier tree generation remain valid. OKF
        flat-concept sidecars are not generation-versioned and are never swept,
        so those of the removed subtree are deleted here, right after the
        publication, under the tree lock.
        """

        async def apply(txn: WriteTransaction) -> tuple[bool, list[str]]:
            node = find_node_by_id(txn.tree.get("structure", []), node_id)
            flat_keys = _collect_concept_id_keys(node) if node is not None else []
            removed = _delete_node(txn.tree, node_id)
            if not removed:
                txn.noop = True  # nothing changed: do not mint an empty generation
            return removed, flat_keys

        removed, flat_keys = await self._mutate(tree_name, apply)
        if removed and flat_keys:
            async with tree_lock(self._storage_dir, tree_name, timeout=self._lock_timeout_s):
                live = set(_collect_concept_id_keys(self._store.load(tree_name).get("structure", [])))
                for key in flat_keys:
                    if key not in live:
                        self._content_store.delete_node(tree_name, key)
        return {"tree_name": tree_name, "removed": removed}

    async def add_node(
        self,
        tree_name: str,
        title: str,
        body: str = "",
        parent_node_id: Optional[str] = None,
        summary: Optional[str] = None,
        categories: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Atomically create a single node and register its content.

        The PageIndex authoring primitive: an agent says "register this
        finding under section X" and gets back the new ``node_id`` —
        one call, one node, body persisted via :class:`NodeContentStore`,
        tags merged in the same write.

        Args:
            tree_name: Tree to insert into.
            title: Node title — the human-facing label that BM25 and
                the LLM walker see.
            body: Markdown body. Persisted as the node's sidecar so
                ``retrieve`` returns it verbatim. Empty body is allowed
                (synthetic / placeholder nodes).
            parent_node_id: Insert under this node id; ``None`` appends
                at the tree root.
            summary: Optional short description the LLM walker uses
                when deciding which node to dive into. Defaults to an
                empty string.
            categories: Free-form tags merged as a set.
            metadata: Arbitrary key/value pairs (equality-only matching
                at search time).

        Returns:
            ``{tree_name, node_id, parent_node_id}`` with the post-splice
            ``node_id`` of the new node.
        """
        if not isinstance(title, str) or not title.strip():
            raise ValueError("add_node requires a non-empty title")

        node: dict[str, Any] = {
            "title": title.strip(),
            "summary": summary or "",
        }
        if categories:
            node["categories"] = sorted({str(c) for c in categories})
        if metadata:
            node["metadata"] = dict(metadata)

        async def apply(txn: WriteTransaction) -> str | None:
            inserted_node = copy.deepcopy(node)
            new_ids = splice_subtree(txn.tree, inserted_node, parent_node_id=parent_node_id)
            new_id = new_ids[0] if new_ids else inserted_node.get("node_id")
            txn.set_body(inserted_node, body)
            return new_id

        new_id = await self._mutate(tree_name, apply)
        return {
            "tree_name": tree_name,
            "node_id": new_id,
            "parent_node_id": parent_node_id,
        }

    async def update_node_content(
        self,
        tree_name: str,
        node_id: str,
        body: str,
    ) -> dict[str, Any]:
        """Overwrite a node's sidecar markdown without touching the tree.

        Use this when an agent revises a finding — the ToC entry stays
        put (same title, summary, position) but the body is rewritten.
        Marks the BM25 index dirty so the next search reflects the
        new content.

        Raises:
            KeyError: If ``node_id`` does not exist in the tree.
        """
        async def apply(txn: WriteTransaction) -> None:
            node = find_node_by_id(txn.tree.get("structure", []), node_id)
            if node is None:
                raise KeyError(f"node_id {node_id!r} not found in tree {tree_name!r}")
            txn.set_body(node, body or "")

        await self._mutate(tree_name, apply)
        return {
            "tree_name": tree_name,
            "node_id": node_id,
            "bytes": len(body or ""),
        }

    async def update_node(
        self,
        tree_name: str,
        node_id: str,
        title: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> dict[str, Any]:
        """Rename and/or re-summarize an existing node.

        Persists the tree and marks the BM25 index dirty (title and
        summary both feed the corpus). Body / categories / metadata
        are untouched — use :meth:`update_node_content` or
        :meth:`tag_node` for those.

        Raises:
            KeyError: If ``node_id`` does not exist.
            ValueError: If neither ``title`` nor ``summary`` is set.
        """
        if title is None and summary is None:
            raise ValueError("update_node needs at least one of title / summary")

        async def apply(txn: WriteTransaction) -> tuple[Any, Any]:
            node = find_node_by_id(txn.tree.get("structure", []), node_id)
            if node is None:
                raise KeyError(f"node_id {node_id!r} not found in tree {tree_name!r}")
            if title is not None:
                if not isinstance(title, str) or not title.strip():
                    raise ValueError("title must be a non-empty string")
                node["title"] = title.strip()
            if summary is not None:
                node["summary"] = summary
            return node.get("title"), node.get("summary")

        updated_title, updated_summary = await self._mutate(tree_name, apply)
        return {
            "tree_name": tree_name,
            "node_id": node_id,
            "title": updated_title,
            "summary": updated_summary,
        }


# ---- module-level helpers ----------------------------------------------


def _pop_node_field(subtree: Any, field: str) -> dict[str, str]:
    """Remove ``field`` from every node and return ``{node_id: value}``.

    Used by markdown-path ingest to move the inline ``text`` field
    written by :func:`md_to_tree` into :class:`NodeContentStore` —
    keyed by ``node_id`` so it matches the PDF ingest contract.

    Nodes without a ``node_id`` (e.g. synthetic root containers) are
    skipped; the field is still removed from them so the persisted
    tree stays lean.
    """
    out: dict[str, str] = {}

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            value = node.pop(field, None)
            nid = node.get("node_id")
            if nid and isinstance(value, str) and value:
                out[str(nid)] = value
            children = node.get("nodes")
            if children:
                _walk(children)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    if isinstance(subtree, dict) and "structure" in subtree:
        _walk(subtree.get("structure"))
    else:
        _walk(subtree)
    return out


def _strip_keys_in_place(subtree: Any, keys: tuple[str, ...]) -> None:
    """Remove ``keys`` from every node dict reached from ``subtree``.

    PageIndex trees are the canonical on-disk artefact for retrieval;
    build-time scratch fields like ``token_count`` and ``line_num``
    have no consumer at retrieval time and would bloat the JSON.
    """

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for k in keys:
                node.pop(k, None)
            children = node.get("nodes")
            if children:
                _walk(children)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    if isinstance(subtree, dict) and "structure" in subtree:
        _walk(subtree.get("structure"))
    else:
        _walk(subtree)


def _capture_node_id_object_map(subtree: Any) -> dict[str, dict[str, Any]]:
    """Record ``node_id -> node-dict`` references for every node in ``subtree``.

    ``splice_subtree`` reuses these dict objects in-place; later
    reindexing rewrites their ``node_id`` field without changing the
    object identity. Holding the references lets us recover the
    post-splice ids without rewalking the parent tree.
    """
    out: dict[str, dict[str, Any]] = {}

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            nid = node.get("node_id")
            if nid:
                out[str(nid)] = node
            children = node.get("nodes")
            if children:
                _walk(children)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    if isinstance(subtree, dict) and "structure" in subtree:
        _walk(subtree.get("structure"))
    else:
        _walk(subtree)
    return out


def _collect_concept_id_keys(node: Any) -> list[str]:
    """Return flattened concept_id keys for every node reachable from ``node``.

    Returns only nodes that carry a ``concept_id`` field; plain ``node_id``
    values are not included.  The flattened form
    replaces ``/`` with ``--`` to match the :class:`NodeContentStore` key
    layout written by OKF sidecar projection.

    Args:
        node: A node dict or list of node dicts.

    Returns:
        List of flattened concept_id strings (may be empty for non-OKF trees).
    """
    keys: list[str] = []

    try:
        from parrot.knowledge.pageindex.okf.projection import (
            flatten_concept_id_for_filename,
        )
    except ImportError:
        return keys

    def _walk(n: Any) -> None:
        if isinstance(n, dict):
            cid = n.get("concept_id")
            if cid:
                keys.append(flatten_concept_id_for_filename(cid))
            children = n.get("nodes")
            if isinstance(children, list):
                for child in children:
                    _walk(child)
        elif isinstance(n, list):
            for item in n:
                _walk(item)

    _walk(node)
    return keys
