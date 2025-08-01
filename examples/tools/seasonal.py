import asyncio
import base64
from pathlib import Path
import pandas as pd
import numpy as np
from parrot.tools.seasonaldetection import (
    SeasonalDetectionTool
)


# Example usage and testing
async def example_usage():
    """Example of how to use the CorrelationAnalysisTool."""
    # Create sample sales and foot traffic data
    np.random.seed(42)
    dates = pd.date_range('2023-01-01', periods=52, freq='W')

    # Simulate foot traffic with some trend and seasonality
    foot_traffic = 1000 + np.random.normal(0, 100, 52) + np.sin(np.arange(52) * 2 * np.pi / 52) * 200

    # Sales correlated with foot traffic + some noise
    sales = foot_traffic * 0.8 + np.random.normal(0, 50, 52)

    # Census/demographic data (some correlated, some not)
    sample_data = {
        'date': dates,
        'sales': sales,
        'foot_traffic': foot_traffic,
        'avg_age': 35 + np.random.normal(0, 5, 52),
        'income_median': 50000 + np.random.normal(0, 5000, 52),
        'population_density': 2000 + np.random.normal(0, 200, 52),
        'temperature': 20 + 15 * np.sin(np.arange(52) * 2 * np.pi / 52) + np.random.normal(0, 3, 52),
        'marketing_spend': np.random.exponential(500, 52),
        'competitor_stores': np.random.poisson(3, 52),
        'unemployment_rate': 5 + np.random.normal(0, 0.5, 52)
    }

    # Add some correlation between sales and marketing spend
    sample_data['sales'] = sample_data['sales'] + sample_data['marketing_spend'] * 0.1

    df = pd.DataFrame(sample_data)

    # Initialize the tool
    tool = SeasonalDetectionTool()

    result = await tool.execute(
        dataframe=df,
        title="Weekly Sales and Foot Traffic Analysis",
        time_column='date',
        value_column='foot_traffic',
        confidence_level=0.05,
        generate_plots=True,
        perform_decomposition=True,
        remove_trend=True  # Also test after detrending
    )
    # Access results
    print(result)
    print(f"Status: {result.status}")
    print(f"Overall conclusion: {result.result['overall_conclusion']['conclusion']}")
    print(f"Recommendation: {result.result['overall_conclusion']['recommendation']}")

if __name__ == "__main__":
    asyncio.run(example_usage())
