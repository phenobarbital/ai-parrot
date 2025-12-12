"""
Complete Usage Example: WhatIfTool with PandasAgent
Shows how to integrate and use the What-If analysis tool
"""

import asyncio
import pandas as pd
import numpy as np
from parrot.bots.data import PandasAgent
from parrot.clients.factory import LLMFactory
from parrot.tools.whatif import integrate_whatif_tool
from parrot.tools.whatif import (
    WhatIfDSL,
    WhatIfInput,
    WhatIfObjective,
    WhatIfConstraint,
    WhatIfAction,
    DerivedMetric
)


async def main():
    """
    Complete example of using WhatIfTool with PandasAgent
    """

    # ===== Step 1: Create Sample Data =====
    print("=" * 70)
    print("Step 1: Creating Sample Data")
    print("=" * 70)

    # Sample data with visits, revenue, expenses by region
    np.random.seed(42)
    regions = ['North', 'South', 'East', 'West'] * 25

    data = {
        'region': regions,
        'visits': np.random.randint(100, 500, 100),
        'revenue': np.random.randint(50000, 150000, 100),
        'expenses': np.random.randint(30000, 80000, 100),
        'headcount': np.random.randint(10, 50, 100),
    }

    df = pd.DataFrame(data)

    # Add some derived calculations manually for reference
    df['revenue_per_visit'] = df['revenue'] / df['visits']
    df['expenses_per_visit'] = df['expenses'] / df['visits']

    print(f"\nDataFrame shape: {df.shape}")
    print(f"Columns: {list(df.columns)}")
    print("\nSample data:")
    print(df.head(10))
    print("\nBaseline totals:")
    print(f"  Total revenue: ${df['revenue'].sum():,.2f}")
    print(f"  Total expenses: ${df['expenses'].sum():,.2f}")
    print(f"  Total visits: {df['visits'].sum():,}")
    print(f"  Total headcount: {df['headcount'].sum():,}")

    # ===== Step 2: Initialize PandasAgent =====
    print("\n" + "=" * 70)
    print("Step 2: Initialize PandasAgent")
    print("=" * 70)

    # Create LLM client
    client = LLMFactory.create(
        llm='google',
        model='gemini-2.5-pro',
        # llm="anthropic",
        # model="claude-sonnet-4-5",
    )

    # Create PandasAgent
    agent = PandasAgent(
        llm=client,
        name="FinancialAnalyst",
        description="Expert data analyst specializing in financial scenarios",
        df={'regional_data': df},  # Load the DataFrame
        enable_cache=False
    )

    print("✅ PandasAgent created")
    print(f"   Loaded DataFrames: {list(agent.dataframes.keys())}")

    # ===== Step 3: Integrate WhatIfTool =====
    print("\n" + "=" * 70)
    print("Step 3: Integrate WhatIfTool")
    print("=" * 70)

    whatif_tool = integrate_whatif_tool(agent)

    await agent.configure()

    print("✅ WhatIfTool integrated")
    print(f"   Tool name: {whatif_tool.name}")
    print(f"   Available tools: {[t.name for t in agent.tools]}")

    # ===== Step 4: Example Queries =====
    print("\n" + "=" * 70)
    print("Step 4: Running What-If Scenarios")
    print("=" * 70)

    # Example 1: Simple Impact Analysis
    print("\n--- Example 1: What if we close the West region? ---")
    response1 = await agent.ask(
        "What if we close the West region? Show me the impact on revenue and expenses."
    )
    print(f"\nResponse:\n{response1.response}")

    # Example 2: Proportional Scaling
    print("\n\n--- Example 2: What if we increase visits by 30%? ---")
    response2 = await agent.ask(
        "What if we increase visits by 30%? How would that affect revenue and expenses? "
        "Assume revenue and expenses scale proportionally with visits."
    )
    print(f"\nResponse:\n{response2.response}")

    # Example 3: Optimization with Constraints
    print("\n\n--- Example 3: Reduce expenses without hurting revenue ---")
    response3 = await agent.ask(
        "I need to reduce total expenses to 4.5 million, but revenue cannot drop "
        "by more than 5%. What's the best combination of actions to achieve this?"
    )
    print(f"\nResponse:\n{response3.response}")

    # Example 4: Regional Scaling
    print("\n\n--- Example 4: Increase visits in specific region ---")
    response4 = await agent.ask(
        "What if we increase visits by 50% in the North region only? "
        "Show me how revenue and expenses would change."
    )
    print(f"\nResponse:\n{response4.response}")

    # Example 5: Multi-objective Optimization
    print("\n\n--- Example 5: Maximize profit with constraints ---")
    response5 = await agent.ask(
        "Find the best scenario to maximize profit while keeping total headcount "
        "above 1500 and ensuring the expenses-to-revenue ratio stays under 60%."
    )
    print(f"\nResponse:\n{response5.response}")

    # ===== Step 5: Programmatic Tool Usage =====
    print("\n" + "=" * 70)
    print("Step 5: Direct Tool Usage (Programmatic)")
    print("=" * 70)
    # Example: Direct tool call
    tool_input = WhatIfInput(
        scenario_description="increase_visits_20pct",
        objectives=[],
        constraints=[],
        possible_actions=[
            WhatIfAction(
                type="scale_proportional",
                target="visits",
                parameters={
                    "min_pct": 20,
                    "max_pct": 20,
                    "affected_columns": ["revenue", "expenses"],
                    "by_region": False
                }
            )
        ],
        derived_metrics=[
            DerivedMetric(
                name="revenue_per_visit",
                formula="revenue / visits",
                description="Average revenue per visit"
            ),
            DerivedMetric(
                name="expenses_per_visit",
                formula="expenses / visits",
                description="Average expenses per visit"
            )
        ],
        max_actions=1,
        algorithm="greedy",
        df_name="regional_data"
    )

    result = await whatif_tool._execute(**tool_input.dict())

    print("\nDirect Tool Call Result:")
    if result.success:
        print(result.result['visualization'])
        print(f"\n{result.result['comparison_table']}")
    else:
        print(f"Error: {result.error}")

    # ===== Step 6: Compare Cached Scenarios =====
    print("\n" + "=" * 70)
    print("Step 6: Cached Scenarios")
    print("=" * 70)

    print(f"\nCached scenarios: {list(whatif_tool.scenarios_cache.keys())}")

    # You can access cached scenarios programmatically
    for scenario_id, scenario_result in whatif_tool.scenarios_cache.items():
        print(f"\n{scenario_id}:")
        print(f"  Actions taken: {len(scenario_result.actions)}")
        print(f"  Derived metrics: {list(scenario_result.calculator.formulas.keys())}")


