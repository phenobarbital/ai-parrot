"""
Comprehensive tests for RedisKnowledgeBase implementations.
"""
import asyncio
from typing import List, Dict, Any
from parrot.stores.kb.redis import RedisKnowledgeBase
from parrot.stores.kb.user import UserPreferences
from parrot.stores.kb.doc import UserContext, DocumentMetadata, ChatbotSettings


async def test_user_preferences():
    """Test UserPreferences knowledge base."""
    print("\n" + "="*60)
    print("TEST: User Preferences")
    print("="*60)

    prefs = UserPreferences()

    # Test connection
    if not await prefs.ping():
        print("❌ Redis connection failed!")
        return
    print("✓ Redis connection successful")

    user_id = "user_123"

    try:
        # Test 1: Set individual preferences
        print("\n--- Test 1: Set Preferences ---")
        await prefs.set_preference(user_id, "theme", "dark")
        await prefs.set_preference(user_id, "language", "python")
        await prefs.set_preference(user_id, "notifications", True)
        await prefs.set_preference(user_id, "favorite_topics", ["AI", "ML", "Data Science"])
        print("✓ Preferences set successfully")

        # Test 2: Get individual preference
        print("\n--- Test 2: Get Individual Preference ---")
        theme = await prefs.get_preference(user_id, "theme")
        print(f"Theme: {theme}")
        assert theme == "dark", "Theme mismatch"
        print("✓ Individual preference retrieved")

        # Test 3: Get all preferences
        print("\n--- Test 3: Get All Preferences ---")
        all_prefs = await prefs.get_all_preferences(user_id)
        print(f"All preferences: {all_prefs}")
        assert len(all_prefs) == 4, "Preference count mismatch"
        print("✓ All preferences retrieved")

        # Test 4: Search preferences
        print("\n--- Test 4: Search Preferences ---")
        results = await prefs.search("python", user_id=user_id)
        print(f"Search results for 'python': {len(results)} found")
        for result in results:
            print(f"  - {result['content']}")
        assert len(results) > 0, "No results found"
        print("✓ Search successful")

        # Test 5: Update preference
        print("\n--- Test 5: Update Preference ---")
        await prefs.set_preference(user_id, "theme", "light")
        updated_theme = await prefs.get_preference(user_id, "theme")
        print(f"Updated theme: {updated_theme}")
        assert updated_theme == "light", "Theme update failed"
        print("✓ Preference updated")

        # Test 6: Delete preference
        print("\n--- Test 6: Delete Preference ---")
        deleted = await prefs.delete_preference(user_id, "notifications")
        assert deleted, "Delete failed"
        remaining_prefs = await prefs.get_all_preferences(user_id)
        assert "notifications" not in remaining_prefs, "Preference not deleted"
        print("✓ Preference deleted")

        # Test 7: Bulk operations
        print("\n--- Test 7: Bulk Operations ---")
        user_2 = "user_456"
        user_3 = "user_789"

        await prefs.set_preference(user_2, "theme", "blue")
        await prefs.set_preference(user_3, "theme", "green")

        bulk_data = await prefs.bulk_get([user_id, user_2, user_3])
        print(f"Bulk retrieved: {len(bulk_data)} users")
        assert len(bulk_data) == 3, "Bulk get failed"
        print("✓ Bulk operations successful")

    finally:
        # Cleanup
        await prefs.delete(user_id)
        await prefs.delete("user_456")
        await prefs.delete("user_789")
        await prefs.close()
        print("\n✓ Cleanup completed")


