"""
Complete Working Example - Product Research Orchestrator
Copy this file and run it to test the orchestrator system.
"""
import sys
import asyncio
from parrot.bots.agent import BasicAgent
from parrot.bots.orchestration.agent import OrchestratorAgent
from parrot.tools.google import GoogleSearchTool


async def create_product_research_orchestrator():
    """
    Create a working product research orchestrator.

    Returns a configured orchestrator ready to use.
    """

    # ========================================================================
    # 1. CREATE SPECIALIST AGENTS
    # ========================================================================

    print("📦 Creating specialist agents...")

    # Technical Specifications Specialist
    tech_specialist = BasicAgent(
        name="TechSpecialist",
        agent_id="tech_specialist",
        role="Technical Specifications Expert",
        goal="Find detailed technical specifications and features",
        capabilities="Hardware specs, software features, technical measurements",
        system_prompt="""You are a technical specifications expert.

Your expertise:
- Hardware specifications (CPU, RAM, storage, display)
- Software features and capabilities
- Technical measurements (dimensions, weight, battery life)
- Standards and compatibility

IMPORTANT: Always use your web search tool to find current, accurate information.

Response format:
- Start with product name
- List specs in categories
- Include sources and dates
- Be specific with numbers and units""",
        use_llm='google'
    )

    # Pricing Research Specialist
    price_specialist = BasicAgent(
        name="PriceSpecialist",
        agent_id="price_specialist",
        role="Pricing Research Expert",
        goal="Find current market prices and deals",
        capabilities="Retail prices, price comparisons, discounts, availability",
        system_prompt="""You are a pricing research expert.

Your expertise:
- Current retail prices from major retailers
- Price ranges for different configurations
- Available discounts and promotions
- Price trends and best deals

IMPORTANT: Always use your web search tool to find current prices.

Response format:
- List prices by retailer
- Note configuration/model differences
- Mention any current deals
- Include dates when prices were found""",
        use_llm='google'
    )

    review_specialist = BasicAgent(
        name="ReviewSpecialist",
        agent_id="review_specialist",
        role="Product Review Expert",
        goal="Find and summarize product reviews",
        capabilities="Customer reviews, expert opinions, pros and cons",
        system_prompt="""You are a product review expert.

Your expertise:
- Analyzing customer reviews
- Summarizing expert opinions
- Identifying pros and cons

IMPORTANT: Always use your web search tool to find current, accurate information.

Response format:
- Start with product name
- List key points from reviews
- Include sources and dates
- Be specific with quotes and citations""",
        use_llm='google'
    )

    # Add search tools to specialists
    search_tool = GoogleSearchTool()
    agents = [tech_specialist, price_specialist, review_specialist]
    for specialist in agents:
        specialist.tool_manager.add_tool(search_tool)
        await specialist.configure()

    print("✅ Specialists configured")

    # ========================================================================
    # 2. CREATE ORCHESTRATOR
    # ========================================================================

    print("\n🎭 Creating orchestrator...")

    orchestrator = OrchestratorAgent(
        name="ProductResearchCoordinator",
        agent_id="product_coordinator",
        use_llm='google',
        orchestration_prompt="""You are a Product Research Coordinator that delegates to specialist agents.

═══════════════════════════════════════════════════════════════
⚠️  CRITICAL INSTRUCTION: You MUST use specialist tools to answer
    questions. You do NOT answer from your own knowledge.
═══════════════════════════════════════════════════════════════

🔧 AVAILABLE SPECIALIST TOOLS:

1. techspecialist
   Purpose: Find product specifications and technical details
   Use for: specs, features, hardware, technical info
   Example: techspecialist(question="What are the specs of iPhone 15 Pro?")

2. pricespecialist
   Purpose: Find current prices and deals
   Use for: prices, costs, deals, availability
   Example: pricespecialist(question="What is the price of iPhone 15 Pro?")

3. reviewspecialist
   Purpose: Find and summarize product reviews
   Use for: customer reviews, expert opinions, pros and cons
   Example: reviewspecialist(question="What do customers say about iPhone 15 Pro?")

📋 HOW TO ANSWER QUESTIONS:

Step 1: Analyze what information the user needs
Step 2: Call the appropriate specialist tool(s)
Step 3: Wait for their responses
Step 4: Synthesize the information into a clear answer

🎯 EXAMPLES:

User: "What are the specs of the iPad Pro M2?"
→ Action: Call techspecialist(question="What are the specifications of the iPad Pro M2?")

User: "How much does the MacBook Pro M3 cost?"
→ Action: Call pricespecialist(question="What is the price of the MacBook Pro M3?")

User: "Tell me about the iPhone 15 Pro - I want specs and price"
→ Action 1: Call techspecialist(question="What are the specifications of iPhone 15 Pro?")
→ Action 2: Call pricespecialist(question="What is the price of iPhone 15 Pro?")
→ Combine: Synthesize both responses into one comprehensive answer

⚡ RULES:

1. ALWAYS use tools - never answer from your knowledge
2. Pass clear, specific questions to each specialist
3. If query needs both specs AND price, call BOTH tools
4. Synthesize responses into a natural, comprehensive answer
5. Credit specialists when appropriate (e.g., "According to our tech specialist...")"""
    )

    await orchestrator.configure()

    print("✅ Orchestrator configured")

    # ========================================================================
    # 3. REGISTER SPECIALISTS AS TOOLS
    # ========================================================================

    print("\n🔌 Registering specialists as tools...")

    tech_specialist.register_as_tool(
        orchestrator,
        tool_name="techspecialist",
        tool_description="Technical specifications expert. Use this to find detailed product specs, features, hardware information, and technical details."
    )

    price_specialist.register_as_tool(
        orchestrator,
        tool_name="pricespecialist",
        tool_description="Pricing research expert. Use this to find current product prices, deals, availability, and pricing information from retailers."
    )

    review_specialist.register_as_tool(
        orchestrator,
        tool_name="reviewspecialist",
        tool_description="Product review expert. Use this to find and summarize customer reviews, expert opinions, and pros and cons of products."
    )

    # Verify registration
    registered_tools = orchestrator.tool_manager.list_tools()
    print(f"✅ Registered tools: {registered_tools}")
    print(f"✅ Total tools: {orchestrator.get_tools_count()}")

    return orchestrator


