"""Opaque-Source Resolvers for FEAT-228 Data-Plane Authorization.

Per-type resource identifier extraction for non-SQL DataSource subclasses
(Mongo, Iceberg, Delta, Airtable, Smartsheet).  Each source type has a
dedicated extraction strategy that returns a :class:`PhysicalResources` with
``source_type`` and ``source_id`` populated.

Resource identifier format (Spec §2):
    ``source:<type>:<identifier>``
    (e.g. ``source:mongo:finance_db.transactions``)

This module is imported lazily by the physical-resource resolver
(:mod:`parrot.tools.dataset_manager.sources.resolver`) for any source type
it does not handle directly.  All source imports are conditional (wrapped in
``try/except ImportError``) because Mongo, Iceberg, and Delta are optional
dependencies.

Usage::

    from parrot.tools.dataset_manager.sources.opaque import resolve_opaque_source

    resources = resolve_opaque_source(mongo_source)
    # resources.source_type = "mongo"
    # resources.source_id  = "finance_db.transactions"
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parrot.tools.dataset_manager.sources.base import DataSource
    from parrot.tools.dataset_manager.sources.resolver import PhysicalResources


def resolve_opaque_source(source: "DataSource") -> "PhysicalResources":
    """Extract resource identifiers from non-SQL DataSource subclasses.

    Uses ``isinstance`` dispatch per source type.  All imports are
    conditional so missing optional dependencies cause a graceful fallback
    to an empty :class:`PhysicalResources` rather than an ``ImportError``.

    Args:
        source: Any :class:`~parrot.tools.dataset_manager.sources.base.DataSource`
            subclass.  SQL sources are **not** handled here; they belong to the
            main resolver.

    Returns:
        :class:`PhysicalResources` with ``source_type`` and ``source_id``
        populated for known source types, or empty for unrecognised types.
    """
    from parrot.tools.dataset_manager.sources.resolver import PhysicalResources

    # ── MongoSource ─────────────────────────────────────────────────────────
    try:
        from parrot.tools.dataset_manager.sources.mongo import MongoSource

        if isinstance(source, MongoSource):
            return PhysicalResources(
                source_type="mongo",
                source_id=f"{source._database}.{source._collection}",
            )
    except ImportError:
        pass

    # ── IcebergSource ────────────────────────────────────────────────────────
    try:
        from parrot.tools.dataset_manager.sources.iceberg import IcebergSource

        if isinstance(source, IcebergSource):
            return PhysicalResources(
                source_type="iceberg",
                # table_id is already fully-qualified, e.g. "demo.cities"
                source_id=source._table_id,
            )
    except ImportError:
        pass

    # ── DeltaTableSource ─────────────────────────────────────────────────────
    try:
        from parrot.tools.dataset_manager.sources.deltatable import DeltaTableSource

        if isinstance(source, DeltaTableSource):
            return PhysicalResources(
                source_type="delta",
                # _path is the canonical identifier (local, s3://, gs://)
                source_id=source._path,
            )
    except ImportError:
        pass

    # ── AirtableSource ───────────────────────────────────────────────────────
    try:
        from parrot.tools.dataset_manager.sources.airtable import AirtableSource

        if isinstance(source, AirtableSource):
            return PhysicalResources(
                source_type="airtable",
                source_id=f"{source.base_id}.{source.table}",
            )
    except ImportError:
        pass

    # ── SmartsheetSource ─────────────────────────────────────────────────────
    try:
        from parrot.tools.dataset_manager.sources.smartsheet import SmartsheetSource

        if isinstance(source, SmartsheetSource):
            return PhysicalResources(
                source_type="smartsheet",
                source_id=str(source.sheet_id),
            )
    except ImportError:
        pass

    # Unknown opaque source — fail-open (no resource info)
    return PhysicalResources()
