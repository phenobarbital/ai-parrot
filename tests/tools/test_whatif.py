
import pytest
import pandas as pd
import numpy as np
import asyncio
from parrot.tools.whatif import WhatIfTool, WhatIfInput, WhatIfDSL, Action

# Mock Agent
class MockAgent:
    def __init__(self, df):
        self.dataframes = {"default": df}
        self.tool_manager = self
        self.system_prompt_template = ""
        self.logger = self

    def register_tool(self, tool):
        pass
        
    def info(self, msg):
        print(f"INFO: {msg}")
        
    def error(self, msg):
        print(f"ERROR: {msg}")
        
    def debug(self, msg):
        pass

# Data setup
@pytest.fixture
def augmented_df():
    data = {
        "Project": ["IT Vision", "Walmart Overnight Reset", "Symbits", "Roadshows", "Pokemon", "Bose", "Belkin", "Flex", "Hisense", "Walmart Assembly", "Trend Micro", "TCT Mobile", "Epson (US & Canada)", "MI/VIBA", "Corporate Expenses", "Corporate Allocation", "TCI"],
        "Revenue": [937492.00, 36157600.00, 4817110.00, 3215130.00, 14016900.00, 4911350.00, 3002310.00, 18028500.00, 12526400.00, 18105100.00, 2987540.00, 3203600.00, 14554200.00, 2089110.00, 1811810.00, 0.00, 581375.00],
        "Expenses": [118826.00, 10370000.00, 1873180.00, 1647660.00, 8485300.00, 3073610.00, 2061430.00, 12908700.00, 9067360.00, 14713600.00, 2437000.00, 3124510.00, 15658800.00, 8308480.00, 15936000.00, 0.00, -233574.00],
        # New columns as requested
        "payroll": np.random.uniform(50000, 500000, 17),
        "other_expenses": np.random.uniform(10000, 100000, 17),
        "fte": np.random.randint(5, 100, 17),
        "visits": np.random.randint(1000, 50000, 17),
        "ebitda": np.random.uniform(-100000, 3000000, 17)
    }
    return pd.DataFrame(data)


@pytest.mark.asyncio
async def test_scale_entity_belkin_50pct(augmented_df):
    """Test the exact scenario: 'What if Project Belkin is reduced to 50%?'"""
    
    # Expected values
    total_rev_baseline = augmented_df['Revenue'].sum()
    belkin_rev = augmented_df.loc[augmented_df['Project'] == "Belkin", "Revenue"].values[0]
    
    # After reducing Belkin to 50%, new total should be:
    expected_new_total = total_rev_baseline - (belkin_rev * 0.5)
    expected_pct_change = ((expected_new_total - total_rev_baseline) / total_rev_baseline) * 100
    
    print(f"Baseline Revenue: ${total_rev_baseline:,.2f}")
    print(f"Belkin Revenue: ${belkin_rev:,.2f}")
    print(f"Expected New Total: ${expected_new_total:,.2f}")
    print(f"Expected % Change: {expected_pct_change:.2f}%")
    
    # Use the DSL directly
    dsl = WhatIfDSL(augmented_df, "reduce_belkin_50pct")
    dsl.can_scale_entity(
        entity_column="Project",
        target_columns=["Revenue", "Expenses"],
        entities=["Belkin"],
        min_pct=-50,
        max_pct=-50
    )
    
    # Find the Belkin action
    belkin_action = next((a for a in dsl.possible_actions if "Belkin" in a.name), None)
    assert belkin_action is not None, "Belkin action should be generated"
    assert belkin_action.operation == "scale_by_value"
    
    # Apply the action
    res_df = dsl._apply_action(belkin_action)
    
    # Verify Belkin revenue is now 50% of original
    new_belkin_rev = res_df.loc[res_df['Project'] == "Belkin", "Revenue"].values[0]
    assert np.isclose(new_belkin_rev, belkin_rev * 0.5), f"Belkin revenue should be 50%: got {new_belkin_rev}"
    
    # Verify total revenue
    new_total = res_df['Revenue'].sum()
    assert np.isclose(new_total, expected_new_total, atol=1.0), f"Expected {expected_new_total}, got {new_total}"
    
    # Verify % change is around -1.07%, NOT -96%!
    actual_pct_change = ((new_total - total_rev_baseline) / total_rev_baseline) * 100
    print(f"Actual % Change: {actual_pct_change:.2f}%")
    
    # The change should be small (~-1%), NOT large
    assert abs(actual_pct_change) < 5.0, f"Change should be small, got {actual_pct_change:.2f}%"
    assert abs(actual_pct_change - expected_pct_change) < 0.01, f"Change should match expected"


