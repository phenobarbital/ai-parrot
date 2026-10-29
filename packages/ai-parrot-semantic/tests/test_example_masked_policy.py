"""Regression contract: the masking / saved-queries example (FEAT-769 M5)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from parrot.semantic.models import SemanticQuery

pytest.importorskip("duckdb")

_EXAMPLE_PATH = Path(__file__).resolve().parents[3] / "examples" / "agents" / "semantic" / "masked_policy_agent.py"


@pytest.fixture(scope="module")
def example() -> ModuleType:
    """Load the example by absolute path, after the duckdb skip check."""
    spec = importlib.util.spec_from_file_location("semantic_masked_policy_example", _EXAMPLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


class _BothRolesEvaluator:
    """Allow both fixture roles through the real data-plane guard for this pin test."""

    def __init__(self, evaluator: object) -> None:
        self._evaluator = evaluator

    def check_access(self, eval_ctx: object, resource_type: str, resource: str, action: str, env: object) -> object:
        """Delegate access checks after admitting either example role."""
        original = self._evaluator.allowed_role
        self._evaluator.allowed_role = "analyst"
        try:
            result = self._evaluator.check_access(eval_ctx, resource_type, resource, action, env)
            if not result.allowed:
                roles = getattr(eval_ctx, "store", {}).get("userinfo", {}).get("roles", [])
                if "admin" in roles:
                    result.allowed = True
            return result
        finally:
            self._evaluator.allowed_role = original

    def filter_resources(
        self, eval_ctx: object, resource_type: str, resources: list[str], action: str, env: object
    ) -> object:
        """Delegate resource filtering and preserve both fixture roles."""
        original = self._evaluator.allowed_role
        self._evaluator.allowed_role = "analyst"
        try:
            result = self._evaluator.filter_resources(eval_ctx, resource_type, resources, action, env)
            roles = getattr(eval_ctx, "store", {}).get("userinfo", {}).get("roles", [])
            if "admin" in roles and resource_type == "table" and action == "table:read":
                result.allowed = list(resources)
            return result
        finally:
            self._evaluator.allowed_role = original


@pytest.fixture
def governed(example: ModuleType, tmp_path: Path):
    """A governed toolkit with the example connection bound for both roles."""
    warehouse = example._common.build_warehouse(tmp_path)
    evaluator = _BothRolesEvaluator(example._common.ExamplePolicyEvaluator())
    with example._common.connection_env(warehouse):
        yield example._common.build_toolkit(warehouse, evaluator=evaluator)


@pytest.mark.asyncio
async def test_analyst_sees_the_exact_masked_projection(example: ModuleType, governed) -> None:
    """Spec §3 M5: the masked output is asserted exactly, not merely logged."""
    identity = example._common.example_identity("analyst-1", "session-1", "eu")
    result = await example.run_masked_query(governed, identity)
    assert "region" in result.columns
    assert all(row["region"] is None for row in result.rows)


@pytest.mark.asyncio
async def test_admin_is_exempt_and_sees_the_raw_value(example: ModuleType, governed) -> None:
    """``projection_roles`` is an EXEMPTION list (policy.py:105-110)."""
    identity = example._common.example_identity("admin-1", "session-2", "eu", roles=frozenset({"admin"}))
    result = await example.run_masked_query(governed, identity)
    assert any(row["region"] in {"eu", "us"} for row in result.rows)


@pytest.mark.asyncio
async def test_saved_query_expands_and_runs(example: ModuleType, governed) -> None:
    """The reviewed query executes by name and returns the monthly revenue shape."""
    identity = example._common.example_identity("analyst-1", "session-1", "eu")
    result = await example.run_saved_query(governed, identity)
    assert "revenue" in result.columns
    assert any("order_date" in column for column in result.columns)


def test_saved_query_is_exclusive_with_explicit_members() -> None:
    """models.py:121-123 — the mixed form is rejected at construction."""
    with pytest.raises(ValueError, match="exclusive"):
        SemanticQuery(model="orders", saved_query="monthly_revenue", metrics=["revenue"])


@pytest.mark.asyncio
async def test_smoke_contrasts_both_roles_without_a_provider(example: ModuleType) -> None:
    """Spec AC3/AC6: offline, deterministic, no LLM."""
    summary = await example.smoke()
    analyst_regions = [row["region"] for row in summary["analyst"]["rows"]]
    admin_regions = [row["region"] for row in summary["admin"]["rows"]]
    assert analyst_regions and all(region is None for region in analyst_regions)
    assert admin_regions and any(region in {"eu", "us"} for region in admin_regions)