async def test_orchestrator():
    """
    Test the orchestrator with various queries.
    """

    # Create orchestrator
    orchestrator = await create_product_research_orchestrator()

    # Test queries
    test_queries = [
        # {
        #     "name": "Specs Only",
        #     "query": "What are the technical specifications of the iPad Pro M2?",
        #     "expected_tools": ["techspecialist"]
        # },
        # {
        #     "name": "Price Only",
        #     "query": "How much does the iPhone 15 Pro cost?",
        #     "expected_tools": ["pricespecialist"]
        # },
        # {
        #     "name": "Both Specs and Price",
        #     "query": "Tell me about the MacBook Pro M3 - I need both specs and pricing information",
        #     "expected_tools": ["techspecialist", "pricespecialist"]
        # },
        {
            "name": "Specs, Price, and Reviews",
            "query": "What are the specs, price, and customer reviews for the Samsung Galaxy S23 Ultra?",
            "expected_tools": ["techspecialist", "pricespecialist", "reviewspecialist"]
        },
    ]

    print("\n" + "="*80)
    print("TESTING ORCHESTRATOR")
    print("="*80)

    for i, test in enumerate(test_queries, 1):
        print(f"\n{'='*80}")
        print(f"TEST {i}: {test['name']}")
        print(f"{'='*80}")
        print(f"Query: {test['query']}")
        print(f"Expected tools: {test['expected_tools']}")
        print()

        # Execute query
        response = await orchestrator.conversation(
            question=test['query'],
            use_conversation_history=False
        )

        # Display response
        print(f"📝 RESPONSE:")
        print("-" * 80)
        print(response.content)
        print()

        # Check tool usage
        if response.tool_calls:
            tools_used = [tc.name for tc in response.tool_calls]
            print(f"✅ Tools used: {tools_used}")

            # Verify expected tools
            all_expected = all(tool in tools_used for tool in test['expected_tools'])
            if all_expected:
                print(f"✅ All expected tools were called")
            else:
                print(f"⚠️  Expected {test['expected_tools']}, got {tools_used}")

            # Show tool details
            for tc in response.tool_calls:
                print(f"\n  🔧 {tc.name}:")
                print(f"     Input: {tc.arguments}")
        else:
            print("❌ FAILED: No tools were used!")
            print("   This is a problem - orchestrator should always use tools")

        print()


async def interactive_mode():
    """
    Interactive mode to test orchestrator with custom queries.
    """

    orchestrator = await create_product_research_orchestrator()

    print("\n" + "="*80)
    print("INTERACTIVE MODE")
    print("="*80)
    print("\nYou can now ask product research questions.")
    print("The orchestrator will delegate to specialist agents.")
    print("\nExamples:")
    print("  - What are the specs of the iPhone 15 Pro?")
    print("  - How much does the iPad Pro M2 cost?")
    print("  - Tell me about the MacBook Pro M3 - specs and price")
    print("\nType 'quit' to exit\n")

    while True:
        try:
            query = input("Your question: ").strip()

            if query.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break

            if not query:
                continue

            print(f"\n🤔 Processing...")

            response = await orchestrator.conversation(
                question=query,
                use_conversation_history=False
            )

            print(f"\n📝 Response:")
            print("-" * 80)
            print(response.content)

            if response.tool_calls:
                print(f"\n🔧 Tools used: {[tc.name for tc in response.tool_calls]}")
            else:
                print(f"\n⚠️  No tools used")

            print()

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")


async def main():
    """
    Main entry point.
    """
    if len(sys.argv) > 1 and sys.argv[1] == "interactive":
        await interactive_mode()
    else:
        await test_orchestrator()


if __name__ == "__main__":
    asyncio.run(main())
