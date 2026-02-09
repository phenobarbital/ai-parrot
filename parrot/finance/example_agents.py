"""
Trading Swarm - Usage Example
==============================

Example of how to instantiate and use the Trading Swarm agents.
"""

import asyncio
from parrot.finance.agents import (
    create_all_agents,
    create_macro_analyst,
    create_stock_executor,
)


async def example_basic_usage():
    """Basic example: create individual agents."""
    # Create a single analyst
    macro_analyst = create_macro_analyst()
    print(f"Created: {macro_analyst.name} (ID: {macro_analyst.agent_id})")
    print(f"Model: {macro_analyst.llm}")
    
    # Create a single executor
    stock_executor = create_stock_executor()
    print(f"\nCreated: {stock_executor.name} (ID: {stock_executor.agent_id})")
    print(f"Capabilities: {stock_executor.capabilities.capabilities}")
    print(f"Platforms: {stock_executor.capabilities.platforms}")
    print(f"Max order %: {stock_executor.capabilities.constraints.max_order_pct}")


async def example_create_all():
    """Example: create all agents at once."""
    all_agents = create_all_agents()
    
    print("=== Trading Swarm Agents ===\n")
    
    for layer_name, agents in all_agents.items():
        print(f"\n{layer_name.upper().replace('_', ' ')}:")
        for agent_id, agent in agents.items():
            print(f"  - {agent.name} ({agent.agent_id}) - Model: {agent.llm}")
    
    # Count total agents
    total = sum(len(agents) for agents in all_agents.values())
    print(f"\nTotal agents created: {total}")


async def example_agent_interaction():
    """Example: basic agent interaction."""
    # Create an analyst
    analyst = create_macro_analyst()
    
    # Example of how you would use it (requires actual implementation)
    # This is just to show the interface
    print(f"\nAgent: {analyst.name}")
    print(f"Instructions: {analyst.goal}")
    
    # In a real scenario, you would:
    # 1. Prepare the research briefing
    # 2. Call the agent with the briefing
    # 3. Get the analyst report back
    # Example (pseudo-code):
    # briefing = prepare_research_briefing(...)
    # report = await analyst.invoke(question=format_briefing(briefing))


async def main():
    """Run all examples."""
    print("=" * 60)
    print("TRADING SWARM - AGENT EXAMPLES")
    print("=" * 60)
    
    print("\n1. Basic Usage Example:")
    print("-" * 60)
    await example_basic_usage()
    
    print("\n\n2. Create All Agents Example:")
    print("-" * 60)
    await example_create_all()
    
    print("\n\n3. Agent Interaction Example:")
    print("-" * 60)
    await example_agent_interaction()
    
    print("\n" + "=" * 60)
    print("Examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
