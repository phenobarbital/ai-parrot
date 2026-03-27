"""Unit tests for TASK-457: compare_scenarios tool + system prompt + integration helper."""
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock
from parrot_tools.whatif_toolkit import (
    WhatIfToolkit, ScenarioState,
    WHATIF_TOOLKIT_SYSTEM_PROMPT, integrate_whatif_toolkit,
)
from parrot_tools.whatif import WhatIfAction


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        'Project': ['A', 'B', 'C'],
        'Revenue': [100000, 200000, 150000],
        'Expenses': [80000, 150000, 120000],
    })


@pytest.fixture
def toolkit_with_solved(sample_df):
    """Toolkit with two solved scenarios using actual WhatIfDSL runs."""
    dm = MagicMock()
    dm.add_dataframe = AsyncMock(return_value="ok")
    toolkit = WhatIfToolkit(dataset_manager=dm)
    return toolkit, sample_df


class TestCompareScenarios:
    @pytest.mark.asyncio
    async def test_compare_two_solved_scenarios(self, toolkit_with_solved):
        toolkit, df = toolkit_with_solved
        # Create and solve two scenarios
        toolkit._scenarios["sc_1"] = ScenarioState(
            id="sc_1", description="remove A", df_name="test",
            df=df, derived_metrics=[],
            actions=[WhatIfAction(type="exclude_values", target="Project",
                                   parameters={"column": "Project", "values": ["A"]})],
            objectives=[], constraints=[]
        )
        toolkit._scenarios["sc_2"] = ScenarioState(
            id="sc_2", description="remove B", df_name="test",
            df=df, derived_metrics=[],
            actions=[WhatIfAction(type="exclude_values", target="Project",
                                   parameters={"column": "Project", "values": ["B"]})],
            objectives=[], constraints=[]
        )
        # Solve both
        await toolkit.simulate(scenario_id="sc_1")
        await toolkit.simulate(scenario_id="sc_2")

        result = await toolkit.compare_scenarios(scenario_ids=["sc_1", "sc_2"])
        assert "sc_1" in result
        assert "sc_2" in result

    @pytest.mark.asyncio
    async def test_error_unsolved_scenario(self, sample_df):
        toolkit = WhatIfToolkit()
        toolkit._scenarios["sc_1"] = ScenarioState(
            id="sc_1", description="test", df_name="test",
            df=sample_df, derived_metrics=[], actions=[],
            objectives=[], constraints=[]
        )
        with pytest.raises(ValueError, match="not been simulated"):
            await toolkit.compare_scenarios(scenario_ids=["sc_1", "sc_2"])

    @pytest.mark.asyncio
    async def test_error_nonexistent_scenario(self):
        toolkit = WhatIfToolkit()
        with pytest.raises(ValueError, match="not found"):
            await toolkit.compare_scenarios(scenario_ids=["sc_1", "sc_2"])

    @pytest.mark.asyncio
    async def test_minimum_two_scenarios(self):
        toolkit = WhatIfToolkit()
        with pytest.raises(ValueError, match="At least 2"):
            await toolkit.compare_scenarios(scenario_ids=["sc_1"])


class TestSystemPrompt:
    def test_system_prompt_exists(self):
        assert "quick_impact" in WHATIF_TOOLKIT_SYSTEM_PROMPT
        assert "describe_scenario" in WHATIF_TOOLKIT_SYSTEM_PROMPT

    def test_system_prompt_has_decision_guide(self):
        assert "Decision Guide" in WHATIF_TOOLKIT_SYSTEM_PROMPT

    def test_system_prompt_mentions_all_tools(self):
        assert "add_actions" in WHATIF_TOOLKIT_SYSTEM_PROMPT
        assert "set_constraints" in WHATIF_TOOLKIT_SYSTEM_PROMPT
        assert "simulate" in WHATIF_TOOLKIT_SYSTEM_PROMPT
        assert "compare_scenarios" in WHATIF_TOOLKIT_SYSTEM_PROMPT


class TestIntegrateHelper:
    def test_integrate_function_exists(self):
        assert callable(integrate_whatif_toolkit)

    def test_integrate_creates_toolkit(self):
        agent = MagicMock()
        agent.dataset_manager = MagicMock()
        agent.pandas_tool = MagicMock()
        agent.tool_manager = MagicMock()
        agent.add_system_prompt = MagicMock()

        result = integrate_whatif_toolkit(agent)
        assert isinstance(result, WhatIfToolkit)
        assert agent.tool_manager.register.call_count == 6
        agent.add_system_prompt.assert_called_once()
