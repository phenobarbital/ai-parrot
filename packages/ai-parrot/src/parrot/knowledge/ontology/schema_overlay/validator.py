"""Schema Overlay dry-run validator (FEAT-159 TASK-1094).

Performs sandboxed validation of a schema overlay candidate before it can
transition from ``pending_review`` to ``approved``.  The dry-run is the
mandatory approval gate.

Validation pipeline (v1)
-------------------------
1. Parse ``overlay.definition`` into the appropriate schema model.
2. Build an ``OntologyDefinition`` from the candidate.
3. Call ``merger.merge_with_overlay()`` on a private call — does NOT mutate
   the tenant's ``TenantOntologyManager`` cache.
4. For ``traversal_pattern`` overlays: run ``validate_aql()`` on the
   ``query_template``.
5. Catch ``FrameworkOverrideError`` if the overlay attempts to mutate a
   framework item.
6. Return a ``DryRunReport`` with per-check results and wall-clock timing.

A ``ONTOLOGY_DRY_RUN_TIMEOUT_S`` timeout (default 10 s) is enforced via
``asyncio.wait_for``.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from parrot.knowledge.ontology.exceptions import (
    AQLValidationError,
    DryRunFailedError,
    FrameworkOverrideError,
)
from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.schema import (
    EntityDef,
    OntologyDefinition,
    RelationDef,
    TraversalPattern,
)
from parrot.knowledge.ontology.schema_overlay.models import DryRunReport, SchemaOverlayRow
from parrot.knowledge.ontology.tenant import TenantOntologyManager
from parrot.knowledge.ontology.validators import validate_aql

logger = logging.getLogger("Parrot.Ontology.SchemaOverlay.Validator")

try:
    from parrot.conf import ONTOLOGY_DRY_RUN_TIMEOUT_S  # type: ignore[attr-defined]
except (ImportError, AttributeError):
    ONTOLOGY_DRY_RUN_TIMEOUT_S = 10


async def dry_run_overlay(
    tenant_id: str,
    overlay: SchemaOverlayRow,
    tenant_manager: TenantOntologyManager,
    merger: OntologyMerger,
) -> DryRunReport:
    """Sandboxed validation of a schema overlay candidate.

    The function does NOT mutate the ``tenant_manager`` cache.  It obtains
    the current YAML path chain from the manager's internal state, then
    calls ``merger.merge_with_overlay()`` independently.

    Args:
        tenant_id: Tenant owning the overlay.
        overlay: The schema overlay row to validate.
        tenant_manager: Provides YAML path resolution for the tenant.
        merger: ``OntologyMerger`` to use for the sandboxed merge.

    Returns:
        ``DryRunReport`` with ``ok``, per-check results, and timing.
    """
    try:
        report = await asyncio.wait_for(
            _run_checks(tenant_id, overlay, tenant_manager, merger),
            timeout=ONTOLOGY_DRY_RUN_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        return DryRunReport(
            ok=False,
            checks=[{
                "check_name": "timeout",
                "passed": False,
                "details": f"Dry-run exceeded {ONTOLOGY_DRY_RUN_TIMEOUT_S}s timeout.",
            }],
            error="Dry-run timed out.",
            duration_ms=ONTOLOGY_DRY_RUN_TIMEOUT_S * 1000,
        )
    return report


async def _run_checks(
    tenant_id: str,
    overlay: SchemaOverlayRow,
    tenant_manager: TenantOntologyManager,
    merger: OntologyMerger,
) -> DryRunReport:
    """Inner validation pipeline (wrapped in a timeout by caller)."""
    start = time.monotonic()
    checks: list[dict] = []
    overall_ok = True
    error_msg: str | None = None

    # ── Step 1: Build OntologyDefinition from overlay definition ─────────────
    parse_check, candidate_def = _parse_definition(overlay)
    checks.append(parse_check)
    if not parse_check["passed"]:
        overall_ok = False
        error_msg = parse_check["details"]
        return _make_report(overall_ok, checks, error_msg, start)

    # ── Step 2: Discover YAML paths for tenant (sandbox — no cache mutate) ───
    yaml_paths = _resolve_yaml_paths(tenant_id, tenant_manager)

    # ── Step 3: Sandboxed merge ──────────────────────────────────────────────
    merge_check = _check_merge(yaml_paths, [candidate_def], merger)
    checks.append(merge_check)
    if not merge_check["passed"]:
        overall_ok = False
        if error_msg is None:
            error_msg = merge_check["details"]

    # ── Step 4: AQL validation for traversal patterns ────────────────────────
    if overlay.overlay_kind == "traversal_pattern":
        query_template = overlay.definition.get("query_template", "")
        aql_check = await _check_aql(query_template)
        checks.append(aql_check)
        if not aql_check["passed"]:
            overall_ok = False
            if error_msg is None:
                error_msg = aql_check["details"]

    logger.info(
        "Dry-run for overlay '%s' (tenant '%s'): %s — %d checks in %.0fms.",
        overlay.name,
        tenant_id,
        "PASS" if overall_ok else "FAIL",
        len(checks),
        (time.monotonic() - start) * 1000,
    )

    return _make_report(overall_ok, checks, error_msg, start)


# ── Helper functions ─────────────────────────────────────────────────────────

def _parse_definition(
    overlay: SchemaOverlayRow,
) -> tuple[dict, OntologyDefinition]:
    """Parse the overlay ``definition`` dict into an ``OntologyDefinition``.

    Returns a ``(check_result, candidate_def)`` tuple.  On failure, the
    ``candidate_def`` is a minimal empty definition (unused by the caller
    when the check fails).
    """
    check: dict = {"check_name": "definition_parse", "passed": True, "details": "OK"}
    try:
        defn = overlay.definition

        if overlay.overlay_kind == "entity_type":
            entity = EntityDef(**defn)
            candidate = OntologyDefinition(
                name=overlay.name,
                entities={overlay.name: entity},
            )
        elif overlay.overlay_kind == "relation_type":
            relation = RelationDef(**defn)
            candidate = OntologyDefinition(
                name=overlay.name,
                relations={overlay.name: relation},
            )
        elif overlay.overlay_kind == "traversal_pattern":
            pattern = TraversalPattern(**defn)
            candidate = OntologyDefinition(
                name=overlay.name,
                traversal_patterns={overlay.name: pattern},
            )
        else:
            raise ValueError(f"Unknown overlay_kind: {overlay.overlay_kind!r}")

        return check, candidate

    except Exception as exc:
        check["passed"] = False
        check["details"] = f"Failed to parse overlay definition: {exc}"
        return check, OntologyDefinition(name="__empty__")


def _resolve_yaml_paths(
    tenant_id: str,
    tenant_manager: TenantOntologyManager,
) -> list[Path]:
    """Resolve the YAML chain for *tenant_id* without populating the cache.

    Replicates the path-discovery logic from ``TenantOntologyManager.resolve``
    but does NOT call ``resolve()`` (which would populate ``_cache``).
    """
    paths: list[Path] = []

    ontology_dir = tenant_manager._ontology_dir
    base_file = tenant_manager._base_file
    domains_dir = tenant_manager._domains_dir
    clients_dir = tenant_manager._clients_dir

    base_path = ontology_dir / base_file
    if base_path.exists():
        paths.append(base_path)
    else:
        from parrot.knowledge.ontology.parser import OntologyParser
        default_base = OntologyParser.get_defaults_dir() / base_file
        if default_base.exists():
            paths.append(default_base)

    client_path = ontology_dir / clients_dir / f"{tenant_id}.ontology.yaml"
    if client_path.exists():
        paths.append(client_path)

    return paths


def _check_merge(
    yaml_paths: list[Path],
    overlay_defs: list[OntologyDefinition],
    merger: OntologyMerger,
) -> dict:
    """Run ``merge_with_overlay`` and catch any merge / framework error."""
    check: dict = {"check_name": "merge_validation", "passed": True, "details": "OK"}
    try:
        if yaml_paths:
            merger.merge_with_overlay(yaml_paths, overlay_defs)
        else:
            # No YAML paths — just merge the definitions to check inter-def rules.
            merger.merge_definitions(overlay_defs)
    except FrameworkOverrideError as exc:
        check["passed"] = False
        check["details"] = (
            f"FrameworkOverrideError: overlay attempts to redefine "
            f"'{exc.entity_name}' which is a framework-protected item."
        )
    except Exception as exc:
        check["passed"] = False
        check["details"] = f"Merge validation failed: {exc}"
    return check


async def _check_aql(query_template: str) -> dict:
    """Validate AQL query template for safety."""
    check: dict = {"check_name": "aql_validation", "passed": True, "details": "OK"}
    if not query_template:
        check["passed"] = False
        check["details"] = "traversal_pattern has no query_template."
        return check
    try:
        await validate_aql(query_template)
    except AQLValidationError as exc:
        check["passed"] = False
        check["details"] = f"AQL validation failed: {exc}"
    except Exception as exc:
        check["passed"] = False
        check["details"] = f"Unexpected AQL check error: {exc}"
    return check


def _make_report(
    ok: bool,
    checks: list[dict],
    error: str | None,
    start: float,
) -> DryRunReport:
    duration_ms = int((time.monotonic() - start) * 1000)
    return DryRunReport(ok=ok, checks=checks, error=error, duration_ms=duration_ms)
