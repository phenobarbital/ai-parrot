import unittest
import asyncio
from parrot.integrations.telegram.callbacks import (
    CallbackData,
    CallbackRegistry,
    telegram_callback,
    CallbackContext,
    build_inline_keyboard,
)

class TestCallbackData(unittest.TestCase):
    def test_encode_decode(self):
        prefix = "test"
        payload = {"id": 123, "action": "delete"}
        
        encoded = CallbackData.encode(prefix, payload)
        # Check limit (64 bytes)
        self.assertLessEqual(len(encoded.encode('utf-8')), 64)
        print(f"Encoded length: {len(encoded.encode('utf-8'))} bytes")
        
        decoded_prefix, decoded_payload = CallbackData.decode(encoded)
        self.assertEqual(decoded_prefix, prefix)
        self.assertEqual(decoded_payload, payload)

    def test_encode_too_long(self):
        prefix = "long"
        payload = {"data": "x" * 60} # Will exceed 64 bytes
        
        with self.assertRaises(ValueError):
            CallbackData.encode(prefix, payload)

class TestCallbackRegistry(unittest.TestCase):
    def test_discovery(self):
        class MyAgent:
            @telegram_callback("foo")
            async def handle_foo(self, ctx):
                pass
            
            @telegram_callback("bar")
            async def handle_bar(self, ctx):
                pass
                
            async def ignored(self):
                pass
                
        agent = MyAgent()
        registry = CallbackRegistry()
        count = registry.discover_from_agent(agent)
        
        self.assertEqual(count, 2)
        self.assertIn("foo", registry.prefixes)
        self.assertIn("bar", registry.prefixes)
        
        # Test matching
        match = registry.match("foo:{}")
        self.assertIsNotNone(match)
        self.assertEqual(match[0].prefix, "foo")
        
        match = registry.match("baz:{}")
        self.assertIsNone(match)

class TestKeyboardBuilder(unittest.TestCase):
    def test_build(self):
        buttons = [
            [{"text": "Btn1", "prefix": "p1", "payload": {"id": 1}}],
            [
                {"text": "Btn2", "prefix": "p2", "payload": {}},
                {"text": "Btn3", "url": "http://google.com"}
            ]
        ]
        
        kb = build_inline_keyboard(buttons)
        self.assertIn("inline_keyboard", kb)
        rows = kb["inline_keyboard"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[0]), 1)
        self.assertEqual(len(rows[1]), 2)
        
        # Check encoded data
        btn1 = rows[0][0]
        self.assertEqual(btn1["text"], "Btn1")
        self.assertTrue(btn1["callback_data"].startswith("p1:"))
        
        btn3 = rows[1][1]
        self.assertEqual(btn3["url"], "http://google.com")
        self.assertNotIn("callback_data", btn3)

if __name__ == "__main__":
    unittest.main()
