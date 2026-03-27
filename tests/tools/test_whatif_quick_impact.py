"""Unit tests for TASK-456: quick_impact tool method."""
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock
from parrot_tools.whatif_toolkit import WhatIfToolkit


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        'Project': ['IT Vision', 'Walmart', 'Symbits', 'Belkin', 'Flex'],
        'Region': ['North', 'South', 'East', 'West', 'North'],
        'Revenue': [500000, 800000, 300000, 400000, 350000],
        'Expenses': [400000, 600000, 250000, 350000, 300000],
        'kiosks': [50, 80, 30, 40, 35],
        'visits': [1000, 2000, 800, 1200, 900],
    })


@pytest.fixture
def toolkit(sample_df):
    dm = MagicMock()
    dm.get_dataframe = AsyncMock(return_value={'dataframe': sample_df})
    dm.add_dataframe = AsyncMock(return_value="ok")
    return WhatIfToolkit(dataset_manager=dm)


class TestQuickImpact:
    @pytest.mark.asyncio
    async def test_exclude_values(self, toolkit):
        result = await toolkit.quick_impact(
            df_name="test",
            action_description="remove Belkin",
            action_type="exclude_values",
            target="Project",
            parameters={"column": "Project", "values": ["Belkin"]}
        )
        assert "Revenue" in result
        # Should show impact
        assert "Metric" in result or "|" in result

    @pytest.mark.asyncio
    async def test_close_region(self, toolkit):
        result = await toolkit.quick_impact(
            df_name="test",
            action_description="close North region",
            action_type="close_region",
            target="Region",
            parameters={"regions": ["North"]}
        )
        assert "Revenue" in result

    @pytest.mark.asyncio
    async def test_adjust_metric(self, toolkit):
        result = await toolkit.quick_impact(
            df_name="test",
            action_description="increase visits by 30%",
            action_type="adjust_metric",
            target="visits",
            parameters={"min_pct": 30, "max_pct": 30}
        )
        assert "visits" in result.lower() or "Visits" in result

    @pytest.mark.asyncio
    async def test_scale_entity(self, toolkit):
        result = await toolkit.quick_impact(
            df_name="test",
            action_description="reduce Belkin by 50%",
            action_type="scale_entity",
            target="Project",
            parameters={
                "entity_column": "Project",
                "entities": ["Belkin"],
                "target_columns": ["Revenue", "Expenses"],
                "min_pct": -50, "max_pct": -50
            }
        )
        assert "Revenue" in result

    @pytest.mark.asyncio
    async def test_invalid_column(self, toolkit):
        result = await toolkit.quick_impact(
            df_name="test",
            action_description="remove X",
            action_type="exclude_values",
            target="NonExistent",
            parameters={"column": "NonExistent", "values": ["X"]}
        )
        assert "not found" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_unknown_action_type(self, toolkit):
        result = await toolkit.quick_impact(
            df_name="test",
            action_description="something",
            action_type="unknown_type",
            target="Revenue",
        )
        assert "error" in result.lower() or "unknown" in result.lower()

    @pytest.mark.asyncio
    async def test_dataset_not_found(self):
        toolkit = WhatIfToolkit()
        result = await toolkit.quick_impact(
            df_name="nonexistent",
            action_description="test",
            action_type="exclude_values",
            target="col",
        )
        assert "error" in result.lower() or "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_registers_result_in_dm(self, toolkit):
        await toolkit.quick_impact(
            df_name="test",
            action_description="remove Belkin",
            action_type="exclude_values",
            target="Project",
            parameters={"column": "Project", "values": ["Belkin"]}
        )
        toolkit._dm.add_dataframe.assert_called_once()
