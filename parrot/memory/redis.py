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
        metadata: Optional[Dict[str, Any]] = None,
        chatbot_id: Optional[str] = None
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
        else:
            data = await self.redis.get(key)
            if data:
                return {"raw_data": data}
            return None

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


# Example usage and testing
async def test_redis_conversation():
    """Test Redis conversation memory."""

    # Test with hash storage (recommended)
    redis_memory = RedisConversation(use_hash_storage=True)

    # Test connection
    if not await redis_memory.ping():
        print("Redis connection failed!")
        return

    user_id = "test_user"
    session_id = "test_session"
    chatbot_id = "test_chatbot"

    try:
        # Create history
        history = await redis_memory.create_history(
            user_id,
            session_id,
            chatbot_id=chatbot_id
        )
        print(f"Created history: {history.session_id}")

        # Add a turn
        turn = ConversationTurn(
            turn_id="turn1",
            user_id=user_id,
            user_message="Hello, I'm testing Redis storage",
            assistant_response="Hello! Redis storage is working correctly."
        )

        await redis_memory.add_turn(user_id, session_id, turn, chatbot_id=chatbot_id)
        print("Added turn successfully")

        # Retrieve and verify
        retrieved_history = await redis_memory.get_history(
            user_id,
            session_id,
            chatbot_id=chatbot_id
        )
        if retrieved_history:
            print(f"Retrieved history with {len(retrieved_history.turns)} turns")
            print(f"First turn response: {retrieved_history.turns[0].assistant_response}")

        # Debug the conversation
        debug_info = await redis_memory.debug_conversation(
            user_id,
            session_id,
            chatbot_id=chatbot_id
        )
        print(f"Debug info: {debug_info}")

        # Clean up
        await redis_memory.delete_history(user_id, session_id, chatbot_id=chatbot_id)
        print("Cleaned up test data")

    finally:
        await redis_memory.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_redis_conversation())
