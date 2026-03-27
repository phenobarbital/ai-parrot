"""Unit tests for TASK-455: simulate tool method with DatasetManager integration."""
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock
from parrot_tools.whatif_toolkit import WhatIfToolkit, ScenarioState
from parrot_tools.whatif import WhatIfAction, WhatIfObjective, DerivedMetric


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        'Project': ['IT Vision', 'Walmart', 'Symbits', 'Belkin', 'Flex'],
        'Revenue': [500000, 800000, 300000, 400000, 350000],
        'Expenses': [400000, 600000, 250000, 350000, 300000],
        'kiosks': [50, 80, 30, 40, 35],
    })


@pytest.fixture
def toolkit_with_ready_scenario(sample_df):
    dm = MagicMock()
    dm.add_dataframe = AsyncMock(return_value="registered")
    toolkit = WhatIfToolkit(dataset_manager=dm)
    toolkit._scenarios["sc_1"] = ScenarioState(
        id="sc_1", description="test scenario", df_name="test",
        df=sample_df, derived_metrics=[],
        actions=[WhatIfAction(type="exclude_values", target="Project",
                               parameters={"column": "Project", "values": ["Belkin"]})],
        objectives=[], constraints=[]
    )
    return toolkit


class TestSimulate:
    @pytest.mark.asyncio
    async def test_simulate_returns_comparison(self, toolkit_with_ready_scenario):
        result = await toolkit_with_ready_scenario.simulate(scenario_id="sc_1")
        assert "Metric" in result or "Revenue" in result

    @pytest.mark.asyncio
    async def test_registers_result_in_dm(self, toolkit_with_ready_scenario):
        await toolkit_with_ready_scenario.simulate(scenario_id="sc_1")
        toolkit_with_ready_scenario._dm.add_dataframe.assert_called_once()

    @pytest.mark.asyncio
    async def test_scenario_is_solved_after_simulate(self, toolkit_with_ready_scenario):
        await toolkit_with_ready_scenario.simulate(scenario_id="sc_1")
        assert toolkit_with_ready_scenario._scenarios["sc_1"].is_solved

    @pytest.mark.asyncio
    async def test_error_when_no_actions(self, sample_df):
        toolkit = WhatIfToolkit()
        toolkit._scenarios["sc_empty"] = ScenarioState(
            id="sc_empty", description="empty", df_name="test",
            df=sample_df, derived_metrics=[], actions=[],
            objectives=[], constraints=[]
        )
        with pytest.raises(ValueError, match="no actions"):
            await toolkit.simulate(scenario_id="sc_empty")

    @pytest.mark.asyncio
    async def test_scenario_not_found(self):
        toolkit = WhatIfToolkit()
        with pytest.raises(ValueError, match="not found"):
            await toolkit.simulate(scenario_id="nonexistent")

    @pytest.mark.asyncio
    async def test_without_dm_skips_registration(self, sample_df):
        toolkit = WhatIfToolkit()  # no DM
        toolkit._scenarios["sc_1"] = ScenarioState(
            id="sc_1", description="test", df_name="test",
            df=sample_df, derived_metrics=[],
            actions=[WhatIfAction(type="exclude_values", target="Project",
                                   parameters={"column": "Project", "values": ["Belkin"]})],
            objectives=[], constraints=[]
        )
        result = await toolkit.simulate(scenario_id="sc_1")
        assert "Revenue" in result

    @pytest.mark.asyncio
    async def test_simulate_with_objectives(self, sample_df):
        dm = MagicMock()
        dm.add_dataframe = AsyncMock(return_value="ok")
        toolkit = WhatIfToolkit(dataset_manager=dm)
        toolkit._scenarios["sc_1"] = ScenarioState(
            id="sc_1", description="optimize", df_name="test",
            df=sample_df, derived_metrics=[],
            actions=[WhatIfAction(type="exclude_values", target="Project",
                                   parameters={"column": "Project", "values": ["Belkin"]})],
            objectives=[WhatIfObjective(type="maximize", metric="Revenue")],
            constraints=[]
        )
        result = await toolkit.simulate(scenario_id="sc_1")
        assert toolkit._scenarios["sc_1"].is_solved

    @pytest.mark.asyncio
    async def test_result_dataframe_name(self, toolkit_with_ready_scenario):
        await toolkit_with_ready_scenario.simulate(scenario_id="sc_1")
        call_args = toolkit_with_ready_scenario._dm.add_dataframe.call_args
        assert "whatif_sc_1_result" in str(call_args)

    @pytest.mark.asyncio
    async def test_pandas_tool_synced(self, sample_df):
        dm = MagicMock()
        dm.add_dataframe = AsyncMock(return_value="ok")
        pandas_tool = MagicMock()
        pandas_tool.sync_from_manager = MagicMock()
        toolkit = WhatIfToolkit(dataset_manager=dm, pandas_tool=pandas_tool)
        toolkit._scenarios["sc_1"] = ScenarioState(
            id="sc_1", description="test", df_name="test",
            df=sample_df, derived_metrics=[],
            actions=[WhatIfAction(type="exclude_values", target="Project",
                                   parameters={"column": "Project", "values": ["Belkin"]})],
            objectives=[], constraints=[]
        )
        await toolkit.simulate(scenario_id="sc_1")
        pandas_tool.sync_from_manager.assert_called_once()
