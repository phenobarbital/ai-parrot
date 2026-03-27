
import asyncio
import logging
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os

# Add project root to sys.path
sys.path.append(os.getcwd())

from parrot.tools.manager import ToolManager
from parrot.a2a.models import RegisteredAgent, AgentCard

# Mock response data
MOCK_AGENT_JSON = {
    "protocolVersion": "0.3",
    "name": "WeatherAgent",
    "description": "Provides weather info",
    "version": "1.0.0",
    "url": "http://weather-agent.com",
    "capabilities": {
        "streaming": True,
        "pushNotifications": False,
        "stateTransitionHistory": False
    },
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
    "skills": [
        {
            "id": "skill-weather-1",
            "name": "get_current_weather",
            "description": "Get weather for city",
            "tags": ["weather", "forecast"],
            "inputSchema": {},
            "examples": []
        }
    ],
    "iconUrl": None,
    "tags": ["weather", "public"]
}

async def verify_a2a_registration():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("Verifier")
    
    manager = ToolManager()
    
    # Mock aiohttp.ClientSession
    with patch('aiohttp.ClientSession') as MockSession:
        # The session instance (returned by ClientSession())
        session_instance = AsyncMock()
        # The response instance (returned by get context manager)
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = MOCK_AGENT_JSON
        
        # When entering ClientSession context
        MockSession.return_value.__aenter__.return_value = session_instance
        
        # When calling session.get(), it returns a context manager
        # We need session_instance.get to be a Mock that returns an AsyncContextManager
        get_context = AsyncMock()
        get_context.__aenter__.return_value = mock_response
        
        # IMPORTANT: session.get() is usually not awaited directly, the result is used in async with
        # By default AsyncMock is a coroutine function. We need it to be a regular function returning the context.
        # However, aiohttp ClientSession methods ARE async... wait.
        # No, session.get() returns _RequestContextManager which is an async context manager.
        # It is NOT a coroutine function. It is a regular function returning an async context manager.
        
        session_instance.get = MagicMock()
        session_instance.get.return_value = get_context
        
        logger.info("Testing register_a2a_agent...")
        url = "http://weather-agent.com"
        agent = await manager.register_a2a_agent(url)

        
        # Verify registration
        assert isinstance(agent, RegisteredAgent)
        assert agent.card.name == "WeatherAgent"
        assert agent.url == url
        assert len(agent.card.skills) == 1
        assert agent.card.skills[0].name == "get_current_weather"
        logger.info("✅ Registration successful")
        
        # Verify retrieval methods
        logger.info("Testing retrieval methods...")
        
        # get_a2a_agents
        agents = manager.get_a2a_agents()
        assert len(agents) == 1
        assert agents[0] == agent
        logger.info("✅ get_a2a_agents passed")
        
        # list_a2a_agents
        names = manager.list_a2a_agents()
        assert "WeatherAgent" in names
        logger.info("✅ list_a2a_agents passed")
        
        # get_by_skill
        by_skill = manager.get_by_skill("weather")
        assert len(by_skill) == 1
        by_skill_name = manager.get_by_skill("get_current_weather")
        assert len(by_skill_name) == 1
        by_skill_fail = manager.get_by_skill("stocks")
        assert len(by_skill_fail) == 0
        logger.info("✅ get_by_skill passed")
        
        # get_by_tag
        by_tag = manager.get_by_tag("public")
        assert len(by_tag) == 1
        by_tag_fail = manager.get_by_tag("private")
        assert len(by_tag_fail) == 0
        logger.info("✅ get_by_tag passed")
        
        # search_a2a_agents
        search = manager.search_a2a_agents("forecast")
        assert len(search) == 1
        search_desc = manager.search_a2a_agents("Provides weather")
        assert len(search_desc) == 1
        search_fail = manager.search_a2a_agents("finance")
        assert len(search_fail) == 0
        logger.info("✅ search_a2a_agents passed")

if __name__ == "__main__":
    asyncio.run(verify_a2a_registration())