async def test_user_context():
    """Test UserContext knowledge base."""
    print("\n" + "="*60)
    print("TEST: User Context")
    print("="*60)

    context = UserContext()

    if not await context.ping():
        print("❌ Redis connection failed!")
        return
    print("✓ Redis connection successful")

    user_id = "user_context_test"

    try:
        # Test: Update context
        print("\n--- Test: Update Context ---")
        context_data = {
            "last_topic": "machine learning",
            "last_query": "explain neural networks",
            "session_start": "2025-10-12T00:00:00",
            "interests": ["AI", "Python", "Data Science"]
        }
        await context.update_context(user_id, context_data)
        print("✓ Context updated")

        # Test: Retrieve context
        print("\n--- Test: Retrieve Context ---")
        retrieved = await context.get(user_id)
        print(f"Retrieved context: {retrieved}")
        assert retrieved["last_topic"] == "machine learning"
        print("✓ Context retrieved successfully")

        # Test: Search context
        print("\n--- Test: Search Context ---")
        results = await context.search("neural", user_id=user_id)
        print(f"Search results: {len(results)} found")
        for result in results:
            print(f"  - {result['content']}")
        print("✓ Context search successful")

        # Test: TTL check
        print("\n--- Test: TTL Check ---")
        ttl = await context.get_ttl(user_id)
        print(f"Context TTL: {ttl} seconds (~{ttl/86400:.1f} days)")
        assert ttl > 0, "TTL not set"
        print("✓ TTL verified")

    finally:
        await context.delete(user_id)
        await context.close()
        print("\n✓ Cleanup completed")


async def test_chatbot_settings():
    """Test ChatbotSettings knowledge base."""
    print("\n" + "="*60)
    print("TEST: Chatbot Settings")
    print("="*60)

    settings = ChatbotSettings()

    if not await settings.ping():
        print("❌ Redis connection failed!")
        return
    print("✓ Redis connection successful")

    bot_id = "bot_test_123"

    try:
        # Test: Set multiple settings
        print("\n--- Test: Set Settings ---")
        await settings.set_setting(bot_id, "temperature", 0.7)
        await settings.set_setting(bot_id, "max_tokens", 2048)
        await settings.set_setting(bot_id, "system_prompt", "You are a helpful assistant")
        await settings.set_setting(bot_id, "tools_enabled", True)
        print("✓ Settings configured")

        # Test: Get individual setting
        print("\n--- Test: Get Individual Setting ---")
        temp = await settings.get_setting(bot_id, "temperature")
        print(f"Temperature: {temp}")
        assert temp == 0.7, "Setting retrieval failed"
        print("✓ Individual setting retrieved")

        # Test: Get all settings
        print("\n--- Test: Get All Settings ---")
        all_settings = await settings.get(bot_id)
        print(f"All settings: {all_settings}")
        assert len(all_settings) == 4, "Settings count mismatch"
        print("✓ All settings retrieved")

        # Test: List all bots
        print("\n--- Test: List All Bots ---")
        # Create another bot
        await settings.set_setting("bot_456", "temperature", 0.5)

        all_bots = await settings.list_all()
        print(f"Total bots configured: {len(all_bots)}")
        for bot in all_bots:
            print(f"  - {bot['identifier']}: {len(bot['data'])} settings")
        print("✓ Bot listing successful")

    finally:
        await settings.delete(bot_id)
        await settings.delete("bot_456")
        await settings.close()
        print("\n✓ Cleanup completed")


