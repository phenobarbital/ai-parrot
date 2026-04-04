"""
Navigator Agent Example - PageIndex-powered Knowledge Architecture.

Three-layer knowledge system:
- Layer 1: PageIndex tree context in system prompt (compact node summaries, ~2K tokens)
- Layer 2: search_widget_docs() - LLM tree-search retrieval per query (on-demand)
- Layer 3: get_widget_schema() - exact JSON from production DB (on-demand)

No FAISS, no embedding model, no vector database required.
Uses gemini-flash-lite for PageIndex operations (cheap + fast).

Usage:
    python examples/navigator_agent.py
"""
import asyncio
import logging

from parrot.bots.agent import BasicAgent
from parrot.bots.prompts import PromptBuilder
from parrot.clients.google import GoogleGenAIClient
from parrot.pageindex import PageIndexLLMAdapter

from parrot_tools.navigator import (
    NavigatorToolkit,
    NavigatorPageIndex,
    get_navigator_layers,
    get_navigator_configure_context,
)

logging.basicConfig(level=logging.INFO)

CONNECTION_PARAMS = {
    "host": "localhost",
    "port": 5432,
    "username": "troc_pgdata",
    "password": "your_password",
    "database": "navigator",
}


async def main():
    # ─── Initialize PageIndex (LLM-driven, vectorless) ───
    # Uses a lightweight LLM for indexing and retrieval
    client = GoogleGenAIClient()
    adapter = PageIndexLLMAdapter(client=client, model="gemini-2.0-flash-lite")

    # Build the knowledge tree from markdown docs
    # First run indexes all docs + generates summaries (~30s)
    # Subsequent runs load from cache (~instant)
    page_index = NavigatorPageIndex()
    await page_index.build(adapter)

    # ─── Layer 1: Composable Prompt with tree context ───
    builder = PromptBuilder.default()
    for layer in get_navigator_layers():
        builder.add(layer)

    # ─── Layer 2+3: NavigatorToolkit with PageIndex + DB ───
    toolkit = NavigatorToolkit(
        connection_params=CONNECTION_PARAMS,
        user_id=1,  # superuser for demo
        default_client_id=1,
        page_index=page_index,  # Enables search_widget_docs()
    )

    # ─── Create Agent ───
    agent = BasicAgent(
        name="NavigatorAgent",
        role="a Navigator platform administrator",
        goal="Help users manage Programs, Modules, Dashboards, and Widgets.",
        backstory=(
            "Expert in Navigator platform with knowledge of all 66 widget types, "
            "their JSON configurations, the permission model, and entity hierarchy."
        ),
        llm="google:gemini-2.5-flash",
        system_prompt=builder,
        tools=toolkit.get_tools(),
    )

    # Configure: resolves static prompt layers
    # Layer 1 tree context is injected here (node IDs + summaries)
    await agent.configure(
        **get_navigator_configure_context(page_index),
    )

    async with agent:
        print("\n" + "=" * 60)
        print("NAVIGATOR AGENT - PageIndex RAG")
        print("=" * 60)

        queries = [
            # Layer 1 answers (tree context in prompt — knows node structure):
            "What categories of widgets are available?",

            # Layer 2 answers (search_widget_docs — retrieves detailed docs):
            "How do I configure an api-card widget with KPI metrics and drilldowns?",

            # Layer 3 answers (get_widget_schema — exact JSON from DB):
            "Get me the exact production JSON for creating an api-echarts bar chart",

            # Combined flow (all 3 layers + write tools):
            "Create a dashboard called 'KPI Overview' in module 900 of program 108 "
            "with a card widget showing total_sales, units_sold, and goal_percentage",
        ]

        for q in queries:
            print(f"\n{'─' * 60}")
            print(f"USER: {q}")
            print(f"{'─' * 60}")
            response = await agent.ask(q)
            print(f"\nAGENT: {response.output[:600]}")
            print()


if __name__ == "__main__":
    asyncio.run(main())
