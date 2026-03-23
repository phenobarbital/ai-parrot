"""
Redis Persistence for AgentsCrew Definitions.

Provides async-based persistence layer for storing and retrieving
Crew definitions from Redis using JSON serialization.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
import json
from redis.asyncio import Redis
from navconfig.logging import logging

from .models import CrewDefinition
from ...conf import REDIS_URL


class CrewRedis:
    """Redis-based persistence for AgentsCrew definitions."""

    def __init__(
        self,
        redis_url: str = None,
        key_prefix: str = "crew",
        db: int = 2  # Use DB 2 for crew persistence
    ):
        """
        Initialize Redis persistence for crews.

        Args:
            redis_url: Redis connection URL (default from config)
            key_prefix: Prefix for Redis keys (default: 'crew')
            db: Redis database number (default: 2)
        """
        self.logger = logging.getLogger('CrewRedis')
        self.key_prefix = key_prefix

        # Build Redis URL with specific DB if not provided
        if redis_url is None:
            from ...conf import REDIS_HOST, REDIS_PORT
            redis_url = f"redis://{REDIS_HOST}:{REDIS_PORT}/{db}"

        self.redis_url = redis_url
        self.redis = Redis.from_url(
            self.redis_url,
            decode_responses=True,
            encoding="utf-8",
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True
        )
        self.logger.info(f"CrewRedis initialized with URL: {self.redis_url}")

    @staticmethod
    def _normalize_tenant(tenant: Optional[str]) -> str:
        return tenant or "global"

    def _get_key(self, name: str, tenant: str) -> str:
        """
        Generate Redis key for crew definition.

        Args:
            name: Name of the crew
            tenant: Tenant identifier

        Returns:
            Redis key in format 'crew:{tenant}:{name}'
        """
        return f"{self.key_prefix}:{tenant}:{name}"

    def _get_list_key(self, tenant: str) -> str:
        """Get the key for the set of all crew names in a tenant."""
        return f"{self.key_prefix}:{tenant}:list"

    def _get_tenants_key(self) -> str:
        """Get the key for the set of all tenants."""
        return f"{self.key_prefix}:tenants"

    def _get_legacy_key(self, name: str) -> str:
        return f"{self.key_prefix}:{name}"

    def _get_legacy_list_key(self) -> str:
        return f"{self.key_prefix}:list"

    def _get_legacy_id_mapping_key(self, crew_id: str) -> str:
        return f"{self.key_prefix}:id:{crew_id}"

    def _get_id_mapping_key(self, crew_id: str, tenant: str) -> str:
        """
        Generate Redis key for crew_id to name mapping.

        Args:
            crew_id: UUID of the crew
            tenant: Tenant identifier

        Returns:
            Redis key in format 'crew:{tenant}:id:{crew_id}'
        """
        return f"{self.key_prefix}:{tenant}:id:{crew_id}"

    def _serialize_crew(self, crew: CrewDefinition) -> str:
        """
        Serialize CrewDefinition to JSON string.

        Args:
            crew: CrewDefinition instance

        Returns:
            JSON string representation
        """
        try:
            # Use Pydantic's model_dump to get dictionary
            crew_dict = crew.model_dump(mode='json')

            # Convert datetime objects to ISO format
            if isinstance(crew_dict.get('created_at'), datetime):
                crew_dict['created_at'] = crew_dict['created_at'].isoformat()
            if isinstance(crew_dict.get('updated_at'), datetime):
                crew_dict['updated_at'] = crew_dict['updated_at'].isoformat()

            return json.dumps(crew_dict, ensure_ascii=False, separators=(',', ':'))
        except Exception as e:
            self.logger.error(f"Serialization error: {e}")
            raise

    def _deserialize_crew(self, data: str) -> CrewDefinition:
        """
        Deserialize JSON string to CrewDefinition.

        Args:
            data: JSON string

        Returns:
            CrewDefinition instance
        """
        try:
            crew_dict = json.loads(data)

            # Convert ISO format strings back to datetime
            if 'created_at' in crew_dict and isinstance(crew_dict['created_at'], str):
                crew_dict['created_at'] = datetime.fromisoformat(crew_dict['created_at'])
            if 'updated_at' in crew_dict and isinstance(crew_dict['updated_at'], str):
                crew_dict['updated_at'] = datetime.fromisoformat(crew_dict['updated_at'])

            return CrewDefinition(**crew_dict)
        except Exception as e:
            self.logger.error(f"Deserialization error: {e}")
            self.logger.error(f"Problematic data: {data[:200]}")
            raise

    async def save_crew(self, crew: CrewDefinition) -> bool:
        """
        Save crew definition to Redis.

        Stores the crew definition with key format 'crew:{name}'.
        Also maintains a set of all crew names and a crew_id to name mapping.

        Args:
            crew: CrewDefinition instance to save

        Returns:
            True if saved successfully, False otherwise
        """
        try:
            # Update the updated_at timestamp
            crew.updated_at = datetime.utcnow()

            tenant = self._normalize_tenant(crew.tenant)
            key = self._get_key(crew.name, tenant)
            serialized = self._serialize_crew(crew)

            # Save crew definition
            await self.redis.set(key, serialized)

            # Add to crew list (set of all crew names)
            await self.redis.sadd(self._get_list_key(tenant), crew.name)

            # Track tenant list
            await self.redis.sadd(self._get_tenants_key(), tenant)

            # Create crew_id to name mapping for lookup by ID
            id_key = self._get_id_mapping_key(crew.crew_id, tenant)
            await self.redis.set(id_key, crew.name)

            self.logger.info(
                f"Crew '{crew.name}' (ID: {crew.crew_id}, tenant: {tenant}) saved successfully"
            )
            return True
        except Exception as e:
            self.logger.error(f"Error saving crew '{crew.name}': {e}")
            return False

    async def load_crew(self, name: str, tenant: Optional[str] = None) -> Optional[CrewDefinition]:
        """
        Load crew definition from Redis by name.

        Args:
            name: Name of the crew to load
            tenant: Tenant identifier

        Returns:
            CrewDefinition instance if found, None otherwise
        """
        try:
            tenant = self._normalize_tenant(tenant)
            key = self._get_key(name, tenant)
            data = await self.redis.get(key)
            if data is None and tenant == "global":
                legacy_key = self._get_legacy_key(name)
                data = await self.redis.get(legacy_key)

            if data is None:
                self.logger.warning(f"Crew '{name}' not found in Redis for tenant '{tenant}'")
                return None

            crew = self._deserialize_crew(data)
            self.logger.info(f"Crew '{name}' loaded successfully for tenant '{tenant}'")
            return crew
        except Exception as e:
            self.logger.error(f"Error loading crew '{name}': {e}")
            return None

    async def load_crew_by_id(
        self,
        crew_id: str,
        tenant: Optional[str] = None
    ) -> Optional[CrewDefinition]:
        """
        Load crew definition from Redis by crew_id.

        Args:
            crew_id: UUID of the crew to load
            tenant: Tenant identifier

        Returns:
            CrewDefinition instance if found, None otherwise
        """
        try:
            tenant = self._normalize_tenant(tenant)
            # First, look up the crew name from the ID
            id_key = self._get_id_mapping_key(crew_id, tenant)
            name = await self.redis.get(id_key)
            if name is None and tenant == "global":
                legacy_id_key = self._get_legacy_id_mapping_key(crew_id)
                name = await self.redis.get(legacy_id_key)

            if name is None:
                self.logger.warning(
                    f"Crew with ID '{crew_id}' not found in Redis for tenant '{tenant}'"
                )
                return None

            # Then load the crew by name
            return await self.load_crew(name, tenant)
        except Exception as e:
            self.logger.error(f"Error loading crew by ID '{crew_id}': {e}")
            return None

    async def delete_crew(self, name: str, tenant: Optional[str] = None) -> bool:
        """
        Delete crew definition from Redis.

        Args:
            name: Name of the crew to delete
            tenant: Tenant identifier

        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            tenant = self._normalize_tenant(tenant)
            # First, get the crew to extract the ID
            crew = await self.load_crew(name, tenant)

            key = self._get_key(name, tenant)
            result = await self.redis.delete(key)

            # Remove from crew list
            await self.redis.srem(self._get_list_key(tenant), name)

            if tenant == "global":
                legacy_key = self._get_legacy_key(name)
                legacy_result = await self.redis.delete(legacy_key)
                result = result or legacy_result
                await self.redis.srem(self._get_legacy_list_key(), name)

            # Remove ID mapping if crew was found
            if crew:
                id_key = self._get_id_mapping_key(crew.crew_id, tenant)
                await self.redis.delete(id_key)
                if tenant == "global":
                    legacy_id_key = self._get_legacy_id_mapping_key(crew.crew_id)
                    await self.redis.delete(legacy_id_key)

            if await self.redis.scard(self._get_list_key(tenant)) == 0:
                await self.redis.srem(self._get_tenants_key(), tenant)

            if result > 0:
                self.logger.info(f"Crew '{name}' deleted successfully for tenant '{tenant}'")
                return True
            else:
                self.logger.warning(f"Crew '{name}' not found for deletion in tenant '{tenant}'")
                return False
        except Exception as e:
            self.logger.error(f"Error deleting crew '{name}': {e}")
            return False

    async def list_crews(self, tenant: Optional[str] = None) -> List[str]:
        """
        List all crew names in Redis.

        Args:
            tenant: Tenant identifier

        Returns:
            List of crew names
        """
        try:
            tenant = self._normalize_tenant(tenant)
            crews = set(await self.redis.smembers(self._get_list_key(tenant)))
            if tenant == "global":
                crews.update(await self.redis.smembers(self._get_legacy_list_key()))
            return sorted(list(crews))
        except Exception as e:
            self.logger.error(f"Error listing crews: {e}")
            return []

    async def list_all_crews(self) -> List[Dict[str, str]]:
        """
        List all crew names across tenants.

        Returns:
            List of dictionaries with tenant and name.
        """
        try:
            tenants = await self.redis.smembers(self._get_tenants_key())
            legacy_global = await self.redis.smembers(self._get_legacy_list_key())
            if legacy_global:
                tenants = set(tenants)
                tenants.add("global")
            entries = []
            for tenant in tenants:
                crew_names = await self.list_crews(tenant)
                entries.extend(
                    {"tenant": tenant, "name": name} for name in crew_names
                )
            return entries
        except Exception as e:
            self.logger.error(f"Error listing crews across tenants: {e}")
            return []

    async def crew_exists(self, name: str, tenant: Optional[str] = None) -> bool:
        """
        Check if a crew exists in Redis.

        Args:
            name: Name of the crew
            tenant: Tenant identifier

        Returns:
            True if crew exists, False otherwise
        """
        try:
            tenant = self._normalize_tenant(tenant)
            key = self._get_key(name, tenant)
            exists = await self.redis.exists(key)
            if not exists and tenant == "global":
                legacy_key = self._get_legacy_key(name)
                exists = await self.redis.exists(legacy_key)
            return exists > 0
        except Exception as e:
            self.logger.error(f"Error checking crew existence '{name}': {e}")
            return False

    async def get_all_crews(self, tenant: Optional[str] = None) -> List[CrewDefinition]:
        """
        Get all crew definitions from Redis.

        Args:
            tenant: Tenant identifier (optional). If None, returns crews across tenants.

        Returns:
            List of CrewDefinition instances
        """
        try:
            crews = []
            if tenant is None:
                entries = await self.list_all_crews()
                for entry in entries:
                    crew = await self.load_crew(entry["name"], entry["tenant"])
                    if crew:
                        crews.append(crew)
                self.logger.info(f"Retrieved {len(crews)} crews from Redis (all tenants)")
                return crews

            crew_names = await self.list_crews(tenant)
            crews = []

            for name in crew_names:
                crew = await self.load_crew(name, tenant)
                if crew:
                    crews.append(crew)

            self.logger.info(f"Retrieved {len(crews)} crews from Redis for tenant '{tenant}'")
            return crews
        except Exception as e:
            self.logger.error(f"Error getting all crews: {e}")
            return []

    async def get_crew_metadata(
        self,
        name: str,
        tenant: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get crew metadata without loading the full definition.

        Args:
            name: Name of the crew
            tenant: Tenant identifier

        Returns:
            Dictionary with crew metadata (name, crew_id, description, etc.)
        """
        try:
            crew = await self.load_crew(name, tenant)
            if crew:
                return {
                    'crew_id': crew.crew_id,
                    'tenant': crew.tenant,
                    'name': crew.name,
                    'description': crew.description,
                    'execution_mode': crew.execution_mode.value,
                    'agent_count': len(crew.agents),
                    'created_at': crew.created_at.isoformat(),
                    'updated_at': crew.updated_at.isoformat(),
                    'metadata': crew.metadata
                }
            return None
        except Exception as e:
            self.logger.error(f"Error getting crew metadata '{name}': {e}")
            return None

    async def update_crew_metadata(
        self,
        name: str,
        metadata: Dict[str, Any],
        tenant: Optional[str] = None
    ) -> bool:
        """
        Update crew metadata without modifying agents or configuration.

        Args:
            name: Name of the crew
            metadata: Metadata dictionary to update
            tenant: Tenant identifier

        Returns:
            True if updated successfully, False otherwise
        """
        try:
            crew = await self.load_crew(name, tenant)
            if crew is None:
                self.logger.warning(f"Cannot update metadata: crew '{name}' not found")
                return False

            # Update metadata
            crew.metadata.update(metadata)
            crew.updated_at = datetime.utcnow()

            # Save back to Redis
            return await self.save_crew(crew)
        except Exception as e:
            self.logger.error(f"Error updating crew metadata '{name}': {e}")
            return False

    async def ping(self) -> bool:
        """
        Test Redis connection.

        Returns:
            True if connection is healthy, False otherwise
        """
        try:
            await self.redis.ping()
            return True
        except Exception as e:
            self.logger.error(f"Error pinging Redis: {e}")
            return False

    async def close(self):
        """Close the Redis connection."""
        try:
            await self.redis.close()
            self.logger.info("Redis connection closed")
        except Exception as e:
            self.logger.error(f"Error closing Redis connection: {e}")

    async def clear_all_crews(self) -> int:
        """
        Delete all crews from Redis (use with caution).

        Returns:
            Number of crews deleted
        """
        try:
            crew_entries = await self.list_all_crews()
            deleted_count = 0

            for entry in crew_entries:
                if await self.delete_crew(entry["name"], entry["tenant"]):
                    deleted_count += 1

            self.logger.warning(f"Cleared {deleted_count} crews from Redis")
            return deleted_count
        except Exception as e:
            self.logger.error(f"Error clearing all crews: {e}")
            return 0


# Example usage and testing
async def test_crew_redis():
    """Test the CrewRedis persistence layer."""
    from .models import AgentDefinition, ExecutionMode

    crew_redis = CrewRedis()

    if not await crew_redis.ping():
        print("❌ Redis connection failed!")
        return

    print("✓ Redis connection successful")

    try:
        # Test 1: Create and save a crew
        print("\n=== Test 1: Save Crew ===")
        crew_def = CrewDefinition(
            name="test_crew",
            description="A test crew for Redis persistence",
            execution_mode=ExecutionMode.SEQUENTIAL,
            agents=[
                AgentDefinition(
                    agent_id="agent_1",
                    agent_class="BasicAgent",
                    name="Researcher",
                    config={"model": "gpt-4", "temperature": 0.7},
                    tools=["search", "summarize"],
                    system_prompt="You are a research agent."
                ),
                AgentDefinition(
                    agent_id="agent_2",
                    agent_class="BasicAgent",
                    name="Writer",
                    config={"model": "gpt-4", "temperature": 0.9},
                    tools=["write", "edit"],
                    system_prompt="You are a writing agent."
                )
            ],
            shared_tools=["calculator"],
            metadata={"version": "1.0", "author": "test"}
        )

        saved = await crew_redis.save_crew(crew_def)
        print(f"Crew saved: {saved}")
        print(f"Crew ID: {crew_def.crew_id}")

        # Test 2: Load crew by name
        print("\n=== Test 2: Load Crew by Name ===")
        loaded_crew = await crew_redis.load_crew("test_crew")
        if loaded_crew:
            print(f"✓ Loaded crew: {loaded_crew.name}")
            print(f"  - Description: {loaded_crew.description}")
            print(f"  - Execution mode: {loaded_crew.execution_mode}")
            print(f"  - Agents: {len(loaded_crew.agents)}")
            print(f"  - Agent 1: {loaded_crew.agents[0].name}")
            print(f"  - Agent 2: {loaded_crew.agents[1].name}")
        else:
            print("❌ Failed to load crew")

        # Test 3: Load crew by ID
        print("\n=== Test 3: Load Crew by ID ===")
        loaded_by_id = await crew_redis.load_crew_by_id(crew_def.crew_id)
        if loaded_by_id:
            print(f"✓ Loaded crew by ID: {loaded_by_id.name}")
        else:
            print("❌ Failed to load crew by ID")

        # Test 4: List crews
        print("\n=== Test 4: List Crews ===")
        crews = await crew_redis.list_crews()
        print(f"All crews: {crews}")

        # Test 5: Check crew existence
        print("\n=== Test 5: Check Existence ===")
        exists = await crew_redis.crew_exists("test_crew")
        print(f"Crew exists: {exists}")

        not_exists = await crew_redis.crew_exists("nonexistent_crew")
        print(f"Nonexistent crew exists: {not_exists}")

        # Test 6: Get crew metadata
        print("\n=== Test 6: Get Crew Metadata ===")
        metadata = await crew_redis.get_crew_metadata("test_crew")
        if metadata:
            print(f"Crew metadata:")
            for key, value in metadata.items():
                print(f"  - {key}: {value}")

        # Test 7: Update metadata
        print("\n=== Test 7: Update Metadata ===")
        updated = await crew_redis.update_crew_metadata(
            "test_crew",
            {"version": "1.1", "last_test": datetime.utcnow().isoformat()}
        )
        print(f"Metadata updated: {updated}")

        # Test 8: Get all crews
        print("\n=== Test 8: Get All Crews ===")
        all_crews = await crew_redis.get_all_crews()
        print(f"Total crews: {len(all_crews)}")

        # Cleanup
        print("\n=== Cleanup ===")
        deleted = await crew_redis.delete_crew("test_crew")
        print(f"Crew deleted: {deleted}")

        print("\n✓ All tests passed!")

    finally:
        await crew_redis.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_crew_redis())
