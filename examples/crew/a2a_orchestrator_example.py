"""
A2A Orchestrator Example - Hybrid Local + Remote Agent Orchestration

This example demonstrates how to use A2AOrchestratorAgent to coordinate
both local specialized agents and remote A2A agents.

Usage:
    python examples/crew/a2a_orchestrator_example.py

Requirements:
    - For full functionality, have A2A servers running on:
      - localhost:8082 (e.g., a DataAgent)
      - localhost:8083 (e.g., a SearchAgent)
    - The example handles offline remote agents gracefully
"""
import sys
import asyncio
from typing import Optional

from parrot.bots.agent import BasicAgent
from parrot.bots.orchestration import A2AOrchestratorAgent
from parrot.tools.google import GoogleSearchTool


# ─────────────────────────────────────────────────────────────────────────────
# Local Specialist Agents
# ─────────────────────────────────────────────────────────────────────────────

async def create_web_search_agent() -> BasicAgent:
    """Create a local web search specialist agent."""
    agent = BasicAgent(
        name="WebSearchAgent",
        llm="google:gemini-2.0-flash",
        system_prompt="""
You are a web search specialist. Your role is to:
- Search the web for current information
- Find relevant sources and articles
- Summarize search results concisely

Always cite your sources and indicate when information may be outdated.
""",
        tools=[GoogleSearchTool()],
    )
    await agent.configure()
    return agent


async def create_analysis_agent() -> BasicAgent:
    """Create a local data analysis specialist agent."""
    agent = BasicAgent(
        name="DataAnalysisAgent",
        llm="google:gemini-2.0-flash",
        system_prompt="""
You are a data analysis specialist. Your role is to:
- Analyze information and data provided to you
- Identify patterns and insights
- Provide statistical summaries when relevant
- Draw logical conclusions from evidence

Be precise and cite the specific data points that support your conclusions.
""",
    )
    await agent.configure()
    return agent


async def create_summary_agent() -> BasicAgent:
    """Create a local summarization specialist agent."""
    agent = BasicAgent(
        name="SummaryAgent",
        llm="google:gemini-2.0-flash",
        system_prompt="""
You are a summarization specialist. Your role is to:
- Condense complex information into clear summaries
- Highlight key points and takeaways
- Structure information logically
- Write in a clear, accessible style

Aim for brevity while preserving essential information.
""",
    )
    await agent.configure()
    return agent


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator Setup
# ─────────────────────────────────────────────────────────────────────────────

async def create_hybrid_orchestrator(
    remote_endpoint_1: str = "http://localhost:8082",
    remote_endpoint_2: str = "http://localhost:8083",
    connect_remote: bool = True,
) -> A2AOrchestratorAgent:
    """
    Create a hybrid orchestrator with local and remote agents.

    Args:
        remote_endpoint_1: URL for first remote A2A agent
        remote_endpoint_2: URL for second remote A2A agent
        connect_remote: If True, attempt to connect to remote agents

    Returns:
        Configured A2AOrchestratorAgent
    """
    # Create the orchestrator
    orchestrator = A2AOrchestratorAgent(
        name="HybridOrchestrator",
        llm="google:gemini-2.0-flash",
    )
    await orchestrator.configure()

    # ─────────────────────────────────────────────────────────────
    # Add 3 Local Agents
    # ─────────────────────────────────────────────────────────────

    print("\n📍 Setting up LOCAL agents...")

    # 1. Web Search Agent
    web_search_agent = await create_web_search_agent()
    orchestrator.add_agent(
        web_search_agent,
        description="Search the web for current information, news, and articles"
    )
    print(f"   ✅ Added local agent: {web_search_agent.name}")

    # 2. Data Analysis Agent
    analysis_agent = await create_analysis_agent()
    orchestrator.add_agent(
        analysis_agent,
        description="Analyze data and information to find patterns and insights"
    )
    print(f"   ✅ Added local agent: {analysis_agent.name}")

    # 3. Summary Agent
    summary_agent = await create_summary_agent()
    orchestrator.add_agent(
        summary_agent,
        description="Summarize complex information into clear, concise overviews"
    )
    print(f"   ✅ Added local agent: {summary_agent.name}")

    # ─────────────────────────────────────────────────────────────
    # Add 2 Remote A2A Agents
    # ─────────────────────────────────────────────────────────────

    if connect_remote:
        print("\n🌐 Setting up REMOTE A2A agents...")

        # Remote Agent 1 (e.g., localhost:8082)
        try:
            conn1 = await orchestrator.add_a2a_agent(
                remote_endpoint_1,
                register_as_tool=True,
            )
            print(f"   ✅ Connected to remote agent: {conn1.name} at {remote_endpoint_1}")
            print(f"      Skills: {[s.name for s in conn1.card.skills]}")
        except Exception as e:
            print(f"   ⚠️  Could not connect to {remote_endpoint_1}: {e}")
            print("      (This is expected if no A2A server is running there)")

        # Remote Agent 2 (e.g., localhost:8083)
        try:
            conn2 = await orchestrator.add_a2a_agent(
                remote_endpoint_2,
                register_as_tool=True,
            )
            print(f"   ✅ Connected to remote agent: {conn2.name} at {remote_endpoint_2}")
            print(f"      Skills: {[s.name for s in conn2.card.skills]}")
        except Exception as e:
            print(f"   ⚠️  Could not connect to {remote_endpoint_2}: {e}")
            print("      (This is expected if no A2A server is running there)")

    # Print summary
    print("\n" + "=" * 60)
    print("ORCHESTRATOR READY")
    print("=" * 60)
    agents = orchestrator.list_all_agents()
    print(f"Local agents ({len(agents['local'])}): {agents['local']}")
    print(f"Remote agents ({len(agents['remote'])}): {agents['remote']}")
    print("=" * 60 + "\n")

    return orchestrator


