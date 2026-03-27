"""Unit tests for TASK-454: add_actions and set_constraints tool methods."""
import pytest
import pandas as pd
from parrot_tools.whatif_toolkit import WhatIfToolkit, ScenarioState
from parrot_tools.whatif import WhatIfAction, WhatIfObjective, WhatIfConstraint, DerivedMetric


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
def toolkit_with_scenario(sample_df):
    toolkit = WhatIfToolkit()
    toolkit._scenarios["sc_1"] = ScenarioState(
        id="sc_1", description="test", df_name="test",
        df=sample_df, derived_metrics=[], actions=[],
        objectives=[], constraints=[]
    )
    return toolkit


@pytest.fixture
def toolkit_with_derived(sample_df):
    toolkit = WhatIfToolkit()
    toolkit._scenarios["sc_1"] = ScenarioState(
        id="sc_1", description="test", df_name="test",
        df=sample_df,
        derived_metrics=[DerivedMetric(name="ebitda", formula="Revenue - Expenses")],
        actions=[], objectives=[], constraints=[]
    )
    return toolkit


class TestAddActions:
    @pytest.mark.asyncio
    async def test_add_valid_action(self, toolkit_with_scenario):
        result = await toolkit_with_scenario.add_actions(
            scenario_id="sc_1",
            actions=[WhatIfAction(type="exclude_values", target="Project",
                                   parameters={"column": "Project", "values": ["A"]})]
        )
        assert len(toolkit_with_scenario._scenarios["sc_1"].actions) == 1
        assert "1 action(s) added" in result

    @pytest.mark.asyncio
    async def test_invalid_column_reported(self, toolkit_with_scenario):
        result = await toolkit_with_scenario.add_actions(
            scenario_id="sc_1",
            actions=[WhatIfAction(type="exclude_values", target="BadColumn",
                                   parameters={"column": "BadColumn", "values": ["X"]})]
        )
        assert "not found" in result.lower()
        assert len(toolkit_with_scenario._scenarios["sc_1"].actions) == 0

    @pytest.mark.asyncio
    async def test_invalid_scenario_id(self, toolkit_with_scenario):
        with pytest.raises(ValueError):
            await toolkit_with_scenario.add_actions(scenario_id="bad_id", actions=[])

    @pytest.mark.asyncio
    async def test_partial_success(self, toolkit_with_scenario):
        result = await toolkit_with_scenario.add_actions(
            scenario_id="sc_1",
            actions=[
                WhatIfAction(type="exclude_values", target="Project",
                             parameters={"column": "Project", "values": ["A"]}),
                WhatIfAction(type="exclude_values", target="NonExist",
                             parameters={"column": "NonExist", "values": ["X"]}),
            ]
        )
        assert len(toolkit_with_scenario._scenarios["sc_1"].actions) == 1
        assert "1 action(s) added" in result
        assert "1 action(s) invalid" in result

    @pytest.mark.asyncio
    async def test_adjust_metric_valid(self, toolkit_with_scenario):
        result = await toolkit_with_scenario.add_actions(
            scenario_id="sc_1",
            actions=[WhatIfAction(type="adjust_metric", target="Revenue",
                                   parameters={"min_pct": 10, "max_pct": 30})]
        )
        assert len(toolkit_with_scenario._scenarios["sc_1"].actions) == 1

    @pytest.mark.asyncio
    async def test_adjust_metric_non_numeric(self, toolkit_with_scenario):
        result = await toolkit_with_scenario.add_actions(
            scenario_id="sc_1",
            actions=[WhatIfAction(type="adjust_metric", target="Project",
                                   parameters={})]
        )
        assert "not numeric" in result.lower()

    @pytest.mark.asyncio
    async def test_scenario_becomes_ready(self, toolkit_with_scenario):
        assert not toolkit_with_scenario._scenarios["sc_1"].is_ready
        await toolkit_with_scenario.add_actions(
            scenario_id="sc_1",
            actions=[WhatIfAction(type="exclude_values", target="Project",
                                   parameters={"column": "Project", "values": ["A"]})]
        )
        assert toolkit_with_scenario._scenarios["sc_1"].is_ready


class TestSetConstraints:
    @pytest.mark.asyncio
    async def test_set_valid_objective(self, toolkit_with_scenario):
        result = await toolkit_with_scenario.set_constraints(
            scenario_id="sc_1",
            objectives=[WhatIfObjective(type="maximize", metric="Revenue")]
        )
        assert len(toolkit_with_scenario._scenarios["sc_1"].objectives) == 1

    @pytest.mark.asyncio
    async def test_invalid_metric_name(self, toolkit_with_scenario):
        result = await toolkit_with_scenario.set_constraints(
            scenario_id="sc_1",
            constraints=[WhatIfConstraint(type="max_change", metric="nonexistent", value=5.0)]
        )
        assert "not found" in result.lower() or "warning" in result.lower()

    @pytest.mark.asyncio
    async def test_derived_metric_valid(self, toolkit_with_derived):
        result = await toolkit_with_derived.set_constraints(
            scenario_id="sc_1",
            objectives=[WhatIfObjective(type="maximize", metric="ebitda")]
        )
        assert len(toolkit_with_derived._scenarios["sc_1"].objectives) == 1

    @pytest.mark.asyncio
    async def test_invalid_scenario_id(self, toolkit_with_scenario):
        with pytest.raises(ValueError):
            await toolkit_with_scenario.set_constraints(scenario_id="bad_id")

    @pytest.mark.asyncio
    async def test_optional_params(self, toolkit_with_scenario):
        result = await toolkit_with_scenario.set_constraints(scenario_id="sc_1")
        assert "Objectives: 0" in result
        assert "Constraints: 0" in result
