"""Manuals knowledge plane — equipment procedure graph (FEAT-601).

Every public name is resolved lazily from the submodule that defines it, so
importing ``parrot.knowledge.manuals`` needs no asyncpg, arango or pymupdf.
"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY_EXPORTS: dict[str, str] = {
    **dict.fromkeys(
        (
            "ManualCard",
            "Procedure",
            "Step",
            "StepIdentity",
            "PartRef",
            "ToolRef",
            "Hazard",
            "MediaRef",
            "MediaLink",
            "SerialRange",
            "Applicability",
            "Callout",
            "CalloutMap",
            "CalloutLink",
            "ManualVersion",
            "EquipmentRef",
            "Tip",
            "mint_step_id",
            "content_hash",
            "normalize_serial",
            "applies",
            "manual_snapshot_payload",
            "ProcedureCitation",
            "derive_provenance",
            "ProcedureRef",
            "ProcedureView",
            "StepView",
            "HazardView",
            "MediaView",
            "TipView",
            "Prerequisites",
            "ProcedureAnswer",
        ),
        "models",
    ),
    "PROCEDURES_DOMAIN": "domain",
    "ProceduresDomainNotLoaded": "domain",
    "default_tenant_manager": "domain",
    "ManualCatalogStore": "catalog",
    "SearchHit": "catalog",
    "UpsertResult": "catalog",
    "VerificationQueueEntry": "catalog",
    "AnswerRecord": "catalog",
    "PublicationRecord": "catalog",
    "PostgresManualCatalog": "catalog_postgres",
    "draft_manual": "carding",
    "assemble_card": "carding",
    "extract_figures": "figures",
    "pair_figures": "figures",
    "caption_figures": "figures",
    "upload_figures": "figures",
    "presign": "figures",
    "map_callouts": "figures",
    "align_video": "video",
    "relink_tips": "tips",
    "add_tip": "tips",
    "retire_tip": "tips",
    "RelinkReport": "tips",
    "ManualCardDataSource": "datasource",
    "ManualGraphLoader": "graph_loader",
    "EdgeSpec": "graph_loader",
    "GraphPublicationReport": "graph_loader",
    "ManualLibrary": "library",
    "IngestResult": "library",
    "export_bundle": "export",
}

__all__ = tuple(sorted(_LAZY_EXPORTS))


def __getattr__(name: str) -> Any:
    """Resolve a public name from its defining submodule on first access."""
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f".{module_name}", __name__), name)
    globals()[name] = value
    return value
