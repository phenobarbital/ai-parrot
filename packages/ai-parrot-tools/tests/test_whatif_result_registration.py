"""Tests for publishing a scenario's result DataFrame back to the catalog.

``simulate`` and ``quick_impact`` register their mutated DataFrame so a
follow-up question can query it. That registration used to ``await``
``DatasetManager.add_dataframe``, which is synchronous: the call itself went
through, then awaiting its ``str`` return raised ``TypeError`` into a blanket
``except: pass``.

The harm was not a missing dataset — it was that the same blanket handler
swallowed *genuine* failures while ``simulate`` still told the model
"Result DataFrame registered as ...". These tests pin the honest contract:
register when possible, say so only when true, and never let a catalog
problem break the analysis itself.
"""
import pandas as pd
import pytest
from parrot_tools.whatif import DerivedMetric, WhatIfAction
from parrot_tools.whatif_toolkit import WhatIfToolkit

EBITDA = DerivedMetric(name="ebitda", formula="revenue - payroll - expenses")

BUMP_ACME = WhatIfAction(
    type="scale_entity",
    target="customer",
    parameters={
        "entity_column": "customer",
        "entities": ["Acme"],
        "target_columns": ["expenses"],
        "min_pct": 15,
        "max_pct": 15,
    },
)


@pytest.fixture
def clients_df() -> pd.DataFrame:
    """Two clients with revenue/payroll/expenses."""
    return pd.DataFrame(
        {
            "customer": ["Acme", "Umbrella"],
            "revenue": [1_200_000.0, 2_100_000.0],
            "payroll": [400_000.0, 700_000.0],
            "expenses": [350_000.0, 640_000.0],
        }
    )


class SyncManager:
    """Catalog whose add_dataframe is synchronous, like DatasetManager."""

    def __init__(self, dataframes: dict) -> None:
        self.stored = dict(dataframes)

    def get_active_dataframes(self) -> dict:
        """Return the catalog contents."""
        return self.stored

    def _resolve_name(self, identifier: str) -> str:
        """Names only; no aliases in this stub."""
        return identifier

    def add_dataframe(self, name=None, df=None, description=None) -> str:
        """Store the dataset and return its name (never a coroutine)."""
        self.stored[name] = df
        return name


class AsyncManager(SyncManager):
    """Duck-typed catalog whose add_dataframe is a coroutine."""

    async def add_dataframe(self, name=None, df=None, description=None) -> str:
        """Store the dataset asynchronously."""
        self.stored[name] = df
        return name


class BrokenManager(SyncManager):
    """Catalog that cannot accept the result."""

    def add_dataframe(self, name=None, df=None, description=None):
        """Always fail."""
        raise RuntimeError("catalog unavailable")


class RecordingPandasTool:
    """Stand-in for PythonPandasTool, recording REPL syncs."""

    def __init__(self) -> None:
        self.syncs = 0

    def sync_from_manager(self) -> None:
        """Count a sync."""
        self.syncs += 1


def scenario_id(described: str) -> str:
    """Pull the scenario id out of describe_scenario output."""
    return next(token for token in described.split() if token.startswith("sc_"))


async def run_simulation(toolkit: WhatIfToolkit) -> str:
    """Drive one scenario through describe -> add_actions -> simulate."""
    sid = scenario_id(
        await toolkit.describe_scenario("clients", "registration probe", [EBITDA])
    )
    await toolkit.add_actions(sid, [BUMP_ACME])
    return await toolkit.simulate(sid, max_actions=1)


# ── the happy path ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_simulate_registers_the_mutated_dataframe(clients_df):
    """The registered dataset holds the scenario's values, not the baseline."""
    manager = SyncManager({"clients": clients_df})
    toolkit = WhatIfToolkit(dataset_manager=manager)

    output = await run_simulation(toolkit)

    stored = [name for name in manager.stored if name.startswith("whatif_")]
    assert len(stored) == 1
    result_df = manager.stored[stored[0]]
    # Acme's expenses moved by +15%; Umbrella's did not.
    assert float(result_df.loc[result_df["customer"] == "Acme", "expenses"].iloc[0]) == (
        pytest.approx(350_000.0 * 1.15)
    )
    assert f"registered as: '{stored[0]}'" in output


@pytest.mark.asyncio
async def test_an_async_manager_is_awaited(clients_df):
    """A duck-typed async catalog still receives the result."""
    manager = AsyncManager({"clients": clients_df})
    toolkit = WhatIfToolkit(dataset_manager=manager)

    output = await run_simulation(toolkit)

    assert any(name.startswith("whatif_") for name in manager.stored)
    assert "Result DataFrame registered as" in output


@pytest.mark.asyncio
async def test_quick_impact_reports_the_dataset_it_registered(clients_df):
    """A registered dataset nobody is told about cannot be queried."""
    manager = SyncManager({"clients": clients_df})
    toolkit = WhatIfToolkit(dataset_manager=manager)

    output = await toolkit.quick_impact(
        df_name="clients",
        action_description="Acme expenses +15%",
        action_type="scale_entity",
        target="customer",
        parameters={
            "entity_column": "customer",
            "entities": ["Acme"],
            "target_columns": ["expenses"],
            "min_pct": 15,
            "max_pct": 15,
        },
    )

    assert "whatif_quick_scale_entity_result" in manager.stored
    assert "whatif_quick_scale_entity_result" in output


@pytest.mark.asyncio
async def test_the_pandas_repl_is_synced(clients_df):
    """Registering is pointless if the REPL namespace never sees it."""
    manager = SyncManager({"clients": clients_df})
    pandas_tool = RecordingPandasTool()
    toolkit = WhatIfToolkit(dataset_manager=manager, pandas_tool=pandas_tool)

    await run_simulation(toolkit)

    assert pandas_tool.syncs == 1


# ── failure must be honest, not fatal ────────────────────────────────────


@pytest.mark.asyncio
async def test_failed_registration_is_not_announced(clients_df):
    """The regression: never claim a dataset the model cannot then find."""
    toolkit = WhatIfToolkit(dataset_manager=BrokenManager({"clients": clients_df}))

    output = await run_simulation(toolkit)

    assert "Result DataFrame registered as" not in output


@pytest.mark.asyncio
async def test_failed_registration_still_returns_the_analysis(clients_df):
    """A catalog problem must not cost the user their answer."""
    toolkit = WhatIfToolkit(dataset_manager=BrokenManager({"clients": clients_df}))

    output = await run_simulation(toolkit)

    assert "Simulation complete" in output
    assert "ebitda" in output


@pytest.mark.asyncio
async def test_failed_registration_is_logged(clients_df, caplog):
    """The swallowed error becomes a visible warning."""
    toolkit = WhatIfToolkit(dataset_manager=BrokenManager({"clients": clients_df}))

    with caplog.at_level("WARNING"):
        await run_simulation(toolkit)

    assert any("could not register result dataset" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_no_manager_means_no_claim(clients_df):
    """Without a catalog there is nothing to register and nothing to claim."""

    class Host:
        """Parent agent with only a dataframes registry."""

        def __init__(self) -> None:
            self.dataframes = {"clients": clients_df}

    toolkit = WhatIfToolkit()
    toolkit._parent_agent = Host()

    output = await run_simulation(toolkit)

    assert "Simulation complete" in output
    assert "Result DataFrame registered as" not in output
