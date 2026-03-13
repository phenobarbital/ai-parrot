import pytest
import uuid
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.core.exceptions import HumanInteractionInterrupt
from parrot.integrations.core.state import IntegrationStateManager

pytestmark = pytest.mark.asyncio

@pytest.fixture
def mock_store():
    store = AsyncMock()
    # Basic dictionary backing for store
    data = {}
    async def mock_get(key):
        return data.get(key)
    async def mock_set(key, value, timeout=None, expire=None):
        data[key] = value
        
    async def mock_delete(key):
        if key in data:
            del data[key]
            
    store.get.side_effect = mock_get
    store.set.side_effect = mock_set
    store.delete.side_effect = mock_delete
    return store


async def test_set_and_get_suspended_state(mock_store):
    manager = IntegrationStateManager(store=mock_store)
    
    integration_id = "telegram"
    chat_id = "12345"
    user_id = "user_1"
    session_id = str(uuid.uuid4())
    
    # Set state
    await manager.set_suspended_state(
        integration_id=integration_id,
        chat_id=chat_id,
        user_id=user_id,
        session_id=session_id,
        agent_name="TestAgent"
    )
    
    # Get state
    state = await manager.get_suspended_session(integration_id, chat_id, user_id)
    assert state is not None
    assert state["session_id"] == session_id
    assert state["agent_name"] == "TestAgent"
    

async def test_clear_suspended_state(mock_store):
    manager = IntegrationStateManager(store=mock_store)
    
    integration_id = "telegram"
    chat_id = "12345"
    user_id = "user_1"
    session_id = str(uuid.uuid4())
    
    # Set state
    await manager.set_suspended_state(integration_id, chat_id, user_id, session_id, "TestAgent")
    
    # Clear state
    await manager.clear_suspended_state(integration_id, chat_id, user_id)
    
    # Get state should be None
    state = await manager.get_suspended_session(integration_id, chat_id, user_id)
    assert state is None