# ─────────────────────────────────────────────────────────────────────────────
# Test Scenarios
# ─────────────────────────────────────────────────────────────────────────────

async def test_orchestrator(orchestrator: A2AOrchestratorAgent):
    """Run test queries through the orchestrator."""

    test_queries = [
        # Test that uses local agents
        "What are the latest developments in AI? Search the web and summarize the key points.",

        # Test that could use remote agents (if available)
        "Use the list_available_a2a_agents tool to show me what remote agents are available.",
    ]

    for i, query in enumerate(test_queries, 1):
        print(f"\n{'─' * 60}")
        print(f"TEST {i}: {query[:50]}...")
        print('─' * 60)

        try:
            response = await orchestrator.ask(query)
            print(f"\n📤 Response:\n{response}")
        except Exception as e:
            print(f"\n❌ Error: {e}")

        print()


async def interactive_mode(orchestrator: A2AOrchestratorAgent):
    """Interactive mode for testing the orchestrator."""

    print("\n🎮 INTERACTIVE MODE")
    print("Type your queries below. Type 'quit' or 'exit' to stop.")
    print("Type 'agents' to list all available agents.")
    print("Type 'stats' to see usage statistics.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Goodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ('quit', 'exit'):
            print("👋 Goodbye!")
            break

        if user_input.lower() == 'agents':
            agents = orchestrator.list_all_agents()
            print(f"\n📍 Local agents: {agents['local']}")
            print(f"🌐 Remote agents: {agents['remote']}\n")
            continue

        if user_input.lower() == 'stats':
            stats = orchestrator.get_all_agent_stats()
            print(f"\nOrchestration stats: {stats}\n")
            continue

        try:
            response = await orchestrator.ask(user_input)
            print(f"\n🤖 Orchestrator: {response}\n")
        except Exception as e:
            print(f"\n❌ Error: {e}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    """Main entry point."""

    print("\n" + "=" * 60)
    print("A2A ORCHESTRATOR EXAMPLE")
    print("Hybrid Local + Remote Agent Orchestration")
    print("=" * 60)

    # Parse command line arguments
    mode = "interactive"
    connect_remote = True

    if len(sys.argv) > 1:
        if sys.argv[1] == "--test":
            mode = "test"
        elif sys.argv[1] == "--no-remote":
            connect_remote = False
        elif sys.argv[1] == "--help":
            print("""
Usage: python a2a_orchestrator_example.py [OPTIONS]

Options:
    --test        Run test queries instead of interactive mode
    --no-remote   Don't attempt to connect to remote A2A agents
    --help        Show this help message
""")
            return

    # Create the orchestrator
    orchestrator = await create_hybrid_orchestrator(
        connect_remote=connect_remote
    )

    try:
        if mode == "test":
            await test_orchestrator(orchestrator)
        else:
            await interactive_mode(orchestrator)
    finally:
        # Cleanup
        print("\n🔄 Shutting down...")
        await orchestrator.shutdown()
        print("✅ Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
