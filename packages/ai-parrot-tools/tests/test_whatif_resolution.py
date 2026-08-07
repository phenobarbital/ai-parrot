"""Tests for WhatIfToolkit dataset resolution (names, aliases, casing).

Every what-if tool documents ``df_name`` as "name or alias", and PandasAgent
tells the LLM to refer to datasets by their alias (``df1``, ``df2``...). Alias
lookups therefore have to work, or an LLM that follows the prompt is always
told the dataset does not exist.

These tests pin all three wiring shapes the toolkit is used in: a standalone
DatasetManager, a manager owned by the parent agent, and a bare agent with no
manager at all.
"""
import pandas as pd
import pytest
from parrot.tools.dataset_manager import DatasetManager
from parrot_tools.whatif_toolkit import WhatIfToolkit


@pytest.fixture
def clients_df() -> pd.DataFrame:
    """A small client P&L frame."""
    return pd.DataFrame(
        {
            "customer": ["Acme", "Globex"],
            "revenue": [1_200_000.0, 850_000.0],
            "payroll": [400_000.0, 300_000.0],
            "expenses": [350_000.0, 260_000.0],
        }
    )


@pytest.fixture
def manager(clients_df: pd.DataFrame) -> DatasetManager:
    """A DatasetManager holding the frame under the name 'clients'."""
    dm = DatasetManager()
    dm.add_dataframe(name="clients", df=clients_df, description="client P&L")
    return dm


class BareAgent:
    """Parent agent exposing only a `dataframes` registry (no manager)."""

    def __init__(self, dataframes: dict) -> None:
        self.dataframes = dataframes


class AgentWithManager:
    """Parent agent that keeps its DatasetManager private, like PandasAgent."""

    def __init__(self, dataframes: dict, dm: DatasetManager) -> None:
        self.dataframes = dataframes
        self._dataset_manager = dm


@pytest.mark.asyncio
async def test_resolves_by_name_from_manager_alone(manager, clients_df):
    """A DatasetManager with no parent agent can resolve a dataset."""
    toolkit = WhatIfToolkit(dataset_manager=manager)

    name, df = await toolkit._resolve_dataframe("clients")

    assert name == "clients"
    assert df.equals(clients_df)


@pytest.mark.asyncio
async def test_resolves_by_alias_from_manager_alone(manager, clients_df):
    """The alias the agent advertises to the LLM resolves to the dataset."""
    alias = manager._get_alias_map()["clients"]
    toolkit = WhatIfToolkit(dataset_manager=manager)

    name, df = await toolkit._resolve_dataframe(alias)

    # The canonical name is returned, never the alias, so result labels and
    # registered result names stay stable.
    assert name == "clients"
    assert df.equals(clients_df)


@pytest.mark.asyncio
async def test_resolves_by_alias_via_parent_agent_manager(manager, clients_df):
    """PandasAgent keeps its manager private; the toolkit must still find it."""
    agent = AgentWithManager({"clients": clients_df}, manager)
    toolkit = WhatIfToolkit()
    toolkit._parent_agent = agent

    name, df = await toolkit._resolve_dataframe("df1")

    assert name == "clients"
    assert df.equals(clients_df)


@pytest.mark.asyncio
async def test_resolution_is_case_insensitive(manager, clients_df):
    """A differently-cased name still resolves."""
    toolkit = WhatIfToolkit(dataset_manager=manager)

    name, _ = await toolkit._resolve_dataframe("CLIENTS")

    assert name == "clients"


@pytest.mark.asyncio
async def test_resolves_from_parent_agent_without_manager(clients_df):
    """The plain `agent.dataframes` fallback keeps working."""
    toolkit = WhatIfToolkit()
    toolkit._parent_agent = BareAgent({"clients": clients_df})

    name, df = await toolkit._resolve_dataframe("clients")

    assert name == "clients"
    assert df.equals(clients_df)


@pytest.mark.asyncio
async def test_unknown_dataset_lists_names_and_aliases(manager, clients_df):
    """The error tells the LLM what it could have asked for instead."""
    agent = AgentWithManager({"clients": clients_df}, manager)
    toolkit = WhatIfToolkit()
    toolkit._parent_agent = agent

    with pytest.raises(ValueError) as excinfo:
        await toolkit._resolve_dataframe("ghost")

    message = str(excinfo.value)
    assert "ghost" in message
    assert "clients" in message
    assert "df1" in message


@pytest.mark.asyncio
async def test_no_datasets_reports_clearly():
    """With nothing loaded the message says so rather than listing nothing."""
    toolkit = WhatIfToolkit()

    with pytest.raises(ValueError, match="No datasets are loaded"):
        await toolkit._resolve_dataframe("clients")


@pytest.mark.asyncio
async def test_broken_manager_falls_back_to_parent_agent(clients_df):
    """A manager that raises must not break resolution."""

    class BrokenManager:
        """Manager whose every accessor raises."""

        def get_active_dataframes(self):
            raise RuntimeError("boom")

        def _resolve_name(self, identifier):
            raise RuntimeError("boom")

        def _get_alias_map(self):
            raise RuntimeError("boom")

    toolkit = WhatIfToolkit(dataset_manager=BrokenManager())
    toolkit._parent_agent = BareAgent({"clients": clients_df})

    name, df = await toolkit._resolve_dataframe("clients")

    assert name == "clients"
    assert df.equals(clients_df)


@pytest.mark.asyncio
async def test_quick_impact_accepts_an_alias(manager):
    """End to end: the fast-path tool works when called with the alias."""
    toolkit = WhatIfToolkit(dataset_manager=manager)

    result = await toolkit.quick_impact(
        df_name="df1",
        action_description="Acme expenses +15%",
        action_type="scale_entity",
        target="customer",
        parameters={
            "entity_column": "customer",
            "entities": ["Acme"],
            "target_columns": ["expenses"],
            "min_pct": 15,
            "max_pct": 15,
            "derived_metrics": [
                {"name": "ebitda", "formula": "revenue - payroll - expenses"}
            ],
        },
    )

    # 610,000 baseline expenses + 15% of Acme's 350,000 = 662,500
    assert "662,500.00" in result
    assert "Error" not in result
