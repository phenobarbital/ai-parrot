"""Shared fixtures for WorkingMemoryToolkit tests."""
import numpy as np
import pandas as pd
import pytest

from parrot.tools.working_memory import WorkingMemoryToolkit


@pytest.fixture
def census_df() -> pd.DataFrame:
    """Generate a synthetic US Census-style DataFrame."""
    np.random.seed(42)
    n = 500
    states = np.random.choice(["CA", "TX", "NY", "FL", "IL"], n)
    return pd.DataFrame({
        "COUNTY_FIPS": [f"{s}_{i:03d}" for i, s in enumerate(states)],
        "STATE": states,
        "POPULATION": np.random.randint(5000, 500000, n),
        "MEDIAN_EARNINGS_2023_25plus_yrs": np.random.uniform(25000, 120000, n).round(2),
        "POVERTY_RATE": np.random.uniform(0.05, 0.35, n).round(4),
        "BACHELORS_DEGREE_PCT": np.random.uniform(0.10, 0.65, n).round(4),
    })


@pytest.fixture
def sales_df() -> pd.DataFrame:
    """Generate a synthetic sales DataFrame."""
    np.random.seed(42)
    n = 500
    states = np.random.choice(["CA", "TX", "NY", "FL", "IL"], n)
    return pd.DataFrame({
        "FIPS_CODE": [f"{s}_{i:03d}" for i, s in enumerate(states)],
        "TOTAL_SALES": np.random.uniform(10000, 5000000, n).round(2),
        "NUM_TRANSACTIONS": np.random.randint(50, 10000, n),
        "AVG_ORDER_VALUE": np.random.uniform(15, 250, n).round(2),
    })


@pytest.fixture
def toolkit(census_df: pd.DataFrame, sales_df: pd.DataFrame) -> WorkingMemoryToolkit:
    """Create a WorkingMemoryToolkit with pre-loaded census and sales DataFrames."""
    tk = WorkingMemoryToolkit(
        session_id="test-session",
        max_rows=5,
        max_cols=20,
    )
    # Store synchronously via catalog for setup
    tk._catalog.put("census_raw", census_df, description="US Census")
    tk._catalog.put("sales_raw", sales_df, description="Sales data")
    return tk
