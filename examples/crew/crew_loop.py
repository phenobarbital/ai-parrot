from typing import Any
import asyncio
from parrot.bots.agent import Agent
from parrot.bots.orchestration.crew import AgentCrew
from parrot.tools.google import GoogleSearchTool

async def quick_loop_example():
    """
    Simple example: Agents work in sequence.
    """
    print("Creating pipeline agents...")

    # Create agents for sequential processing
    researcher = Agent(
        name="Researcher",
        system_prompt="Create a market analysis over AI-powered gadgets or devices, if reports is marked as NEEDS REVISION, improve it based on the reviewer's comments.",
        use_llm='google'
    )
    analyzer = Agent(
        name="Analyzer",
        system_prompt="You analyze research data and extract useful insights, use google search to find more information if needed.",
        use_llm='google'
    )
    reporter = Agent(
        name="Reviewer",
        system_prompt="You review reports and mark them as FINAL or NEEDS REVISION with comments.",
        use_llm='google'
    )

    # Add tools and configure
    web_tool = GoogleSearchTool()
    for agent in [researcher, analyzer, reporter]:
        agent.tool_manager.add_tool(web_tool)
        await agent.configure()

    # Create crew
    crew = AgentCrew(
        name="TestLoopCrew", agents=[researcher, analyzer, reporter]
    )

    # Execute sequentially (pipeline)
    product = "Agricultural Drones or Smart Farming Devices"
    print(f"\nResearching {product} sequentially...")

    result = await crew.run_loop(
        initial_task=f"Research {product}",
        condition="Stop when the reviewer marks the report as FINAL",
        max_iterations=4,
    )

    # Show final result
    print(f"\n✅ Final Report:\n")
    print(result['final_result'])

    summary = crew.get_execution_summary()
    print(f"\n⏱️  Total time: {summary['total_execution_time']:.2f}s")

    return result


if __name__ == "__main__":
    asyncio.run(quick_loop_example())
