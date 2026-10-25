"""Regression contract for fail-closed semantic PBAC."""

from pathlib import Path

import pytest
from sqlglot import parse_one
from sqlglot.optimizer.qualify import qualify

from parrot.auth.exceptions import AuthorizationRequired
from parrot.semantic.errors import SemanticAccessError
from parrot.semantic.governance import pbac
from parrot.semantic.governance.pbac import PbacGate, resources_from_ast
from parrot.semantic.loader import PhysicalSchema
from parrot.tools.dataset_manager.sources.resolver import PhysicalResources


class _Guard:
    """Deterministic guard double with a configured evaluator."""

    def __init__(self, *, deny: bool = False) -> None:
        self._evaluator = object()
        self.deny = deny
        self.calls: list[PhysicalResources] = []

    async def authorize_source(self, ctx: object, resources: PhysicalResources) -> None:
        """Record or deny one authorization attempt."""
        self.calls.append(resources)
        if self.deny:
            raise AuthorizationRequired("semantic_query", "denied")


class _Policy:
    """Minimal loaded-model policy contract."""

    governed = True


class _Model:
    """Minimal loaded-model contract for manifest authorization."""

    schema = PhysicalSchema(driver="pg", tables={"sales.orders": {"id": "INT"}})
    policy = _Policy()


@pytest.mark.asyncio
async def test_manifest_and_exact_evaluator_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Require both exact navigator-auth modules and authorize the full manifest."""
    assert tmp_path.is_dir()
    guard = _Guard()
    monkeypatch.setattr(
        pbac.importlib.util,
        "find_spec",
        lambda module: None if module.endswith(".evaluator") else object(),
    )
    unavailable = PbacGate(guard)  # type: ignore[arg-type]
    with pytest.raises(SemanticAccessError) as error:
        await unavailable.authorize(object(), PhysicalResources(driver="pg"), governed=True)  # type: ignore[arg-type]
    assert error.value.code == "pbac_unavailable"
    assert guard.calls == []

    monkeypatch.setattr(pbac.importlib.util, "find_spec", lambda module: object())
    gate = PbacGate(guard)  # type: ignore[arg-type]
    manifest = await gate.authorize_manifest(object(), _Model())  # type: ignore[arg-type]
    assert manifest == PhysicalResources(driver="pg", tables={"pg:sales.orders"})
    assert guard.calls == [manifest]


@pytest.mark.asyncio
async def test_cte_alias_physical_resources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exclude CTE aliases and reject post-compile resources outside the manifest."""
    assert tmp_path.is_dir()
    schema = PhysicalSchema(driver="pg", tables={"sales.orders": {"id": "INT"}})
    tree = qualify(
        parse_one("WITH recent AS (SELECT id FROM sales.orders) SELECT id FROM recent"),
        schema=schema.sqlglot_schema(),
        validate_qualify_columns=False,
    )
    assert resources_from_ast(tree, "pg") == PhysicalResources(driver="pg", tables={"pg:sales.orders"})

    monkeypatch.setattr(pbac.importlib.util, "find_spec", lambda module: object())
    guard = _Guard()
    gate = PbacGate(guard)  # type: ignore[arg-type]
    with pytest.raises(SemanticAccessError) as error:
        await gate.authorize(
            object(),  # type: ignore[arg-type]
            PhysicalResources(driver="pg", tables={"pg:private.payroll"}),
            governed=True,
            manifest=PhysicalResources(driver="pg", tables={"pg:sales.orders"}),
        )
    assert error.value.code == "outside_manifest"
    assert guard.calls == []


@pytest.mark.asyncio
async def test_sensitive_usage_lineage_matrix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Close missing-subject and policy-denial paths while preserving explicit opt-out."""
    assert tmp_path.is_dir()
    monkeypatch.setattr(pbac.importlib.util, "find_spec", lambda module: object())
    guard = _Guard(deny=True)
    gate = PbacGate(guard)  # type: ignore[arg-type]
    resources = PhysicalResources(driver="pg", tables={"pg:sales.orders"})

    with pytest.raises(SemanticAccessError) as missing:
        await gate.authorize(None, resources, governed=True)
    assert missing.value.code == "no_subject"

    with pytest.raises(SemanticAccessError) as denied:
        await gate.authorize(object(), resources, governed=True)  # type: ignore[arg-type]
    assert denied.value.code == "pbac_denied"

    await PbacGate(None).authorize(None, resources, governed=False)
