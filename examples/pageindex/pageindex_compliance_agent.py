"""End-to-end demo: a regulatory-compliance agent built on PageIndexToolkit.

The script exercises every public tool surfaced by
:class:`parrot.pageindex.PageIndexToolkit` against a real PDF and a
:class:`parrot.bots.agent.BasicAgent`:

* ``import_pdf``        — ingest a large regulatory PDF into a named tree
* ``list_trees``        — list trees currently in the storage directory
* ``get_tree``          — fetch the full tree dict
* ``search``            — BM25-only / LLM-walk-only / hybrid (BM25 + LLM)
* ``retrieve``          — hybrid search + concatenated-text aggregation
* ``insert_content``    — Two-Step Chain-of-Thought ingest of raw text
* ``import_file``       — ingest a single text file as a new branch
* ``delete_node``       — prune a branch by node id
* ``PageIndexRetriever`` — LLM-only tree-walk against the persisted tree

The PDF defaults to ``examples/pageindex/data/AICPA_SOC2_Compliance_Guide_on_AWS.pdf``
— a TOC-bearing AWS SOC 2 guide that exercises the with-TOC path. To
swap in a different compliance corpus (GDPR, NIST SP 800-53, HIPAA
Privacy Rule, PCI DSS, ISO 27001 excerpt, …), drop it under
``examples/pageindex/data/`` and pass the path::

    python examples/pageindex_compliance_agent.py path/to/your.pdf

Any compliance PDF with reasonable headings — TOC or not — will produce
a usable tree. The demo queries below assume SOC 2 / AWS subject matter
but the toolkit itself is content-agnostic.

Requirements:
    * ``GOOGLE_API_KEY`` exported and reachable via navconfig.
    * ``ai-parrot[retrieval]`` or ``ai-parrot[embeddings]`` installed
      so the ``bm25s`` package is available for hybrid search.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from parrot.bots.agent import BasicAgent
from parrot.clients.google.client import GoogleGenAIClient
from parrot.models.google import GoogleModel
from parrot.pageindex import (
    PageIndexLLMAdapter,
    PageIndexRetriever,
    PageIndexToolkit,
)


LOG = logging.getLogger("pageindex_compliance_agent")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
# Heavy model handles the reasoning-bound calls — TOC extraction, hierarchy
# generation, search-tree walks. Light model handles the high-fan-out,
# narrowly-scoped helpers — TOC page detection, title verification,
# per-node summaries, and the doc description.

HEAVY_MODEL = GoogleModel.GEMINI_3_FLASH_PREVIEW.value
LIGHT_MODEL = GoogleModel.GEMINI_3_FLASH_LITE_PREVIEW.value


# ---------------------------------------------------------------------------
# Storage layout
# ---------------------------------------------------------------------------

DEFAULT_PDF = Path("examples/pageindex/data/AICPA_SOC2_Compliance_Guide_on_AWS.pdf")
STORAGE_DIR = Path("examples/pageindex/store")
TREE_NAME = "compliance"


# ---------------------------------------------------------------------------
# Agent system prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a SOC 2 / AWS compliance assistant grounded in a single source
document indexed as a PageIndex tree named "compliance" — the AICPA
SOC 2 Compliance Guide on AWS.

You have access to a PageIndex toolkit; the most useful tools are:
- pageindex_search(tree_name, query, top_k, use_bm25, use_llm_walk, rerank)
- pageindex_retrieve(tree_name, query, top_k)
- pageindex_get_tree(tree_name)
- pageindex_insert_content(tree_name, content, hint, parent_node_id)

When the user asks about SOC 2 controls, Trust Services Criteria, or
how to map them onto AWS services:
1. Call pageindex_retrieve to ground your answer in the source text.
2. Cite the section title returned in the retrieval.
3. If retrieval returns nothing, say so explicitly instead of guessing.

Be precise: audit language matters. Quote short excerpts when useful.
"""


# ---------------------------------------------------------------------------
# Demo helpers
# ---------------------------------------------------------------------------

def _print_header(title: str) -> None:
    bar = "=" * 70
    print(f"\n{bar}\n  {title}\n{bar}")


def _print_search_results(results: list[dict]) -> None:
    if not results:
        print("  (no results)")
        return
    for r in results:
        print(
            f"  [{r['node_id']}] {r['title']!s:<60}  "
            f"score={r['score']:.4f}  source={r['source']}"
        )


