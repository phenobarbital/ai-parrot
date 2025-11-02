"""
Simple Usage Example for Agent Orchestration

Quick start guide for using the enhanced agent crew system.
"""
from typing import Any
import asyncio
from parrot.bots.agent import BasicAgent
from parrot.bots.orchestration.crew import AgentCrew, FlowContext
from parrot.bots.orchestration.fsm import AgentsFlow
from parrot.bots.orchestration.agent import OrchestratorAgent
from parrot.tools.google import GoogleSearchTool

async def quick_parallel_example():
    """
    Simplest example: 3 agents research in parallel.
    """
    print("Creating research agents...")

    # Create 3 specialized agents
    agent1 = BasicAgent(
        name="InfoAgent",
        system_prompt="You find product specifications and features.",
        use_llm='google'
    )

    agent2 = BasicAgent(
        name="PriceAgent",
        system_prompt="You find current product prices.",
        use_llm='google'
    )

    agent3 = BasicAgent(
        name="ReviewAgent",
        system_prompt="You analyze product reviews.",
        use_llm='google'
    )

    # Add web search tool to all agents
    web_tool = GoogleSearchTool()
    for agent in [agent1, agent2, agent3]:
        agent.tool_manager.add_tool(web_tool)
        await agent.configure()

    # Create crew
    crew = AgentCrew(agents=[agent1, agent2, agent3])

    # Define parallel tasks
    product = "iPhone 15 Pro"
    tasks = [
        {'agent_id': 'InfoAgent', 'query': f"Find specs for {product}"},
        {'agent_id': 'PriceAgent', 'query': f"Find prices for {product}"},
        {'agent_id': 'ReviewAgent', 'query': f"Find reviews for {product}"}
    ]

    # Execute in parallel
    print(f"\nResearching {product} in parallel...")
    result = await crew.run_parallel(tasks)

    # Show results
    print(f"\n✅ Completed in {result['total_execution_time']:.2f}s\n")
    for agent_id, output in result['results'].items():
        print(f"{agent_id}:\n{output[:200]}...\n")

    return result


async def quick_sequential_example():
    """
    Simple example: Agents work in sequence.
    """
    print("Creating pipeline agents...")

    # Create agents for sequential processing
    researcher = BasicAgent(
        name="Researcher",
        system_prompt="You research products thoroughly.",
        use_llm='google'
    )

    analyzer = BasicAgent(
        name="Analyzer",
        system_prompt="You analyze research data and extract insights.",
        use_llm='google'
    )

    reporter = BasicAgent(
        name="Reporter",
        system_prompt="You create clear, concise reports.",
        use_llm='google'
    )

    # Add tools and configure
    web_tool = GoogleSearchTool()
    for agent in [researcher, analyzer, reporter]:
        agent.tool_manager.add_tool(web_tool)
        await agent.configure()

    # Create crew
    crew = AgentCrew(agents=[researcher, analyzer, reporter])

    # Execute sequentially (pipeline)
    product = "MacBook Pro M3"
    print(f"\nResearching {product} sequentially...")

    result = await crew.run_sequential(
        query=f"Research {product}",
        pass_full_context=True
    )

    # Show final result
    print(f"\n✅ Final Report:\n")
    print(result['final_result'])

    summary = crew.get_execution_summary()
    print(f"\n⏱️  Total time: {summary['total_execution_time']:.2f}s")

    return result

