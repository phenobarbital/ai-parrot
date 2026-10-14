"""Structural contracts the GraphIndex / wiki graph tree consumes (FEAT-540 M2 + M7).

Runtime imports are stdlib-only. Framework classes satisfy these Protocols structurally; they never inherit.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


def edge_key(source_id: str, target_id: str, kind: str) -> str:
    """Return the canonical edge identity shared by every backend.

    Args:
        source_id: Source node id.
        target_id: Target node id.
        kind: Edge kind.

    Returns:
        The ``source|target|kind`` item key.
    """
    return f"{source_id}|{target_id}|{kind}"


class ProviderNotAvailable(RuntimeError):
    """A required provider was never injected; the CLI maps it to exit code 2."""

    def __init__(self, role: str, distribution: str, extra: str | None = None) -> None:
        self.role, self.distribution, self.extra = role, distribution, extra
        hint = f"pip install {distribution}[{extra}]" if extra else f"pip install {distribution}"
        super().__init__(f"No {role} provider is configured. Install or configure one ({hint}).")


class CapabilityUnavailable(RuntimeError):
    """The selected graph backend does not implement an optional capability."""

    def __init__(self, backend: str, capability: str) -> None:
        self.backend, self.capability = backend, capability
        super().__init__(f"Graph backend {backend!r} does not support {capability!r}.")


@runtime_checkable
class Embedder(Protocol):
    """Vector provider for graph nodes — the subset builder/retriever/signals call."""

    async def embed_nodes(self, nodes: list[Any], batch_size: int = 64) -> list[Any]: ...
    def get_embedding(self, node_id: str) -> Any | None: ...
    async def search_similar(self, query: str, /, top_k: int = 10) -> list[tuple[str, float]]: ...


@runtime_checkable
class LLMCaller(Protocol):
    """Mirror of PageIndexLLMAdapter.ask / ask_structured / ask_json."""

    async def ask(
        self,
        prompt: str,
        structured_output: Any = None,
        temperature: float = 0.0,
        system_prompt: str | None = None,
    ) -> Any: ...

    async def ask_structured(
        self,
        prompt: str,
        output_type: Any,
        temperature: float = 0.0,
        system_prompt: str | None = None,
    ) -> Any: ...

    async def ask_json(
        self,
        prompt: str,
        temperature: float = 0.0,
        system_prompt: str | None = None,
    ) -> Any: ...


@runtime_checkable
class PageIndexer(Protocol):
    """The six PageIndexToolkit methods the extractors call."""

    async def list_trees(self) -> list[str]: ...
    async def create_tree(self, tree_name: str, doc_name: str | None = None) -> dict[str, Any]: ...
    async def delete_tree(self, tree_name: str) -> dict[str, Any]: ...
    async def get_tree(self, tree_name: str) -> dict[str, Any]: ...
    async def insert_markdown(
        self,
        tree_name: str,
        markdown: str,
        parent_node_id: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]: ...
    async def insert_ebook(
        self,
        tree_name: str,
        sections: list[Any],
        parent_node_id: str | None = None,
    ) -> dict[str, Any]: ...


@runtime_checkable
class GraphPersistence(Protocol):
    """Base contract every GraphIndex backend satisfies (persist_sqlite.py is the reference).

    Semantics:
    - ``apply_update`` is atomic — all items land or none — and allocates ``CommitReceipt.seq``
      INSIDE the same transaction/batch, strictly monotonic per tenant (SQLite: rowid/seq table,
      Postgres: sequence, Arango: ``_next_seq`` doc; HelixDB: Meta counter);
    - edge identity is ``edge_key(source_id, target_id, kind)`` — ``protocols.py`` exports one
      canonical ``edge_key()`` and a backend never duplicates an edge with the same key inside
      one commit;
    - pre-images captured by a commit include the node state AND the incident edges removed with a
      node, so ``revert_commit`` restores both; revert is itself a new commit;
    - revert conflict rule: a later commit (higher ``seq``) touching any item key of the commit being
      reverted => ``revert_commit`` is refused with the conflicting commit id;
    - ``replace_document_slice`` is atomic per ``document_uri`` and idempotent on identical input;
    - ``load_graph`` returns the CURRENT graph (no soft-deleted items);
    - a missing tenant store is created lazily by the first write and reads as empty, never as an error;
    - backend errors propagate as the driver's exception — a backend never swallows them into an
      empty result.
    The conformance suite asserts every bullet against every registered backend.
    """

    async def persist_graph(self, ctx: Any, nodes: list[Any], edges: list[Any]) -> dict[str, Any]: ...
    async def replace_document_slice(
        self,
        ctx: Any,
        document_uri: str,
        nodes: list[Any],
        edges: list[Any],
    ) -> dict[str, Any]: ...
    async def load_graph(self, ctx: Any) -> tuple[list[Any], list[Any]]: ...
    async def apply_update(self, ctx: Any, update: Any) -> Any: ...
    async def get_commit(self, ctx: Any, commit_id: str) -> dict[str, Any] | None: ...
    async def list_commits(self, ctx: Any, *, limit: int = 50) -> list[dict[str, Any]]: ...
    async def revert_commit(
        self,
        ctx: Any,
        commit_id: str,
        *,
        agent_id: str,
        run_id: str | None = None,
    ) -> Any: ...
    async def close(self) -> None: ...


@runtime_checkable
class IncrementalPersistence(Protocol):
    """Backends that can tell whether a source file is stale."""

    async def is_stale(self, ctx: Any, source_uri: str, mtime: float, sha1: str) -> bool: ...


@runtime_checkable
class TemporalGraphPersistence(Protocol):
    """Backends that support time-travel queries."""

    async def as_of(self, ctx: Any, when: Any) -> tuple[list[Any], list[Any]]: ...
    async def history(self, ctx: Any, concept_id: str) -> list[Any]: ...
    async def diff(self, ctx: Any, concept_id: str, t1: Any, t2: Any) -> Any: ...


@runtime_checkable
class EmbeddingPersistence(Protocol):
    """Backends that durably store vectors (durable vectors live here, not in the embedder)."""

    async def upsert_embeddings(self, ctx: Any, vectors: dict[str, Any], *, model: str = "") -> int: ...


@runtime_checkable
class HybridRetrievalPersistence(Protocol):
    """Backends that implement hybrid (vector + lexical) retrieval."""

    async def hybrid_retrieve(self, ctx: Any, query: str, *, top_k: int = 10, **options: Any) -> list[Any]: ...


@runtime_checkable
class SourceCoherencePersistence(Protocol):
    """Backends exposing their ``files`` plane for source-coherence checks."""

    async def file_hashes(self, ctx: Any) -> list[tuple[str, str]]:
        """Return every ``(source_uri, sha1)`` from the ``files`` plane, sorted by ``source_uri``."""
        ...
