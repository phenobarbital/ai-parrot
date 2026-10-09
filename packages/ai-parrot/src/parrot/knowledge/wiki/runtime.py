"""Public, click-free builders for the supervised wiki-ingest service stack.

The builders are kept separate from command-line concerns so async servers can
construct the charter triage and ingest services without importing CLI code or
starting a nested event loop.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import BaseWikiStore

if TYPE_CHECKING:
    from parrot.knowledge.wiki.charter import Charter
    from parrot.knowledge.wiki.inbox.processor import InboxRuntime

logger = logging.getLogger(__name__)

__all__ = ["WikiRuntimeError", "build_triage_adapters", "build_novelty_scorer", "build_ingest_runtime"]


class WikiRuntimeError(RuntimeError):
    """An LLM client or the supervised-ingest runtime could not be constructed."""


def build_triage_adapters(lightweight_model: str, model: str) -> tuple[Any, Any, str, bool]:
    """Construct the lightweight/heavy ``PageIndexLLMAdapter`` pair.

    Args:
        lightweight_model: Stage-1 triage model spec (``provider:model``).
        model: Stage-2 model spec, also used for page generation.

    Returns:
        ``(lightweight_adapter, heavy_adapter, lightweight_model_id, same_provider)``.
    """
    from parrot.clients.factory import LLMFactory
    from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter

    light_provider, light_model_id = LLMFactory.parse_llm_string(lightweight_model)
    heavy_provider, heavy_model_id = LLMFactory.parse_llm_string(model)
    light_client = LLMFactory.create(lightweight_model)
    heavy_client = light_client if model == lightweight_model else LLMFactory.create(model)
    light_adapter = PageIndexLLMAdapter(light_client, model=light_model_id)
    heavy_adapter = PageIndexLLMAdapter(heavy_client, model=heavy_model_id)
    same_provider = light_provider == heavy_provider
    return light_adapter, heavy_adapter, light_model_id, same_provider


async def build_novelty_scorer(root: Path, config: WikiProjectConfig, store: BaseWikiStore) -> Any:
    """Construct a grounding-backed or search-proxy novelty scorer.

    Args:
        root: Wiki project root.
        config: The project's ``WikiProjectConfig``.
        store: The open retrieval-plane store (search-proxy fallback).

    Returns:
        A configured ``NoveltyScorer``.
    """
    from parrot.knowledge.wiki.search import WikiCombinedSearch
    from parrot.knowledge.wiki.triage import NoveltyScorer

    graph_db = config.graph_path(root) / f"{config.wiki_name}.db"
    if not graph_db.exists():
        return NoveltyScorer(
            grounding_evaluator=None,
            search=WikiCombinedSearch(None, None, store=store),
        )

    try:
        from parrot.knowledge.graphindex.assemble import GraphAssembler
        from parrot.knowledge.graphindex.factory import (
            HashingGraphEmbedder,
            make_stub_tenant_context,
        )
        from parrot.knowledge.graphindex.grounding import GroundingEvaluator
        from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever
    except ImportError:
        return NoveltyScorer(
            grounding_evaluator=None,
            search=WikiCombinedSearch(None, None, store=store),
        )

    async def _build_evaluator() -> Any:
        persistence = SQLitePersistence(config.graph_path(root))
        ctx = make_stub_tenant_context(config.wiki_name)
        nodes, edges = await persistence.load_graph(ctx)
        assembler = GraphAssembler(tenant_id=config.wiki_name)
        for node in nodes:
            assembler.add_node(node)
        for edge in edges:
            assembler.add_edge(edge)
        embedder = HashingGraphEmbedder()
        if nodes:
            await embedder.embed_nodes(nodes)
        retriever = GraphExpandedRetriever(graph=assembler.graph, nodes=nodes, embedder=embedder)
        return GroundingEvaluator(retriever)

    evaluator = await _build_evaluator()
    return NoveltyScorer(grounding_evaluator=evaluator)


def build_ingest_runtime(
    root: Path,
    config: WikiProjectConfig,
    store: BaseWikiStore,
    sources: SourceCollectionManager,
    charter: "Charter",
    charter_path: Path,
    *,
    lightweight_model: str,
    model: str,
    novelty_scorer: Any,
    adapters: tuple[Any, Any, str, bool] | None = None,
    fetch_timeout: float = 30.0,
) -> "InboxRuntime":
    """Build the supervised-ingestion service bindings for one wiki.

    Args:
        root: Wiki project root.
        config: Resolved project configuration.
        store: Open retrieval-plane store.
        sources: Source manifest manager matching ``store``.
        charter: Parsed editorial charter.
        charter_path: Source path for ``charter``.
        lightweight_model: Stage-1 model spec recorded in the runtime.
        model: Stage-2 model spec.
        novelty_scorer: Prebuilt scorer from ``build_novelty_scorer``.
        adapters: Prebuilt adapter tuple; built here when ``None``.
        fetch_timeout: URL acquisition timeout in seconds.

    Returns:
        The ``InboxRuntime`` consumed by the inbox processor.

    Raises:
        WikiRuntimeError: If adapters cannot be constructed.
    """
    from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
    from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
    from parrot.knowledge.wiki.documents import DocumentAcquirer
    from parrot.knowledge.wiki.inbox.processor import InboxRuntime
    from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator
    from parrot.knowledge.wiki.models import WikiConfig
    from parrot.knowledge.wiki.search import WikiCombinedSearch
    from parrot.knowledge.wiki.triage import IngestTriageRouter

    if adapters is None:
        try:
            adapters = build_triage_adapters(lightweight_model, model)
        except Exception as exc:
            raise WikiRuntimeError(f"Could not build LLM client(s) for {lightweight_model!r}/{model!r}: {exc}") from exc
    light_adapter, heavy_adapter, light_model_id, same_provider = adapters

    wiki_dir = config.storage_path(root)
    pageindex_dir = wiki_dir / "pageindex"
    pi_toolkit = PageIndexToolkit(
        heavy_adapter,
        storage_dir=pageindex_dir,
        lightweight_model=light_model_id if same_provider else None,
    )
    if not same_provider:
        logger.info(
            "Stage-1/Stage-2 triage models use different providers "
            "(%s / %s); PageIndexToolkit will use the Stage-2 (heavy) "
            "model for its own internal page-generation steps too.",
            lightweight_model,
            model,
        )
    bookkeeper = WikiBookkeeper()
    orchestrator = WikiIngestOrchestrator(
        pi_toolkit,
        None,
        sources,
        bookkeeper,
        store=store,
        sync_graph=config.sync_graph,
    )
    router = IngestTriageRouter(charter, light_adapter, sources, novelty_scorer, heavy_adapter=heavy_adapter)
    wiki_config = WikiConfig(
        wiki_name=config.wiki_name,
        storage_dir=wiki_dir,
        charter_path=charter_path,
        sync_graph=config.sync_graph,
        storage_backend=config.backend,
    )
    return InboxRuntime(
        root=root,
        config=config,
        wiki_config=wiki_config,
        charter=charter,
        store=store,
        sources=sources,
        bookkeeper=bookkeeper,
        acquirer=DocumentAcquirer(fetch_timeout=fetch_timeout),
        router=router,
        orchestrator=orchestrator,
        light_adapter=light_adapter,
        heavy_adapter=heavy_adapter,
        search=WikiCombinedSearch(None, None, store=store),
        models={"lightweight": lightweight_model, "heavy": model},
    )