async def quick_flow_example():
    # Create agents (using your existing Agent classes)
    writer = BasicAgent(
        name="writer",
        system_prompt="Draft a short paragraph on the given topic.",
        use_llm='google'
    )

    editor1 = BasicAgent(
        name="editor1",
        system_prompt="Edit for grammar and clarity.",
        use_llm='google'
    )

    editor2 = BasicAgent(
        name="editor2",
        system_prompt="Edit for style and tone.",
        use_llm='google'
    )

    final_reviewer = BasicAgent(
        name="final_reviewer",
        system_prompt="Consolidate edits into final version.",
        use_llm='google'
    )

    # Add tools and configure
    web_tool = GoogleSearchTool()
    for agent in [writer, editor1, editor2, final_reviewer]:
        agent.tool_manager.add_tool(web_tool)
        await agent.configure()

    # Create crew
    crew = AgentCrew(agents=[writer, editor1, editor2, final_reviewer])

    # Define workflow: writer -> [editor1, editor2] -> final_reviewer
    crew.task_flow(writer, [editor1, editor2])  # Parallel execution
    crew.task_flow(editor1, final_reviewer)      # Both editors must complete
    crew.task_flow(editor2, final_reviewer)      # before final reviewer runs

    # Optional: Validate workflow before running
    await crew.validate_workflow()

    # Optional: Visualize workflow
    print(crew.visualize_workflow())

    # Optional: Define callback for monitoring
    async def on_complete(agent_name: str, result: Any, context: FlowContext):
        print(f"✓ {agent_name} completed: {result[:100]}...")

    # Run the workflow
    final_results = await crew.run_flow(
        initial_task="Write about climate change",
        on_agent_complete=on_complete
    )

    # Access results
    print("\nFinal Results:")
    print(final_results["results"]["final_reviewer"])

    return final_results

async def orchestrator_example():
    """
    Orchestrator with improved prompting for better tool usage.
    """
    print("Creating orchestrator with specialists...")

    # Create specialist agents with CLEAR roles and goals
    spec_agent = BasicAgent(
        name="TechSpecialist",
        agent_id="tech_specialist",
        role="Technical Specifications Expert",
        goal="Find detailed technical specifications and features of products",
        system_prompt="""You are a technical specifications expert.

Your specialty is finding detailed technical information about products including:
- Hardware specifications (processor, RAM, storage, display)
- Software features and capabilities
- Technical measurements (dimensions, weight, battery)
- Supported standards and compatibility

Always search the web for the most current and accurate information.
Provide specific technical details with sources.""",
        use_llm='google'
    )

    price_agent = BasicAgent(
        name="PriceSpecialist",
        agent_id="price_specialist",
        role="Pricing Research Expert",
        goal="Find current market prices and pricing information",
        system_prompt="""You are a pricing research expert.

Your specialty is finding pricing information including:
- Current retail prices from major retailers
- Price ranges across different configurations
- Available discounts or promotions
- Historical price trends

Always search the web for current pricing.
Provide specific prices with retailer sources and dates.""",
        use_llm='google'
    )

    # Add search tools
    web_tool = GoogleSearchTool()
    for agent in [spec_agent, price_agent]:
        agent.tool_manager.add_tool(web_tool)
        await agent.configure()

    # Create orchestrator with VERY EXPLICIT instructions
    orchestrator = OrchestratorAgent(
        name="ProductResearchCoordinator",
        agent_id="coordinator",
        use_llm='google',
        orchestration_prompt="""You are a Product Research Coordinator that delegates tasks to specialist agents.

**CRITICAL: You MUST use the specialist tools to answer questions. You cannot answer directly.**

Available Specialist Tools:
1. techspecialist - Technical specifications expert
   - Use for: product specs, features, technical details
   - Example: "What are the specs of iPhone 15?"

2. pricespecialist - Pricing research expert
   - Use for: prices, costs, pricing information
   - Example: "What is the price of iPhone 15?"

**How to Answer Questions:**

Step 1: Identify what information is needed
Step 2: Call the appropriate specialist tool(s)
Step 3: Synthesize their responses into a complete answer

**Examples:**

Question: "What are the specs of the iPad Pro M2?"
→ Call techspecialist with question: "What are the specifications of the iPad Pro M2?"

Question: "How much does the MacBook Pro cost?"
→ Call pricespecialist with question: "What is the current price of the MacBook Pro?"

Question: "Tell me about the iPhone 15 Pro - specs and price"
→ Call techspecialist with question: "What are the specifications of iPhone 15 Pro?"
→ Call pricespecialist with question: "What is the price of iPhone 15 Pro?"
→ Combine both responses

**IMPORTANT:**
- ALWAYS use tools - don't try to answer from your own knowledge
- If a question needs both specs and price, call BOTH tools
- Pass clear, specific questions to each specialist
- Wait for tool responses before answering the user"""
    )

    await orchestrator.configure()

    # Register specialists as tools with CLEAR descriptions
    spec_agent.register_as_tool(
        orchestrator,
        tool_name="techspecialist",  # Simple, clear name
        tool_description="Technical specifications expert. Use this to find detailed product specs, features, and technical information."
    )

    price_agent.register_as_tool(
        orchestrator,
        tool_name="pricespecialist",  # Simple, clear name
        tool_description="Pricing research expert. Use this to find current product prices, costs, and pricing information from retailers."
    )

    # Verify tools are registered
    print(f"\n📋 Registered tools: {orchestrator.tool_manager.list_tools()}")
    print(f"📊 Tool count: {orchestrator.get_tools_count()}")

    # Test questions
    test_questions = [
        "What are the specs of the iPad Pro M2?",
        "How much does the iPad Pro M2 cost?",
        "Tell me about the iPhone 15 Pro - both specs and price"
    ]

    for i, question in enumerate(test_questions, 1):
        print(f"\n{'='*80}")
        print(f"TEST {i}: {question}")
        print('='*80)

        response = await orchestrator.conversation(
            question=question,
            use_conversation_history=False
        )

        print(f"\n📝 Response:\n{response.content}")

        if response.tool_calls:
            print(f"\n✅ Tools used: {len(response.tool_calls)}")
            for tc in response.tool_calls:
                print(f"  - {tc.name}: {tc.arguments} → {tc.result[:100]}...")
        else:
            print("\n⚠️  WARNING: No tools were used!")

        print()

    return orchestrator

