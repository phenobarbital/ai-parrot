"""Tests for the metric store and metrics.yaml seed loader (FEAT-756 M2)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from parrot.metrics.loader import load_agent_metrics, load_metrics_yaml, seed_store
from parrot.metrics.models import MetricDefinition
from parrot.metrics.store import InMemoryMetricStore


@pytest.mark.asyncio
async def test_inmemory_store_crud(worked_hours_def: MetricDefinition) -> None:
    """The in-memory store isolates values and supports CRUD operations."""
    store = InMemoryMetricStore([worked_hours_def])
    saved = await store.get("worked_hours", tenant=None)
    assert saved == worked_hours_def
    assert saved is not worked_hours_def
    saved.name = "Changed"
    assert (await store.get("worked_hours", tenant=None)).name == "Worked Hours"
    with pytest.raises(ValueError):
        await store.save(worked_hours_def)

    replacement = worked_hours_def.model_copy(update={"name": "Updated"})
    assert await store.save(replacement, overwrite=True) == "worked_hours"
    assert (await store.get("worked_hours", tenant=None)).name == "Updated"
    tenant_definition = worked_hours_def.model_copy(update={"tenant": "acme", "program": "other"})
    await store.save(tenant_definition)
    assert [definition.id for definition in await store.list(tenant=None, program="flex")] == ["worked_hours"]
    assert await store.delete("worked_hours", tenant=None) is True
    assert await store.delete("worked_hours", tenant=None) is False


def _write(path: Path, entries: list[dict[str, object]]) -> None:
    """Write a metrics.yaml fixture with its parent tree."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"metrics": entries}))


def test_load_metrics_yaml_forces_tenant_and_drops_invalid(tmp_path: Path, worked_hours_def: MetricDefinition) -> None:
    """Tenant files force their namespace and report invalid YAML rows."""
    data = worked_hours_def.model_dump(mode="json")
    data.pop("tenant")
    _write(
        tmp_path / "metrics.yaml",
        [
            data | {"global_only": True},
            data | {"id": "public_metric", "visibility": "public"},
            data | {"id": "other_tenant", "tenant": "other"},
            {"id": "bad"},
            data | {"id": "worked_hours"},
        ],
    )

    definitions, report = load_metrics_yaml(tmp_path / "metrics.yaml", tenant="acme")

    assert [definition.id for definition in definitions] == ["worked_hours"]
    assert definitions[0].tenant == "acme"
    assert definitions[0].global_only is False
    assert report.loaded == ["worked_hours"]
    assert len(report.dropped) == 4
    assert any("global_only reset" in note for note in report.notes)


def test_load_agent_metrics_discovers_tenant_trees(
    tmp_path: Path, worked_hours_def: MetricDefinition, caplog: pytest.LogCaptureFixture
) -> None:
    """Tenant metrics load without requiring a sibling skills directory."""
    agent_root = tmp_path / "agents" / "x"
    global_data = worked_hours_def.model_dump(mode="json")
    tenant_data = global_data.copy()
    tenant_data.pop("tenant")
    _write(agent_root / "metrics.yaml", [global_data])
    _write(agent_root / "tenants" / "acme" / "metrics.yaml", [tenant_data])
    (agent_root / "tenants" / "Bad Name").mkdir(parents=True)

    with caplog.at_level(logging.WARNING):
        result = load_agent_metrics(agent_root)

    assert {tenant: [definition.id for definition in definitions] for tenant, definitions in result.items()} == {
        None: ["worked_hours"],
        "acme": ["worked_hours"],
    }
    assert result["acme"][0].tenant == "acme"
    assert "Skipping tenant dir" in caplog.text


def test_load_metrics_yaml_missing_file_is_empty(tmp_path: Path) -> None:
    """A missing metrics YAML file is an empty, non-error input."""
    definitions, report = load_metrics_yaml(tmp_path / "missing.yaml")
    assert definitions == []
    assert report.loaded == []
    assert report.dropped == []


@pytest.mark.asyncio
async def test_seed_store_idempotent(worked_hours_def: MetricDefinition) -> None:
    """Duplicate writes are skipped and overwrite mode deterministically upserts."""
    store = InMemoryMetricStore()
    definitions = {None: [worked_hours_def]}
    assert await seed_store(store, definitions) == 1
    assert await seed_store(store, definitions) == 0
    assert await seed_store(store, definitions, overwrite=True) == 1
