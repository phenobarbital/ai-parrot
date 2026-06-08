"""End-to-end demo: an LLM-Wiki knowledge-repo agent.

Composes the three AI-Parrot knowledge subsystems into a single agent-maintained
knowledge repository (see :mod:`wiki` for the concept mapping):

* **PageIndex** holds durable, cross-linked *wiki pages*.
* **GraphIndex** holds the *knowledge graph* the agent grows via write tools.
* **Ontology** adds a structured entity layer (optional, degrades gracefully).

The demo walks the full LLM-Wiki loop:

1. **Ingest**     — compile ``raw/*.md`` sources into PageIndex pages.
2. **Bridge**     — derive graph DOCUMENT/SECTION nodes from the page tree.
3. **Agent**      — wire a ``WikiAgent`` with both toolkits (+ Ontology).
4. **Query**      — answer a question, grounded + cited.
5. **Contribute** — the LLM does the bookkeeping: file a new concept, cross-link
                    it, attach a summary, and add a synthesised wiki page.
6. **Re-query**   — show the freshly filed concept is now searchable.
7. **Lint**       — report orphan nodes / community structure.

Two run modes
-------------
* Full agentic demo (default) — requires ``GOOGLE_API_KEY`` (PageIndex ingest
  and the agent both call an LLM)::

      python examples/knowledge_wiki/llm_wiki_agent.py

* Offline demo (no API key) — exercises the *real* PageIndex and GraphIndex
  toolkits deterministically, skipping only the LLM/agent phases::

      python examples/knowledge_wiki/llm_wiki_agent.py --no-llm

Enabling the Ontology layer fully is optional: provide an ArangoDB-backed
``TenantOntologyManager`` + ``OntologyGraphStore`` to :func:`wiki.build_wiki_agent`.
Without them the ontology pipeline reports ``"not_configured"`` and the agent
runs as a PageIndex + GraphIndex agent.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Allow `python examples/knowledge_wiki/llm_wiki_agent.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from parrot.knowledge.graphindex.schema import (  # noqa: E402
    EdgeKind,
    NodeKind,
    UniversalEdge,
    UniversalNode,
)

import wiki  # noqa: E402

LOG = logging.getLogger("llm_wiki_agent")

HERE = Path(__file__).resolve().parent
RAW_DIR = HERE / "raw"
STORE_DIR = HERE / "store"
TREE_NAME = "knowledge_wiki"

HEAVY_MODEL = "gemini-3-flash-preview"
LIGHT_MODEL = "gemini-3-flash-lite-preview"

SYSTEM_PROMPT = """\
You are the editor of an LLM knowledge wiki backed by two stores:

- a PageIndex tree named "knowledge_wiki" — durable, citable wiki pages, and
- a GraphIndex knowledge graph of typed concepts and their relationships.

When the user asks a question:
1. Ground your answer with pageindex_retrieve (or graphindex find_node /
   relevance) and cite the page title or concept you used.
2. If you discover a concept the wiki is missing, FILE IT: call
   graphindex create_concept, link it to related nodes with link_nodes, and add
   a short wiki page with pageindex add_node. You are the editor — keep the wiki
   cross-referenced and tidy, do not just answer and forget.
