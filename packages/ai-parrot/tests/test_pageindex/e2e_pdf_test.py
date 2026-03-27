"""End-to-end test: build PageIndex tree from a real PDF and search it.

Uses gemini-3-flash-preview via GoogleGenAIClient.
Requires GOOGLE_API_KEY to be available via navconfig.
"""
import asyncio
import json
import logging
import sys
import os

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("e2e_pageindex")

PDF_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "arxiv_2408_09869.pdf")
MODEL = "gemini-3-flash-preview"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "docling_structure.json")


async def main():
    from parrot.clients.google.client import GoogleGenAIClient
    from parrot.pageindex.llm_adapter import PageIndexLLMAdapter
    from parrot.pageindex.builder import build_page_index
    from parrot.pageindex.retriever import PageIndexRetriever

    # ── Step 1: Build the PageIndex tree ──
    logger.info("=" * 60)
    logger.info("STEP 1: Building PageIndex tree from %s", os.path.basename(PDF_PATH))
    logger.info("Model: %s", MODEL)
    logger.info("=" * 60)

    client = GoogleGenAIClient()
    adapter = PageIndexLLMAdapter(client, model=MODEL)

    tree = await build_page_index(
        doc=PDF_PATH,
        adapter=adapter,
        options={
            "if_add_node_summary": "yes",
            "if_add_doc_description": "yes",
            "if_add_node_id": "yes",
        },
    )

    # Save the tree
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(tree, f, indent=2, ensure_ascii=False)
    logger.info("Tree saved to %s", OUTPUT_PATH)

    # Print structure overview
    structure = tree.get("structure", [])
    logger.info("Doc name: %s", tree.get("doc_name", "unknown"))
    if tree.get("doc_description"):
        logger.info("Doc description: %s", tree["doc_description"][:200])

    def print_tree(nodes, indent=0):
        for n in nodes:
            node_id = n.get("node_id", "?")
            title = n.get("title", "Untitled")
            pages = ""
            if n.get("start_index") and n.get("end_index"):
                pages = f" (pp. {n['start_index']}-{n['end_index']})"
            summary = n.get("summary", "")[:80]
            logger.info(
                "%s[%s] %s%s%s",
                "  " * indent,
                node_id,
                title,
                pages,
                f" — {summary}" if summary else "",
            )
            if n.get("nodes"):
                print_tree(n["nodes"], indent + 1)

    logger.info("--- Tree Structure ---")
    print_tree(structure)

    # ── Step 2: Tree-search RAG retrieval ──
    logger.info("=" * 60)
    logger.info("STEP 2: Tree-search RAG retrieval")
    logger.info("=" * 60)

    retriever = PageIndexRetriever(tree, adapter)

    queries = [
        "What document formats does Docling support?",
        "How does the OCR pipeline work?",
        "What is the table structure recognition model?",
    ]

    for query in queries:
        logger.info("--- Query: %s ---", query)
        result = await retriever.search(query)
        logger.info("Thinking: %s", result.thinking[:200])
        logger.info("Matched nodes: %s", result.node_list)

        # Retrieve full context
        context = await retriever.retrieve(query)
        if context:
            logger.info("Context preview (%d chars): %s...", len(context), context[:200])
        else:
            logger.info("No context retrieved")
        logger.info("")

    # ── Step 3: System prompt context ──
    logger.info("=" * 60)
    logger.info("STEP 3: Tree context for system prompt")
    logger.info("=" * 60)
    tree_ctx = retriever.get_tree_context()
    logger.info("Tree context (%d chars):\n%s", len(tree_ctx), tree_ctx[:500])

    logger.info("=" * 60)
    logger.info("END-TO-END TEST COMPLETE")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
