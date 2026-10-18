"""Real (un-mocked) BasicAgent integration test.

Kept out of ``test_basic_agent_new.py`` on purpose: that module's module-scoped
``mock_agent_deps_module`` fixture replaces ``parrot.clients.google`` in
``sys.modules`` until the module finishes, so a "real" test placed there silently
receives the mocked ``GoogleGenAIClient``.
"""
import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_real_integration():
    """
    Test REAL BasicAgent against Google/OpenAI/Groq if keys exist.
    Skipped if no API key found.
    """
    import os

    # We strictly respect the rule: NO MOCKS in integration tests.
    if not os.getenv("GOOGLE_API_KEY"):
        pytest.skip("GOOGLE_API_KEY not found")

    from parrot.bots.agent import BasicAgent

    # We use a real agent
    agent = BasicAgent(name="RealTestAgent", use_llm="google", model="gemini-3.1-flash-lite-preview")

    response = await agent.conversation("Hello, who are you?")
    assert response is not None
    assert len(response.output) > 0
    print(f"Integration Response: {response.output}")
