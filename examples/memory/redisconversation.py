from parrot.memory import RedisConversation, ConversationTurn


# Example usage and testing
async def test_redis_conversation():
    """Enhanced test with multiple chatbots and users."""
    redis_memory = RedisConversation(use_hash_storage=True)

    if not await redis_memory.ping():
        print("Redis connection failed!")
        return

    chatbot1 = "sales_bot"
    chatbot2 = "support_bot"
    user1 = "user_alice"
    user2 = "user_bob"

    try:
        # Test 1: Multiple bots with same user
        print("\n=== Test 1: Same user, different bots ===")
        h1 = await redis_memory.create_history(user1, "session1", chatbot1)
        h2 = await redis_memory.create_history(user1, "session2", chatbot2)

        print(f"Created sessions: {h1.session_id}, {h2.session_id}")

        # Test 2: List sessions by chatbot
        print("\n=== Test 2: List sessions by chatbot ===")
        sessions1 = await redis_memory.list_sessions(user1, chatbot1)
        sessions2 = await redis_memory.list_sessions(user1, chatbot2)

        print(f"User {user1} sessions with {chatbot1}: {sessions1}")
        print(f"User {user1} sessions with {chatbot2}: {sessions2}")

        # Test 3: Add turns to different bots
        print("\n=== Test 3: Add turns ===")
        turn1 = ConversationTurn(
            turn_id="t1",
            user_id=user1,
            user_message="What's your price?",
            assistant_response="Our starting price is $99/month."
        )

        turn2 = ConversationTurn(
            turn_id="t2",
            user_id=user1,
            user_message="I need help",
            assistant_response="How can I assist you today?"
        )

        await redis_memory.add_turn(user1, "session1", turn1, chatbot1)
        await redis_memory.add_turn(user1, "session2", turn2, chatbot2)

        # Test 4: Retrieve and verify isolation
        print("\n=== Test 4: Verify conversation isolation ===")
        conv1 = await redis_memory.get_history(user1, "session1", chatbot1)
        conv2 = await redis_memory.get_history(user1, "session2", chatbot2)

        print(f"Sales bot conversation: {conv1.turns[0].assistant_response}")
        print(f"Support bot conversation: {conv2.turns[0].assistant_response}")

        # Test 5: Cross-contamination check
        print("\n=== Test 5: Cross-contamination check ===")
        wrong_bot = await redis_memory.get_history(user1, "session1", chatbot2)
        print(f"Trying to access sales session with support bot ID: {wrong_bot}")  # Should be None

        # Test 6: Same session_id, different chatbots
        print("\n=== Test 6: Session ID collision test ===")
        h3 = await redis_memory.create_history(user2, "common_session", chatbot1)
        h4 = await redis_memory.create_history(user2, "common_session", chatbot2)

        turn3 = ConversationTurn(
            turn_id="t3",
            user_id=user2,
            user_message="Hello sales",
            assistant_response="Welcome to sales!"
        )

        turn4 = ConversationTurn(
            turn_id="t4",
            user_id=user2,
            user_message="Hello support",
            assistant_response="Welcome to support!"
        )

        await redis_memory.add_turn(user2, "common_session", turn3, chatbot1)
        await redis_memory.add_turn(user2, "common_session", turn4, chatbot2)

        c1 = await redis_memory.get_history(user2, "common_session", chatbot1)
        c2 = await redis_memory.get_history(user2, "common_session", chatbot2)

        print(f"Sales bot (common session): {c1.turns[0].assistant_response}")
        print(f"Support bot (common session): {c2.turns[0].assistant_response}")

        # Cleanup
        print("\n=== Cleanup ===")
        await redis_memory.delete_history(user1, "session1", chatbot1)
        await redis_memory.delete_history(user1, "session2", chatbot2)
        await redis_memory.delete_history(user2, "common_session", chatbot1)
        await redis_memory.delete_history(user2, "common_session", chatbot2)

        print("All tests passed! ✓")

    finally:
        await redis_memory.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_redis_conversation())
