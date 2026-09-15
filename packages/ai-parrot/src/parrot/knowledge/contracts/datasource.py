"""Catalog-backed ontology datasource for contract cards (FEAT-539 M5).

:class:`ContractCardDataSource` projects the authoritative Postgres catalog
into the five contracts ontology entities. It is registered with
``DataSourceFactory`` under the name ``contractcard`` (the ``source:`` of
every contracts entity in the domain YAML) and receives its **tenant-bound**
catalog through the source configuration — never through a call argument.

Routing note (spec §2): the requested field sets *overlap* — ``Person`` and
``Party`` both carry ``party_id``/``name``, ``Obligation`` carries
``contract_id`` — so entity inference tests the key markers in a fixed
order: ``obligation_id``, ``person_id``, ``party_id``, ``contract_id``,
``standard_id``. A request that is not a subset of the matched entity's
fields is rejected rather than silently projected.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from .catalog import ContractCatalogStore
from .models import ContractCard
from .standards import STANDARDS

try:  # pragma: no cover - satellite package is an optional dependency
    from parrot_loaders.extractors.base import (
        ExtractDataSource,
        ExtractedRecord,
        ExtractionResult,
    )
    from parrot_loaders.extractors.factory import DataSourceFactory

    _LOADERS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the satellite
    _LOADERS_AVAILABLE = False
    ExtractDataSource = object  # type: ignore[assignment,misc]
    ExtractedRecord = None  # type: ignore[assignment]
    ExtractionResult = None  # type: ignore[assignment]
    DataSourceFactory = None  # type: ignore[assignment]

__all__ = (
    "SOURCE_NAME",
    "ENTITY_FIELDS",
    "ENTITY_ROUTING_ORDER",
    "UnknownFieldRequest",
    "ContractCardDataSource",
    "register",
)

logger = logging.getLogger(__name__)

#: The ``source:`` declared by every contracts entity in the domain YAML.
SOURCE_NAME = "contractcard"

#: Key markers tested **in this order** because the field sets overlap.
ENTITY_ROUTING_ORDER: tuple[tuple[str, str], ...] = (
    ("obligation_id", "Obligation"),
    ("person_id", "Person"),
    ("party_id", "Party"),
    ("contract_id", "Contract"),
    ("standard_id", "ComplianceStandard"),
)

#: The fields each entity projection can supply.
ENTITY_FIELDS: dict[str, frozenset[str]] = {
    "Contract": frozenset(
        {
            "contract_id",
            "title",
            "contract_type",
            "status",
            "effective_date",
            "expiration_date",
            "auto_renew",
            "notice_days",
            "notice_deadline",
            "renewal_period_months",
            "governing_law",
            "parent_contract_id",
            "owner_employee_id",
            "department",
            "counterparty_names",
            "verification",
            "verified_by",
            "source_uri",
            "source_sha256",
            "versions",
            "summary",
            "card_revision",
            "active",
        }
    ),
    "Party": frozenset({"party_id", "name", "aliases", "kind", "is_us"}),
    "Person": frozenset({"person_id", "name", "title", "party_id", "employee_id"}),
    "Obligation": frozenset(
        {
            "obligation_id",
            "contract_id",
            "kind",
            "standard_id",
            "obligor",
            "text",
            "node_id",
            "page",
            "due_date",
            "recurrence",
            "verification",
            "active",
        }
    ),
    "ComplianceStandard": frozenset({"standard_id", "name", "aliases"}),
}


class UnknownFieldRequest(ValueError):
    """The requested field set matches no contracts entity unambiguously."""


def _iso(value: Any) -> Any:
    """Render dates/datetimes as ISO-8601 strings, leave the rest alone."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


