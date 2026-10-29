"""Runnable Agent example with semantic tools and a guarded private dataset facade."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from parrot.auth import DataPlanePolicyGuard, PermissionContext, RlsRegistry, UserSession
from parrot.bots import Agent
from parrot.semantic.context import SemanticRequestIdentity, bind_semantic_context, require_identity
from parrot.semantic.errors import SemanticResultError
from parrot.semantic.handoff import GovernedDatasetSink, ReadAuthorizer, handle_owner
from parrot.semantic.models import SemanticQuery
from parrot.semantic.results import ResultHandle
from parrot.semantic.toolkit import SemanticLayerToolkit
from parrot.tools.dataset_manager import DatasetManager
from parrot.tools.toolkit import AbstractToolkit

LOGGER = logging.getLogger(__name__)

CONNECTION_ENV = "PARROT_SEMANTIC_CONN_SEMANTIC_EXAMPLE_DATABASE"
_ALLOWED_DRIVER = "duckdb"
_ALLOWED_TABLE = "duckdb:sales.orders"
_ALLOWED_ROLE = "analyst"


class GuardedDatasetFacade(AbstractToolkit):
    """Host example adapter; only guarded methods are exposed to the Agent.

    The DatasetManager is deliberately private and never receives a result as a
    dataframe.  This small facade stores immutable result-handle copies, so every
    route can authorize the *current* semantic identity before returning data.
    """

    tool_prefix = "guarded_dataset"
    exclude_tools = ("publish",)
    guarded_reads = True

    def __init__(self, scope_id: str, owner: tuple[str, str, str, str]) -> None:
        """Create a single-owner facade and its inaccessible DatasetManager.

        Args:
            scope_id: Stable host scope for exactly one owner tuple.
            owner: Immutable ``(agent, user, tenant, session)`` owner tuple.
        """
        super().__init__()
        self.scope_id = scope_id
        self.owner = owner
        self._manager = DatasetManager()
        self._results: dict[str, ResultHandle] = {}
        self._authorizers: dict[str, ReadAuthorizer] = {}

    async def publish(self, name: str, handle: ResultHandle, authorize_read: ReadAuthorizer) -> dict[str, Any]:
        """Privately retain a copied handle and its mandatory per-result read callback."""
        if handle_owner(handle) != self.owner:
            raise SemanticResultError("result_unavailable", "Result is unavailable")
        self._results[name] = handle.model_copy(deep=True)
        self._authorizers[name] = authorize_read
        return {"name": name, "scope_id": self.scope_id, "rows": len(handle.rows)}

    async def list_datasets(self) -> dict[str, list[str]]:
        """List privately published dataset names after authorizing every entry."""
        for name in self._results:
            await self._read(name)
        return {"datasets": sorted(self._results)}

    async def describe_dataset(self, name: str) -> dict[str, Any]:
        """Return guarded metadata for one published result."""
        handle = await self._read(name)
        return {"name": name, "columns": list(handle.columns), "model": handle.model, "rows": len(handle.rows)}

    async def query_dataset(self, name: str) -> dict[str, list[dict[str, Any]]]:
        """Return a defensive copy of guarded result rows."""
        handle = await self._read(name)
        return {"rows": [dict(row) for row in handle.rows]}

    async def export_dataset(self, name: str) -> dict[str, Any]:
        """Return guarded export data without exposing a manager or dataframe."""
        handle = await self._read(name)
        return {"columns": list(handle.columns), "rows": [dict(row) for row in handle.rows]}

    async def cached_dataset(self, name: str) -> dict[str, list[dict[str, Any]]]:
        """Read a cached view only after current authorization succeeds."""
        return await self.query_dataset(name)

    async def derive_dataset(self, name: str) -> dict[str, Any]:
        """Return derived-copy provenance while preserving the source expiry."""
        handle = await self._read(name)
        return {
            "rows": [dict(row) for row in handle.rows],
            "model": handle.model,
            "model_digest": handle.model_digest,
            "policy_digest": handle.policy_digest,
            "expires_at": handle.expires_at.isoformat(),
        }

    async def _read(self, name: str) -> ResultHandle:
        """Authorize the current caller and return a private handle.

        Args:
            name: Published result name.

        Returns:
            The private retained result handle.

        Raises:
            SemanticResultError: If the result is missing or authorization fails.
        """
        authorize_read = self._authorizers.get(name)
        if authorize_read is None or name not in self._results:
            raise SemanticResultError("result_unavailable", "Result is unavailable")
        identity = require_identity()
        # Defence in depth: the facade only ever serves its own owner, even
        # before the semantic read authorizer re-checks the full provenance.
        if _owner_of(identity) != self.owner:
            raise SemanticResultError("result_unavailable", "Result is unavailable")
        await authorize_read(identity)
        return self._results[name]


def _owner_of(identity: SemanticRequestIdentity) -> tuple[str, str, str, str]:
    """Return the ``(agent, user, tenant, session)`` owner tuple of a trusted identity."""
    return (identity.agent_id, identity.ctx.user_id, identity.ctx.tenant_id, identity.session_id)


def _scope_id(owner: tuple[str, str, str, str]) -> str:
    """Derive a stable, non-reversible scope id from an owner tuple."""
    return "semantic-" + hashlib.sha256("\x1f".join(owner).encode("utf-8")).hexdigest()[:16]


class ExamplePolicyEvaluator:
    """Explicit allow-list PBAC evaluator for the local fixture.

    It is a real evaluator plugged into the core :class:`DataPlanePolicyGuard`
    (no gate is bypassed): only ``analyst`` subjects may connect to DuckDB and
    read ``sales.orders``. ``revoke()`` withdraws the grant so later reads fail.
    Production hosts use the navigator-auth ``PolicyEvaluator`` instead.
    """

    def __init__(self) -> None:
        """Start with the fixture grant enabled."""
        self.revoked = False

    def revoke(self) -> None:
        """Withdraw the fixture grant for every subsequent decision."""
        self.revoked = True

    def _permits(self, eval_ctx: Any) -> bool:
        """Return whether the evaluated subject holds the analyst grant."""
        userinfo = getattr(eval_ctx, "store", {}).get("userinfo", {})
        return not self.revoked and _ALLOWED_ROLE in userinfo.get("roles", [])

    def check_access(self, eval_ctx: Any, resource_type: str, resource: str, action: str, env: Any) -> SimpleNamespace:
        """Allow only ``driver:connect`` on the DuckDB driver for analysts."""
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
        """Return only the fixture table for analysts performing ``table:read``."""
        del env
        if not self._permits(eval_ctx) or resource_type != "table" or action != "table:read":
            return SimpleNamespace(allowed=[])
        return SimpleNamespace(allowed=[resource for resource in resources if resource == _ALLOWED_TABLE])


def build_guard(evaluator: ExamplePolicyEvaluator, rls_registry: RlsRegistry) -> DataPlanePolicyGuard:
    """Build the core data-plane guard around the example evaluator."""
    return DataPlanePolicyGuard(evaluator=evaluator, rls_registry=rls_registry)


class _OwnerFacadeFactory:
    """Create one guarded private facade for each exact trusted owner tuple."""

    def __init__(self) -> None:
        """Initialize the per-owner facade map."""
        self.facades: dict[tuple[str, str, str, str], GuardedDatasetFacade] = {}
        self.sinks: dict[tuple[str, str, str, str], _FacadeSink] = {}

    async def __call__(self, identity: SemanticRequestIdentity) -> GovernedDatasetSink:
        """Return the facade belonging to the supplied trusted identity."""
        owner = _owner_of(identity)
        if owner not in self.facades:
            self.facades[owner] = GuardedDatasetFacade(_scope_id(owner), owner)
        if owner not in self.sinks:
            self.sinks[owner] = _FacadeSink(self.facades[owner])
        return self.sinks[owner]


class _FacadeSink:
    """Conforming host sink that delegates to an AbstractToolkit facade by composition."""

    guarded_reads = True

    def __init__(self, facade: GuardedDatasetFacade) -> None:
        """Bind one non-toolkit sink to one private guarded facade."""
        self.scope_id = facade.scope_id
        self.owner = facade.owner
        self._facade = facade

    async def publish(self, name: str, handle: ResultHandle, authorize_read: ReadAuthorizer) -> dict[str, Any]:
        """Delegate publication without exposing the toolkit as a host sink."""
        return await self._facade.publish(name, handle, authorize_read)


def build_warehouse(directory: Path) -> Path:
    """Create deterministic DuckDB fixtures for two subjects."""
    import duckdb

    directory.mkdir(parents=True, exist_ok=True)
    warehouse = directory / "semantic-example.duckdb"
    connection = duckdb.connect(str(warehouse))
    try:
        connection.execute("CREATE SCHEMA sales")
        connection.execute("CREATE TABLE sales.orders (id INTEGER, region VARCHAR, amount DECIMAL)")
        connection.execute("INSERT INTO sales.orders VALUES (1, 'eu', 12.50), (2, 'us', 25.00)")
    finally:
        connection.close()
    return warehouse


def build_models_dir(directory: Path) -> Path:
    """Write own-format graph and governed policy fixtures."""
    models_dir = directory / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / "orders.yml").write_text(
        """models:
  - name: orders
    table: sales.orders
    columns: {id: INTEGER, region: VARCHAR, amount: DECIMAL}
    primary_key: [id]
    dimensions: [{name: region, kind: categorical, column: region}]
    metrics: [{name: revenue, agg: sum, column: amount}]
    relationships: []
