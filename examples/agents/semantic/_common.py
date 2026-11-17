"""Shared scaffolding for the governed semantic-layer examples (FEAT-769).

These helpers are used by the four example agents in this directory. The relocated
``agent_semantic_example.py`` deliberately keeps its own private copies — see the spec
section "Why ``_common.py`` does not absorb the moved example".
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from parrot.auth import DataPlanePolicyGuard, PermissionContext, RlsRegistry, UserSession
from parrot.semantic.context import SemanticRequestIdentity
from parrot.semantic.toolkit import SemanticLayerToolkit

LOGGER = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent / "models"
MODELS_UNGOVERNED_DIR = Path(__file__).parent / "models_ungoverned"

#: Connection of the `orders` model (models/orders.policy.yaml).
CONNECTION_ENV = "PARROT_SEMANTIC_CONN_SEMANTIC_EXAMPLE_DATABASE"
#: Connection of the `customers` model (models/customers.policy.yaml) — a SECOND warehouse.
CONNECTION_ENV_DIM = "PARROT_SEMANTIC_CONN_SEMANTIC_DIM_DATABASE"

_ALLOWED_DRIVER = "duckdb"
_ALLOWED_TABLES = ("duckdb:sales.orders", "duckdb:dim.customers")
_ALLOWED_ROLE = "analyst"
_WAREHOUSE_NAME = "semantic-example.duckdb"
_DIM_WAREHOUSE_NAME = "semantic-dim.duckdb"


class ExamplePolicyEvaluator:
    """Explicit allow-list PBAC evaluator plugged into the real DataPlanePolicyGuard.

    No gate is bypassed: only an ``analyst`` subject may connect to DuckDB and read the
    two fixture tables. ``revoke()`` withdraws the grant so later decisions fail closed.
    Production hosts use the navigator-auth ``PolicyEvaluator`` instead.
    """

    def __init__(self, *, allowed_role: str = _ALLOWED_ROLE) -> None:
        """Start with the fixture grant enabled for ``allowed_role``."""
        self.allowed_role = allowed_role
        self.revoked = False

    def revoke(self) -> None:
        """Withdraw the fixture grant for every subsequent decision."""
        self.revoked = True

    def _permits(self, eval_ctx: Any) -> bool:
        """Return whether the evaluated subject still holds the fixture grant."""
        userinfo = getattr(eval_ctx, "store", {}).get("userinfo", {})
        return not self.revoked and self.allowed_role in userinfo.get("roles", [])

    def check_access(self, eval_ctx: Any, resource_type: str, resource: str, action: str, env: Any) -> SimpleNamespace:
        """Allow only ``driver:connect`` on the DuckDB driver for the allowed role."""
        del env
        allowed = (
            self._permits(eval_ctx)
            and resource_type == "driver"
            and resource == _ALLOWED_DRIVER
            and action == "driver:connect"
        )
        return SimpleNamespace(allowed=allowed)

    def filter_resources(
        self, eval_ctx: Any, resource_type: str, resources: list[str], action: str, env: Any
    ) -> SimpleNamespace:
        """Return only fixture tables for an allowed ``table:read`` subject."""
        del env
        if not self._permits(eval_ctx) or resource_type != "table" or action != "table:read":
            return SimpleNamespace(allowed=[])
        return SimpleNamespace(allowed=[resource for resource in resources if resource in _ALLOWED_TABLES])


def build_guard(evaluator: ExamplePolicyEvaluator, rls_registry: RlsRegistry) -> DataPlanePolicyGuard:
    """Build the core data-plane guard around the example evaluator."""
    return DataPlanePolicyGuard(evaluator=evaluator, rls_registry=rls_registry)


def build_warehouse(directory: Path) -> Path:
    """Create the deterministic DuckDB warehouse for the ``orders`` connection.

    Args:
        directory: Directory the warehouse file is created in; created if absent.

    Returns:
        The path of the created warehouse file.
    """
    import duckdb

    directory.mkdir(parents=True, exist_ok=True)
    warehouse = directory / _WAREHOUSE_NAME
    connection = duckdb.connect(str(warehouse))
    try:
        connection.execute("CREATE SCHEMA sales")
        connection.execute("CREATE SCHEMA dim")
        connection.execute(
            "CREATE TABLE sales.orders (id INTEGER, customer_id INTEGER, tenant_id VARCHAR, "
            "region VARCHAR, order_date TIMESTAMP, amount DECIMAL)"
        )
        connection.execute("CREATE TABLE dim.customers (id INTEGER, tenant_id VARCHAR, email VARCHAR, salary DECIMAL)")
        connection.execute(
            "INSERT INTO sales.orders VALUES "
            "(1, 10, 'tenant-a', 'eu', '2026-01-01', 12.50), "
            "(2, 20, 'tenant-b', 'us', '2026-01-02', 25.00)"
        )
        connection.execute(
            "INSERT INTO dim.customers VALUES "
            "(10, 'tenant-a', 'a@example.test', 100.00), "
            "(20, 'tenant-b', 'b@example.test', 200.00)"
        )
    finally:
        connection.close()
    return warehouse


def build_dim_warehouse(directory: Path) -> Path:
    """Create the second warehouse, holding only ``dim.customers``.

    Args:
        directory: Directory the warehouse file is created in; created if absent.

    Returns:
        The path of the created warehouse file.
    """
    import duckdb

    directory.mkdir(parents=True, exist_ok=True)
    warehouse = directory / _DIM_WAREHOUSE_NAME
    connection = duckdb.connect(str(warehouse))
    try:
        connection.execute("CREATE SCHEMA dim")
        connection.execute("CREATE TABLE dim.customers (id INTEGER, tenant_id VARCHAR, email VARCHAR, salary DECIMAL)")
        connection.execute(
            "INSERT INTO dim.customers VALUES "
            "(10, 'tenant-a', 'a@example.test', 100.00), "
            "(20, 'tenant-b', 'b@example.test', 200.00)"
        )
    finally:
        connection.close()
    return warehouse


@contextmanager
def connection_env(warehouse: Path, dim_warehouse: Path | None = None) -> Iterator[None]:
    """Bind example connection variables only for the enclosed block.

    Args:
        warehouse: Warehouse backing the ``semantic_example`` connection.
        dim_warehouse: Optional warehouse backing the ``semantic_dim`` connection.
    """
    bindings = {CONNECTION_ENV: str(warehouse)}
    if dim_warehouse is not None:
        bindings[CONNECTION_ENV_DIM] = str(dim_warehouse)
    previous = {name: os.environ.get(name) for name in bindings}
    os.environ.update(bindings)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def example_identity(
    user_id: str,
    session_id: str,
    program: str,
    *,
    roles: frozenset[str] = frozenset({_ALLOWED_ROLE}),
) -> SemanticRequestIdentity:
    """Build the trusted fixture identity bound around every governed call.

    Args:
        user_id: Subject identifier.
        session_id: Session identifier; part of the result owner tuple.
        program: Value of the ``programs`` subject attribute the RLS rule filters on.
        roles: Subject roles; ``analyst`` by default.

    Returns:
        A frozen :class:`SemanticRequestIdentity`.
    """
    context = PermissionContext(session=UserSession(user_id, "example-tenant", roles, {"programs": [program]}))
    return SemanticRequestIdentity(ctx=context, channel="agent", agent_id="semantic-examples", session_id=session_id)


def build_toolkit(
    warehouse: Path,
    *,
    evaluator: ExamplePolicyEvaluator | None = None,
    models_dir: Path | None = None,
    **extra: Any,
) -> SemanticLayerToolkit:
    """Build a governed SemanticLayerToolkit over the committed fixture models.

    Args:
        warehouse: Warehouse the toolkit's connection resolves to; bound by the caller.
        evaluator: Example evaluator; a fresh permissive one when omitted.
        models_dir: Model directory; :data:`MODELS_DIR` when omitted.
        **extra: Extra kwargs forwarded verbatim to :class:`SemanticLayerToolkit`.

    Returns:
        A toolkit wired to a real guard — never a bypassed one.
    """
    del warehouse
    rls_registry = RlsRegistry()
    return SemanticLayerToolkit(
        models_dir=models_dir or MODELS_DIR,
        dialect="duckdb",
        dataplane_guard=build_guard(evaluator or ExamplePolicyEvaluator(), rls_registry),
        rls_registry=rls_registry,
        **extra,
    )
