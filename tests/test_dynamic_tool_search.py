
import unittest
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock, patch
from parrot.clients.base import ToolDefinition
from parrot.clients.gpt import OpenAIClient

# Define a hidden tool function
def hidden_tool_func(arg: str) -> str:
    return f"Hidden executed"

class TestDynamicToolSearch(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Setup client with mock API key
        self.client = OpenAIClient(api_key="sk-test", use_tools=True)
        # Manually register the tool as ToolDefinition
        self.hidden_tool_def = ToolDefinition(
            name="hidden_tool",
            description="A hidden tool for testing",
            input_schema={"type": "object", "properties": {"arg": {"type": "string"}}},
            function=hidden_tool_func
        )
        self.client.tool_manager.register_tool(self.hidden_tool_def)
        
        # Ensure search_tools is available
        tools = self.client.tool_manager.all_tools()
        self.search_tool = next((t for t in tools if t.name == "search_tools"), None)

    async def test_prepare_lazy_tools(self):
        """Verify _prepare_lazy_tools returns only search_tools"""
        lazy_tools = self.client._prepare_lazy_tools()
        self.assertEqual(len(lazy_tools), 1)
        self.assertEqual(lazy_tools[0]['function']['name'], 'search_tools')

    async def test_check_new_tools(self):
        """Verify _check_new_tools parses search_tools output correctly"""
        search_result = json.dumps([
            {"name": "hidden_tool", "description": "desc"}
        ])
        
        new_tools = self.client._check_new_tools("search_tools", search_result)
        self.assertEqual(new_tools, ["hidden_tool"])

    @patch('parrot.clients.gpt.OpenAIClient._execute_tool')
    async def test_ask_lazy_flow(self, mock_execute):
        """
        Verify the lazy loading flow in ask():
        1. Call ask(lazy_loading=True)
        2. LLM calls search_tools
        3. Client executes search_tools -> returns hidden_tool
        4. Client updates tools
        5. LLM calls hidden_tool
        """
        
        # Helper to create a mock message object with attribute access
        def create_mock_message(role, content=None, tool_calls=None):
            msg = MagicMock()
            msg.role = role
            msg.content = content
            msg.tool_calls = []
            if tool_calls:
                for tc in tool_calls:
                    tc_obj = MagicMock()
                    tc_obj.id = tc['id']
                    tc_obj.type = 'function'
                    tc_obj.function = MagicMock()
                    tc_obj.function.name = tc['function']['name']
                    tc_obj.function.arguments = tc['function']['arguments']
                    msg.tool_calls.append(tc_obj)
            return msg

        # Helper to create a mock response object
        def create_mock_response(message):
            choice = MagicMock()
            choice.message = message
            choice.finish_reason = "tool_calls" if message.tool_calls else "stop"
            choice.stop_reason = choice.finish_reason
            
            resp = MagicMock()
            resp.choices = [choice]
            # Mock usage
            usage = MagicMock()
            usage.completion_tokens = 10
            usage.prompt_tokens = 5
            usage.total_tokens = 15
            resp.usage = usage
            
            # Satisfy raw_response validation
            # We must use a side_effect or lambda to mimic dict() behavior
            resp.dict.return_value = {"id": "mock_id", "object": "chat.completion"}
            
            return resp

        # Response 1: Tool Call search_tools
        msg1 = create_mock_message("assistant", tool_calls=[{
            "id": "call_1",
            "function": {
                "name": "search_tools",
                "arguments": '{"query": "hidden"}'
            }
        }])
        resp1 = create_mock_response(msg1)

        # Response 2: Tool Call hidden_tool
        msg2 = create_mock_message("assistant", tool_calls=[{
            "id": "call_2",
            "function": {
                "name": "hidden_tool",
                "arguments": '{"arg": "test"}'
            }
        }])
        resp2 = create_mock_response(msg2)

        # Response 3: Final answer
        msg3 = create_mock_message("assistant", content="Done")
        resp3 = create_mock_response(msg3)

        # Set up the client mock
        self.client.client = MagicMock()
        # Mock the chat.completions.create method
        self.client.client.chat.completions.create = AsyncMock(side_effect=[resp1, resp2, resp3])

        # Mock query generator to prevent it from failing if called
        # self.client._chat_completion = AsyncMock(side_effect=[resp1, resp2, resp3])
        # IMPORTANT: The code uses self.client.chat.completions.create directly in the loop 
        # inside `ask` method (lines 837-846 depending on use_responses branch).
        # We need to ensure we mock the right path.
        # It seems `self.client.chat.completions.create` is the standard path.

        # Correct mock for _execute_tool to return string results
        async def execute_side_effect(name, args):
            if name == "search_tools":
                return json.dumps([{"name": "hidden_tool", "description": "desc"}])
            if name == "hidden_tool":
                return "Hidden executed"
            return "Unknown"
        self.client._execute_tool = execute_side_effect

        # Call ask
        result = await self.client.ask("Find hidden tool", lazy_loading=True)

        # Assertions
        # Check that we made 3 API calls
        self.assertEqual(self.client.client.chat.completions.create.call_count, 3)
        
        calls = self.client.client.chat.completions.create.call_args_list
        
        # Call 1: Only search_tools available
        kwargs1 = calls[0].kwargs
        tool_names_1 = [t['function']['name'] for t in kwargs1['tools']]
        self.assertIn('search_tools', tool_names_1)
        self.assertNotIn('hidden_tool', tool_names_1)
        
        # Call 2: Hidden tool should appear after discovery
        kwargs2 = calls[1].kwargs
        tool_names_2 = [t['function']['name'] for t in kwargs2['tools']]
        self.assertIn('hidden_tool', tool_names_2)
        
        print("✅ Lazy loading flow verified successfully")

if __name__ == '__main__':
    unittest.main()
