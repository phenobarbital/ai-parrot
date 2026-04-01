#!/usr/bin/env python3
"""
Gorilla Sheds Advisor — Multi-mixin product advisor example.

Demonstrates how to compose all major AI-Parrot capabilities into a single
interactive product advisor agent:

- ProductAdvisorMixin  — guided product selection (start, filter, compare, recommend)
- OntologyRAGMixin     — ontology-enriched retrieval (vector-only degradation)
- EpisodicMemoryMixin  — cross-session conversational memory
- IntentRouterMixin    — pre-RAG query routing
- WorkingMemoryToolkit — intermediate analytics store
- PageIndexRetriever   — tree-structured navigation of company/product info
- BaseBot              — LLM conversation engine

Usage:
    python examples/shoply/sample.py

Requires:
    - PostgreSQL with pgvector (gorillashed.products populated)
    - Redis for state/session management
    - examples/shoply/data/page_index.json (run scraper.py first)
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from navconfig import BASE_DIR
from parrot.bots.base import BaseBot
from parrot.bots.mixins.intent_router import IntentRouterMixin
from parrot.advisors import ProductAdvisorMixin, ProductCatalog
from parrot.memory.episodic.mixin import EpisodicMemoryMixin
from parrot.knowledge.ontology.mixin import OntologyRAGMixin
from parrot.pageindex.retriever import PageIndexRetriever
from parrot.pageindex.llm_adapter import PageIndexLLMAdapter
from parrot.registry.capabilities.models import (
    CapabilityEntry,
    IntentRouterConfig,
    ResourceType,
)
from parrot.registry.capabilities.registry import CapabilityRegistry

CATALOG_ID = "gorillashed"
SCHEMA = "gorillashed"
TABLE = "products"
DATA_DIR = BASE_DIR / "examples" / "shoply" / "data"

logger = logging.getLogger(__name__)


async def get_catalog() -> ProductCatalog:
    """Get a configured ProductCatalog for Gorilla Sheds.

    The ``gorillashed.products`` table must already exist and be populated.
    No table creation or data insertion is performed.

    Returns:
        Initialised ProductCatalog instance.
    """
    catalog = ProductCatalog(
        catalog_id=CATALOG_ID,
        table=TABLE,
        schema=SCHEMA,
    )
    await catalog.initialize(create_table=False)
    return catalog


# ---------------------------------------------------------------------------
# Bot class — mixin order matters for MRO
# ---------------------------------------------------------------------------

class GorillaAdvisorBot(
    IntentRouterMixin,
    OntologyRAGMixin,
    EpisodicMemoryMixin,
    ProductAdvisorMixin,
    BaseBot,
):
    """Multi-mixin advisor bot for Gorilla Sheds.

    Inherits from all required mixins with IntentRouterMixin first
    (intercepts ``conversation()`` calls) and BaseBot last (provides
    the concrete LLM conversation implementation).
    """
    pass


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a friendly and knowledgeable sales advisor for Gorilla Sheds, a leading
supplier of premium garden sheds, workshops, and outdoor buildings.

Your capabilities:
- **Product Search**: Search and recommend sheds based on customer needs (size,
  material, budget, use case).
- **Product Comparison**: Compare up to 3 products side-by-side on key dimensions.
- **FAQ & Company Info**: Answer questions about ordering, delivery, installation,
  warranty, and company policies.
- **Installation Guidance**: Explain the shed installation process and requirements.
- **Guided Selection**: Walk customers through a structured selection wizard to
  narrow down the best product.

Guidelines:
- Be warm, helpful, and conversational.
- When a customer is unsure, ask clarifying questions about their needs.
- Always provide specific product names and key specs when recommending.
- If you don't know something, say so honestly rather than guessing.
- Use the product catalog and company information available to you.
- Prices and availability should be verified on the website.
"""


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

