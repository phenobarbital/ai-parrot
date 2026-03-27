"""Integration tests for TASK-464: End-to-end validation of WhatIfToolkit."""
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock
from parrot_tools.whatif_toolkit import WhatIfToolkit
from parrot_tools.whatif import (
    WhatIfTool,
    DerivedMetric,
    WhatIfAction,
    WhatIfObjective,
    WhatIfConstraint,
)


@pytest.fixture
def pokemon_df():
    return pd.DataFrame({
        'Project': ['IT Vision', 'Walmart', 'Symbits', 'Belkin', 'Flex'],
        'Revenue': [500000, 800000, 300000, 400000, 350000],
        'Expenses': [400000, 600000, 250000, 350000, 300000],
        'kiosks': [50, 80, 30, 40, 35],
        'warehouses': [3, 5, 2, 3, 2],
    })


@pytest.fixture
def toolkit(pokemon_df):
    dm = MagicMock()
    dm.get_dataframe = AsyncMock(return_value={'dataframe': pokemon_df})
    dm.add_dataframe = AsyncMock(return_value="registered")
    pandas_tool = MagicMock()
    pandas_tool.sync_from_manager = MagicMock()
    return WhatIfToolkit(dataset_manager=dm, pandas_tool=pandas_tool)


class TestToolkitWithDatasetManager:
    @pytest.mark.asyncio
    async def test_scenario_resolves_datasets_from_dm(self, toolkit):
        result = await toolkit.describe_scenario(
            df_name="pokemon", scenario_description="test"
        )
        toolkit._dm.get_dataframe.assert_called_once_with("pokemon")
        assert "sc_1" in result

    @pytest.mark.asyncio
    async def test_result_registered_back_in_dm(self, toolkit):
        desc = await toolkit.describe_scenario(
            df_name="pokemon", scenario_description="remove Belkin"
        )
        await toolkit.add_actions(
            scenario_id="sc_1",
            actions=[WhatIfAction(
                type="exclude_values", target="Project",
                parameters={"column": "Project", "values": ["Belkin"]}
            )],
        )
        await toolkit.simulate(scenario_id="sc_1")
        toolkit._dm.add_dataframe.assert_called_once()
        call_kwargs = toolkit._dm.add_dataframe.call_args
        assert "whatif_sc_1_result" in str(call_kwargs)


class TestFullWorkflow:
    @pytest.mark.asyncio
    async def test_describe_add_simulate_compare(self, toolkit):
        # Step 1: describe
        desc = await toolkit.describe_scenario(
            df_name="pokemon",
            scenario_description="remove Belkin project",
            derived_metrics=[DerivedMetric(name="ebitda", formula="Revenue - Expenses")],
        )
        assert "sc_1" in desc
        assert "ebitda" in desc

        # Step 2: add actions
        act_result = await toolkit.add_actions(
            scenario_id="sc_1",
            actions=[WhatIfAction(
                type="exclude_values", target="Project",
                parameters={"column": "Project", "values": ["Belkin"]}
            )],
        )
        assert "1 action(s) added" in act_result

        # Step 3: set constraints
        const_result = await toolkit.set_constraints(
            scenario_id="sc_1",
            objectives=[WhatIfObjective(type="maximize", metric="Revenue")],
        )
        assert "Objectives: 1" in const_result

        # Step 4: simulate
        sim_result = await toolkit.simulate(scenario_id="sc_1")
        assert "Revenue" in sim_result

        # Create second scenario
        desc2 = await toolkit.describe_scenario(
            df_name="pokemon",
            scenario_description="remove Flex project",
        )
        await toolkit.add_actions(
            scenario_id="sc_2",
            actions=[WhatIfAction(
                type="exclude_values", target="Project",
                parameters={"column": "Project", "values": ["Flex"]}
            )],
        )
        await toolkit.simulate(scenario_id="sc_2")

        # Step 5: compare
        compare_result = await toolkit.compare_scenarios(
            scenario_ids=["sc_1", "sc_2"]
        )
        assert "sc_1" in compare_result
        assert "sc_2" in compare_result


class TestPokemonScenario:
    @pytest.mark.asyncio
    async def test_quick_impact_remove_belkin(self, toolkit):
        result = await toolkit.quick_impact(
            df_name="pokemon",
            action_description="remove Belkin",
            action_type="exclude_values",
            target="Project",
            parameters={"column": "Project", "values": ["Belkin"]}
        )
        assert "Revenue" in result

    @pytest.mark.asyncio
    async def test_quick_impact_scale_entity(self, toolkit):
        result = await toolkit.quick_impact(
            df_name="pokemon",
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
    async def test_quick_impact_adjust_metric(self, toolkit):
        result = await toolkit.quick_impact(
            df_name="pokemon",
            action_description="increase kiosks by 30%",
            action_type="adjust_metric",
            target="kiosks",
            parameters={"min_pct": 30, "max_pct": 30}
        )
        assert "kiosks" in result.lower() or "Kiosks" in result

    @pytest.mark.asyncio
    async def test_quick_impact_close_region(self, toolkit):
        result = await toolkit.quick_impact(
            df_name="pokemon",
            action_description="exclude Walmart",
            action_type="exclude_values",
            target="Project",
            parameters={"column": "Project", "values": ["Walmart"]}
        )
        assert "Revenue" in result

    @pytest.mark.asyncio
    async def test_quick_impact_scale_proportional(self, toolkit):
        result = await toolkit.quick_impact(
            df_name="pokemon",
            action_description="increase kiosks by 20% with revenue scaling",
            action_type="scale_proportional",
            target="kiosks",
            parameters={
                "affected_columns": ["Revenue"],
                "min_pct": 20, "max_pct": 20
            }
        )
        assert "kiosks" in result.lower() or "Kiosks" in result


class TestLegacyCompat:
    @pytest.mark.asyncio
    async def test_legacy_tool_produces_result(self, pokemon_df):
        """Existing WhatIfTool pattern still works."""
        agent = type('Agent', (), {'dataframes': {'pokemon': pokemon_df}})()
        tool = WhatIfTool()
        tool._parent_agent = agent

        result = await tool._execute(
            scenario_description="remove Belkin",
            possible_actions=[{
                "type": "exclude_values",
                "target": "Project",
                "parameters": {"column": "Project", "values": ["Belkin"]},
            }],
            df_name="pokemon",
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_legacy_with_objectives(self, pokemon_df):
        """Legacy WhatIfTool with optimization still works."""
        agent = type('Agent', (), {'dataframes': {'pokemon': pokemon_df}})()
        tool = WhatIfTool()
        tool._parent_agent = agent

        result = await tool._execute(
            scenario_description="optimize revenue",
            possible_actions=[{
                "type": "exclude_values",
                "target": "Project",
                "parameters": {"column": "Project", "values": ["Belkin", "Symbits"]},
            }],
            objectives=[{"type": "maximize", "metric": "Revenue"}],
            df_name="pokemon",
        )
        assert result.success
