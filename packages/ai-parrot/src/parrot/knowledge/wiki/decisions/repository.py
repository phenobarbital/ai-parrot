"""Store-facing persistence for ADR records (FEAT-578 Module 2).

The only module in ``decisions/`` that touches a :class:`BaseWikiStore`, and
the only place the store's raw failures become typed :class:`DecisionError`
codes. Every ADR mutation in the feature goes through :meth:`save`.
"""

from __future__ import annotations

import logging

from parrot.knowledge.wiki.decisions.codec import decision_from_page, decision_to_page
from parrot.knowledge.wiki.decisions.models import (
    ADR_CATEGORY,
    ADR_INVENTORY_LIMIT,
    ADR_READ_ONLY,
    ADR_REVISION_CONFLICT,
    ADR_WRITE_UNSUPPORTED,
    DecisionDiagnostic,
    DecisionError,
    DecisionRecord,
)
from parrot.knowledge.wiki.store import BaseWikiStore


class DecisionRepository:
    """Bounded ADR inventory reads and compare-and-swap writes."""

    def __init__(self, store: BaseWikiStore, max_records: int = 10_000) -> None:
        """Bind a backend without bypassing its read-only policy.

        Args:
            store: Any wiki backend. A read-only or CAS-less store is
                accepted here and refused at write time, so reads keep
                working on a foreign or archived plane.
            max_records: Inventory bound from ``DecisionConfig.max_records``.
        """
        self._store = store
        self._max_records = max_records
        self.logger = logging.getLogger(__name__)
        #: Decode failures from the last ``inventory()`` call, surfaced by the
        #: service as dossier diagnostics rather than raised.
        self.last_diagnostics: list[DecisionDiagnostic] = []

    async def get(self, decision_id: str) -> tuple[DecisionRecord, str | None] | None:
        """Load one record together with the page hash to CAS against.

        Returns:
            ``(record, content_hash)``, or ``None`` when no such page
            exists. Pass the returned hash straight back to :meth:`save`
            as ``expected_content_hash`` — reading it from anywhere else
            reopens the race this class exists to close.

        Raises:
            DecisionError: ``ADR_SCHEMA_UNSUPPORTED`` when the page exists
                but is not a decodable managed record.
        """
        page = await self._store.get_page(decision_id, include_body=True)
        if page is None:
            return None
        return decision_from_page(page), page.get("content_hash")

    async def inventory(self) -> list[DecisionRecord]:
        """Load the complete bounded ADR inventory.

        Reads ``limit=max_records + 1`` so an overflow is detectable rather
        than silently truncated into a wrong "no decisions" answer.

        Raises:
            DecisionError: ``ADR_INVENTORY_LIMIT`` when the plane holds more
                than ``max_records`` ADR pages.
        """
        self.last_diagnostics = []
        stubs = await self._store.list_pages(category=ADR_CATEGORY, limit=self._max_records + 1)
        if len(stubs) > self._max_records:
            raise DecisionError(
                ADR_INVENTORY_LIMIT,
                f"ADR inventory exceeds max_records={self._max_records}; raise the bound or prune records",
            )
        records: list[DecisionRecord] = []
        for stub in stubs:
            concept_id = stub.get("concept_id")
            page = await self._store.get_page(concept_id, include_body=True)
            if page is None:
                # Deleted between list_pages() and get_page() — not an
                # inventory-level error, just skip it.
                continue
            try:
                records.append(decision_from_page(page))
            except DecisionError as exc:
                self.last_diagnostics.append(
                    DecisionDiagnostic(code=exc.code, message=str(exc), decision_id=exc.decision_id or concept_id)
                )
        return records

    async def save(self, record: DecisionRecord, expected_content_hash: str | None) -> DecisionRecord:
        """CAS one full record and its audit history.

        Args:
            record: The complete replacement record, audit history included.
                Partial writes do not exist — the page body is the record.
            expected_content_hash: The hash returned by :meth:`get`, or
                ``None`` to insert a record that must not already exist.

        Returns:
            The record as written.

        Raises:
            DecisionError: ``ADR_REVISION_CONFLICT`` when the precondition
                did not hold, ``ADR_WRITE_UNSUPPORTED`` on a backend without
                a conditional write, ``ADR_READ_ONLY`` on a read-only plane,
                ``ADR_RECORD_TOO_LARGE`` from the codec.
        """
        page = decision_to_page(record)
        try:
            ok = await self._store.compare_and_swap_page(page, expected_content_hash)
        except NotImplementedError as exc:
            raise DecisionError(
                ADR_WRITE_UNSUPPORTED,
                f"backend {type(self._store).__name__} has no conditional page write",
                decision_id=record.decision_id,
            ) from exc
        except PermissionError as exc:
            raise DecisionError(ADR_READ_ONLY, str(exc), decision_id=record.decision_id) from exc
        if not ok:
            raise DecisionError(
                ADR_REVISION_CONFLICT,
                f"{record.decision_id} changed since it was read; re-read and retry the review",
                decision_id=record.decision_id,
            )
        self.logger.debug("save: wrote %s revision %s", record.decision_id, record.revision)
        return record
