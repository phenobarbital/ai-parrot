from typing import List, Dict, Any, Optional
from datetime import datetime
import json
from redis.asyncio import Redis
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa
from .abstract import ConversationMemory, ConversationHistory, ConversationTurn
from ..conf import REDIS_HISTORY_URL


class RedisConversation(ConversationMemory):
    """Redis-based conversation memory with proper encoding handling."""

    def __init__(
        self,
        redis_url: str = None,
        key_prefix: str = "conversation",
        use_hash_storage: bool = True
    ):
        self.redis_url = redis_url or REDIS_HISTORY_URL
        self.key_prefix = key_prefix
        self.use_hash_storage = use_hash_storage
        self.redis = Redis.from_url(
            self.redis_url,
            decode_responses=True,
            encoding="utf-8",
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True
        )

    def _get_key(
        self,
        user_id: str,
        session_id: str,
        chatbot_id: Optional[str] = None
    ) -> str:
        """Generate Redis key for conversation history."""
        parts = [self.key_prefix]
        if chatbot_id:
            parts.append(str(chatbot_id))
        parts.extend([user_id, session_id])
        return ":".join(parts)

    def _get_user_sessions_key(
        self,
        user_id: str,
        chatbot_id: Optional[str] = None
    ) -> str:
        """Generate Redis key for user's session list."""
        parts = [f"{self.key_prefix}_sessions"]
        if chatbot_id:
            parts.append(str(chatbot_id))
        parts.append(user_id)
        return ":".join(parts)

    def _serialize_data(self, data: Any) -> str:
        """Serialize data to JSON string with proper encoding."""
        try:
            # Use standard json module with specific settings to avoid encoding issues
            return json.dumps(data, ensure_ascii=False, separators=(',', ':'), default=str)
        except Exception as e:
            print(f"Serialization error: {e}")
            # Fallback to your custom encoder
            return json_encoder(data)

    def _deserialize_data(self, data: str) -> Any:
        """Deserialize JSON string to Python object."""
        try:
            # Use standard json module first
            return json.loads(data)
        except Exception as e:
            print(f"Deserialization error with standard json: {e}")
            # Fallback to your custom decoder
            try:
                # Fallback to your custom decoder
                return json_decoder(data)
            except Exception as e2:
                print(f"Deserialization error with custom decoder: {e2}")
                print(f"Problematic data (first 200 chars): {data[:200]}")
                return None

    async def create_history(
        self,
        user_id: str,
        session_id: str,
        chatbot_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ConversationHistory:
        """Create a new conversation history."""
        history = ConversationHistory(
            session_id=session_id,
            user_id=user_id,
            chatbot_id=chatbot_id,
            metadata=metadata or {}
        )

        if self.use_hash_storage:
            # Method 1: Using Redis Hash (RECOMMENDED for objects)
            key = self._get_key(user_id, session_id, chatbot_id)
            history_dict = history.to_dict()

            # Store each field separately in a hash
            mapping = {
                'session_id': history_dict['session_id'],
                'user_id': history_dict['user_id'],
                'chatbot_id': chatbot_id,
                'turns': self._serialize_data(history_dict['turns']),
                'created_at': history_dict['created_at'],
                'updated_at': history_dict['updated_at'],
                'metadata': self._serialize_data(history_dict['metadata'])
            }
            if history_dict.get('chatbot_id') is not None:
                mapping['chatbot_id'] = history_dict['chatbot_id']
            await self.redis.hset(key, mapping=mapping)
        else:
            # Method 2: Using simple key-value storage
            key = self._get_key(user_id, session_id, chatbot_id)
            serialized_data = self._serialize_data(history.to_dict())
            await self.redis.set(key, serialized_data)

        # Add to user sessions set
        await self.redis.sadd(
            self._get_user_sessions_key(user_id, chatbot_id),
            session_id
        )
        return history

    async def get_history(
        self,
        user_id: str,
        session_id: str,
        chatbot_id: Optional[str] = None
    ) -> Optional[ConversationHistory]:
        """Get a conversation history."""
        key = self._get_key(user_id, session_id, chatbot_id)

        if self.use_hash_storage:
            # Method 1: Get from Redis Hash
            data = await self.redis.hgetall(key)
            if not data:
                return None

            try:
                # Reconstruct the history dict
                history_dict = {
                    'session_id': data['session_id'],
                    'user_id': data['user_id'],
                    'chatbot_id': data.get('chatbot_id', chatbot_id),
                    'turns': self._deserialize_data(data['turns']),
                    'created_at': data['created_at'],
                    'updated_at': data['updated_at'],
                    'metadata': self._deserialize_data(data['metadata'])
                }
                return ConversationHistory.from_dict(history_dict)
            except (KeyError, ValueError) as e:
                print(f"Error deserializing conversation history: {e}")
                return None
        else:
            # Method 2: Get from simple key-value
            data = await self.redis.get(key)
            if data:
                try:
                    history_dict = self._deserialize_data(data)
                    if history_dict is not None and chatbot_id and not history_dict.get('chatbot_id'):
                        history_dict['chatbot_id'] = chatbot_id
                    return ConversationHistory.from_dict(history_dict)
                except (ValueError, KeyError) as e:
                    print(f"Error deserializing conversation history: {e}")
                    return None
            return None

    async def update_history(self, history: ConversationHistory) -> None:
        """Update a conversation history."""
        key = self._get_key(history.user_id, history.session_id, history.chatbot_id)

        if self.use_hash_storage:
            # Method 1: Update Redis Hash
            history_dict = history.to_dict()
            mapping = {
                'session_id': history_dict['session_id'],
                'user_id': history_dict['user_id'],
                'turns': self._serialize_data(history_dict['turns']),
                'created_at': history_dict['created_at'],
                'updated_at': history_dict['updated_at'],
                'metadata': self._serialize_data(history_dict['metadata'])
            }
            if history_dict.get('chatbot_id') is not None:
                mapping['chatbot_id'] = history_dict['chatbot_id']
            await self.redis.hset(key, mapping=mapping)
        else:
            # Method 2: Update simple key-value
            serialized_data = self._serialize_data(history.to_dict())
            await self.redis.set(key, serialized_data)

    async def add_turn(
        self,
        user_id: str,
        session_id: str,
        turn: ConversationTurn,
        chatbot_id: Optional[str] = None
    ) -> None:
        """Add a turn to the conversation efficiently."""
        if self.use_hash_storage:
            # Optimized: Only update the turns field
            key = self._get_key(user_id, session_id, chatbot_id)

            # Get current turns
            current_turns_data = await self.redis.hget(key, 'turns')
            if current_turns_data:
                turns = self._deserialize_data(current_turns_data)
            else:
                turns = []

            # Add new turn
            turns.append(turn.to_dict())

            # Update only the turns and updated_at fields
            mapping = {
                'turns': self._serialize_data(turns),
                'updated_at': datetime.now().isoformat()
            }
            if chatbot_id is not None:
                mapping['chatbot_id'] = str(chatbot_id)
            await self.redis.hset(key, mapping=mapping)
        else:
            # Fallback to full history update
            history = await self.get_history(user_id, session_id, chatbot_id)
            if history:
                history.add_turn(turn)
                await self.update_history(history)

    async def clear_history(
        self,
        user_id: str,
        session_id: str,
        chatbot_id: Optional[str] = None
    ) -> None:
        """Clear a conversation history."""
        if self.use_hash_storage:
            # Optimized: Only clear turns
            key = self._get_key(user_id, session_id, chatbot_id)
            # Reset turns to empty list and update updated_at
            mapping = {
                'turns': self._serialize_data([]),
                'updated_at': datetime.now().isoformat()
            }
            if chatbot_id is not None:
                mapping['chatbot_id'] = str(chatbot_id)
            await self.redis.hset(key, mapping=mapping)
        else:
            history = await self.get_history(user_id, session_id, chatbot_id)
            if history:
                history.clear_turns()
                await self.update_history(history)

    async def list_sessions(
        self,
        user_id: str,
        chatbot_id: Optional[str] = None
    ) -> List[str]:
        """List all session IDs for a user."""
        sessions = await self.redis.smembers(
            self._get_user_sessions_key(user_id, chatbot_id)
        )
        # Since decode_responses=True, sessions should already be strings
        return list(sessions)

    async def delete_history(
        self,
        user_id: str,
        session_id: str,
        chatbot_id: Optional[str] = None
    ) -> bool:
        """Delete a conversation history entirely."""
        key = self._get_key(user_id, session_id, chatbot_id)
        result = await self.redis.delete(key)
        await self.redis.srem(
            self._get_user_sessions_key(user_id, chatbot_id),
            session_id
        )
        return result > 0

    async def close(self):
        """Close the Redis connection."""
        try:
            await self.redis.close()
        except Exception as e:
            self.logger.error(f"Error closing Redis connection: {e}")

    async def ping(self) -> bool:
        """Test Redis connection."""
        try:
            await self.redis.ping()
            return True
        except Exception as e:
            self.logger.error(f"Error pinging Redis: {e}")
            return False

    # Additional utility methods for debugging
    async def get_raw_data(
        self,
        user_id: str,
        session_id: str,
        chatbot_id: Optional[str] = None
    ) -> Optional[Dict]:
        """Get raw data from Redis for debugging."""
        key = self._get_key(user_id, session_id, chatbot_id)

        if self.use_hash_storage:
            return await self.redis.hgetall(key)
        data = await self.redis.get(key)
        return {"raw_data": data} if data else None

    async def debug_conversation(
        self,
        user_id: str,
        session_id: str,
        chatbot_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Debug method to inspect conversation data."""
        raw_data = await self.get_raw_data(user_id, session_id, chatbot_id)
        history = await self.get_history(user_id, session_id, chatbot_id)

        return {
            "raw_data": raw_data,
            "parsed_history": history.to_dict() if history else None,
            "turns_count": len(history.turns) if history else 0,
            "storage_method": "hash" if self.use_hash_storage else "string"
        }

    async def list_sessions_by_chatbot(
        self,
        chatbot_id: str,
        user_id: Optional[str] = None
    ) -> List[str]:
        """List all sessions for a specific chatbot.

        Args:
            chatbot_id: The chatbot identifier
            user_id: Optional user filter

        Returns:
            List of session IDs
        """
        if user_id:
            # Get sessions for specific user and chatbot
            return await self.list_sessions(user_id, chatbot_id)

        # Get all sessions for this chatbot across all users
        pattern = f"{self.key_prefix}:{chatbot_id}:*"
        sessions = []
        cursor = 0

        while True:
            cursor, keys = await self.redis.scan(
                cursor,
                match=pattern,
                count=100
            )
            for key in keys:
                # Extract session_id from key
                # Format: conversation:chatbot_id:user_id:session_id
                parts = key.split(':')
                if len(parts) >= 4:
                    sessions.append(parts[3])

            if cursor == 0:
                break

        return sessions


    async def get_chatbot_stats(self, chatbot_id: str) -> Dict[str, Any]:
        """Get statistics for a specific chatbot.

        Returns:
            Dictionary with conversation counts, active users, etc.
        """
        pattern = f"{self.key_prefix}:{chatbot_id}:*"
        total_conversations = 0
        total_turns = 0
        unique_users = set()
        cursor = 0

        while True:
            cursor, keys = await self.redis.scan(
                cursor,
                match=pattern,
                count=100
            )
            total_conversations += len(keys)

            for key in keys:
                # Extract user_id
                parts = key.split(':')
                if len(parts) >= 3:
                    unique_users.add(parts[2])

                # Count turns
                if self.use_hash_storage:
                    turns_data = await self.redis.hget(key, 'turns')
                    if turns_data:
                        turns = self._deserialize_data(turns_data)
                        total_turns += len(turns)

            if cursor == 0:
                break

        return {
            'chatbot_id': chatbot_id,
            'total_conversations': total_conversations,
            'total_turns': total_turns,
            'unique_users': len(unique_users),
            'avg_turns_per_conversation': total_turns / total_conversations if total_conversations > 0 else 0
        }


    async def delete_all_chatbot_conversations(
        self,
        chatbot_id: str,
        user_id: Optional[str] = None
    ) -> int:
        """Delete all conversations for a chatbot.

        Args:
            chatbot_id: The chatbot identifier
            user_id: Optional user filter

        Returns:
            Number of conversations deleted
        """
        if user_id:
            pattern = f"{self.key_prefix}:{chatbot_id}:{user_id}:*"
        else:
            pattern = f"{self.key_prefix}:{chatbot_id}:*"

        deleted_count = 0
        cursor = 0

        while True:
            cursor, keys = await self.redis.scan(
                cursor,
                match=pattern,
                count=100
            )

            if keys:
                deleted_count += await self.redis.delete(*keys)

            if cursor == 0:
                break

        # Also clean up session sets
        if user_id:
            await self.redis.delete(self._get_user_sessions_key(user_id, chatbot_id))
        else:
            # Clean all user session sets for this chatbot
            session_pattern = f"{self.key_prefix}_sessions:{chatbot_id}:*"
            cursor = 0
            while True:
                cursor, session_keys = await self.redis.scan(
                    cursor,
                    match=session_pattern,
                    count=100
                )
                if session_keys:
                    await self.redis.delete(*session_keys)
                if cursor == 0:
                    break

        return deleted_count

    async def _update_chatbot_index(
        self,
        chatbot_id: str,
        user_id: str,
        session_id: str,
        operation: str = 'add'
    ) -> None:
        """Maintain reverse index for fast chatbot queries.

        Args:
            chatbot_id: The chatbot identifier
            user_id: The user identifier
            session_id: The session identifier
            operation: 'add' or 'remove'
        """
        # Index: all users who interacted with this chatbot
        users_key = f"{self.key_prefix}_index:chatbot_users:{chatbot_id}"

        if operation == 'add':
            await self.redis.sadd(users_key, user_id)
            # Set expiry if needed
            # await self.redis.expire(users_key, 86400 * 30)  # 30 days
        elif operation == 'remove':
            # Check if user has any other sessions with this chatbot
            sessions = await self.list_sessions(user_id, chatbot_id)
            if not sessions:
                await self.redis.srem(users_key, user_id)


    async def get_chatbot_users(self, chatbot_id: str) -> List[str]:
        """Get all users who have interacted with a chatbot."""
        users_key = f"{self.key_prefix}_index:chatbot_users:{chatbot_id}"
        users = await self.redis.smembers(users_key)
        return list(users)

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
