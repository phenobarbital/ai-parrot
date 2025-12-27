
import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass, field
from typing import List, Any

from parrot.clients.google import GoogleGenAIClient
# We don't need real imports if we mock correctly, but let's keep it safe
# from google.genai.types import FinishReason

# Helper classes to simulate GenAI objects without MagicMock overhead for serialization
@dataclass
class MockFinishReason:
    name: str
    
    def __str__(self):
        return self.name

@dataclass
class MockPart:
    text: str = ""
    function_call: Any = None
    
    def __post_init__(self):
        # Determine strict structure for Google Client checks
        pass

@dataclass
class MockContent:
    parts: List[MockPart] = field(default_factory=list)

@dataclass
class MockCandidate:
    finish_reason: MockFinishReason
    content: MockContent = None

class MockResponse:
    def __init__(self, candidates=None, text=""):
        self.candidates = candidates or []
        self.text = text
        self.usage_metadata = None # satisfy usage check

class TestRetryLogic(unittest.IsolatedAsyncioTestCase):
    async def test_retry_malformed_function_call(self):
        # Setup mock client
        client = GoogleGenAIClient(api_key="fake_key")
        client.client = MagicMock()
        client.client.aio.chats.create = MagicMock()
        
        # Mock chat session
        mock_chat = AsyncMock()
        client.client.aio.chats.create.return_value = mock_chat
        
        # Mock responses: 
        # 1. Malformed Function Call
        malformed_candidate = MockCandidate(
            finish_reason=MockFinishReason(name="MALFORMED_FUNCTION_CALL")
        )
        
        # 2. Success
        success_candidate = MockCandidate(
            finish_reason=MockFinishReason(name="STOP"),
            content=MockContent(parts=[MockPart(text="Success!")])
        )
        
        response1 = MockResponse(candidates=[malformed_candidate])
        response2 = MockResponse(candidates=[success_candidate], text="Success!")
        
        # Configure side_effect for send_message
        mock_chat.send_message.side_effect = [response1, response2]
        
        # Execute
        print("\n--- Testing Retry Logic ---")
        response = await client.ask("test prompt", retry_on_fail=True, max_retries=2)
        
        # Verify
        print(f"Response text: {response.content}")
        self.assertIn("Success!", response.content)
        self.assertEqual(mock_chat.send_message.call_count, 2)
        print("✅ Retry logic worked as expected (called twice).")

    async def test_no_retry_if_disabled(self):
        # Setup mock client
        client = GoogleGenAIClient(api_key="fake_key")
        client.client = MagicMock()
        client.client.aio.chats.create = MagicMock()
        
        # Mock chat session
        mock_chat = AsyncMock()
        client.client.aio.chats.create.return_value = mock_chat
        
        # Mock responses: 
        # 1. Malformed Function Call
        malformed_candidate = MockCandidate(
            finish_reason=MockFinishReason(name="MALFORMED_FUNCTION_CALL")
        )
        
        response1 = MockResponse(candidates=[malformed_candidate])
        
        # Configure side_effect
        mock_chat.send_message.side_effect = [response1]
        
        # Execute
        print("\n--- Testing Retry Disabled ---")
        try:
             response = await client.ask("test prompt", retry_on_fail=False)
        except Exception:
             pass 
        
        # Verify
        self.assertEqual(mock_chat.send_message.call_count, 1)
        print("✅ Retry disabled logic worked (called once).")

if __name__ == '__main__':
    unittest.main()