async def ensure_tree(toolkit: PageIndexToolkit, pdf_path: Path) -> dict:
    """Build the compliance tree from ``pdf_path`` if it is not already on disk."""
    existing = await toolkit.list_trees()
    if TREE_NAME in existing:
        LOG.info("Reusing existing tree %r from %s", TREE_NAME, STORAGE_DIR)
        return await toolkit.get_tree(TREE_NAME)

    LOG.info("Creating new tree %r and importing %s", TREE_NAME, pdf_path)
    await toolkit.create_tree(TREE_NAME, doc_name=pdf_path.name)
    result = await toolkit.import_pdf(
        tree_name=TREE_NAME,
        pdf_path=str(pdf_path),
        with_summaries=True,
        with_doc_description=True,
    )
    LOG.info(
        "import_pdf -> doc_name=%s, new_node_ids=%d",
        result.get("doc_name"),
        len(result.get("new_node_ids") or []),
    )
    if result.get("doc_description"):
        LOG.info("doc_description: %s", result["doc_description"][:240])
    return await toolkit.get_tree(TREE_NAME)


async def demo_search_variants(toolkit: PageIndexToolkit) -> None:
    """Compare BM25-only, LLM-only and hybrid hits side-by-side."""
    query = (
        "which AWS services help satisfy the SOC 2 Security trust services "
        "criterion for logical access controls"
    )

    _print_header(f"search — BM25 only — {query!r}")
    _print_search_results(
        await toolkit.search(
            TREE_NAME, query, top_k=5, use_bm25=True, use_llm_walk=False,
        )
    )

    _print_header(f"search — LLM tree-walk only — {query!r}")
    _print_search_results(
        await toolkit.search(
            TREE_NAME, query, top_k=5, use_bm25=False, use_llm_walk=True,
        )
    )

    _print_header(f"search — Hybrid (BM25 + LLM, RRF-fused) — {query!r}")
    _print_search_results(
        await toolkit.search(
            TREE_NAME, query, top_k=5, use_bm25=True, use_llm_walk=True,
        )
    )


async def demo_retrieve(toolkit: PageIndexToolkit) -> None:
    """Show the aggregated-text retrieval that an Agent would normally use."""
    query = (
        "what evidence should we collect to demonstrate the SOC 2 "
        "availability criterion is met in an AWS environment"
    )
    text = await toolkit.retrieve(TREE_NAME, query, top_k=3)
    _print_header(f"retrieve(top_k=3) — {query!r}")
    if not text:
        print("  (no text retrieved)")
        return
    excerpt = text if len(text) < 1500 else text[:1500] + "\n  …(truncated)"
    print(excerpt)


async def demo_two_step_ingest(toolkit: PageIndexToolkit) -> None:
    """Drop an out-of-band note into the tree via the two-step CoT pipeline."""
    note = (
        "INTERNAL NOTE — Q3 2026 SOC 2 audit prep.\n"
        "Three follow-up actions after the readiness assessment with our QSA:\n"
        "1. Enable AWS CloudTrail organization-wide trail with log file "
        "validation and immutable S3 storage to satisfy CC7.2 monitoring.\n"
        "2. Add quarterly access-review attestation for all IAM roles tagged "
        "production, evidencing CC6.1 logical access controls.\n"
        "3. Document the change-management workflow in AWS CodePipeline + "
        "Jira, mapping each gate to CC8.1 change authorization criteria."
    )
    _print_header("insert_content — Two-Step Chain-of-Thought ingest")
    result = await toolkit.insert_content(
        TREE_NAME, note, hint="Internal SOC 2 audit follow-ups from QSA readiness review",
    )
    print(f"  new_node_ids: {result['new_node_ids']}")
    print(f"  title:        {result['title']}")
    print(f"  summary:      {result['summary']}")