# ===== Additional Helper: Create Scenario Manually =====

async def manual_scenario_example():
    """
    Example of using the DSL directly (without LLM)
    """
    # Create sample data
    df = pd.DataFrame({
        'region': ['North', 'South', 'East', 'West'] * 10,
        'revenue': np.random.randint(50000, 150000, 40),
        'expenses': np.random.randint(30000, 80000, 40),
        'visits': np.random.randint(100, 500, 40),
    })

    # Build scenario using DSL
    scenario = (
        WhatIfDSL(df, name="reduce_expenses_preserve_revenue")
        # Define derived metrics
        .register_derived_metric("revenue_per_visit", "revenue / visits")
        .register_derived_metric("expenses_per_visit", "expenses / visits")
        .register_derived_metric("profit", "revenue - expenses")
        # Initialize optimizer
        .initialize_optimizer()
        # Set objectives
        .target("expenses", 2000000, weight=2.0)
        # Set constraints
        .constrain_change("revenue", max_pct=5.0)
        # Define possible actions
        .can_close_regions()
        .can_adjust_metric("expenses", min_pct=-40, max_pct=0, by_region=True)
        # Solve
        .solve(max_actions=3, algorithm="greedy")
    )

    # View results
    print(scenario.visualize())

    # Get comparison data
    comparison = scenario.compare()
    print("\nDetailed comparison:")
    print(comparison)

    return scenario


if __name__ == "__main__":
    # Run main example
    asyncio.run(main())

    # Uncomment to run manual DSL example
    # asyncio.run(manual_scenario_example())
