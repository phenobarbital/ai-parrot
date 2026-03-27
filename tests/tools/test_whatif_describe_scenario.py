"""Unit tests for TASK-453: describe_scenario tool method."""
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock
from parrot_tools.whatif_toolkit import WhatIfToolkit
from parrot_tools.whatif import DerivedMetric


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        'Project': ['A', 'B', 'C', 'D'],
        'Region': ['North', 'South', 'North', 'South'],
        'Revenue': [100000, 200000, 150000, 180000],
        'Expenses': [80000, 150000, 120000, 140000],
        'kiosks': [50, 80, 60, 70],
    })


@pytest.fixture
def toolkit_with_dm(sample_df):
    dm = MagicMock()
    dm.get_dataframe = AsyncMock(return_value={'dataframe': sample_df})
    return WhatIfToolkit(dataset_manager=dm)


@pytest.fixture
def toolkit_with_parent(sample_df):
    toolkit = WhatIfToolkit()
    toolkit._parent_agent = type('Agent', (), {'dataframes': {'test': sample_df}})()
    return toolkit


class TestDescribeScenario:
    @pytest.mark.asyncio
    async def test_creates_scenario(self, toolkit_with_dm):
        result = await toolkit_with_dm.describe_scenario(
            df_name="test", scenario_description="test scenario"
        )
        assert "sc_" in result
        assert len(toolkit_with_dm._scenarios) == 1

    @pytest.mark.asyncio
    async def test_detects_column_types(self, toolkit_with_dm):
        result = await toolkit_with_dm.describe_scenario(
            df_name="test", scenario_description="test"
        )
        assert "Revenue" in result
        assert "numeric" in result.lower() or "categorical" in result.lower()

    @pytest.mark.asyncio
    async def test_validates_derived_metrics(self, toolkit_with_dm):
        result = await toolkit_with_dm.describe_scenario(
            df_name="test", scenario_description="test",
            derived_metrics=[DerivedMetric(name="ebitda", formula="Revenue - Expenses")]
        )
        assert "ebitda" in result
        assert "validated" in result.lower() or "OK" in result

    @pytest.mark.asyncio
    async def test_invalid_formula_fails(self, toolkit_with_dm):
        with pytest.raises(ValueError, match="nonexistent"):
            await toolkit_with_dm.describe_scenario(
                df_name="test", scenario_description="test",
                derived_metrics=[DerivedMetric(name="bad", formula="nonexistent_col * 2")]
            )

    @pytest.mark.asyncio
    async def test_parent_agent_fallback(self, toolkit_with_parent):
        result = await toolkit_with_parent.describe_scenario(
            df_name="test", scenario_description="test"
        )
        assert "sc_" in result
        assert len(toolkit_with_parent._scenarios) == 1

    @pytest.mark.asyncio
    async def test_dataset_not_found(self):
        toolkit = WhatIfToolkit()
        with pytest.raises(ValueError, match="not found"):
            await toolkit.describe_scenario(
                df_name="nonexistent", scenario_description="test"
            )

    @pytest.mark.asyncio
    async def test_multiple_scenarios(self, toolkit_with_dm):
        r1 = await toolkit_with_dm.describe_scenario(
            df_name="test", scenario_description="first"
        )
        r2 = await toolkit_with_dm.describe_scenario(
            df_name="test", scenario_description="second"
        )
        assert "sc_1" in r1
        assert "sc_2" in r2
        assert len(toolkit_with_dm._scenarios) == 2

    @pytest.mark.asyncio
    async def test_suggested_actions_included(self, toolkit_with_dm):
        result = await toolkit_with_dm.describe_scenario(
            df_name="test", scenario_description="test"
        )
        assert "Suggested actions" in result
