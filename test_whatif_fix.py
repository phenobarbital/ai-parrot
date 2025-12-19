#!/usr/bin/env python3
"""
Test script to verify the WhatIf Tool fix for closing projects
"""
import pandas as pd
from parrot.tools.whatif import WhatIfTool

# Create sample data similar to the user's scenario
data = {
    'project': ['Belkin', 'Belkin', 'Acme', 'Acme', 'TechCo', 'TechCo'],
    'month': ['Jan', 'Feb', 'Jan', 'Feb', 'Jan', 'Feb'],
    'year': [2024, 2024, 2024, 2024, 2024, 2024],
    'quarter': ['Q1', 'Q1', 'Q1', 'Q1', 'Q1', 'Q1'],
    'revenue': [100000, 120000, 80000, 90000, 150000, 160000],
    'expenses': [60000, 70000, 50000, 55000, 90000, 95000],
}

df = pd.DataFrame(data)

# Mock parent agent with dataframes
class MockAgent:
    def __init__(self):
        self.dataframes = {'troc_projects_financials': df}

# Initialize the WhatIf tool
tool = WhatIfTool()
tool.set_parent_agent(MockAgent())

# Test the scenario: "What if we close the Belkin project?"
print("Testing WhatIf Tool with 'close Belkin project' scenario...")
print(f"Original DataFrame:\n{df}\n")
print(f"Total Revenue (before): {df['revenue'].sum()}")
print(f"Total Expenses (before): {df['expenses'].sum()}\n")

# Create the input for the tool
import asyncio

async def test_whatif():
    input_data = {
        "scenario_description": "Closing Belkin Project",
        "df_name": "troc_projects_financials",
        "objectives": [],
        "constraints": [],
        "possible_actions": [
            {
                "type": "exclude_values",
                "target": "project",
                "parameters": {
                    "column": "project",
                    "values": ["Belkin"]
                }
            }
        ],
        "derived_metrics": [
            {
                "name": "profit",
                "formula": "revenue - expenses",
                "description": "Total profit"
            }
        ],
        "max_actions": 1,
        "algorithm": "greedy"
    }
    
    result = await tool._execute(**input_data)
    
    if result.success:
        print("✅ SUCCESS! The tool executed without errors.")
        print(f"\nResult: {result.result}")
        
        # Show comparison
        if 'comparison' in result.result:
            print("\n📊 Comparison:")
            comparison = result.result['comparison']
            for metric, values in comparison.items():
                print(f"  {metric}:")
                for key, val in values.items():
                    print(f"    {key}: {val}")
    else:
        print(f"❌ FAILED: {result.error}")
        return False
    
    return True

# Run the async test
success = asyncio.run(test_whatif())

if success:
    print("\n✅ Test passed! The WhatIf Tool now correctly handles closing projects.")
else:
    print("\n❌ Test failed! There's still an issue.")