async def test_document_metadata():
    """Test DocumentMetadata knowledge base."""
    print("\n" + "="*60)
    print("TEST: Document Metadata")
    print("="*60)

    docs = DocumentMetadata()

    if not await docs.ping():
        print("❌ Redis connection failed!")
        return
    print("✓ Redis connection successful")

    doc_id = "doc_123"
    user_id = "user_doc_test"

    try:
        # Test: Add document
        print("\n--- Test: Add Document ---")
        await docs.add_document(
            doc_id=doc_id,
            user_id=user_id,
            title="Machine Learning Guide",
            filename="ml_guide.pdf",
            description="Comprehensive guide to ML algorithms",
            tags=["machine-learning", "AI", "tutorial"],
            file_size=1024000,
            mime_type="application/pdf"
        )
        print("✓ Document metadata added")

        # Test: Retrieve document
        print("\n--- Test: Retrieve Document ---")
        doc_data = await docs.get(doc_id)
        print(f"Document: {doc_data['title']}")
        print(f"Tags: {doc_data['tags']}")
        assert doc_data['title'] == "Machine Learning Guide"
        print("✓ Document retrieved")

        # Test: Search documents
        print("\n--- Test: Search Documents ---")
        results = await docs.search("machine learning", user_id=user_id)
        print(f"Search results: {len(results)} found")
        for result in results:
            print(f"  - {result['content']}")
        assert len(results) > 0, "Search failed"
        print("✓ Document search successful")

        # Test: Add multiple documents
        print("\n--- Test: Multiple Documents ---")
        await docs.add_document(
            doc_id="doc_456",
            user_id=user_id,
            title="Python Best Practices",
            filename="python_guide.pdf",
            description="Clean code principles in Python",
            tags=["python", "coding", "best-practices"]
        )

        # Count documents for user
        pattern = "doc_meta:*"
        count = await docs.count(pattern)
        print(f"Total documents: {count}")
        assert count >= 2, "Document count mismatch"
        print("✓ Multiple documents managed")

    finally:
        await docs.delete(doc_id)
        await docs.delete("doc_456")
        await docs.close()
        print("\n✓ Cleanup completed")


async def test_advanced_operations():
    """Test advanced operations across KB types."""
    print("\n" + "="*60)
    print("TEST: Advanced Operations")
    print("="*60)

    prefs = UserPreferences()

    if not await prefs.ping():
        print("❌ Redis connection failed!")
        return

    try:
        # Test: Bulk insert
        print("\n--- Test: Bulk Insert ---")
        users_data = [
            {"id": "bulk_1", "theme": "dark", "lang": "python"},
            {"id": "bulk_2", "theme": "light", "lang": "javascript"},
            {"id": "bulk_3", "theme": "auto", "lang": "rust"},
        ]

        count = await prefs.bulk_insert(users_data, identifier_key='id')
        print(f"Bulk inserted: {count} users")
        assert count == 3, "Bulk insert failed"
        print("✓ Bulk insert successful")

        # Test: List all
        print("\n--- Test: List All ---")
        all_entries = await prefs.list_all(limit=10)
        print(f"Total entries: {len(all_entries)}")
        for entry in all_entries[:3]:
            print(f"  - {entry['identifier']}: {entry['data']}")
        print("✓ List all successful")

        # Test: Pattern matching
        print("\n--- Test: Pattern Count ---")
        count = await prefs.count(pattern="user_prefs:bulk_*")
        print(f"Entries matching 'bulk_*': {count}")
        assert count == 3, "Pattern count failed"
        print("✓ Pattern matching works")

        # Test: Bulk delete
        print("\n--- Test: Bulk Delete ---")
        deleted = await prefs.bulk_delete(["bulk_1", "bulk_2", "bulk_3"])
        print(f"Bulk deleted: {deleted} entries")
        assert deleted == 3, "Bulk delete failed"
        print("✓ Bulk delete successful")

        # Test: Clear all with pattern
        print("\n--- Test: Clear Pattern ---")
        # Add some test data
        await prefs.set_preference("clear_1", "test", "value")
        await prefs.set_preference("clear_2", "test", "value")

        cleared = await prefs.clear_all(pattern="user_prefs:clear_*")
        print(f"Cleared: {cleared} entries")
        print("✓ Pattern clear successful")

    finally:
        await prefs.close()
        print("\n✓ Cleanup completed")


async def run_all_tests():
    """Run all tests."""
    print("\n" + "#"*60)
    print("# REDIS KNOWLEDGE BASE - COMPREHENSIVE TEST SUITE")
    print("#"*60)

    tests = [
        test_user_preferences,
        test_user_context,
        test_chatbot_settings,
        test_document_metadata,
        test_advanced_operations,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            print(f"\n❌ TEST FAILED: {test.__name__}")
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "#"*60)
    print(f"# TEST SUMMARY: {passed} passed, {failed} failed")
    print("#"*60)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