3. If retrieval returns nothing, say so instead of guessing.
"""


def _header(title: str) -> None:
    bar = "=" * 72
    print(f"\n{bar}\n  {title}\n{bar}")


# ---------------------------------------------------------------------------
# Offline demo — real toolkits, deterministic, no API key
# ---------------------------------------------------------------------------

async def run_offline_demo() -> int:
    """Exercise the real PageIndex + GraphIndex toolkits without any LLM."""
    STORE_DIR.mkdir(parents=True, exist_ok=True)

    _header("Offline demo — no LLM, real toolkits")
    print("PageIndex ingest and the agent need an LLM; this mode skips them and")
    print("drives the toolkits directly so the loop is fully reproducible.\n")

    # --- PageIndex: build pages with add_node (no LLM needed) ---------------
    from parrot.knowledge.pageindex import PageIndexLLMAdapter

    class _NullClient:
        """Placeholder client — add_node / BM25 search never call it."""

    adapter = PageIndexLLMAdapter(client=_NullClient(), model=HEAVY_MODEL)
    pi = wiki.build_pageindex_toolkit(adapter=adapter, storage_dir=STORE_DIR)

    if TREE_NAME in await pi.list_trees():
        await pi.delete_tree(TREE_NAME)
    await pi.create_tree(TREE_NAME, doc_name="Knowledge Wiki")
    for src in sorted(RAW_DIR.glob("*.md")):
        title = src.stem.replace("_", " ").title()
        await pi.add_node(
            tree_name=TREE_NAME,
            title=title,
            body=src.read_text(encoding="utf-8"),
            summary=f"Seed page compiled from {src.name}",
            categories=["seed"],
        )
    _header("PageIndex — pages created + BM25 retrieval")
    pages = (await pi.get_tree(TREE_NAME)).get("structure", [])
    print(f"  {len(pages)} pages: {[p['title'] for p in pages]}")
    hits = await pi.search(
        TREE_NAME, "knowledge graph write tools", top_k=3,
        use_bm25=True, use_llm_walk=False,
    )
    for h in hits:
        print(f"  [{h['source']}] {h['title']}  score={h['score']:.3f}")

    # --- GraphIndex: seed graph, then the agent's "contribution" loop -------
    seed_nodes = [
        UniversalNode(node_id="doc::wiki", kind=NodeKind.DOCUMENT,
                      title="Knowledge Wiki", source_uri="wiki://",
                      summary="Root of the knowledge wiki."),
        UniversalNode(node_id="c::pageindex", kind=NodeKind.CONCEPT,
                      title="PageIndex", source_uri="wiki://pageindex",
                      summary="Hierarchical wiki pages with hybrid search."),
        UniversalNode(node_id="c::graphindex", kind=NodeKind.CONCEPT,
                      title="GraphIndex", source_uri="wiki://graphindex",
                      summary="Agent-maintained knowledge graph with FAISS."),
    ]
    seed_edges = [
        UniversalEdge(source_id="doc::wiki", target_id="c::pageindex",
                      kind=EdgeKind.CONTAINS),
        UniversalEdge(source_id="doc::wiki", target_id="c::graphindex",
                      kind=EdgeKind.CONTAINS),
    ]
    gi = await wiki.build_graphindex_toolkit(seed_nodes, seed_edges)
    print(f"\n  GraphIndex write tools enabled: {gi._write_supported}")
    print(f"  Tools available: {len(gi.list_tool_names())}")

    _header("GraphIndex — the agent contributes a new concept")
    created = await gi.create_concept(
        title="Hybrid Retrieval",
        summary="Fusing BM25 lexical search with an LLM tree-walk via RRF.",
        categories=["retrieval"],
    )
    print(f"  create_concept -> {created}")
    new_id = created["node_id"]
    linked = await gi.link_nodes("c::pageindex", new_id, kind="references")
    print(f"  link_nodes     -> {linked}")
    await gi.attach_summary(new_id, "Hybrid retrieval blends sparse + dense signals.")

    _header("GraphIndex — the new concept is immediately searchable")
    found = await gi.find_node("hybrid retrieval bm25 fusion")
    print(f"  find_node      -> {found}")
    rel = await gi.relevance("c::pageindex", new_id)
    print(f"  relevance(PageIndex, HybridRetrieval): "
          f"combined={rel.get('combined')}, direct={rel.get('direct')}")
    community = await gi.find_community(new_id)
    print(f"  find_community -> {community.get('community_id', community)}")

    # --- Lint ---------------------------------------------------------------
    _header("Lint — knowledge-repo health")
    report = await wiki.wiki_lint(gi, pi, TREE_NAME)
    print(f"  {report}")

    print("\nOffline demo complete.")
    return 0


# ---------------------------------------------------------------------------
# Full agentic demo — requires GOOGLE_API_KEY
# ---------------------------------------------------------------------------

async def run_full_demo(reset: bool) -> int:
    from parrot.clients.google.client import GoogleGenAIClient
    from parrot.knowledge.pageindex import PageIndexLLMAdapter

    STORE_DIR.mkdir(parents=True, exist_ok=True)

    async with GoogleGenAIClient() as client:
        adapter = PageIndexLLMAdapter(client=client, model=HEAVY_MODEL)
        pi = wiki.build_pageindex_toolkit(
            adapter=adapter, storage_dir=STORE_DIR, lightweight_model=LIGHT_MODEL,
        )

        # 1. Ingest raw sources into wiki pages.
        _header("1. Ingest — compile raw/ into wiki pages")
        if reset and TREE_NAME in await pi.list_trees():
            await pi.delete_tree(TREE_NAME)
        summary = await wiki.seed_wiki_from_raw(pi, TREE_NAME, RAW_DIR,
                                                doc_name="Knowledge Wiki")
        print(f"  ingested {summary['count']} sources")

        # 2. Bridge: derive graph nodes/edges from the page tree.
        _header("2. Bridge — graph nodes from the page tree")
        nodes, edges = await wiki.graph_seed_from_tree(pi, TREE_NAME)
        gi = await wiki.build_graphindex_toolkit(nodes, edges)
        print(f"  seeded graph: {len(nodes)} nodes, {len(edges)} edges")

        # 3. Build the agent (Ontology degrades gracefully when unconfigured).
        _header("3. Agent — WikiAgent with PageIndex + GraphIndex (+ Ontology)")
        agent = wiki.build_wiki_agent(
            name="WikiEditor",
            llm=f"google:{HEAVY_MODEL}",
            system_prompt=SYSTEM_PROMPT,
            pi_toolkit=pi,
            gi_toolkit=gi,
        )
        await agent.configure()

        async with agent:
            # 4. Query with citations.
            _header("4. Query — grounded, cited answer")
            q1 = ("How does AI-Parrot let an agent contribute its own knowledge "
                  "back into the wiki? Cite the page you used.")
            print(f"User: {q1}\n")
            r1 = await agent.ask(q1)
            print("Agent:\n" + (getattr(r1, "output", None) or str(r1)))

            # 5. Contribute — ask the editor to file and cross-link a concept.
            _header("5. Contribute — the LLM files a new concept + page")
            q2 = ("Define 'Reciprocal Rank Fusion' as it relates to PageIndex "
                  "hybrid search. File it as a new concept in the graph, link it "
                  "to the relevant nodes, and add a short wiki page for it.")
            print(f"User: {q2}\n")
            r2 = await agent.ask(q2)
            print("Agent:\n" + (getattr(r2, "output", None) or str(r2)))

        # 6. Re-query the graph directly to confirm the contribution landed.
        _header("6. Re-query — is the new knowledge searchable?")
        found = await gi.find_node("reciprocal rank fusion")
        print(f"  find_node -> {found}")

        # 7. Lint.
        _header("7. Lint — knowledge-repo health")
        print(f"  {await wiki.wiki_lint(gi, pi, TREE_NAME)}")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM-Wiki knowledge-repo demo.")
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Run the offline demo (real toolkits, no API key needed).",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Delete and rebuild the wiki tree before ingesting (full mode).",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.no_llm:
        sys.exit(asyncio.run(run_offline_demo()))

    if not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        print(
            "ERROR: full agentic demo needs GOOGLE_API_KEY (or GEMINI_API_KEY).\n"
            "Run the offline demo instead:\n"
            "  python examples/knowledge_wiki/llm_wiki_agent.py --no-llm",
            file=sys.stderr,
        )
        sys.exit(2)

    sys.exit(asyncio.run(run_full_demo(args.reset)))


if __name__ == "__main__":
    main()
