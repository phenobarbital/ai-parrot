"""
Test to verify AgentTool schema structure is correct for Google GenAI
"""
import asyncio
import json
from parrot.bots.agent import BasicAgent


async def test_schema_structure():
    """Verify the schema has the correct structure."""
    print("="*80)
    print("TEST: AgentTool Schema Structure")
    print("="*80)

    # Create a test agent
    agent = BasicAgent(
        name="TestAgent",
        role="Test Expert",
        goal="Answer test questions",
        system_prompt="You are a test expert.",
        use_llm='google'
    )
    await agent.configure()

    # Convert to tool
    tool = agent.as_tool(
        tool_name="testtool",
        tool_description="A test tool for verification"
    )

    # Get schema
    schema = tool.get_tool_schema()

    print("\n📋 Generated Schema:")
    print(json.dumps(schema, indent=2))

    # Verify structure
    print("\n🔍 Verification:")

    # Check top-level keys
    assert 'name' in schema, "❌ Missing 'name' key"
    print("✅ Has 'name' key")

    assert 'description' in schema, "❌ Missing 'description' key"
    print("✅ Has 'description' key")

    assert 'parameters' in schema, "❌ Missing 'parameters' key (CRITICAL!)"
    print("✅ Has 'parameters' key")

    # Check parameters structure
    params = schema['parameters']
    assert 'type' in params, "❌ Parameters missing 'type'"
    print("✅ Parameters has 'type'")

    assert params['type'] == 'object', "❌ Parameters type should be 'object'"
    print("✅ Parameters type is 'object'")

    assert 'properties' in params, "❌ Parameters missing 'properties'"
    print("✅ Parameters has 'properties'")

    assert 'question' in params['properties'], "❌ Missing 'question' property"
    print("✅ Parameters has 'question' property")

    assert 'required' in params, "❌ Parameters missing 'required'"
    print("✅ Parameters has 'required'")

    assert 'question' in params['required'], "❌ 'question' not in required"
    print("✅ 'question' is in required")

    print("\n✅ Schema structure is CORRECT for Google GenAI!")
    print("\nWhat Google GenAI will extract:")
    print(f"  schema.get('parameters') = {json.dumps(params, indent=2)}")

    return True


async def test_google_genai_extraction():
    """
    Simulate how GoogleGenAIClient extracts the schema.
    """
    print("\n" + "="*80)
    print("TEST: Simulate Google GenAI Schema Extraction")
    print("="*80)

    agent = BasicAgent(
        name="TestAgent",
        system_prompt="You are a test expert.",
        use_llm='google'
    )
    await agent.configure()

    tool = agent.as_tool(tool_name="testtool")

    # Simulate what GoogleGenAIClient does
    full_schema = tool.get_tool_schema()

    print("\n🔧 Full schema returned by get_tool_schema():")
    print(json.dumps(full_schema, indent=2))

    # This is what GoogleGenAIClient does:
    schema = full_schema.get("parameters", {})

    print("\n🔍 Schema extracted by GoogleGenAIClient:")
    print(json.dumps(schema, indent=2))

    # Verify it's not empty
    if not schema:
        print("\n❌ FAILED: Extracted schema is EMPTY!")
        print("   This is why the LLM doesn't pass arguments!")
        return False
    else:
        print("\n✅ SUCCESS: Extracted schema is NOT empty!")
        print("   Google GenAI will use this to know what arguments to pass")

        # Verify it has the right structure
        if 'properties' in schema and 'question' in schema['properties']:
            print("✅ Schema includes 'question' parameter")
            print("   LLM will now pass: {'question': '...'}")
            return True
        else:
            print("❌ Schema missing 'question' parameter")
            return False


async def test_with_orchestrator():
    """Test with actual orchestrator setup."""
    print("\n" + "="*80)
    print("TEST: With Orchestrator (Quick Check)")
    print("="*80)

    from parrot.bots.flows.agents import OrchestratorAgent

    # Create specialist
    specialist = BasicAgent(
        name="Specialist",
        system_prompt="You are a helpful specialist.",
        use_llm='google'
    )
    await specialist.configure()

    # Create orchestrator
    orchestrator = OrchestratorAgent(
        name="Coordinator",
        use_llm='google',
        orchestration_prompt="Use 'specialist' tool to answer questions."
    )
    await orchestrator.configure()

    # Register
    specialist.register_as_tool(
        orchestrator,
        tool_name="specialist"
    )

    # Check the tool in LLM's tool manager
    llm_tools = orchestrator._llm.tool_manager.list_tools()
    print(f"\n📋 Tools in LLM: {llm_tools}")

    if 'specialist' not in llm_tools:
        print("❌ Tool not in LLM manager")
        return False

    # Get the tool and check schema
    tool = orchestrator._llm.tool_manager.get_tool('specialist')
    schema = tool.get_tool_schema()

    print(f"\n🔍 Tool schema in LLM:")
    print(json.dumps(schema, indent=2))

    # Verify parameters key exists
    if 'parameters' not in schema:
        print("\n❌ PROBLEM: No 'parameters' key in schema!")
        print("   Google GenAI won't know what arguments to pass")
        return False
    else:
        print("\n✅ Schema has 'parameters' key")
        params = schema['parameters']
        if 'question' in params.get('properties', {}):
            print("✅ Parameters include 'question'")
            print("   Google GenAI should now pass arguments correctly!")
            return True
        else:
            print("❌ Parameters missing 'question'")
            return False


async def main():
    """Run all schema structure tests."""
    print("\n" + "🧪 TESTING AGENTTOOL SCHEMA STRUCTURE ".center(80, "="))

    results = {}

    # Test 1: Schema structure
    try:
        results['structure'] = await test_schema_structure()
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        results['structure'] = False

    # Test 2: Google GenAI extraction simulation
    try:
        results['extraction'] = await test_google_genai_extraction()
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        results['extraction'] = False

    # Test 3: With orchestrator
    try:
        results['orchestrator'] = await test_with_orchestrator()
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        results['orchestrator'] = False

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
        print("🎉 ALL TESTS PASSED!")
        print("\nThe schema now has the correct structure:")
        print("  - Has 'name' key")
        print("  - Has 'description' key")
        print("  - Has 'parameters' key ← CRITICAL!")
        print("\nGoogle GenAI will now extract parameters correctly")
        print("and pass {'question': '...'} to the tool!")
    else:
        print("⚠️ SOME TESTS FAILED")
        print("\nIf 'parameters' key is missing, Google GenAI won't pass arguments!")
    print("="*80)


if __name__ == "__main__":
    asyncio.run(main())
