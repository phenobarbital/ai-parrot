"""Unit tests for the ResultStorage ABC read-method contract (FEAT-307)."""
import pytest

from parrot.bots.flows.core.storage.backends.base import ResultStorage


class ConcreteStorage(ResultStorage):
    """Minimal concrete subclass for testing."""

    async def save(self, collection, document):
        pass

    async def close(self):
        pass


@pytest.fixture
def storage():
    return ConcreteStorage()


class TestResultStorageABC:
    @pytest.mark.asyncio
    async def test_list_raises_not_implemented(self, storage):
        with pytest.raises(NotImplementedError, match="ConcreteStorage"):
            await storage.list("test_collection")

    @pytest.mark.asyncio
    async def test_get_raises_not_implemented(self, storage):
        with pytest.raises(NotImplementedError, match="ConcreteStorage"):
            await storage.get("test_collection", "some-id")

    @pytest.mark.asyncio
    async def test_delete_raises_not_implemented(self, storage):
        with pytest.raises(NotImplementedError, match="ConcreteStorage"):
            await storage.delete("test_collection", "some-id")

    @pytest.mark.asyncio
    async def test_count_raises_not_implemented(self, storage):
        with pytest.raises(NotImplementedError, match="ConcreteStorage"):
            await storage.count("test_collection")
