"""Source-owned Roblox body enrichment and dependency digest (FEAT-532 TASK-2907).

Post-processes an already-built :class:`~parrot.knowledge.wiki.repo_scan.RepoScan`
(never re-scans, never touches the network, never invokes an external
language tool): attaches a rendered DataModel body section and resolved
API reference edges to each Luau :class:`~parrot.knowledge.wiki.repo_scan.FileSlice`,
using TASK-2898's :class:`~parrot.knowledge.wiki.roblox.models.RobloxInstanceIndex`
and TASK-2901's :class:`~parrot.knowledge.wiki.roblox.models.RobloxApiCatalog`.

Returns a **new** ``RepoScan`` (the input is never mutated) plus one
:class:`~parrot.knowledge.wiki.roblox.models.RobloxFileEnrichment` per
enriched Luau file, carrying the full diagnostic/candidate detail and a
:attr:`~RobloxFileEnrichment.dependency_digest` that changes whenever the
mapping, the API catalog generation, the renderer schema, or the
configured namespace changes — even when the Luau source bytes
themselves are unchanged (spec §"Code-to-API linking": "installing or
refreshing the API or changing a mapping must update edges/body
enrichment even when Luau source bytes are unchanged"). Persisting these
records and deciding *when* to re-enrich an unchanged file is TASK-2909's
responsibility, not this module's.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from parrot.knowledge.wiki.context import qualify_id
from parrot.knowledge.wiki.repo_scan import FileSlice, RepoScan, file_concept_id
from parrot.knowledge.wiki.roblox.models import (
    RobloxApiCatalog,
    RobloxFileEnrichment,
    RobloxInstanceIndex,
    class_page_id,
    enum_page_id,
)
from parrot.knowledge.wiki.roblox.references import extract_api_reference_candidates
from parrot.knowledge.wiki.store import estimate_tokens

logger = logging.getLogger(__name__)

#: Default namespace the federated Roblox API plane is qualified under
#: (spec: "query it through namespace `roblox`"). Callers with a
#: differently-configured namespace pass it explicitly.
DEFAULT_ROBLOX_NAMESPACE = "roblox"


def _dependency_digest(
    mapping_digest: str,
    catalog_generation_id: str | None,
    renderer_schema_version: int,
    namespace: str,
) -> str:
    """Combine every enrichment-affecting identity into one digest.

    Deliberately excludes source bytes — this is the digest of the
    *enrichment context*, not the file. A caller (TASK-2909) compares
    this against a previously stored value to decide whether unchanged
    Luau source still needs re-enrichment because something about the
    mapping/catalog/schema/namespace changed underneath it.
    """
    raw = f"{mapping_digest}|{catalog_generation_id or ''}|{renderer_schema_version}|{namespace}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _render_datamodel_section(rel_path: str, instance_index: RobloxInstanceIndex) -> str:
    """Rendered ``## DataModel`` section for one file's instance mappings.

    Every valid instance association is presented, in the stable sorted
    order :class:`RobloxInstanceIndex` already guarantees — never an
    arbitrary single pick among duplicates.
    """
    instances = instance_index.file_to_instances.get(rel_path, [])
    if not instances:
        return ""
    lines = ["## DataModel"]
    for instance_path in instances:
        class_name = instance_index.class_names.get(instance_path, "")
        suffix = f" ({class_name})" if class_name else ""
        lines.append(f"- `{instance_path}`{suffix}")
    return "\n".join(lines)


def _resolve_external_edges(
    source_concept_id: str,
    candidates,
    catalog: RobloxApiCatalog,
    namespace: str,
) -> list[tuple[str, str, str]]:
    """Render resolved reference candidates as qualified external edges.

    ``(src, dst, rel)`` — the store's actual convention (verified against
    ``store.py``'s ``add_edges``/``replace_source_slice``). Deduplicated;
    never wraps the destination in a local ``file:`` id, and never feeds
    through ``resolve_import()``.
    """
    seen: set[tuple[str, str]] = set()
    edges: list[tuple[str, str, str]] = []
    for candidate in candidates:
        if candidate.target_name in catalog.classes:
            local_id = class_page_id(candidate.target_name)
        elif candidate.target_name in catalog.enums:
            local_id = enum_page_id(candidate.target_name)
        else:
            continue  # should not happen — extract_api_reference_candidates already filters
        qualified = qualify_id(namespace, local_id)
        key = (qualified, "references")
        if key in seen:
            continue
        seen.add(key)
        edges.append((source_concept_id, qualified, "references"))
    return edges


def _enrich_one_file(
    root: Path,
    file_slice: FileSlice,
    instance_index: RobloxInstanceIndex | None,
    catalog: RobloxApiCatalog | None,
    namespace: str,
    renderer_schema_version: int,
) -> tuple[FileSlice, RobloxFileEnrichment]:
    diagnostics: list[str] = []
    rel_path = file_slice.rel_path

    try:
        source = (root / rel_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        diagnostics.append(f"could not re-read source for enrichment: {exc}")
        empty = RobloxFileEnrichment(rel_path=rel_path, diagnostics=diagnostics)
        return file_slice, empty

    mapping_digest = ""
    datamodel_section = ""
    if instance_index is None or instance_index.source_kind == "none":
        diagnostics.append("no DataModel mapping available")
    else:
        mapping_digest = instance_index.mapping_digest
        datamodel_section = _render_datamodel_section(rel_path, instance_index)
        if not datamodel_section:
            diagnostics.append("no DataModel instance mapped to this file")

    reference_candidates: list = []
    external_edges: list[tuple[str, str, str]] = []
    if catalog is None or (not catalog.classes and not catalog.enums):
        diagnostics.append("no API catalog available, skipped API linking")
    else:
        reference_candidates, ref_diagnostics = extract_api_reference_candidates(source, catalog)
        diagnostics.extend(ref_diagnostics)
        if reference_candidates:
            source_concept_id = file_concept_id(rel_path)
            external_edges = _resolve_external_edges(source_concept_id, reference_candidates, catalog, namespace)

    digest = _dependency_digest(
        mapping_digest,
        catalog.generation_id if catalog is not None else None,
        renderer_schema_version,
        namespace,
    )

    updated_record = file_slice.record
    if datamodel_section:
        new_body = f"{file_slice.record.body}\n\n{datamodel_section}"
        updated_record = file_slice.record.model_copy(
            update={"body": new_body, "token_count": estimate_tokens(new_body)}
        )

    updated_slice = file_slice.model_copy(update={"record": updated_record, "external_edges": external_edges})
    enrichment = RobloxFileEnrichment(
        rel_path=rel_path,
        datamodel_section=datamodel_section,
        reference_candidates=reference_candidates,
        dependency_digest=digest,
        diagnostics=diagnostics,
    )
    return updated_slice, enrichment


def enrich_repo_scan(
    scan: RepoScan,
    *,
    instance_index: RobloxInstanceIndex | None,
    catalog: RobloxApiCatalog | None,
    namespace: str = DEFAULT_ROBLOX_NAMESPACE,
    renderer_schema_version: int = 1,
) -> tuple[RepoScan, dict[str, RobloxFileEnrichment]]:
    """Attach DataModel sections and API reference edges to Luau file slices.

    Args:
        scan: An already-built :class:`RepoScan` (from
            :func:`~parrot.knowledge.wiki.repo_scan.scan_repository`).
            Never mutated — a new instance is returned.
        instance_index: TASK-2898's mapping index, or ``None``/
            ``source_kind="none"`` when no valid mapping exists — every
            file then gets no DataModel section, with a diagnostic, and
            local requires/pages remain fully built (never a build
            failure).
        catalog: TASK-2901's API catalog for the currently published
            generation, or ``None``/empty when no API plane has been
            ingested — every file then gets no external edges, with an
            explicit "skipped-linking" diagnostic, and zero network
            access is ever attempted here.
        namespace: The namespace the Roblox API plane is federated
            under — participates in the dependency digest, so
            reconfiguring it invalidates enrichment.
        renderer_schema_version: The active render schema version —
            participates in the dependency digest.

    Returns:
        ``(enriched_scan, enrichment_by_rel_path)``. Only Luau files
        (``FileSlice.language == "luau"``) are touched; every other
        file's slice is returned byte-for-byte identical (polyglot
        scans and non-Luau languages are entirely unaffected). A file
        with neither a DataModel mapping nor any resolved API reference
        still gets a full, valid :class:`RobloxFileEnrichment` record
        (diagnostics-only) — it is never silently dropped from the
        returned mapping.
    """
    enriched_files: list[FileSlice] = []
    enrichment_by_path: dict[str, RobloxFileEnrichment] = {}

    for file_slice in scan.files:
        if file_slice.language != "luau":
            enriched_files.append(file_slice)
            continue
        updated_slice, enrichment = _enrich_one_file(
            scan.root, file_slice, instance_index, catalog, namespace, renderer_schema_version
        )
        enriched_files.append(updated_slice)
        enrichment_by_path[file_slice.rel_path] = enrichment

    enriched_scan = scan.model_copy(update={"files": enriched_files})
    return enriched_scan, enrichment_by_path