class ContractCardDataSource(ExtractDataSource):  # type: ignore[misc]
    """Project the contract catalog into ontology entity records.

    Args:
        name: Source name (``contractcard``).
        config: Must carry ``catalog``: a tenant-bound
            :class:`~parrot.knowledge.contracts.catalog.ContractCatalogStore`.
            An ``include_inactive`` flag (default False) is also honoured.

    Raises:
        RuntimeError: When ``ai-parrot-loaders`` is not installed.
        ValueError: When no catalog was injected.
    """

    def __init__(self, name: str = SOURCE_NAME, config: Optional[dict[str, Any]] = None) -> None:
        if not _LOADERS_AVAILABLE:  # pragma: no cover - depends on install extras
            raise RuntimeError(
                "The contracts ontology datasource requires ai-parrot-loaders " "(pip install ai-parrot-loaders)."
            )
        super().__init__(name=name, config=config or {})
        catalog = self.config.get("catalog")
        if not isinstance(catalog, ContractCatalogStore):
            raise ValueError(
                "ContractCardDataSource requires a tenant-bound ContractCatalogStore "
                "in its source config under 'catalog'."
            )
        self.catalog: ContractCatalogStore = catalog
        self.include_inactive: bool = bool(self.config.get("include_inactive", False))

    # -- entity routing ----------------------------------------------------

    @staticmethod
    def infer_entity(fields: Optional[list[str]]) -> str:
        """Infer which entity a field request addresses.

        Args:
            fields: Requested field names, or ``None`` for the Contract
                projection (the primary entity).

        Returns:
            The entity name.

        Raises:
            UnknownFieldRequest: When no key marker is present, or the
                request is not a subset of the matched entity's fields
                (an ambiguous mix of two entities).
        """
        if not fields:
            return "Contract"
        requested = set(fields)
        for marker, entity in ENTITY_ROUTING_ORDER:
            if marker in requested:
                unknown = requested - ENTITY_FIELDS[entity]
                if unknown:
                    raise UnknownFieldRequest(
                        f"field request matched {entity} on {marker!r} but also asks for "
                        f"{sorted(unknown)}; refusing an ambiguous projection"
                    )
                return entity
        raise UnknownFieldRequest(
            f"no contracts entity owns any of {sorted(requested)}; expected one of "
            f"{[marker for marker, _ in ENTITY_ROUTING_ORDER]}"
        )

    # -- projections -------------------------------------------------------

    async def _cards(self, filters: Optional[dict[str, Any]] = None) -> list[ContractCard]:
        """Load the cards a projection covers, honouring standalone filters."""
        cards = await self.catalog.list_cards(active_only=not self.include_inactive)
        selectors = dict(filters or {})
        contract_id = selectors.pop("contract_id", None)
        if contract_id is not None:
            cards = [card for card in cards if card.contract_id == contract_id]
        status = selectors.pop("status", None)
        if status is not None:
            cards = [card for card in cards if card.status == status]
        verification = selectors.pop("verification", None)
        if verification is not None:
            cards = [card for card in cards if card.verification == verification]
        party_id = selectors.pop("party_id", None)
        if party_id is not None:
            cards = [card for card in cards if any(party.party_id == party_id for party in card.parties)]
        if selectors:
            raise UnknownFieldRequest(f"unsupported filters: {sorted(selectors)}")
        return sorted(cards, key=lambda card: card.contract_id)

    @staticmethod
    def _contract_record(card: ContractCard) -> dict[str, Any]:
        """Project one card into the ``Contract`` vertex payload."""
        return {
            "contract_id": card.contract_id,
            "title": card.title,
            "contract_type": card.contract_type,
            "status": card.status,
            "effective_date": _iso(card.term.effective_date),
            "expiration_date": _iso(card.term.expiration_date),
            "auto_renew": card.term.auto_renew,
            "notice_days": card.term.notice_days,
            "notice_deadline": _iso(card.term.notice_deadline),
            "renewal_period_months": card.term.renewal_period_months,
            "governing_law": card.governing_law,
            "parent_contract_id": card.parent_contract_id,
            "owner_employee_id": card.owner_employee_id,
            "department": card.department,
            "counterparty_names": [party.name for party in card.counterparties],
            "verification": card.verification,
            "verified_by": card.verified_by,
            "source_uri": card.source_uri,
            "source_sha256": card.source_sha256,
            "versions": [
                {
                    "n": version.n,
                    "revision": version.revision,
                    "valid_from": _iso(version.valid_from),
                    "valid_to": _iso(version.valid_to),
                    "kind": version.kind,
                    "amended_by": version.amended_by,
                    "source_sha256": version.source_sha256,
                }
                for version in card.versions
            ],
            "summary": card.summary,
            "card_revision": card.revision,
            "active": card.active,
        }

    @staticmethod
    def _party_records(
        cards: list[ContractCard],
        aliases: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        """Project catalog-wide party identity, unioning aliases."""
        parties: dict[str, dict[str, Any]] = {}
        for card in cards:
            for party in card.parties:
                record = parties.setdefault(
                    party.party_id,
                    {
                        "party_id": party.party_id,
                        "name": party.name,
                        "aliases": [],
                        "kind": party.role,
                        "is_us": party.is_us,
                    },
                )
                record["is_us"] = record["is_us"] or party.is_us
                if party.name != record["name"] and party.name not in record["aliases"]:
                    record["aliases"].append(party.name)
        for party_id, values in aliases.items():
            record = parties.get(party_id)
            if record is None:
                continue
            for alias in values:
                if alias not in record["aliases"]:
                    record["aliases"].append(alias)
        for record in parties.values():
            record["aliases"] = sorted(record["aliases"])
        return [parties[key] for key in sorted(parties)]

    @staticmethod
    def _person_records(cards: list[ContractCard]) -> list[dict[str, Any]]:
        """Project signatories as ``Person`` vertices."""
        people: dict[str, dict[str, Any]] = {}
        for card in cards:
            for signatory in card.signatories:
                people.setdefault(
                    signatory.person_id,
                    {
                        "person_id": signatory.person_id,
                        "name": signatory.name,
                        "title": signatory.title,
                        "party_id": signatory.party_id,
                        "employee_id": signatory.employee_id,
                    },
                )
        return [people[key] for key in sorted(people)]

    @staticmethod
    def _obligation_records(cards: list[ContractCard]) -> list[dict[str, Any]]:
        """Project obligations as ``Obligation`` vertices."""
        records: list[dict[str, Any]] = []
        for card in cards:
            for obligation in card.obligations:
                records.append(
                    {
                        "obligation_id": obligation.obligation_id,
                        "contract_id": obligation.contract_id,
                        "kind": obligation.kind,
                        "standard_id": obligation.standard_id,
                        "obligor": obligation.obligor,
                        "text": obligation.text,
                        "node_id": obligation.node_id,
                        "page": obligation.page,
                        "due_date": _iso(obligation.due_date),
                        "recurrence": obligation.recurrence,
                        "verification": obligation.verification,
                        "active": obligation.active and card.active,
                    }
                )
        records.sort(key=lambda record: record["obligation_id"])
        return records

    @staticmethod
    def _standard_records() -> list[dict[str, Any]]:
        """Return the eight static ``ComplianceStandard`` seeds.

        Seeding happens before ``requires`` edges are discovered, so the
        list is static and deterministic — never derived from cards.
        """
        return [
            {
                "standard_id": standard.standard_id,
                "name": standard.name,
                "aliases": list(standard.aliases),
            }
            for standard in STANDARDS.values()
        ]

    async def records_for(
        self,
        entity: str,
        *,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Project one entity's records.

        Args:
            entity: One of the five contracts entities.
            filters: Standalone selection filters.

        Returns:
            Deterministically ordered plain dicts.

        Raises:
            UnknownFieldRequest: On an unknown entity or filter.
        """
        if entity == "ComplianceStandard":
            return self._standard_records()
        if entity not in ENTITY_FIELDS:
            raise UnknownFieldRequest(f"unknown contracts entity {entity!r}")

        cards = await self._cards(filters)
        if entity == "Contract":
            return [self._contract_record(card) for card in cards]
        if entity == "Party":
            return self._party_records(cards, await self.catalog.all_party_aliases())
        if entity == "Person":
            return self._person_records(cards)
        return self._obligation_records(cards)

    async def snapshot(
        self,
        *,
        filters: Optional[dict[str, Any]] = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return a complete, prevalidated snapshot of every entity.

        The graph loader preflights this before mutating anything, so an
        extraction failure can never be mistaken for "everything was
        deleted".

        Args:
            filters: Optional standalone filters (never used by the
                full-catalog refresh path).

        Returns:
            ``entity name -> records`` for all five entities.
        """
        return {
            entity: await self.records_for(entity, filters=filters)
            for entity in ("Contract", "Party", "Person", "Obligation", "ComplianceStandard")
        }

    # -- ExtractDataSource API --------------------------------------------

    async def extract(
        self,
        fields: Optional[list[str]] = None,
        filters: Optional[dict[str, Any]] = None,
    ) -> "ExtractionResult":
        """Extract one entity's records for the ontology refresh pipeline.

        Extraction failures propagate: an unreachable catalog must never be
        reported as a successful empty snapshot, because the generic diff
        would soft-delete every existing node.

        Args:
            fields: The entity's property names (the pipeline passes these).
            filters: Optional standalone filters.

        Returns:
            An :class:`ExtractionResult` with plain-dict records.

        Raises:
            UnknownFieldRequest: On an unrecognised/ambiguous field request.
        """
        entity = self.infer_entity(fields)
        records = await self.records_for(entity, filters=filters)
        requested = set(fields or [])
        payloads = [
            {key: value for key, value in record.items() if not requested or key in requested} for record in records
        ]
        logger.debug("Projected %d %s records for %s", len(payloads), entity, self.name)
        return ExtractionResult(
            records=[
                ExtractedRecord(data=payload, metadata={"entity": entity, "source": self.name}) for payload in payloads
            ],
            total=len(payloads),
            source_name=self.name,
            extracted_at=datetime.now(tz=timezone.utc),
        )

    async def list_fields(self) -> list[str]:
        """Return every field any contracts entity can supply."""
        return sorted({field for fields in ENTITY_FIELDS.values() for field in fields})


def register() -> None:
    """Register this datasource under ``contractcard``.

    Idempotent; a no-op when ``ai-parrot-loaders`` is not installed.
    """
    if not _LOADERS_AVAILABLE:  # pragma: no cover - depends on install extras
        logger.debug("ai-parrot-loaders is not installed; contractcard not registered")
        return
    DataSourceFactory.register_api_source(SOURCE_NAME, ContractCardDataSource)


register()
