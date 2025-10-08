"""
Debugging script for orchestrator tool calling issues
"""
import asyncio
import json
from parrot.bots.agent import BasicAgent
from parrot.tools.agent import AgentTool
from parrot.bots.orchestration.agent import OrchestratorAgent


async def diagnose_orchestrator():
    """
    Diagnose why orchestrator isn't using tools.
    """
    print("="*80)
    print("ORCHESTRATOR DIAGNOSTIC")
    print("="*80)

    # 1. Create a simple specialist
    specialist = BasicAgent(
        name="TestSpecialist",
        role="Test Expert",
        goal="Answer test questions",
        system_prompt="You are a test expert. Answer questions with 'TEST RESPONSE: ' prefix.",
        use_llm='google'
    )

    await specialist.configure()

    # 2. Create orchestrator
    orchestrator = OrchestratorAgent(
        name="TestOrchestrator",
        use_llm='google',
        orchestration_prompt="""You are a coordinator.

You have one tool available:
- testspecialist: A test expert that answers questions

ALWAYS use the testspecialist tool to answer any question.

When user asks a question:
1. Call testspecialist with the question
2. Return the specialist's response"""
    )

    await orchestrator.configure()

    # 3. Register specialist as tool
    print("\n1. REGISTERING SPECIALIST AS TOOL")
    print("-" * 80)

    specialist.register_as_tool(
        orchestrator,
        tool_name="testspecialist",
        tool_description="Test expert that answers questions"
    )

    # 4. Check tool registration
    print("\n2. TOOL REGISTRATION CHECK")
    print("-" * 80)

    bot_tools = orchestrator.tool_manager.list_tools()
    print(f"Bot tool manager tools: {bot_tools}")

    if hasattr(orchestrator._llm, 'tool_manager'):
        llm_tools = orchestrator._llm.tool_manager.list_tools()
        print(f"LLM tool manager tools: {llm_tools}")

    print(f"Total tool count: {orchestrator.get_tools_count()}")
    print(f"Has tools: {orchestrator.has_tools()}")
    print(f"Tools enabled: {orchestrator.enable_tools}")
    print(f"Operation mode: {orchestrator.operation_mode}")

    # 5. Inspect tool details
    print("\n3. TOOL DETAILS")
    print("-" * 80)

    for tool_name in bot_tools:
        tool = orchestrator.tool_manager.get_tool(tool_name)
        print(f"\nTool: {tool_name}")
        print(f"  Name: {tool.name}")
        print(f"  Description: {tool.description}")
        print(f"  Schema: {json.dumps(tool.get_tool_schema(), indent=2)}")

    # 6. Check LLM configuration
    print("\n4. LLM CONFIGURATION")
    print("-" * 80)

    print(f"LLM class: {orchestrator._llm.__class__.__name__}")
    print(f"Model: {orchestrator._llm_model}")
    print(f"Enable tools in LLM: {getattr(orchestrator._llm, 'enable_tools', 'N/A')}")

    # 7. Test tool call decision
    print("\n5. TOOL CALL DECISION TEST")
    print("-" * 80)

    test_question = "What is 2+2?"
    should_use_tools = orchestrator._use_tools(test_question)
    print(f"Question: {test_question}")
    print(f"Should use tools: {should_use_tools}")
    print(f"Effective mode: {orchestrator.get_operation_mode()}")

    # 8. Try actual execution
    print("\n6. ACTUAL EXECUTION TEST")
    print("-" * 80)

    response = await orchestrator.conversation(
        question="What is 2+2?",
        use_conversation_history=False
    )

    print(f"Response content: {response.content}")
    print(f"Tool calls made: {len(response.tool_calls) if response.tool_calls else 0}")

    if response.tool_calls:
        print("\n✅ SUCCESS! Tools were used:")
        for tc in response.tool_calls:
            print(f"  - {tc.name}: {tc.arguments} -> {tc.result}")
    else:
        print("\n❌ FAILURE: No tools were used")
        print("\nPossible issues:")
        print("  1. Tool schema not compatible with Google GenAI")
        print("  2. System prompt not explicit enough")
        print("  3. LLM not configured to use tools")
        print("  4. Tools not synced to LLM properly")

    # 9. Check system prompt
    print("\n7. SYSTEM PROMPT CHECK")
    print("-" * 80)
    print("System prompt template:")
    print(orchestrator.system_prompt_template[:500] + "...")

    # 10. Summary
    print("\n8. DIAGNOSTIC SUMMARY")
    print("-" * 80)

    issues = []

    if not orchestrator.has_tools():
        issues.append("❌ No tools registered")
    else:
        print("✅ Tools are registered")

    if not orchestrator.enable_tools:
        issues.append("❌ Tools not enabled")
    else:
        print("✅ Tools are enabled")

    if orchestrator.operation_mode == 'conversational':
        issues.append("❌ Operation mode is 'conversational' (should be 'agentic' or 'adaptive')")
    else:
        print(f"✅ Operation mode is '{orchestrator.operation_mode}'")

    if not hasattr(orchestrator._llm, 'tool_manager'):
        issues.append("❌ LLM doesn't have tool_manager")
    else:
        print("✅ LLM has tool_manager")

    if issues:
        print("\n⚠️  ISSUES FOUND:")
        for issue in issues:
            print(f"  {issue}")
    else:
        print("\n✅ All basic checks passed")
        print("   If tools still not working, issue is likely in:")
        print("   - Google GenAI tool schema compatibility")
        print("   - System prompt clarity")
        print("   - Tool calling configuration in Google client")


