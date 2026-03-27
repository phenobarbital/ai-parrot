"""Unit tests for TASK-458: Backward compatibility wrapper + registry updates."""
import pytest
import pandas as pd
from parrot_tools.whatif import WhatIfTool, WhatIfInput


class TestRegistryEntries:
    def test_registry_has_toolkit(self):
        from parrot_tools import TOOL_REGISTRY
        assert "whatif_toolkit" in TOOL_REGISTRY
        assert "whatif" in TOOL_REGISTRY  # preserved

    def test_registry_has_statistical_tools(self):
        from parrot_tools import TOOL_REGISTRY
        assert "sensitivity_analysis" in TOOL_REGISTRY
        assert "montecarlo" in TOOL_REGISTRY
        assert "statistical_tests" in TOOL_REGISTRY
        assert "regression_analysis" in TOOL_REGISTRY
        assert "breakeven" in TOOL_REGISTRY


class TestLegacyWhatIfTool:
    def test_whatif_tool_instantiates(self):
        tool = WhatIfTool()
        assert tool is not None
        assert tool.name == "whatif_scenario"

    def test_whatif_input_validates(self):
        inp = WhatIfInput(
            scenario_description="test scenario",
            possible_actions=[{"type": "close_region", "target": "North"}],
        )
        assert inp.scenario_description == "test scenario"

    @pytest.mark.asyncio
    async def test_legacy_tool_with_parent_agent(self):
        """Legacy WhatIfTool still works when given a parent agent."""
        df = pd.DataFrame({
            'Project': ['A', 'B', 'C'],
            'Revenue': [100000, 200000, 150000],
            'Expenses': [80000, 150000, 120000],
        })
        agent = type('Agent', (), {
            'dataframes': {'test': df},
        })()

        tool = WhatIfTool()
        tool._parent_agent = agent

        result = await tool._execute(
            scenario_description="remove A",
            possible_actions=[{
                "type": "exclude_values",
                "target": "Project",
                "parameters": {"column": "Project", "values": ["A"]},
            }],
            df_name="test",
        )
        assert result.success
        assert "comparison" in result.result or "comparison_table" in result.result


class TestSystemPromptPreserved:
    def test_legacy_system_prompt_exists(self):
        from parrot_tools.whatif import WHATIF_SYSTEM_PROMPT
        assert "What-If" in WHATIF_SYSTEM_PROMPT

    def test_toolkit_system_prompt_exists(self):
        from parrot_tools.whatif_toolkit import WHATIF_TOOLKIT_SYSTEM_PROMPT
        assert "quick_impact" in WHATIF_TOOLKIT_SYSTEM_PROMPT


class TestIntegrationHelpers:
    def test_legacy_integrate_function_exists(self):
        from parrot_tools.whatif import integrate_whatif_tool
        assert callable(integrate_whatif_tool)

    def test_toolkit_integrate_function_exists(self):
        from parrot_tools.whatif_toolkit import integrate_whatif_toolkit
        assert callable(integrate_whatif_toolkit)