async def test_fsm():
    # DAG:
    crew = AgentsFlow(name="ResearchCrew")

    # Create agents
    researcher = BasicAgent(
        name="Researcher",
        system_prompt="You research products thoroughly.",
        llm='google'
    )

    analyzer = BasicAgent(
        name="Analyzer",
        system_prompt="You analyze research data and extract insights.",
        llm='google'
    )

    writer = BasicAgent(
        name="Writer",
        system_prompt="You create clear, concise reports.",
        llm='google'
    )

    error_handler = BasicAgent(
        name="ErrorHandler",
        system_prompt="You fix errors in analysis and retry tasks.",
        llm='google'
    )
    # Add agents
    agents = [researcher, analyzer, writer, error_handler]
    for agent in agents:
        web_tool = GoogleSearchTool()
        agent.tool_manager.add_tool(web_tool)
        await agent.configure()
        crew.add_agent(agent)

    # Define flow
    crew.task_flow(researcher, analyzer)
    crew.task_flow(analyzer, writer)

    # Add error handling
    crew.on_error(analyzer, error_handler,
        instruction="Fix the error and retry"
    )
    crew.task_flow(error_handler, analyzer)

    # Execute
    result = await crew.run_flow("Research AI trends in 2025")

    print(f"\n{'='*80}")
    print("WORKFLOW EXECUTION SUMMARY")
    print(f"{'='*80}")

    # Status information
    print(f"\n✓ Status: {result.status}")
    print(f"✓ Total Time: {result.total_time:.2f}s")
    print(f"✓ Completed Agents: {len([a for a in result.agents if a.status == 'completed'])}/{len(result.agents)}")

    # Execution order with detailed info
    print(f"\n{'─'*80}")
    print("EXECUTION ORDER:")
    print(f"{'─'*80}")
    for i, agent_info in enumerate(result.agents, 1):
        status_icon = "✓" if agent_info.status == "completed" else "✗"
        print(f"{i}. {status_icon} {agent_info.agent_name}")
        print(f"   - Time: {agent_info.execution_time:.2f}s")
        print(f"   - Model: {agent_info.model or 'N/A'}")
        print(f"   - Status: {agent_info.status}")
        if agent_info.error:
            print(f"   - Error: {agent_info.error}")

    # Final output (from terminal agent)
    print(f"\n{'='*80}")
    print("FINAL REPORT (from Writer):")
    print(f"{'='*80}")
    print(result.output)  # or result.content - both work!

    # Error handling
    if result.errors:
        print(f"\n{'='*80}")
        print("ERRORS DETECTED:")
        print(f"{'='*80}")
        for agent_id, error in result.errors.items():
            print(f"❌ {agent_id}: {error}")

    # Metadata
    print(f"\n{'='*80}")
    print("EXECUTION METADATA:")
    print(f"{'='*80}")
    for key, value in result.metadata.items():
        print(f"  {key}: {value}")


