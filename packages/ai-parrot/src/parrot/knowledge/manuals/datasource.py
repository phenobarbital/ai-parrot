"""``manualcard`` ontology datasource: catalog cards to entity records (FEAT-601 M8)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from .catalog import ManualCatalogStore
from .models import ManualCard

try:  # pragma: no cover - satellite package is an optional dependency
    from parrot_loaders.extractors.base import ExtractDataSource, ExtractedRecord, ExtractionResult
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
    "ManualCardDataSource",
    "register",
)

logger = logging.getLogger(__name__)

SOURCE_NAME = "manualcard"
ENTITIES: tuple[str, ...] = ("Equipment", "Manual", "Procedure", "Step", "Part", "Tool", "Hazard", "Media")
ENTITY_ROUTING_ORDER: tuple[tuple[str, str], ...] = (
    ("step_id", "Step"),
    ("media_id", "Media"),
    ("hazard_id", "Hazard"),
    ("part_id", "Part"),
    ("tool_id", "Tool"),
    ("procedure_id", "Procedure"),
    ("equipment_id", "Equipment"),
    ("manual_id", "Manual"),
)
ENTITY_FIELDS: dict[str, frozenset[str]] = {
    "Manual": frozenset({"manual_id", "revision", "source_sha256", "active", "versions", "procedure_ids"}),
    "Equipment": frozenset({"equipment_id", "model", "family", "revision", "aliases"}),
    "Procedure": frozenset(
        {
            "procedure_id",
            "kind",
            "title",
            "estimated_minutes",
            "skill_level",
            "active",
            "verification",
            "versions",
            "manual_id",
            "equipment_ids",
            "step_ids",
            "overview_media_ids",
            "supersedes",
        }
    ),
    "Step": frozenset(
        {
            "step_id",
            "order",
            "source_identity",
            "content_hash",
            "text",
            "torque",
            "duration_minutes",
            "applies_models",
            "applies_serial_ranges",
            "node_id",
            "page",
            "active",
            "procedure_id",
            "parts",
            "tool_ids",
            "hazard_ids",
            "media",
            "precedes",
        }
    ),
    "Part": frozenset({"part_id", "part_number", "name"}),
    "Tool": frozenset({"tool_id", "name", "spec"}),
    "Hazard": frozenset({"hazard_id", "severity", "text"}),
    "Media": frozenset(
        {"media_id", "kind", "storage_key", "uri", "page", "caption", "label", "t_start", "t_end", "origin", "callouts"}
    ),
}


class UnknownFieldRequest(ValueError):
    """A field request that no manuals entity owns, or an ambiguous mix of two."""


def _iso(value: Any) -> Any:
    """Serialize dates and datetimes to ISO strings; pass all other values through."""
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def _versions(versions: list[Any]) -> list[dict[str, Any]]:
    """Project bitemporal version metadata without recursive card snapshots."""
    return [
        {
            "n": version.n,
            "revision": version.revision,
            "valid_from": _iso(version.valid_from),
            "valid_to": _iso(version.valid_to),
            "source_sha256": version.source_sha256,
            "recorded_at": _iso(version.recorded_at),
            "evidence_ref": version.evidence_ref,
        }
        for version in versions
    ]


class ManualCardDataSource(ExtractDataSource):  # type: ignore[misc]
    """Project the manual catalog into ontology entity records."""

    def __init__(self, name: str = SOURCE_NAME, config: Optional[dict[str, Any]] = None) -> None:
        if not _LOADERS_AVAILABLE:  # pragma: no cover - depends on install extras
            raise RuntimeError(
                "The manuals ontology datasource requires ai-parrot-loaders (pip install ai-parrot-loaders)."
            )
        super().__init__(name=name, config=config or {})
        catalog = self.config.get("catalog")
        if not isinstance(catalog, ManualCatalogStore):
            raise ValueError("ManualCardDataSource requires a tenant-bound ManualCatalogStore under config['catalog'].")
        self.catalog: ManualCatalogStore = catalog
        self.include_inactive: bool = bool(self.config.get("include_inactive", False))

    def infer_entity(self, fields: Optional[list[str]]) -> str:
        """Route a field request to an entity by its first fixed key marker."""
        if not fields:
            return "Manual"
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
            f"no manuals entity owns any of {sorted(requested)}; expected one of "
            f"{[marker for marker, _ in ENTITY_ROUTING_ORDER]}"
        )

    async def _cards(self, filters: Optional[dict[str, Any]] = None) -> list[ManualCard]:
        """Load deterministic cards, optionally filtered by manual identity."""
        cards = await self.catalog.list_cards(active_only=not self.include_inactive)
        selectors = dict(filters or {})
        manual_id = selectors.pop("manual_id", None)
        if manual_id is not None:
            cards = [card for card in cards if card.manual_id == manual_id]
        if selectors:
            raise UnknownFieldRequest(f"unsupported filters: {sorted(selectors)}")
        return sorted(cards, key=lambda card: card.manual_id)

    def _procedures(self, card: ManualCard) -> list[Any]:
        """Return projected procedures respecting the inactive-record configuration."""
        return [procedure for procedure in card.procedures if self.include_inactive or procedure.active]

    def _manual_records(self, cards: list[ManualCard]) -> list[dict[str, Any]]:
        """Project one document-level record per manual card."""
        return [
            {
                "manual_id": card.manual_id,
                "revision": card.revision,
                "source_sha256": card.source_sha256,
                "active": True,
                "versions": _versions(card.versions),
                "procedure_ids": [procedure.procedure_id for procedure in self._procedures(card)],
            }
            for card in cards
        ]

    @staticmethod
    def _equipment_records(cards: list[ManualCard]) -> list[dict[str, Any]]:
        """Project catalog-wide equipment identities, deduplicated by id."""
        records: dict[str, dict[str, Any]] = {}
        for card in cards:
            for equipment in card.equipment:
                records.setdefault(
                    equipment.equipment_id,
                    {
                        "equipment_id": equipment.equipment_id,
                        "model": equipment.model,
                        "family": equipment.family,
                        "revision": equipment.revision,
                        "aliases": list(equipment.aliases),
                    },
                )
        return [records[key] for key in sorted(records)]

    def _procedure_records(self, cards: list[ManualCard]) -> list[dict[str, Any]]:
        """Project active procedures and their traversal relationship payloads."""
        records: list[dict[str, Any]] = []
        for card in cards:
            equipment_ids = [equipment.equipment_id for equipment in card.equipment]
            overview_media_ids = [media.media_id for media in card.figures if media.kind == "video_segment"]
            for procedure in self._procedures(card):
                records.append(
                    {
                        "procedure_id": procedure.procedure_id,
                        "kind": procedure.kind,
                        "title": procedure.title.value,
                        "estimated_minutes": procedure.estimated_minutes,
                        "skill_level": procedure.skill_level,
                        "active": procedure.active,
                        "verification": procedure.verification,
                        "versions": _versions(procedure.versions),
                        "manual_id": card.manual_id,
                        "equipment_ids": equipment_ids,
                        "step_ids": [
                            {"step_id": step.identity.step_id, "order": step.order}
                            for step in sorted(procedure.steps, key=lambda step: step.order)
                        ],
                        "overview_media_ids": overview_media_ids,
                        "supersedes": procedure.supersedes,
                    }
                )
        return sorted(records, key=lambda record: record["procedure_id"])

    def _step_records(self, cards: list[ManualCard]) -> list[dict[str, Any]]:
        """Project steps with exact edge-builder fields and deterministic order edges."""
        records: list[dict[str, Any]] = []
        for card in cards:
            for procedure in self._procedures(card):
                steps = sorted(procedure.steps, key=lambda step: step.order)
                for index, step in enumerate(steps):
                    next_steps = (
                        []
                        if index + 1 == len(steps)
                        else [{"step_id": steps[index + 1].identity.step_id, "kind": "order"}]
                    )
                    evidence = step.text.evidence
                    records.append(
                        {
                            "step_id": step.identity.step_id,
                            "order": step.order,
                            "source_identity": step.identity.source_identity,
                            "content_hash": step.identity.content_hash,
                            "text": step.text.value,
                            "torque": step.torque.value if step.torque else None,
                            "duration_minutes": step.duration_minutes.value if step.duration_minutes else None,
                            "applies_models": list(step.applicability.models),
                            "applies_serial_ranges": [
                                serial_range.model_dump(mode="json")
                                for serial_range in step.applicability.serial_ranges
                            ],
                            "node_id": evidence.node_id if evidence else None,
                            "page": evidence.page if evidence else None,
                            "active": procedure.active,
                            "procedure_id": procedure.procedure_id,
                            "parts": [
                                {"part_id": part.part_id, "quantity": part.quantity, "context": None}
                                for part in step.parts
                            ],
                            "tool_ids": [tool.tool_id for tool in step.tools],
                            "hazard_ids": [hazard.hazard_id for hazard in step.hazards],
                            "media": [
                                {
                                    "media_id": media.media_id,
                                    "role": media.role,
                                    "confidence": media.confidence,
                                    "origin": media.origin,
                                }
                                for media in step.media
                            ],
                            "precedes": next_steps,
                        }
                    )
        return sorted(records, key=lambda record: record["step_id"])

    def _part_records(self, cards: list[ManualCard]) -> list[dict[str, Any]]:
        """Project parts referenced globally or by active procedures, deduplicated by id."""
        records: dict[str, dict[str, Any]] = {}
        for card in cards:
            parts = list(card.global_parts)
            parts.extend(
                part for procedure in self._procedures(card) for step in procedure.steps for part in step.parts
            )
            for part in parts:
                records.setdefault(
                    part.part_id,
                    {"part_id": part.part_id, "part_number": part.part_number, "name": part.name.value},
                )
        return [records[key] for key in sorted(records)]

    def _tool_records(self, cards: list[ManualCard]) -> list[dict[str, Any]]:
        """Project tools referenced globally or by active procedures, deduplicated by id."""
        records: dict[str, dict[str, Any]] = {}
        for card in cards:
            tools = list(card.global_tools)
            tools.extend(
                tool for procedure in self._procedures(card) for step in procedure.steps for tool in step.tools
            )
            for tool in tools:
                records.setdefault(tool.tool_id, {"tool_id": tool.tool_id, "name": tool.name.value, "spec": tool.spec})
        return [records[key] for key in sorted(records)]

    def _hazard_records(self, cards: list[ManualCard]) -> list[dict[str, Any]]:
        """Project hazards referenced globally or by active procedures, deduplicated by id."""
        records: dict[str, dict[str, Any]] = {}
        for card in cards:
            hazards = list(card.global_hazards)
            hazards.extend(
                hazard for procedure in self._procedures(card) for step in procedure.steps for hazard in step.hazards
            )
            for hazard in hazards:
                records.setdefault(
                    hazard.hazard_id,
                    {"hazard_id": hazard.hazard_id, "severity": hazard.severity, "text": hazard.text.value},
                )
        return [records[key] for key in sorted(records)]

    @staticmethod
    def _media_records(cards: list[ManualCard]) -> list[dict[str, Any]]:
        """Project catalog-wide media records, deduplicated by id."""
        records: dict[str, dict[str, Any]] = {}
        for card in cards:
            for media in card.figures:
                records.setdefault(
                    media.media_id,
                    {
                        "media_id": media.media_id,
                        "kind": media.kind,
                        "storage_key": media.storage_key,
                        "uri": media.uri,
                        "page": media.page,
                        "caption": media.caption,
                        "label": media.label,
                        "t_start": media.t_start,
                        "t_end": media.t_end,
                        "origin": media.origin,
                        "callouts": [
                            {
                                "part_id": callout.part_id,
                                "callout": callout.callout,
                                "confidence": callout.confidence,
                                "origin": callout.origin,
                            }
                            for callout in media.callouts
                        ],
                    },
                )
        return [records[key] for key in sorted(records)]

    async def records_for(self, entity: str, *, filters: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        """Project one entity's records; unknown entity requests fail loudly."""
        if entity not in ENTITY_FIELDS:
            raise UnknownFieldRequest(f"unknown manuals entity {entity!r}")
        cards = await self._cards(filters)
        projectors = {
            "Manual": self._manual_records,
            "Equipment": self._equipment_records,
            "Procedure": self._procedure_records,
            "Step": self._step_records,
            "Part": self._part_records,
            "Tool": self._tool_records,
            "Hazard": self._hazard_records,
            "Media": self._media_records,
        }
        return projectors[entity](cards)

    async def snapshot(self, *, filters: Optional[dict[str, Any]] = None) -> dict[str, list[dict[str, Any]]]:
        """Return all eight prevalidated entities for graph-loader preflight."""
        return {entity: await self.records_for(entity, filters=filters) for entity in ENTITIES}

    async def extract(
        self, fields: list[str] | None = None, filters: dict[str, Any] | None = None
    ) -> "ExtractionResult":
        """Extract one entity's records; catalog failures propagate unchanged."""
        entity = self.infer_entity(fields)
        records = await self.records_for(entity, filters=filters)
        requested = set(fields or [])
        payloads = [
            {key: value for key, value in record.items() if not requested or key in requested} for record in records
        ]
        self.logger.debug("Projected %d %s records for %s", len(payloads), entity, self.name)
        return ExtractionResult(
            records=[
                ExtractedRecord(data=payload, metadata={"entity": entity, "source": self.name}) for payload in payloads
            ],
            total=len(payloads),
            source_name=self.name,
            extracted_at=datetime.now(tz=timezone.utc),
        )

    async def list_fields(self) -> list[str]:
        """Return every field supplied by any owned manuals entity."""
        return sorted({field for fields in ENTITY_FIELDS.values() for field in fields})


def register() -> None:
    """Register under ``manualcard``; idempotent and optional-loader safe."""
    if not _LOADERS_AVAILABLE:  # pragma: no cover
        logger.debug("ai-parrot-loaders is not installed; manualcard not registered")
        return
    DataSourceFactory.register_api_source(SOURCE_NAME, ManualCardDataSource)


register()
