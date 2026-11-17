"""Deterministic warehouse and model helpers for semantic tests."""

from pathlib import Path
import shutil

import pytest

from parrot.semantic.loader import SemanticModelLoader

_FIXTURES = Path(__file__).parent / "fixtures" / "models"


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    """Copy own-format fixture definitions into an isolated directory."""
    destination = tmp_path / "models"
    shutil.copytree(_FIXTURES, destination)
    (destination / "customers.policy.yaml").write_text(
        "governed: false\nroles: {admin: {metrics: '*', dimensions: '*', usage: '*'}}\n",
        encoding="utf-8",
    )
    return destination


@pytest.fixture
def loaded_models(models_dir: Path) -> dict[str, object]:
    """Load the same typed model snapshot used by compiler/governance tests."""
    return SemanticModelLoader(models_dir, driver="duckdb").load()


@pytest.fixture
def duckdb_warehouse(tmp_path: Path) -> Path:
    """Seed sales.orders and dim.customers in a real file with tenant subsets."""
    duckdb = pytest.importorskip("duckdb")
    warehouse = tmp_path / "warehouse.duckdb"
    connection = duckdb.connect(str(warehouse))
    try:
        connection.execute("CREATE SCHEMA sales")
        connection.execute("CREATE SCHEMA dim")
        connection.execute(
            "CREATE TABLE sales.orders (id INTEGER, customer_id INTEGER, tenant_id VARCHAR, region VARCHAR, order_date TIMESTAMP, amount DECIMAL)"
        )
        connection.execute("CREATE TABLE dim.customers (id INTEGER, tenant_id VARCHAR, email VARCHAR, salary DECIMAL)")
        connection.execute(
            "INSERT INTO sales.orders VALUES (1, 10, 'tenant-a', 'eu', '2026-01-01', 12.50), (2, 20, 'tenant-b', 'us', '2026-01-02', 25.00)"
        )
        connection.execute(
            "INSERT INTO dim.customers VALUES (10, 'tenant-a', 'a@example.test', 100.00), (20, 'tenant-b', 'b@example.test', 200.00)"
        )
    finally:
        connection.close()
    return warehouse
