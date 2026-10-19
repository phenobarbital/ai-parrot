"""Model and DuckDB fixtures shared by semantic-layer test modules."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    """Copy model fixtures and the Ossie document into a temporary directory."""
    destination = tmp_path / "models"
    shutil.copytree(FIXTURES / "models", destination)
    shutil.copy(FIXTURES / "ossie/orders.ossie.json", destination / "orders_ossie.ossie.json")
    return destination


@pytest.fixture
def duckdb_warehouse(tmp_path: Path) -> str:
    """Create a deterministic DuckDB warehouse with order and customer data."""
    duckdb = pytest.importorskip("duckdb")
    path = str(tmp_path / "wh.duckdb")
    connection = duckdb.connect(path)
    try:
        connection.execute("CREATE SCHEMA sales")
        connection.execute("CREATE SCHEMA dim")
        connection.execute(
            "CREATE TABLE sales.orders (region VARCHAR, tenant_id VARCHAR, order_date DATE, "
            "amount DECIMAL(12, 2), customer_id BIGINT)"
        )
        connection.execute("CREATE TABLE dim.customers (id BIGINT, email VARCHAR, salary DECIMAL(12, 2))")
        connection.execute(
            "INSERT INTO sales.orders VALUES "
            "('EU', 'tenant-a', DATE '2026-01-10', 10.00, 1), "
            "('US', 'tenant-b', DATE '2026-02-10', 20.00, 2), "
            "('EU', 'tenant-a', DATE '2026-03-10', 30.00, 1)"
        )
        connection.execute(
            "INSERT INTO dim.customers VALUES (1, 'a@example.test', 50000), (2, 'b@example.test', 60000)"
        )
    finally:
        connection.close()
    return path


@pytest.fixture
def loaded_models(models_dir: Path) -> dict[str, Any]:
    """Load the copied semantic models through the production loader."""
    pytest.importorskip("sidemantic")
    from parrot.semantic.loader import SemanticModelLoader

    return SemanticModelLoader(models_dir, driver="duckdb").load()