""",
        encoding="utf-8",
    )
    (models_dir / "orders.policy.yaml").write_text(
        """governed: true
connection: semantic_example
limits: {default: 100, max: 100}
roles:
  analyst: {metrics: [revenue], dimensions: [region], usage: [sales.orders.region, sales.orders.amount]}
rls:
  - {driver: duckdb, table: sales.orders, predicate_template: "region IN (:subject.programs)", subject_attribute: programs}
""",
        encoding="utf-8",
    )
    return models_dir


@contextmanager
def connection_env(directory: Path) -> Iterator[None]:
    """Expose the fixture warehouse connection only for the enclosed block.

    The previous value of :data:`CONNECTION_ENV` is restored on exit, so the
    example never leaks process-wide configuration.
    """
    previous = os.environ.get(CONNECTION_ENV)
    os.environ[CONNECTION_ENV] = str(directory / "semantic-example.duckdb")
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(CONNECTION_ENV, None)
        else:
            os.environ[CONNECTION_ENV] = previous


def build_toolkits(
    directory: Path, evaluator: ExamplePolicyEvaluator | None = None
) -> tuple[SemanticLayerToolkit, GuardedDatasetFacade]:
    """Wire a real data-plane guard, fixture models and a per-owner host factory.

    Args:
        directory: Writable runtime directory for the warehouse and models.
        evaluator: PBAC evaluator; defaults to a fresh :class:`ExamplePolicyEvaluator`.

    Returns:
        The semantic toolkit and the primary owner's guarded facade.
    """
    build_warehouse(directory)
    models_dir = build_models_dir(directory)
    rls_registry = RlsRegistry()
    factory = _OwnerFacadeFactory()
    toolkit = SemanticLayerToolkit(
        models_dir=models_dir,
        dialect="duckdb",
        dataplane_guard=build_guard(evaluator or ExamplePolicyEvaluator(), rls_registry),
        rls_registry=rls_registry,
        dataset_manager_factory=factory,
    )
    owner = _owner_of(_example_identity("analyst-1", "session-1", "eu"))
    facade = GuardedDatasetFacade(_scope_id(owner), owner)
    factory.facades[owner] = facade
    return toolkit, facade


def build_agent(toolkits: tuple[SemanticLayerToolkit, GuardedDatasetFacade]) -> Agent:
    """Construct Agent with semantic and guarded dataset tools, no real LLM call."""
    semantic, facade = toolkits
    return Agent(name="semantic-example", llm="google", tools=[*semantic.get_tools(), *facade.get_tools()])


def _example_identity(user_id: str, session_id: str, program: str) -> SemanticRequestIdentity:
    """Build a scoped fixture identity with the exact analyst grant."""
    context = PermissionContext(
        session=UserSession(user_id, "example-tenant", frozenset({"analyst"}), {"programs": [program]})
    )
    return SemanticRequestIdentity(ctx=context, channel="agent", agent_id="semantic-example", session_id=session_id)


async def run_demo(directory: Path) -> None:
    """Run scripted scoped query, publication, guarded read and denial examples.

    Raises:
        RuntimeError: If the second session is not denied access.
    """
    semantic, facade = build_toolkits(directory)
    build_agent((semantic, facade))
    owner = _example_identity("analyst-1", "session-1", "eu")
    with connection_env(directory):
        async with bind_semantic_context(owner.ctx, identity=owner):
            query = SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"])
            result = await semantic.query_metrics(query)
            published = await semantic.save_result_as_dataset(result.result_id or "", "eu_revenue")
            LOGGER.info("Published guarded result: %s", published)
            LOGGER.info("Guarded cached read: %s", await facade.cached_dataset("eu_revenue"))
    denied = _example_identity("analyst-2", "session-2", "us")
    async with bind_semantic_context(denied.ctx, identity=denied):
        try:
            await facade.query_dataset("eu_revenue")
        except SemanticResultError:
            LOGGER.info("Second session was denied access to the owner-bound result")
        else:
            raise RuntimeError("Second session unexpectedly read the owner-bound result")


async def main() -> None:
    """Run the demo in a throw-away directory that is removed afterwards."""
    with tempfile.TemporaryDirectory(prefix="semantic-example-") as directory:
        await run_demo(Path(directory))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