async def demo_import_file(toolkit: PageIndexToolkit, tmp_dir: Path) -> None:
    """Ingest a single text file (markdown-ish) via import_file."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    snippet = tmp_dir / "incident_playbook.md"
    snippet.write_text(
        "# Incident Response Playbook (AWS / SOC 2)\n\n"
        "## Detection\n"
        "Open an incident as soon as Amazon GuardDuty, AWS Security Hub, "
        "or an internal alert from CloudWatch indicates a confirmed "
        "unauthorised access to a production AWS account or to customer "
        "data stored in S3, RDS, or DynamoDB.\n\n"
        "## Containment\n"
        "Within 30 minutes of confirmation, revoke compromised IAM "
        "credentials, rotate access keys, and isolate affected EC2 "
        "instances by attaching a quarantine security group. Snapshot the "
        "instance volumes for forensic analysis before terminating.\n\n"
        "## Notification timeline\n"
        "SOC 2 CC2.3 requires that material security incidents are "
        "communicated to internal stakeholders without undue delay. "
        "Notify the CISO and the SOC 2 control owner within 4 hours; "
        "notify affected customers per contractual SLAs (typically 72 "
        "hours for material breaches).\n",
        encoding="utf-8",
    )
    _print_header(f"import_file — {snippet}")
    result = await toolkit.import_file(TREE_NAME, str(snippet))
    print(f"  new_node_ids: {result['new_node_ids']}")
    print(f"  title:        {result['title']}")


async def demo_raw_retriever(adapter: PageIndexLLMAdapter, tree: dict) -> None:
    """Bypass the toolkit and call PageIndexRetriever.search directly."""
    retriever = PageIndexRetriever(
        tree=tree,
        adapter=adapter,
        expert_knowledge=(
            "This tree indexes the AICPA SOC 2 Compliance Guide on AWS. "
            "Top-level sections map to phases of a SOC 2 programme "
            "(Trust Services Criteria, AWS-specific control guidance, "
            "evidence collection, governance). Look for category-specific "
            "criteria sections when answering control-mapping questions."
        ),
    )
    _print_header("PageIndexRetriever.search — direct LLM tree walk")
    result = await retriever.search(
        "how should we structure evidence collection for the "
        "confidentiality trust services criterion in AWS"
    )
    print(f"  thinking : {result.thinking[:240]}…")
    print(f"  node_ids : {result.node_list}")


async def demo_agent(toolkit: PageIndexToolkit) -> None:
    """Wrap the toolkit in a BasicAgent and run a natural-language question."""
    tools = toolkit.get_tools()
    LOG.info("Registering %d PageIndex tools with the agent", len(tools))

    agent = BasicAgent(
        name="ComplianceAgent",
        llm=f"google:{HEAVY_MODEL}",
        system_prompt=SYSTEM_PROMPT,
        tools=list(tools),
        temperature=0.1,
    )
    await agent.configure()

    async with agent:
        prompt = (
            "Summarise how the guide recommends mapping the SOC 2 Security "
            "trust services criterion onto AWS services (think IAM, "
            "CloudTrail, GuardDuty, KMS). Use the pageindex_retrieve tool "
            "against the 'compliance' tree and cite the section title "
            "you used."
        )
        _print_header("BasicAgent.ask — grounded Q&A")
        print(f"User: {prompt}\n")
        response = await agent.ask(prompt)
        text = getattr(response, "output", None) or str(response)
        print(f"Agent:\n{text}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def amain(pdf_path: Path, skip_agent: bool, reset: bool) -> int:
    if not pdf_path.is_file():
        print(
            f"ERROR: PDF not found at {pdf_path}\n\n"
            "Download a regulatory PDF, for example the consolidated GDPR text:\n"
            "  mkdir -p examples/pageindex/data\n"
            "  curl -L -o examples/pageindex/data/gdpr.pdf \\\n"
            "    'https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32016R0679'\n",
            file=sys.stderr,
        )
        return 2

    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    if reset:
        target = STORAGE_DIR / f"{TREE_NAME}.json"
        if target.exists():
            target.unlink()
            LOG.info("Removed cached tree %s", target)

    async with GoogleGenAIClient() as client:
        adapter = PageIndexLLMAdapter(client=client, model=HEAVY_MODEL)

        toolkit = PageIndexToolkit(
            adapter=adapter,
            storage_dir=STORAGE_DIR,
            lightweight_model=LIGHT_MODEL,
            default_bm25_k=20,
        )

        _print_header("list_trees (before ingest)")
        print(f"  {await toolkit.list_trees()}")

        tree = await ensure_tree(toolkit, pdf_path)
        LOG.info(
            "Tree %r ready: %d top-level sections",
            TREE_NAME, len(tree.get("structure", [])),
        )

        _print_header("list_trees (after ingest)")
        print(f"  {await toolkit.list_trees()}")

        await demo_search_variants(toolkit)
        await demo_retrieve(toolkit)
        await demo_two_step_ingest(toolkit)
        await demo_import_file(toolkit, STORAGE_DIR / "extra")
        # Reload tree post-mutation so retriever sees the inserts.
        tree = await toolkit.get_tree(TREE_NAME)
        await demo_raw_retriever(adapter, tree)

        _print_header("Persisted tree summary")
        print(json.dumps(
            {
                "doc_name": tree.get("doc_name"),
                "top_level_sections": [
                    {"node_id": n.get("node_id"), "title": n.get("title")}
                    for n in tree.get("structure", [])
                ],
            },
            indent=2,
            ensure_ascii=False,
        ))

        if not skip_agent:
            await demo_agent(toolkit)

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PageIndex compliance-agent demo."
    )
    parser.add_argument(
        "pdf",
        nargs="?",
        default=str(DEFAULT_PDF),
        help=f"Path to the regulatory PDF (default: {DEFAULT_PDF}).",
    )
    parser.add_argument(
        "--skip-agent",
        action="store_true",
        help="Skip the final BasicAgent question (only run toolkit demos).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete any cached tree and rebuild from the PDF.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s %(name)s: %(message)s",
    )

    sys.exit(asyncio.run(amain(Path(args.pdf), args.skip_agent, args.reset)))


if __name__ == "__main__":
    main()