async def test_direct_tool_call():
    """
    Test calling the AgentTool directly, bypassing orchestrator.
    """
    print("\n" + "="*80)
    print("DIRECT TOOL CALL TEST")
    print("="*80)

    # Create specialist
    specialist = BasicAgent(
        name="DirectSpecialist",
        system_prompt="Answer with 'DIRECT: ' prefix.",
        use_llm='google'
    )

    await specialist.configure()

    # Create tool directly
    tool = AgentTool(
        agent=specialist,
        tool_name="direct_tool",
        tool_description="Direct test tool"
    )

    print(f"\nTool created: {tool.name}")
    print(f"Tool description: {tool.description}")
    print(f"Tool schema: {json.dumps(tool.get_tool_schema(), indent=2)}")

    # Call tool directly
    print("\nCalling tool directly...")
    result = await tool.execute("What is 2+2?")

    print(f"\nDirect call result: {result}")
    print("\n✅ Direct tool call works!")


async def test_minimal_orchestrator():
    """
    Absolute minimal orchestrator test.
    """
    print("\n" + "="*80)
    print("MINIMAL ORCHESTRATOR TEST")
    print("="*80)

    # Minimal specialist
    specialist = BasicAgent(
        name="Mini",
        system_prompt="You answer questions.",
        use_llm='google'
    )
    await specialist.configure()

    # Minimal orchestrator
    orch = OrchestratorAgent(
        name="MiniOrch",
        use_llm='google',
        orchestration_prompt="""Use the 'mini' tool to answer questions.

Tool: mini - answers questions

Always call mini tool with the user's question."""
    )
    await orch.configure()

    # Register
    specialist.register_as_tool(orch, tool_name="mini")

    # Test
    print(f"Tools: {orch.tool_manager.list_tools()}")
    print(f"Count: {orch.get_tools_count()}")

    resp = await orch.conversation(
        question="test",
        use_conversation_history=False
    )

    print(f"Response: {resp.content[:200]}")
    print(f"Tools used: {len(resp.tool_calls) if resp.tool_calls else 0}")


async def main():
    """Run all diagnostics."""
    await diagnose_orchestrator()
    await test_direct_tool_call()
    await test_minimal_orchestrator()


if __name__ == "__main__":
    asyncio.run(main())
