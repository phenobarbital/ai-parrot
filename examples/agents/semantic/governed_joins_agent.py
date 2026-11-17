"""Time grains, the governed cross-model denial, and connection isolation (FEAT-769 M6).

This is NOT a joins demo. The governed path cannot authorize a cross-model join: the
allowed member set is resolved from the ROOT model alone (``catalog.py:66``), so a
qualified member is never granted -- even under ``metrics: "*"``. The compiler, meanwhile,
compiles that join correctly. The denial is the lesson: it is what "fails loudly on
out-of-scope questions instead of inventing a figure" looks like in practice.

Usage::

    python examples/agents/semantic/governed_joins_agent.py --smoke    # all four legs, no LLM
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

import _common  # noqa: E402  (examples/ is not a package)

from parrot.semantic.context import SemanticRequestIdentity, bind_semantic_context  # noqa: E402
from parrot.semantic.errors import SemanticAccessError  # noqa: E402
from parrot.semantic.models import SemanticQuery, SemanticQueryResult, TimeDimension  # noqa: E402
from parrot.semantic.toolkit import SemanticLayerToolkit  # noqa: E402

LOGGER = logging.getLogger(__name__)

#: The qualified member the governed path refuses to authorize from an `orders` root.
UNGRANTABLE_MEMBER = "customers.email"


def _denied_query() -> SemanticQuery:
    """Build the cross-model query the governed path refuses."""
    return SemanticQuery(model="orders", metrics=["revenue"], dimensions=[UNGRANTABLE_MEMBER])


async def run_time_grain(toolkit: SemanticLayerToolkit, identity: SemanticRequestIdentity) -> SemanticQueryResult:
    """Run a governed query over a time dimension with an explicit grain.

    Grains work on a single model; `grain` is mandatory on a ``TimeDimension``
    (``models.py:32-43``).

    Args:
        toolkit: The governed toolkit over the committed fixture.
        identity: The trusted fixture identity.

    Returns:
        The governed result, one row per month.
    """
    query = SemanticQuery(
        model="orders",
        metrics=["revenue"],
        time_dimensions=[TimeDimension(name="order_date", grain="month")],
    )
    async with bind_semantic_context(identity.ctx, identity=identity):
        return await toolkit.query_metrics(query)


async def show_governed_join_denial(
    toolkit: SemanticLayerToolkit, identity: SemanticRequestIdentity
) -> SemanticAccessError:
    """Return the ``member_not_granted`` error a governed cross-model query raises.

    ``RoleCatalog.check_query_rights`` resolves the allowed set from the ROOT model only
    (``catalog.py:66``), so ``customers.email`` is never granted to a query rooted at
    ``orders``. This is the governance surface refusing a question it cannot answer
    truthfully -- not a bug, and not something a policy key can unlock.

    Args:
        toolkit: The governed toolkit.
        identity: The trusted fixture identity.

    Returns:
        The ``SemanticAccessError`` that was raised, for the caller to report.

    Raises:
        RuntimeError: If the query unexpectedly SUCCEEDS. A denial that silently passes is
            a failure of this example, not a pass.
    """
    query = _denied_query()
    async with bind_semantic_context(identity.ctx, identity=identity):
        try:
            await toolkit.query_metrics(query)
        except SemanticAccessError as error:
            LOGGER.info("governed cross-model query denied as expected: %s", error)
            return error
    raise RuntimeError(f"governed cross-model query on {UNGRANTABLE_MEMBER} unexpectedly succeeded")


async def compile_ungoverned_join(directory: Path) -> str:
    """Compile the same join under an explicitly ``governed: false`` model.

    This is the COMPILER surface, not a governance bypass: a different model, in a
    different directory, whose policy declares ``governed: false`` -- which short-circuits
    ``check_query_rights`` (``catalog.py:64-65``). The SQL below is also PRE-RLS
    (``toolkit.py:195``); governed SQL exists only in the audit record.

    Args:
        directory: Scratch directory (unused for execution; this leg only compiles).

    Returns:
        The compiled SQL containing the join.
    """
    del directory
    toolkit = _common.build_toolkit(Path("."), models_dir=_common.MODELS_UNGOVERNED_DIR)
    # The ungoverned twin grants only `admin`; its usage rights still apply to the SQL lineage.
    identity = _common.example_identity("admin-1", "session-1", "eu", roles=frozenset({"admin"}))
    async with bind_semantic_context(identity.ctx, identity=identity):
        compiled = await toolkit.compile_query(_denied_query())
    return str(compiled["sql"])


async def run_on_second_connection(
    toolkit: SemanticLayerToolkit, identity: SemanticRequestIdentity
) -> SemanticQueryResult:
    """Run a governed query rooted at ``customers``, which uses a SECOND warehouse.

    ``customers`` declares ``connection: semantic_dim`` while ``orders`` declares
    ``semantic_example``; the connection is read from the ROOT model's policy
    (``toolkit.py:315,485``) and resolved from the environment
    (``execution.py:26-49``). This demonstrates per-model connection isolation. It is NOT
    a cross-connection refusal -- no such check exists in the library.

    Args:
        toolkit: The governed toolkit.
        identity: The trusted fixture identity.

    Returns:
        The governed result, read from the dim warehouse.
    """
    query = SemanticQuery(model="customers", metrics=["customer_count"], dimensions=["email"])
    async with bind_semantic_context(identity.ctx, identity=identity):
        return await toolkit.query_metrics(query)


async def smoke() -> dict[str, Any]:
    """Run all four legs deterministically, with no LLM and no network.

    Returns:
        A JSON-safe summary labelling which surface produced each outcome.
    """
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        warehouse = _common.build_warehouse(root)
        dim_warehouse = _common.build_dim_warehouse(root)
        identity = _common.example_identity("analyst-1", "session-1", "eu")
        with _common.connection_env(warehouse, dim_warehouse):
            toolkit = _common.build_toolkit(warehouse)
            grain = await run_time_grain(toolkit, identity)
            denial = await show_governed_join_denial(toolkit, identity)
            join_sql = await compile_ungoverned_join(root)
            second = await run_on_second_connection(toolkit, identity)
    return {
        "governed_time_grain": {"columns": grain.columns, "row_count": grain.row_count},
        "governed_join_denied": {
            "code": denial.code,
            "member": (denial.details or {}).get("member"),
        },
        "compiler_only_join_sql": join_sql,
        "governed_second_connection": {
            "connection": "semantic_dim",
            "columns": second.columns,
            "row_count": second.row_count,
        },
    }


async def main() -> None:
    """Run the four legs and print a labelled summary."""
    parser = argparse.ArgumentParser(description="Grains, the governed-join denial, and connection isolation")
    parser.add_argument("--smoke", action="store_true", help="Run all four legs (default)")
    parser.parse_args()
    print(json.dumps(await smoke(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