async def test_simple_delegation():
    """
    Even simpler test - single specialist.
    """
    print("\n" + "="*80)
    print("SIMPLE DELEGATION TEST")
    print("="*80)

    # Create ONE specialist
    specialist = BasicAgent(
        name="WebExpert",
        role="Web Search Expert",
        goal="Search the web for information",
        system_prompt="You search the web for information. Always use your search tool.",
        use_llm='google'
    )

    web_tool = GoogleSearchTool()
    specialist.tool_manager.add_tool(web_tool)
    await specialist.configure()

    # Create orchestrator
    orchestrator = OrchestratorAgent(
        name="SimpleCoordinator",
        use_llm='google',
        orchestration_prompt="""You coordinate with a web search expert.

You have ONE tool:
- webexpert: Searches the web for information

ALWAYS use the webexpert tool to answer questions.
Pass the user's question directly to the tool.

Example:
User: "What is the capital of France?"
→ Call webexpert with question: "What is the capital of France?"
"""
    )

    await orchestrator.configure()

    # Register specialist
    specialist.register_as_tool(
        orchestrator,
        tool_name="webexpert",
        tool_description="Web search expert that finds information online"
    )

    print(f"Registered tools: {orchestrator.tool_manager.list_tools()}")

    # Ask question
    print("\nAsking: What is the price of iPhone 15?")
    response = await orchestrator.conversation(
        question="What is the price of iPhone 15?",
        use_conversation_history=False
    )

    print(f"\n📝 Response:\n{response.content}")

    if response.tool_calls:
        print(f"\n✅ Tool was used!")
        for tc in response.tool_calls:
            print(f"  - {tc.name}")
    else:
        print("\n⚠️  No tool used - checking why...")
        print(f"Tools available: {orchestrator.get_tools_count()}")
        print(f"Tools enabled: {orchestrator.enable_tools}")
        print(f"Operation mode: {orchestrator.operation_mode}")



# Quick test runner
async def run_examples():
    """Run all quick examples."""

    print("="*80)
    print("EXAMPLE 1: PARALLEL EXECUTION")
    print("="*80)
    await quick_parallel_example()

    print("\n" + "="*80)
    print("EXAMPLE 2: SEQUENTIAL EXECUTION")
    print("="*80)
    await quick_sequential_example()

    print("\n" + "="*80)
    print("EXAMPLE 3: WORKFLOW FLOW")
    print("="*80)
    await quick_flow_example()

    # print("\n" + "="*80)
    # print("EXAMPLE 3: ORCHESTRATOR")
    # print("="*80)
    # await orchestrator_example()

    # print("\n" + "="*80)
    # print("EXAMPLE 4: SIMPLE DELEGATION")
    # print("="*80)
    # await test_simple_delegation()

    # print("\n" + "="*80)
    # print("EXAMPLE 5: FSM WORKFLOW")
    # print("="*80)
    # await test_fsm()


if __name__ == "__main__":
    asyncio.run(run_examples())
