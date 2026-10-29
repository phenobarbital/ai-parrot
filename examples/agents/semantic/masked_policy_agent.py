"""Column masking and saved queries on a governed model (FEAT-769 M5).

Two policy features that ``policy.py`` supports but no YAML outside the unit tests
demonstrates: a ``masks:`` rule that redacts a projected column for roles that are not
exempt, and a reviewed ``saved_queries:`` entry executed by name.

Usage::

    python examples/agents/semantic/masked_policy_agent.py --smoke     # no LLM, no network
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

import _common  # noqa: E402  (examples/ is not a package)

from parrot.semantic.context import SemanticRequestIdentity, bind_semantic_context
from parrot.semantic.models import SemanticQuery, SemanticQueryResult
from parrot.semantic.toolkit import SemanticLayerToolkit

#: The physical column masked by models/orders.policy.yaml.
MASKED_COLUMN = "sales.orders.region"
#: The reviewed query that policy file publishes by name.
SAVED_QUERY_NAME = "monthly_revenue"


async def run_masked_query(toolkit: SemanticLayerToolkit, identity: SemanticRequestIdentity) -> SemanticQueryResult:
    """Project the masked column and return the governed result.

    The policy exempts ``admin`` from the mask through ``projection_roles`` and therefore
    masks every other role, ``analyst`` included (``policy.py:105-110``).

    Args:
        toolkit: The governed toolkit.
        identity: The trusted identity whose roles decide whether the mask applies.

    Returns:
        The governed query result; ``region`` is redacted unless the identity is exempt.
    """
    query = SemanticQuery(model="orders", dimensions=["region"])
    async with bind_semantic_context(identity.ctx, identity=identity):
        return await toolkit.query_metrics(query)


async def run_saved_query(toolkit: SemanticLayerToolkit, identity: SemanticRequestIdentity) -> SemanticQueryResult:
    """Execute the reviewed saved query by name.

    ``saved_query`` is exclusive with explicit members, filters and ordering
    (``models.py:121-123``), so the query below carries nothing but the model and the name.

    Args:
        toolkit: The governed toolkit.
        identity: The trusted identity.

    Returns:
        The governed result of the expanded saved query.
    """
    query = SemanticQuery(model="orders", saved_query=SAVED_QUERY_NAME)
    async with bind_semantic_context(identity.ctx, identity=identity):
        return await toolkit.query_metrics(query)


async def smoke() -> dict[str, Any]:
    """Run the masked projection for both roles and the saved query, with no LLM.

    Returns:
        A JSON-safe summary showing the masked and unmasked projections side by side.
    """
    with tempfile.TemporaryDirectory() as directory:
        warehouse = _common.build_warehouse(Path(directory))
        with _common.connection_env(warehouse):
            analyst_toolkit = _common.build_toolkit(warehouse)
            admin_toolkit = _common.build_toolkit(
                warehouse,
                evaluator=_common.ExamplePolicyEvaluator(allowed_role="admin"),
            )
            analyst = _common.example_identity("analyst-1", "session-1", "eu")
            admin = _common.example_identity("admin-1", "session-2", "eu", roles=frozenset({"admin"}))
            analyst_result = await run_masked_query(analyst_toolkit, analyst)
            admin_result = await run_masked_query(admin_toolkit, admin)
            saved_result = await run_saved_query(admin_toolkit, admin)
            return {
                "analyst": analyst_result.model_dump(mode="json"),
                "admin": admin_result.model_dump(mode="json"),
                "saved_query": saved_result.model_dump(mode="json"),
            }


async def main() -> None:
    """Run the deterministic masking and saved-query demonstration."""
    parser = argparse.ArgumentParser(description="Masking and saved queries on a governed model")
    parser.add_argument("--smoke", action="store_true", help="Run the deterministic demo (default)")
    parser.parse_args()
    sys.stdout.write(json.dumps(await smoke(), indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
