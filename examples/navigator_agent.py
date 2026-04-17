"""
Navigator Agent Example - PageIndex-powered Knowledge Architecture.

Three-layer knowledge system:
- Layer 1: PageIndex tree context in system prompt (compact node summaries, ~2K tokens)
- Layer 2: search_widget_docs() - LLM tree-search retrieval per query (on-demand)
- Layer 3: get_widget_schema() - exact JSON from production DB (on-demand)

No FAISS, no embedding model, no vector database required.
Uses gemini-flash-lite for PageIndex operations (cheap + fast).

Usage:
    ENV=production python examples/navigator_agent.py
"""
import asyncio
import logging

from parrot.bots.agent import BasicAgent
from parrot.bots.prompts import PromptBuilder
from parrot.clients.google import GoogleGenAIClient
from parrot.pageindex import PageIndexLLMAdapter

from parrot_tools.navigator import NavigatorToolkit
from parrot_tools.navigator.prompt import NavigatorPageIndex, get_navigator_layers

logging.basicConfig(level=logging.INFO)

import os
from navconfig import config

# Load Postgres DSN from navconfig or environment variable.
# FEAT-106/TASK-745: NavigatorToolkit now accepts dsn= instead of connection_params=.
NAVIGATOR_DSN = os.getenv(
    "NAVIGATOR_PG_DSN",
    (
        "postgres://{user}:{password}@{host}:{port}/{database}?sslmode=require".format(
            user=config.get("DBUSER", os.getenv("DBUSER", "troc_pgdata")),
            password=config.get("DBPWD", os.getenv("DBPWD", "")),
            host=config.get("DBHOST", os.getenv("DBHOST", "localhost")),
            port=int(config.get("DBPORT", os.getenv("DBPORT", "5432"))),
            database=config.get("DBNAME", os.getenv("DBNAME", "navigator")),
        )
    ),
)


async def main():
    # ─── Initialize PageIndex (LLM-driven, vectorless) ───
    client = GoogleGenAIClient()
    adapter = PageIndexLLMAdapter(client=client, model="gemini-3.1-flash-lite-preview")

    # Build the knowledge tree from markdown docs
    # First run indexes all docs + generates summaries (~30s)
    # Subsequent runs load from cache (~instant)
    page_index = NavigatorPageIndex()
    await page_index.build(adapter)

    # ─── Layer 1: Composable Prompt with tree context ───
    # get_navigator_layers(page_index) creates layers with
    # pre-resolved tree context content (no $variables needed)
    builder = PromptBuilder.default()
    for layer in get_navigator_layers(page_index):
        builder.add(layer)

    # ─── Layer 2+3: NavigatorToolkit with PageIndex + DB ───
    # FEAT-106/TASK-745: dsn= replaces connection_params= (breaking change)
    toolkit = NavigatorToolkit(
        dsn=NAVIGATOR_DSN,
        user_id=int(config.get("NAVIGATOR_USER_ID", os.getenv("NAVIGATOR_USER_ID", "1397"))),
        default_client_id=1,
        page_index=page_index,  # Enables nav_search_widget_docs()
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
        tools=toolkit.get_tools(),
    )

    # Assign the PromptBuilder via property setter (not constructor)
    # This replaces the legacy system_prompt_template with composable layers
    agent.prompt_builder = builder

    # Configure the agent
    await agent.configure()

    async with agent:
        print("\n" + "=" * 60)
        print("NAVIGATOR AGENT - PageIndex RAG")
        print("=" * 60)

        # Single comprehensive prompt — the agent handles all steps sequentially
        # using tool calls, maintaining context within one conversation turn.
        prompt = (
            "Execute the following steps in order. "
            "If a step fails, stop and report the error — do NOT proceed to the next step.\n\n"
            "1. Create a program called 'Demo Agent 360' with slug 'demo_agent_360', "
            "abbreviation 'DA360', attributes: {\"version\": \"v3\", \"modules_multisections\": true}. "
            "Assign to client 'navigator-new' and group_ids [1].\n\n"
            "2. Create a module called 'Overview' with slug 'demo_agent_360_overview' "
            "in program 'demo_agent_360'. "
            "Set as parent menu with icon 'mdi:view-dashboard', color '#1E90FF'. "
            "Assign to client 'navigator-new' and group_id 1.\n\n"
            "3. Create a dashboard called 'KPI Overview' inside module 'demo_agent_360_overview' "
            "of program 'demo_agent_360' with dashboard_type '3' and position 1.\n\n"
            "4. Create an api-card widget in dashboard 'KPI Overview' of program 'demo_agent_360' "
            "with 3 KPI metrics: total_sales (format money), units_sold (format integer), "
            "goal_percentage (format percent). Use query_slug 'demo_agent_360_kpi'. "
            "Grid position: h=10, w=12, x=0, y=0.\n\n"
            "Report the result of each step with the created IDs."
        )

        print(f"\n{'─' * 60}")
        print(f"USER: {prompt}")
        print(f"{'─' * 60}")
        response = await agent.ask(prompt)
        print(f"\nAGENT:\n{response.output}")


if __name__ == "__main__":
    asyncio.run(main())