@pytest.mark.asyncio
async def test_whatif_tool_scale_entity_via_execute(augmented_df):
    """Test scale_entity through the WhatIfTool._execute method"""
    agent = MockAgent(augmented_df)
    tool = WhatIfTool()
    tool.set_parent_agent(agent)
    
    # Calculate expected
    total_rev_baseline = augmented_df['Revenue'].sum()
    belkin_rev = augmented_df.loc[augmented_df['Project'] == "Belkin", "Revenue"].values[0]
    expected_new_total = total_rev_baseline - (belkin_rev * 0.5)
    
    # Construct the input as the LLM would
    input_data = {
        "scenario_description": "reduce_belkin_50pct",
        "possible_actions": [
            {
                "type": "scale_entity",
                "target": "Project",
                "parameters": {
                    "entity_column": "Project",
                    "entities": ["Belkin"],
                    "target_columns": ["Revenue", "Expenses"],
                    "min_pct": -50,
                    "max_pct": -50
                }
            }
        ],
        "algorithm": "greedy",
        "max_actions": 1
    }
    
    result = await tool._execute(**input_data)
    assert result.success, f"Tool execution failed: {result.error}"
    
    res_data = result.result
    print(f"Scenario: {res_data['scenario_name']}")
    print(f"Actions applied: {res_data['actions_count']}")
    print(f"Verdict: {res_data['verdict']}")
    
    # Check that Revenue % change is small
    revenue_change = res_data['comparison']['metrics'].get('Revenue', {})
    pct_change = revenue_change.get('pct_change', 0)
    print(f"Revenue % change: {pct_change:.2f}%")
    
    # The change should be around -1%, NOT -96%!
    assert abs(pct_change) < 5.0, f"Revenue change should be small, got {pct_change:.2f}%"


@pytest.mark.asyncio
async def test_whatif_tool_adjust_metric_group_by(augmented_df):
    """Test adjust_metric with group_by parameter"""
    dsl = WhatIfDSL(augmented_df, "test")
    dsl.can_adjust_metric("Revenue", min_pct=-50, max_pct=-50, group_by="Project")
    
    # Find Belkin action
    belkin_action = next((a for a in dsl.possible_actions if "Belkin" in a.name), None)
    assert belkin_action is not None
    
    # Apply it
    res_df = dsl._apply_action(belkin_action)
    
    # Calculate expected
    total_rev = augmented_df['Revenue'].sum()
    belkin_rev = augmented_df.loc[augmented_df['Project'] == "Belkin", "Revenue"].values[0]
    expected_new_total = total_rev - (belkin_rev * 0.5)
    
    new_total = res_df['Revenue'].sum()
    assert np.isclose(new_total, expected_new_total, atol=1.0)
    
    # It should be small (~1-2%), NOT 96%
    drop_pct = (new_total - total_rev) / total_rev * 100
    assert abs(drop_pct) < 10.0


@pytest.mark.asyncio
async def test_whatif_tool_scale_proportional(augmented_df):
    """Test proportional scaling with group_by"""
    dsl = WhatIfDSL(augmented_df)
    dsl.register_derived_metric("Revenue_per_visits", "Revenue / visits")
    dsl.register_derived_metric("Expenses_per_visits", "Expenses / visits")
    
    dsl.can_scale_proportional(
        "visits", 
        affected_columns=["Revenue", "Expenses"], 
        min_pct=20, 
        max_pct=20, 
        group_by="Project"
    )
    
    # Find Belkin action
    action = next((a for a in dsl.possible_actions if "Belkin" in a.name), None)
    assert action is not None
    
    res_df = dsl._apply_action(action)
    
    # Verify Belkin visits increased 20%
    orig_visits = augmented_df.loc[augmented_df['Project'] == "Belkin", "visits"].values[0]
    new_visits = res_df.loc[res_df['Project'] == "Belkin", "visits"].values[0]
    assert np.isclose(new_visits, orig_visits * 1.2)
    
    # Verify Revenue increased 20% (since linear relationship)
    orig_rev = augmented_df.loc[augmented_df['Project'] == "Belkin", "Revenue"].values[0]
    new_rev = res_df.loc[res_df['Project'] == "Belkin", "Revenue"].values[0]
    assert np.isclose(new_rev, orig_rev * 1.2)
    
    # Verify OTHER projects did NOT change
    orig_flex = augmented_df.loc[augmented_df['Project'] == "Flex", "Revenue"].values[0]
    new_flex = res_df.loc[res_df['Project'] == "Flex", "Revenue"].values[0]
    assert np.isclose(new_flex, orig_flex)


@pytest.mark.asyncio  
async def test_scale_entity_affects_multiple_columns(augmented_df):
    """Test that scale_entity correctly scales multiple target columns"""
    dsl = WhatIfDSL(augmented_df, "test")
    dsl.can_scale_entity(
        entity_column="Project",
        target_columns=["Revenue", "Expenses"],
        entities=["Belkin"],
        min_pct=-50,
        max_pct=-50
    )
    
    action = next((a for a in dsl.possible_actions if "Belkin" in a.name), None)
    assert action is not None
    
    res_df = dsl._apply_action(action)
    
    # Both Revenue and Expenses should be scaled
    orig_rev = augmented_df.loc[augmented_df['Project'] == "Belkin", "Revenue"].values[0]
    orig_exp = augmented_df.loc[augmented_df['Project'] == "Belkin", "Expenses"].values[0]
    
    new_rev = res_df.loc[res_df['Project'] == "Belkin", "Revenue"].values[0]
    new_exp = res_df.loc[res_df['Project'] == "Belkin", "Expenses"].values[0]
    
    assert np.isclose(new_rev, orig_rev * 0.5)
    assert np.isclose(new_exp, orig_exp * 0.5)
    
    # Other projects should be unchanged
    orig_flex_rev = augmented_df.loc[augmented_df['Project'] == "Flex", "Revenue"].values[0]
    new_flex_rev = res_df.loc[res_df['Project'] == "Flex", "Revenue"].values[0]
    assert np.isclose(new_flex_rev, orig_flex_rev)

