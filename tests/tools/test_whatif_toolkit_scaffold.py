"""Unit tests for TASK-452: WhatIfToolkit scaffold & ScenarioState model."""
import pytest
import pandas as pd
from parrot_tools.whatif_toolkit import (
    WhatIfToolkit,
    ScenarioState,
    DescribeScenarioInput,
    AddActionsInput,
    SetConstraintsInput,
    SimulateInput,
    QuickImpactInput,
    CompareScenariosInput,
)


class TestScenarioState:
    def test_is_ready_false_when_no_actions(self):
        state = ScenarioState(
            id="sc_1",
            description="test",
            df_name="test",
            df=pd.DataFrame(),
            derived_metrics=[],
            actions=[],
            objectives=[],
            constraints=[],
        )
        assert state.is_ready is False

    def test_is_ready_true_with_actions(self):
        state = ScenarioState(
            id="sc_1",
            description="test",
            df_name="test",
            df=pd.DataFrame(),
            derived_metrics=[],
            actions=[{"type": "adjust_metric", "target": "x", "parameters": {}}],
            objectives=[],
            constraints=[],
        )
        assert state.is_ready is True

    def test_is_solved_false_initially(self):
        state = ScenarioState(
            id="sc_1",
            description="test",
            df_name="test",
            df=pd.DataFrame(),
            derived_metrics=[],
            actions=[],
            objectives=[],
            constraints=[],
        )
        assert state.is_solved is False

    def test_is_solved_true_with_result(self):
        state = ScenarioState(
            id="sc_1",
            description="test",
            df_name="test",
            df=pd.DataFrame(),
            derived_metrics=[],
            actions=[],
            objectives=[],
            constraints=[],
        )
        state.result = True  # Simplified stand-in
        assert state.is_solved is True

    def test_created_at_populated(self):
        state = ScenarioState(
            id="sc_1",
            description="test",
            df_name="test",
            df=pd.DataFrame(),
            derived_metrics=[],
            actions=[],
            objectives=[],
            constraints=[],
        )
        assert state.created_at is not None


class TestWhatIfToolkit:
    def test_instantiation(self):
        toolkit = WhatIfToolkit()
        assert toolkit is not None

    def test_get_tools_returns_six(self):
        toolkit = WhatIfToolkit()
        tools = toolkit.get_tools()
        assert len(tools) == 6

    def test_tool_names(self):
        toolkit = WhatIfToolkit()
        names = toolkit.list_tool_names()
        expected = {
            "describe_scenario",
            "add_actions",
            "set_constraints",
            "simulate",
            "quick_impact",
            "compare_scenarios",
        }
        assert set(names) == expected

    def test_generate_id(self):
        toolkit = WhatIfToolkit()
        id1 = toolkit._generate_id()
        id2 = toolkit._generate_id()
        assert id1 == "sc_1"
        assert id2 == "sc_2"


class TestInputSchemas:
    def test_describe_scenario_input_valid(self):
        inp = DescribeScenarioInput(
            df_name="test_df", scenario_description="test scenario"
        )
        assert inp.df_name == "test_df"

    def test_quick_impact_input_valid(self):
        inp = QuickImpactInput(
            df_name="test_df",
            action_description="remove Belkin",
            action_type="exclude_values",
            target="Project",
        )
        assert inp.action_type == "exclude_values"

    def test_add_actions_input_valid(self):
        inp = AddActionsInput(scenario_id="sc_1", actions=[])
        assert inp.scenario_id == "sc_1"

    def test_set_constraints_input_valid(self):
        inp = SetConstraintsInput(scenario_id="sc_1")
        assert len(inp.objectives) == 0
        assert len(inp.constraints) == 0

    def test_simulate_input_defaults(self):
        inp = SimulateInput(scenario_id="sc_1")
        assert inp.algorithm == "greedy"
        assert inp.max_actions == 5

    def test_compare_scenarios_input_valid(self):
        inp = CompareScenariosInput(scenario_ids=["sc_1", "sc_2"])
        assert len(inp.scenario_ids) == 2
