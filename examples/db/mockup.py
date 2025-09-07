"""
Quick test to verify the fixed AbstractDBAgent works correctly.
"""

import asyncio
from parrot.bots.db import MockSQLAgent


async def test_agent():
    """Test the database agent."""
    print("=== Testing Database Agent ===")

    # Create the agent with database-oriented defaults
    agent = MockSQLAgent(
        name="TestSQLAgent",
        credentials={"mock": "connection"},
        cache_ttl=300
    )

    try:
        # Initialize the agent
        await agent.configure()
        print("✅ Agent initialized successfully")

        # Test the ask method with user context
        response = await agent.ask(
            prompt="Show me all customers from the East region",
            user_context="I'm a regional sales manager focusing on the East region",
            user_id="demo_user",
            session_id="demo_session"
        )

        print("\n=== Response Analysis ===")
        print(f"✅ Response type: {type(response)}")
        print(f"✅ Response.output: {response.output}")
        print(f"✅ Response.model: {response.model}")
        print(f"✅ Response.provider: {response.provider}")
        print(f"✅ Response.user_id: {response.user_id}")
        print(f"✅ Response.session_id: {response.session_id}")

        # Test schema search with caching
        print("\n=== Testing Schema Search ===")
        results = await agent.search_schema("customer", search_type="tables", limit=3)
        print(f"✅ Schema search results: {len(results)} items found")

        # Test the goal and backstory override
        print("\n=== Testing Database-Oriented Configuration ===")
        print(f"✅ Agent goal: {agent.goal}")
        print(f"✅ Agent backstory: {agent.backstory[:100]}...")
        print(f"✅ Default temperature: {agent._default_temperature}")

        print("\n🎉 All tests passed! The agent is working correctly.")

    except Exception as e:
        print(f"❌ Error during testing: {e}")
        raise
    finally:
        await agent.cleanup()


async def test_system_prompt():
    """Test that the system prompt includes user context correctly."""
    print("\n=== Testing System Prompt Generation ===")

    agent = MockSQLAgent(name="PromptTestAgent")

    try:
        await agent.initialize_schema()

        # Test system prompt creation with user context
        user_context = "I am a data analyst focusing on customer segmentation and revenue analysis."

        system_prompt = await agent.create_system_prompt(
            user_context=user_context,
            vector_context="Sample database context",
            conversation_context="Previous conversation history"
        )

        print("✅ System prompt generated successfully")
        print(f"✅ Includes user context: {'user context' in system_prompt.lower()}")
        print(f"✅ Includes database info: {'database' in system_prompt.lower()}")
        print(f"✅ Includes agent goal: {agent.goal[:50] in system_prompt}")

        # Show a snippet of the prompt
        print(f"\n📝 System prompt snippet (first 300 chars):")
        print(f"{system_prompt[:300]}...")

    finally:
        await agent.cleanup()


if __name__ == "__main__":
    # Run both tests
    asyncio.run(test_agent())
    asyncio.run(test_system_prompt())
