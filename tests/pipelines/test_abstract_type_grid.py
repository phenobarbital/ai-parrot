"""Tests for AbstractPlanogramType grid integration (TASK-589)."""
import pytest
from unittest.mock import MagicMock, AsyncMock

from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType
from parrot_pipelines.planogram.grid.strategy import NoGrid


def _make_concrete_type() -> AbstractPlanogramType:
    """Create a minimal concrete subclass of AbstractPlanogramType for testing."""

    class _ConcreteType(AbstractPlanogramType):
        async def compute_roi(self, img):
            return None, None, None, None, []

        async def detect_objects_roi(self, img, roi):
            return []

        async def detect_objects(self, img, roi, macro_objects):
            return [], []

        def check_planogram_compliance(self, identified_products, planogram_description):
            return []

    # Build a minimal mock pipeline
    mock_pipeline = MagicMock()
    mock_pipeline.logger = MagicMock()
    mock_config = MagicMock()

    return _ConcreteType(pipeline=mock_pipeline, config=mock_config)


class TestAbstractTypeGridIntegration:
    """Tests that get_grid_strategy() is correctly added to AbstractPlanogramType."""

    def test_default_returns_no_grid(self):
        """Default get_grid_strategy() returns a NoGrid instance."""
        handler = _make_concrete_type()
        strategy = handler.get_grid_strategy()
        assert isinstance(strategy, NoGrid)

    def test_returns_fresh_instance_each_call(self):
        """Each call returns a new strategy instance (stateless)."""
        handler = _make_concrete_type()
        s1 = handler.get_grid_strategy()
        s2 = handler.get_grid_strategy()
        assert s1 is not s2

    def test_method_is_concrete_not_abstract(self):
        """get_grid_strategy is a concrete method — concrete types get it for free."""
        # If it were abstract, _ConcreteType (which doesn't override it) would fail
        handler = _make_concrete_type()
        assert callable(handler.get_grid_strategy)
        # No TypeError should be raised
        result = handler.get_grid_strategy()
        assert result is not None

    def test_no_circular_import(self):
        """Importing AbstractPlanogramType does not cause circular import errors."""
        # The lazy import pattern should prevent this
        from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType
        from parrot_pipelines.planogram.grid.strategy import NoGrid
        handler = _make_concrete_type()
        assert isinstance(handler.get_grid_strategy(), NoGrid)
