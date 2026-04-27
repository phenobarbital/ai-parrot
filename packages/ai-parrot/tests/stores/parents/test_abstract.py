"""Unit tests for AbstractParentSearcher — TASK-855."""
import pytest

from parrot.stores.parents import AbstractParentSearcher


class TestAbstractParentSearcher:
    """Tests for the AbstractParentSearcher ABC contract."""

    def test_cannot_instantiate_directly(self):
        """AbstractParentSearcher is an ABC and cannot be instantiated directly."""
        with pytest.raises(TypeError):
            AbstractParentSearcher()  # type: ignore[abstract]

    def test_subclass_must_implement_fetch(self):
        """A subclass that does not implement fetch() cannot be instantiated."""
        class Incomplete(AbstractParentSearcher):
            pass

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    @pytest.mark.asyncio
    async def test_default_health_check_returns_true(self):
        """The default health_check() implementation returns True."""
        class Minimal(AbstractParentSearcher):
            async def fetch(self, parent_ids):
                return {}

        searcher = Minimal()
        assert await searcher.health_check() is True

    @pytest.mark.asyncio
    async def test_concrete_subclass_fetch_returns_empty_for_empty_input(self):
        """A well-behaved subclass returns {} for an empty parent_ids list."""
        class Minimal(AbstractParentSearcher):
            async def fetch(self, parent_ids):
                return {}

        searcher = Minimal()
        result = await searcher.fetch([])
        assert result == {}

    def test_concrete_subclass_can_be_instantiated(self):
        """A subclass that implements fetch() can be instantiated."""
        class Concrete(AbstractParentSearcher):
            async def fetch(self, parent_ids):
                return {}

        searcher = Concrete()
        assert isinstance(searcher, AbstractParentSearcher)