async def create_advisor_bot() -> GorillaAdvisorBot:
    """Create and configure the full Gorilla Sheds advisor bot.

    Returns:
        Fully configured GorillaAdvisorBot ready for conversation.

    Raises:
        FileNotFoundError: If page_index.json is missing (run scraper.py first).
    """
    # 1. Load catalog (already populated in PgVector)
    catalog = await get_catalog()

    # 2. Load PageIndex tree
    page_index_path = DATA_DIR / "page_index.json"
    if not page_index_path.exists():
        raise FileNotFoundError(
            f"PageIndex not found at {page_index_path}. "
            "Run `python examples/shoply/scraper.py` first."
        )
    tree_data = json.loads(page_index_path.read_text(encoding="utf-8"))

    # 3. Create bot with all mixins
    bot = GorillaAdvisorBot(
        name="Gorilla Sheds Advisor",
        llm="google:gemini-3-flash-preview",
        system_prompt=SYSTEM_PROMPT,
        catalog=catalog,
        catalog_id=CATALOG_ID,
        auto_register_tools=True,
        max_tokens=4096,
        temperature=0.3,
        # EpisodicMemoryMixin config
        enable_episodic_memory=True,
        episodic_backend="faiss",  # use faiss for simplicity
    )

    # 4. Configure base bot (LLM client, tool manager, etc.)
    await bot.configure()

    # 5. Configure ProductAdvisorMixin
    await bot.configure_advisor(catalog=catalog)

    # 6. Configure EpisodicMemoryMixin
    await bot._configure_episodic_memory()

    # 7. Set up PageIndexRetriever
    llm_client = getattr(bot, "_llm", None)
    if llm_client:
        adapter = PageIndexLLMAdapter(client=llm_client)
        retriever = PageIndexRetriever.from_json(
            json_data=tree_data,
            adapter=adapter,
            expert_knowledge=(
                "This is a product catalog for Gorilla Sheds. "
                "Sections include company info, FAQ, installation process, "
                "and individual product listings."
            ),
        )
        # Expose retriever on bot for IntentRouterMixin discovery
        bot._pageindex_retriever = retriever

    # 8. Configure IntentRouterMixin with capability registry
    registry = CapabilityRegistry()
    registry.register(CapabilityEntry(
        name="product_catalog",
        description="Search and browse Gorilla Sheds product catalog with hybrid semantic + filter search.",
        resource_type=ResourceType.VECTOR_COLLECTION,
    ))
    registry.register(CapabilityEntry(
        name="page_index",
        description="Navigate company info, FAQ, installation guide, and product details via tree search.",
        resource_type=ResourceType.PAGEINDEX,
    ))
    registry.register(CapabilityEntry(
        name="advisor_tools",
        description="Guided product selection wizard: start selection, apply criteria, compare, recommend.",
        resource_type=ResourceType.TOOL,
    ))

    router_config = IntentRouterConfig(
        confidence_threshold=0.6,
        hitl_threshold=0.25,
        strategy_timeout_s=30.0,
        exhaustive_mode=False,
        max_cascades=2,
        # Domain-specific keywords that route to PageIndex tree search
        custom_keywords={
            "base": "graph_pageindex",
            "foundation": "graph_pageindex",
            "maintenance": "graph_pageindex",
            "treatment": "graph_pageindex",
            "assembly": "graph_pageindex",
        },
    )
    bot.configure_router(config=router_config, registry=registry)

    logger.info("GorillaAdvisorBot fully configured and ready.")
    return bot


# ---------------------------------------------------------------------------
# Interactive chat loop
# ---------------------------------------------------------------------------

async def chat_session(bot: GorillaAdvisorBot) -> None:
    """Run an interactive chat loop with the advisor bot.

    Supports commands:
        quit  — exit the chat
        undo  — undo last selection step (ProductAdvisorMixin)
        status — show current selection state

    Args:
        bot: Configured GorillaAdvisorBot.
    """
    session_id = str(uuid.uuid4())
    user_id = "demo_user"

    memory = bot.get_conversation_memory(storage_type="memory")

    print("\n" + "=" * 60)
    print("  Gorilla Sheds Advisor")
    print("  Type your question, or use: quit, undo, status")
    print("=" * 60 + "\n")

    while True:
        try:
            query = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not query:
            continue

        cmd = query.lower()

        if cmd in ("quit", "exit", "bye"):
            print("Goodbye! Thanks for visiting Gorilla Sheds.")
            break

        if cmd == "undo":
            if bot._selection_manager:
                try:
                    state = await bot._selection_manager.undo(session_id)
                    print(f"Advisor: Selection undone. Current filters: {state}")
                except Exception as exc:
                    print(f"Advisor: Could not undo: {exc}")
            else:
                print("Advisor: No active selection to undo.")
            continue

        if cmd == "status":
            if bot._selection_manager:
                try:
                    state = await bot._selection_manager.get_state(session_id)
                    print(f"Advisor: Current state: {state}")
                except Exception as exc:
                    print(f"Advisor: Could not get status: {exc}")
            else:
                print("Advisor: No active selection session.")
            continue

        # Main conversation
        try:
            response = await bot.conversation(
                prompt=query,
                session_id=session_id,
                user_id=user_id,
                search_type="ensemble",
                memory=memory,
            )
            # AIMessage has .response or .content
            text = getattr(response, "response", None) or getattr(response, "content", str(response))
            print(f"Advisor: {text}\n")
        except Exception as exc:
            logger.exception("Error during conversation")
            print(f"Advisor: Sorry, I encountered an error: {exc}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    """Main entry point: create bot and start chat."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    bot = await create_advisor_bot()
    await chat_session(bot)


if __name__ == "__main__":
    asyncio.run(main())
