"""Contracts card & ontology — the core data plane (FEAT-539).

This package owns typed contract models, the async Postgres catalog,
carding, the contract library, evidence archiving and the ontology /
temporal projections. Toolkit, agents, answer flow, jobs and CLI live in
the tools satellite (``parrot_tools.contracts``); core never imports it.

Models and the seeded compliance standards are exported eagerly. The
heavier services are resolved lazily on first attribute access so that
importing the package does not require asyncpg, arango or a PageIndex
backend to be installed.
"""

from __future__ import annotations

from typing import Any

from .models import (
    AnswerKind,
    AnswerProvenance,
    AnswerRecord,
    AuthorizationOutcome,
    CardOrigin,
    Citation,
    ContractAnswer,
    ContractCard,
    ContractHeaderDraft,
    ContractRelation,
    ContractStatus,
    ContractType,
    ContractVersion,
    Evidence,
    Extracted,
    FieldProvenance,
    HandoffBrief,
    IngestItemReport,
    IngestOutcome,
    IngestReport,
    IngestResult,
    Obligation,
    ObligationClauseDraft,
    ObligationKind,
    ObligationsDraft,
    Obligor,
    Party,
    PartyAlias,
    PartyDraft,
    PartyRole,
    PublicationRecord,
    PublicationState,
    PublicationTarget,
    RelationJudgement,
    RelationKind,
    Signatory,
    SignatoryDraft,
    SourceDeltaToken,
    SourceFormat,
    SourceItem,
    TermSpec,
    TocEntry,
    VerificationState,
    VersionKind,
    card_snapshot_payload,
    derive_provenance,
)
from .standards import (
    STANDARD_IDS,
    STANDARDS,
    ComplianceStandard,
    find_standards,
    get_standard,
    normalize_standard_text,
    resolve_standard,
)

#: Public names resolved lazily to the sibling module that defines them.
_LAZY_EXPORTS: dict[str, str] = {
    "ContractCatalogStore": "catalog",
    "CatalogConflictError": "catalog",
    "PostgresContractCatalog": "catalog_postgres",
    "ContractLibrary": "library",
    "EvidenceArchive": "evidence",
    "ContractCardDataSource": "datasource",
    "ContractGraphLoader": "graph_loader",
    "ContractTemporalPublisher": "temporal",
    "ContractRelationStage": "relations",
}

__all__ = (
    "AnswerKind",
    "AnswerProvenance",
    "AnswerRecord",
    "AuthorizationOutcome",
    "CardOrigin",
    "Citation",
    "ComplianceStandard",
    "ContractAnswer",
    "ContractCard",
    "ContractCardDataSource",
    "ContractCatalogStore",
    "ContractGraphLoader",
    "ContractHeaderDraft",
    "ContractLibrary",
    "ContractRelation",
    "ContractRelationStage",
    "ContractStatus",
    "ContractTemporalPublisher",
    "ContractType",
    "ContractVersion",
    "CatalogConflictError",
    "Evidence",
    "EvidenceArchive",
    "Extracted",
    "FieldProvenance",
    "HandoffBrief",
    "IngestItemReport",
    "IngestOutcome",
    "IngestReport",
    "IngestResult",
    "Obligation",
    "ObligationClauseDraft",
    "ObligationKind",
    "ObligationsDraft",
    "Obligor",
    "Party",
    "PartyAlias",
    "PartyDraft",
    "PartyRole",
    "PostgresContractCatalog",
    "PublicationRecord",
    "PublicationState",
    "PublicationTarget",
    "RelationJudgement",
    "RelationKind",
    "STANDARDS",
    "STANDARD_IDS",
    "Signatory",
    "SignatoryDraft",
    "SourceDeltaToken",
    "SourceFormat",
    "SourceItem",
    "TermSpec",
    "TocEntry",
    "VerificationState",
    "VersionKind",
    "card_snapshot_payload",
    "derive_provenance",
    "find_standards",
    "get_standard",
    "normalize_standard_text",
    "resolve_standard",
)


def __getattr__(name: str) -> Any:
    """Resolve the lazily exported contracts services on first access.

    Args:
        name: Attribute being imported from the package.

    Returns:
        The requested class.

    Raises:
        AttributeError: When ``name`` is not a contracts export.
    """
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    module = import_module(f"{__name__}.{module_name}")
    return getattr(module, name)


def __dir__() -> list[str]:
    """List eager and lazy exports for interactive completion."""
    return sorted(__all__)
