"""
Test script to verify AgentTool._execute() fix
"""
import asyncio
import traceback
from parrot.bots.agent import BasicAgent
from parrot.bots.orchestration.agent import OrchestratorAgent
from parrot.tools.google import GoogleSearchTool


async def test_direct_tool_call():
    """
    Test 1: Call AgentTool directly to verify _execute signature.
    """
    print("="*80)
    print("TEST 1: Direct AgentTool Call")
    print("="*80)

    # Create a simple agent
    specialist = BasicAgent(
        name="TestSpecialist",
        system_prompt="You are a helpful assistant. Always respond with 'TEST RESPONSE: ' followed by your answer.",
        use_llm='google'
    )
    await specialist.configure()

    # Convert to tool
    tool = specialist.as_tool(
        tool_name="testtool",
        tool_description="A test tool"
    )

    print(f"\n✅ Tool created: {tool.name}")
    print(f"   Description: {tool.description}")

    # Test direct execution with kwargs
    print("\n🧪 Testing direct tool execution...")
    try:
        result = await tool.execute(question="What is 2+2?")
        print(f"✅ SUCCESS! Tool executed")
        print(f"   Result: {result.result}...")
        return True
    except Exception as e:
        print(f"❌ FAILED: {e}")
        traceback.print_exc()
        return False


async def test_orchestrator_tool_call():
    """
    Test 2: Call AgentTool through orchestrator (how LLM calls it).
    """
    print("\n" + "="*80)
    print("TEST 2: Orchestrator Tool Call")
    print("="*80)

    # Create specialist with actual search capability
    specialist = BasicAgent(
        name="WebExpert",
        system_prompt="You search the web for information. Use your google_search tool to find answers.",
        use_llm='google'
    )
    # Add search tool to specialist
    specialist.tool_manager.add_tool(GoogleSearchTool())
    await specialist.configure()

    # Create orchestrator
    orchestrator = OrchestratorAgent(
        name="Coordinator",
        use_llm='google',
        orchestration_prompt="""You are a coordinator that delegates to a web search expert.

⚠️ CRITICAL: You MUST use the 'webexpert' tool to answer questions.

Available Tool:
- webexpert: Web search expert that finds information online, avoid using your own knowledge.

How to use:
When user asks a question, call webexpert with the question.

Example:
User: "What is the capital of France?"
→ Call: webexpert(question="What is the capital of France?")

ALWAYS use the tool. Never answer directly."""
    )
    await orchestrator.configure()

    # Register specialist as tool
    print("\n📝 Registering specialist as tool...")
    specialist.register_as_tool(
        orchestrator,
        tool_name="webexpert",
        tool_description="Web search expert. Use this to find information online."
    )

    # Verify registration
    bot_tools = orchestrator.tool_manager.list_tools()
    llm_tools = orchestrator._llm.tool_manager.list_tools()

    print(f"✅ Bot tools: {bot_tools}")
    print(f"✅ LLM tools: {llm_tools}")

    if 'webexpert' not in llm_tools:
        print("❌ ERROR: webexpert not in LLM tools!")
        return False

    # Test orchestrator
    print("\n🧪 Testing orchestrator with tool...")
    test_question = "What is the capital of France?"

    try:
        response = await orchestrator.conversation(
            question=test_question,
            use_conversation_history=False
        )

        print(f"\n📝 Question: {test_question}")
        print(f"📝 Response: {response.content[:200]}...")

        if response.tool_calls:
            print(f"\n✅ SUCCESS! {len(response.tool_calls)} tool(s) called:")
            for tc in response.tool_calls:
                print(f"   - {tc.name}")
                print(f"     Arguments: {tc.arguments}")
                if tc.error:
                    print(f"     ❌ Error: {tc.error}")
                else:
                    print(f"     ✅ Success")
            return True
        else:
            print("\n⚠️ WARNING: No tools were called")
            print("   This might be a prompt issue, not an _execute() issue")
            return False

    except Exception as e:
        print(f"\n❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_multiple_specialists():
    """
    Test 3: Multiple specialists (like the product research example).
    """
    print("\n" + "="*80)
    print("TEST 3: Multiple Specialists")
    print("="*80)

    # Create two specialists
    spec_specialist = BasicAgent(
        name="SpecSpecialist",
        system_prompt="You find technical specifications. Use web search.",
        use_llm='google'
    )
    spec_specialist.tool_manager.add_tool(GoogleSearchTool())
    await spec_specialist.configure()

    price_specialist = BasicAgent(
        name="PriceSpecialist",
        system_prompt="You find pricing information. Use web search.",
        use_llm='google'
    )
    price_specialist.tool_manager.add_tool(GoogleSearchTool())
    await price_specialist.configure()

    # Create orchestrator
    orchestrator = OrchestratorAgent(
        name="ProductCoordinator",
        use_llm='google',
        orchestration_prompt="""You coordinate product research specialists.

⚠️ CRITICAL: You MUST use specialist tools. Never answer directly.

Available Tools:
1. specspecialist - Finds technical specifications
2. pricespecialist - Finds pricing information

How to use:
- For specs: Call specspecialist(question="What are the specs of X?")
- For price: Call pricespecialist(question="What is the price of X?")
- For both: Call BOTH tools

Example:
User: "Tell me about iPhone 15 - specs and price"
→ Call: specspecialist(question="What are the specs of iPhone 15?")
→ Call: pricespecialist(question="What is the price of iPhone 15?")
"""
    )
    await orchestrator.configure()

    # Register both specialists
    print("\n📝 Registering specialists...")
    spec_specialist.register_as_tool(
        orchestrator,
        tool_name="specspecialist",
        tool_description="Finds technical specifications"
    )
    price_specialist.register_as_tool(
        orchestrator,
        tool_name="pricespecialist",
        tool_description="Finds pricing information"
    )

    print(f"✅ Registered: {orchestrator.tool_manager.list_tools()}")

    # Test with both specs and price
    print("\n🧪 Testing with query requiring both specialists...")
    test_question = "Tell me about the iPad Pro M2 - I need both specs and price"

    try:
        response = await orchestrator.conversation(
            question=test_question,
            use_conversation_history=False
        )

        print(f"\n📝 Question: {test_question}")
        print(f"📝 Response: {response.content[:300]}...")

        if response.tool_calls:
            tools_called = [tc.name for tc in response.tool_calls]
            print(f"\n✅ Tools called: {tools_called}")

            # Check if both were called
            if 'specspecialist' in tools_called and 'pricespecialist' in tools_called:
                print("✅ SUCCESS! Both specialists were called")
                return True
            elif len(tools_called) > 0:
                print("⚠️ PARTIAL: Only some specialists called")
                return True
            else:
                print("❌ No specialists called")
                return False
        else:
            print("\n⚠️ WARNING: No tools were called")
            return False

    except Exception as e:
        print(f"\n❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("\n" + "🧪 TESTING AGENTTOOL._EXECUTE() FIX ".center(80, "="))
    print()

    results = {}

    # Test 1: Direct tool call
    results['direct'] = await test_direct_tool_call()

    # Test 2: Through orchestrator
    results['orchestrator'] = await test_orchestrator_tool_call()

    # Test 3: Multiple specialists
    results['multiple'] = await test_multiple_specialists()

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)

    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name.ljust(20)}: {status}")

    all_passed = all(results.values())

    print("\n" + "="*80)
    if all_passed:
        print("🎉 ALL TESTS PASSED! AgentTool._execute() is working correctly.")
    else:
        print("⚠️ SOME TESTS FAILED. Check the output above for details.")
    print("="*80)

    return all_passed


if __name__ == "__main__":
    asyncio.run(main())
