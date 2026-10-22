"""FEAT-636 TASK-4107 — persist-time Python gate and one-source fetches."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.linked import executor as executor_mod
from parrot.outputs.a2ui.linked.executor import ExecutionOutcome, SourceOutcome
from parrot.outputs.a2ui.linked.models import PythonTransform, TransformSpec
from parrot.outputs.a2ui.linked.service import LinkedGuardRequired, LinkedSurfaceService
from parrot.outputs.a2ui.recipes.transformers import transformer_registry

from .test_service import _dict_envelope, _envelope, _FakeGuard, owner  # noqa: F401

pytestmark = pytest.mark.asyncio


async def test_fetch_source_passes_params_and_pctx(owner, linked_source, monkeypatch) -> None:
    """One-source execution receives only the requested source, parameters, and principal."""
    seen: dict = {}

    async def _fake(sources, **kwargs):
        seen.update(kwargs, keys=list(sources))
        return ExecutionOutcome(
            outcomes={
                "activity": SourceOutcome(key="activity", rows=[{"a": 1}], snapshot_at=datetime.now(timezone.utc))
            }
        )

    monkeypatch.setattr(executor_mod, "execute_sources", _fake)
    out = await LinkedSurfaceService(guard=_FakeGuard()).fetch_source(
        _dict_envelope(linked_source), "activity", params={"firstdate": "TODAY"}, pctx=owner
    )

    assert out.rows == [{"a": 1}]
    assert out.error_status is None
    assert seen["keys"] == ["activity"]
    assert seen["param_overrides"] == {"activity": {"firstdate": "TODAY"}}
    assert seen["pctx"] is owner
    assert seen["max_snapshot_rows"] is None


async def test_fetch_source_requires_guard(owner, linked_source) -> None:
    """A data-plane fetch fails closed without a configured guard."""
    with pytest.raises(LinkedGuardRequired):
        await LinkedSurfaceService(guard=None).fetch_source(
            _dict_envelope(linked_source), "activity", params={}, pctx=owner
        )


async def test_fetch_source_unknown_or_derived_key(owner, linked_source) -> None:
    """Unknown and derived keys return the same non-oracular not-found response."""
    envelope = _dict_envelope(linked_source)
    envelope["metadata"]["extensions"]["parrot_data_sources"]["summary"] = {
        "kind": "derived",
        "from": "activity",
        "transform": {"ops": [{"op": "select", "columns": ["a"]}]},
        "target": "/summary/rows",
    }
    service = LinkedSurfaceService(guard=_FakeGuard())

    for key in ("missing", "summary"):
        outcome = await service.fetch_source(envelope, key, params={}, pctx=owner)
        assert outcome.error_status == 404
        assert outcome.error_code == "source_not_found"


async def test_fetch_source_transform_error(owner, linked_source, monkeypatch) -> None:
    """Transform-stage errors retain executor's stable 422 mapping."""

    async def _fake(sources, **kwargs):
        return ExecutionOutcome(outcomes={"activity": SourceOutcome(key="activity", error="transform_failed")})

    monkeypatch.setattr(executor_mod, "execute_sources", _fake)
    outcome = await LinkedSurfaceService(guard=_FakeGuard()).fetch_source(
        _dict_envelope(linked_source), "activity", params={}, pctx=owner
    )

    assert outcome.error_status == 422
    assert outcome.error_code == "transform_failed"


async def test_fetch_source_ignored_params_warning(owner, linked_source, monkeypatch) -> None:
    """Locked and undeclared overrides surface as a one-source ignored-parameter warning."""

    async def _fake(sources, **kwargs):
        return ExecutionOutcome(
            outcomes={"activity": SourceOutcome(key="activity", rows=[], ignored_params=["locked", "unknown"])}
        )

    monkeypatch.setattr(executor_mod, "execute_sources", _fake)
    outcome = await LinkedSurfaceService(guard=_FakeGuard()).fetch_source(
        _dict_envelope(linked_source), "activity", params={"locked": "x"}, pctx=owner
    )

    assert outcome.warnings == ["ignored params ['locked', 'unknown']"]


async def test_persist_gate_rejects_unregistered_and_allows_registered(owner, linked_source, monkeypatch) -> None:
    """Persist-time validation rejects unknown transformers but accepts a registry-backed reference."""
    monkeypatch.setattr(transformer_registry, "_transformers", {})
    invalid = linked_source.model_copy(update={"transform": TransformSpec(python=PythonTransform(transformer="nope"))})
    service = LinkedSurfaceService(guard=_FakeGuard())

    with pytest.raises(CatalogValidationError) as info:
        await service.validate_for_persistence(_envelope(invalid), owner_pctx=owner)
    assert info.value.issues[0]["code"] == "python_transform_invalid"
    assert info.value.issues[0]["path"].endswith("/transform/python")

    def registered_transform(inputs: dict, params: dict) -> dict:
        return {"result": inputs["source"]}

    transformer_registry.register("t4107_registered", registered_transform)
    valid = linked_source.model_copy(
        update={"transform": TransformSpec(python=PythonTransform(transformer="t4107_registered"))}
    )
    await service.validate_for_persistence(_envelope(valid), owner_pctx=owner)
