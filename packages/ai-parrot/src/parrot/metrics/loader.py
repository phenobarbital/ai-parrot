"""metrics.yaml seed lane: agent-level and FEAT-707 tenant trees (FEAT-756 M2)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Mapping

import yaml
from pydantic import BaseModel, Field, ValidationError

from parrot.metrics.models import MetricDefinition
from parrot.metrics.store import MetricStore
from parrot.skills.tenancy import TENANTS_DIRNAME, validate_tenant_id
from parrot.utils.paths import secure_path

METRICS_FILENAME = "metrics.yaml"
_LOGGER = logging.getLogger(__name__)


class MetricsYamlReport(BaseModel):
    """Configure-time audit of one YAML file's loaded and dropped metrics."""

    path: str
    tenant: str | None = None
    loaded: list[str] = Field(default_factory=list)
    dropped: list[dict[str, str]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def _drop(report: MetricsYamlReport, entry: str, reason: str) -> None:
    """Record a dropped YAML entry with a bounded reason."""
    report.dropped.append({"entry": entry, "reason": reason})


def load_metrics_yaml(
    path: Path, *, tenant: str | None = None, logger: logging.Logger | None = None
) -> tuple[list[MetricDefinition], MetricsYamlReport]:
    """Load valid definitions from one metrics YAML file without raising for bad rows."""
    log = logger or _LOGGER
    report = MetricsYamlReport(path=str(path), tenant=tenant)
    if not path.is_file():
        return [], report

    try:
        payload = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        reason = f"Unable to load metrics YAML: {exc}"
        _drop(report, "<file>", reason)
        log.warning("Skipping metrics file %s: %s", path, reason)
        return [], report

    if not isinstance(payload, Mapping) or not isinstance(payload.get("metrics"), list):
        reason = "Expected a mapping with a list under 'metrics'"
        _drop(report, "<file>", reason)
        log.warning("Skipping metrics file %s: %s", path, reason)
        return [], report

    definitions: list[MetricDefinition] = []
    seen_ids: set[str] = set()
    for index, raw_entry in enumerate(payload["metrics"]):
        entry_label = str(index)
        if not isinstance(raw_entry, dict):
            _drop(report, entry_label, "Metric entry must be a mapping")
            continue

        entry = raw_entry.copy()
        entry_label = str(entry.get("id", index))
        if "tenant" in entry and entry["tenant"] != tenant:
            _drop(report, entry_label, f"Entry tenant does not match forced tenant {tenant!r}")
            continue
        if tenant is not None and entry.get("visibility") == "public":
            _drop(report, entry_label, "Tenant metrics cannot use public visibility")
            continue
        if tenant is not None and entry.get("global_only") is True:
            entry["global_only"] = False
            report.notes.append(f"{entry_label}: global_only reset to false for tenant metric")

        entry["tenant"] = tenant
        try:
            definition = MetricDefinition.model_validate(entry)
        except ValidationError as exc:
            _drop(report, entry_label, str(exc)[:300])
            continue
        if definition.id in seen_ids:
            _drop(report, definition.id, "Duplicate metric id in file")
            continue

        seen_ids.add(definition.id)
        definitions.append(definition)
        report.loaded.append(definition.id)
    return definitions, report


def load_agent_metrics(
    agent_root: Path, *, logger: logging.Logger | None = None
) -> dict[str | None, list[MetricDefinition]]:
    """Load global and valid tenant metrics from an agent's YAML tree."""
    log = logger or _LOGGER
    global_definitions, _ = load_metrics_yaml(agent_root / METRICS_FILENAME, logger=log)
    result: dict[str | None, list[MetricDefinition]] = {None: global_definitions}
    tenants_root = agent_root / TENANTS_DIRNAME
    if not tenants_root.is_dir():
        return result

    for entry in sorted(tenants_root.iterdir()):
        if not entry.is_dir():
            continue
        try:
            tenant = validate_tenant_id(entry.name)
            path = secure_path(agent_root, TENANTS_DIRNAME, tenant, METRICS_FILENAME, name="tenant id")
        except ValueError as exc:
            log.warning("Skipping tenant dir %s: %s", entry, exc)
            continue
        if not path.is_file():
            continue
        definitions, _ = load_metrics_yaml(path, tenant=tenant, logger=log)
        if definitions:
            result[tenant] = definitions
    return result


async def seed_store(
    store: MetricStore, definitions: Mapping[str | None, Iterable[MetricDefinition]], *, overwrite: bool = False
) -> int:
    """Persist definitions and return the count written, skipping duplicate inserts."""
    written = 0
    for namespace_definitions in definitions.values():
        for definition in namespace_definitions:
            try:
                await store.save(definition, overwrite=overwrite)
            except ValueError:
                continue
            written += 1
    return written
