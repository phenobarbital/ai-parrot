"""Publish the manual catalog into the tenant ontology graph (FEAT-601 M9).

Only manual-owned collections are reconciled. Technician collections are
never read, pruned or deleted here; tips are re-linked afterwards.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Literal, Mapping, Optional, Sequence

from pydantic import BaseModel, Field

from parrot.knowledge.ontology.schema import TenantContext

from .catalog import ManualCatalogStore
from .datasource import ManualCardDataSource
from .domain import (
    OWNED_EDGE_COLLECTIONS,
    OWNED_VERTEX_COLLECTIONS,
    PROCEDURES_DOMAIN,
    TECHNICIAN_COLLECTIONS,
    ProceduresDomainNotLoaded,
    default_tenant_manager,
    resolve_context,
)
from .models import ManualCard, Step
from .tips import RelinkReport, relink_tips

logger = logging.getLogger(__name__)

ENTITY_COLLECTIONS: dict[str, str] = {
    "Equipment": "equipment",
    "Manual": "manual",
    "Procedure": "procedure",
    "Step": "step",
    "Part": "part",
    "Tool": "tool",
    "Hazard": "hazard",
    "Media": "media",
}
ENTITY_KEYS: dict[str, str] = {entity: f"{collection}_id" for entity, collection in ENTITY_COLLECTIONS.items()}
SEED_ORDER: tuple[str, ...] = ("Equipment", "Part", "Tool", "Hazard", "Media", "Manual", "Procedure", "Step")
LIST_PROPERTIES: frozenset[str] = frozenset({"roles", "contexts", "callouts"})
RELATIONAL_FIELDS: frozenset[str] = frozenset(
    {
        "procedure_ids",
        "manual_id",
        "equipment_ids",
        "step_ids",
        "overview_media_ids",
        "supersedes",
        "procedure_id",
        "parts",
        "tool_ids",
        "hazard_ids",
        "media",
        "precedes",
        "callouts",
    }
)
assert not set(TECHNICIAN_COLLECTIONS) & (set(OWNED_VERTEX_COLLECTIONS) | set(OWNED_EDGE_COLLECTIONS))


class EdgeSpec(BaseModel):
    """One deterministic edge the projection intends to exist."""

    collection: str
    source_collection: str
    source_key: str
    target_collection: str
    target_key: str
    properties: dict[str, Any] = Field(default_factory=dict)
    origin: Literal["manual"] = "manual"

    @property
    def source_id(self) -> str:
        """Return the full collection/key identifier of the source."""
        return f"{self.source_collection}/{self.source_key}"

    @property
    def target_id(self) -> str:
        """Return the full collection/key identifier of the target."""
        return f"{self.target_collection}/{self.target_key}"

    def document(self) -> dict[str, Any]:
        """Render the Arango edge document with its generic identity triple."""
        return {
            "_from": self.source_id,
            "_to": self.target_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "kind": self.collection,
            "origin": self.origin,
            **self.properties,
        }


class GraphPublicationReport(BaseModel):
    """What one publication attempt achieved; ``published`` only follows read-back."""

    published: bool = False
    nodes_upserted: dict[str, int] = Field(default_factory=dict)
    edges_created: int = 0
    edges_removed: int = 0
    deactivated: dict[str, list[str]] = Field(default_factory=dict)
    missing_nodes: list[str] = Field(default_factory=list)
    missing_edges: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    tip_relink: Optional[RelinkReport] = None

    def complete(self) -> bool:
        """Return false for publication errors, missing graph records, or failed relinking."""
        return not (self.errors or self.missing_nodes or self.missing_edges or (self.tip_relink and self.tip_relink.failed))


class ManualGraphLoader:
    """Reconcile manual-owned collections; never touches technician collections."""

    def __init__(
        self,
        *,
        catalog: ManualCatalogStore,
        graph_store: Any,
        tenant_manager: Any = None,
        datasource: Optional[ManualCardDataSource] = None,
        ontology_dir: str | Path | None = None,
        domain: str = PROCEDURES_DOMAIN,
    ) -> None:
        self.catalog = catalog
        self.graph_store = graph_store
        self.domain = domain
        self._tenant_manager = tenant_manager or default_tenant_manager(ontology_dir)
        self.datasource = datasource or ManualCardDataSource(config={"catalog": catalog})
        self._lock = asyncio.Lock()
        self._ctx: Optional[TenantContext] = None

    def context(self) -> TenantContext:
        """Resolve and cache the procedures tenant context."""
        if self._ctx is None:
            self._ctx = resolve_context(self._tenant_manager, self.catalog.tenant_id)
        return self._ctx

    async def startup_check(self) -> None:
        """Fail fast when the procedures ontology domain is not loaded."""
        self.context()

    @staticmethod
    def desired_edges(snapshot: dict[str, list[dict[str, Any]]]) -> list[EdgeSpec]:
        """Build deterministic owned edges, collapsing duplicate endpoint pairs."""
        edges: list[EdgeSpec] = []
        manual_ids = {record["manual_id"] for record in snapshot.get("Manual", [])}
        procedure_ids = {record["procedure_id"] for record in snapshot.get("Procedure", [])}
        step_ids = {record["step_id"] for record in snapshot.get("Step", [])}
        equipment_ids = {record["equipment_id"] for record in snapshot.get("Equipment", [])}
        part_ids = {record["part_id"] for record in snapshot.get("Part", [])}
        tool_ids = {record["tool_id"] for record in snapshot.get("Tool", [])}
        hazard_ids = {record["hazard_id"] for record in snapshot.get("Hazard", [])}
        media_ids = {record["media_id"] for record in snapshot.get("Media", [])}

        for procedure in snapshot.get("Procedure", []):
            procedure_id = procedure["procedure_id"]
            if not procedure.get("active", True):
                continue
            manual_id = procedure.get("manual_id")
            if manual_id in manual_ids:
                edges.append(EdgeSpec(collection="documents", source_collection="manual", source_key=manual_id, target_collection="procedure", target_key=procedure_id))
            for equipment_id in procedure.get("equipment_ids", []):
                if equipment_id in equipment_ids:
                    edges.append(EdgeSpec(collection="assembles", source_collection="procedure", source_key=procedure_id, target_collection="equipment", target_key=equipment_id))
            for step in procedure.get("step_ids", []):
                step_id = step["step_id"]
                if step_id in step_ids:
                    edges.append(EdgeSpec(collection="has_step", source_collection="procedure", source_key=procedure_id, target_collection="step", target_key=step_id, properties={"order": step["order"]}))
            for media_id in procedure.get("overview_media_ids", []):
                if media_id in media_ids:
                    edges.append(EdgeSpec(collection="overview_media", source_collection="procedure", source_key=procedure_id, target_collection="media", target_key=media_id))
            supersedes = procedure.get("supersedes")
            if supersedes in procedure_ids:
                edges.append(EdgeSpec(collection="supersedes", source_collection="procedure", source_key=procedure_id, target_collection="procedure", target_key=supersedes))

        for step in snapshot.get("Step", []):
            step_id = step["step_id"]
            if not step.get("active", True):
                continue
            for next_step in step.get("precedes", []):
                target = next_step["step_id"]
                if target in step_ids:
                    edges.append(EdgeSpec(collection="precedes", source_collection="step", source_key=step_id, target_collection="step", target_key=target, properties={"kind": next_step["kind"]}))
            for part in step.get("parts", []):
                target = part["part_id"]
                if target in part_ids:
                    edges.append(EdgeSpec(collection="requires_part", source_collection="step", source_key=step_id, target_collection="part", target_key=target, properties={"quantity": part["quantity"], "contexts": [part.get("context")] if part.get("context") else []}))
            for target in step.get("tool_ids", []):
                if target in tool_ids:
                    edges.append(EdgeSpec(collection="requires_tool", source_collection="step", source_key=step_id, target_collection="tool", target_key=target))
            for target in step.get("hazard_ids", []):
                if target in hazard_ids:
                    edges.append(EdgeSpec(collection="warns", source_collection="step", source_key=step_id, target_collection="hazard", target_key=target))
            for media in step.get("media", []):
                target = media["media_id"]
                if target in media_ids:
                    edges.append(EdgeSpec(collection="illustrated_by", source_collection="step", source_key=step_id, target_collection="media", target_key=target, properties={"roles": [media["role"]], "confidence": media["confidence"]}))

        for media in snapshot.get("Media", []):
            media_id = media["media_id"]
            for callout in media.get("callouts", []):
                target = callout["part_id"]
                if target in part_ids:
                    edges.append(EdgeSpec(collection="depicts", source_collection="media", source_key=media_id, target_collection="part", target_key=target, properties={"callouts": [callout["callout"]], "confidence": callout["confidence"]}))

        merged: dict[tuple[str, str, str], EdgeSpec] = {}
        for edge in edges:
            key = (edge.collection, edge.source_id, edge.target_id)
            current = merged.get(key)
            if current is None:
                merged[key] = edge
                continue
            properties = dict(current.properties)
            for name, value in edge.properties.items():
                if name in LIST_PROPERTIES:
                    properties[name] = sorted(set(properties.get(name, [])) | set(value))
                elif name == "confidence":
                    properties[name] = max(properties.get(name, value), value)
                elif properties.get(name) != value:
                    logger.warning("Conflicting %s on duplicate %s; keeping first", name, key)
            merged[key] = current.model_copy(update={"properties": properties})
        return [merged[key] for key in sorted(merged)]

    @staticmethod
    def _node_payload(record: dict[str, Any], key_field: str) -> dict[str, Any]:
        """Return a vertex payload without relation-builder fields."""
        return {key: value for key, value in record.items() if key == key_field or key not in RELATIONAL_FIELDS}

    async def publish_all(self) -> GraphPublicationReport:
        """Snapshot, reconcile owned graph records, verify them, then relink revised manuals."""
        report = GraphPublicationReport()
        async with self._lock:
            try:
                ctx = self.context()
                snapshot = await self.datasource.snapshot()
            except ProceduresDomainNotLoaded as exc:
                report.errors.append(str(exc))
                return report
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"extraction failed: {exc}")
                return report
            try:
                existing_manuals = {node.get("manual_id") or node.get("_key"): node.get("revision") for node in await self.graph_store.get_all_nodes(ctx, "manual")}
                for entity in SEED_ORDER:
                    collection = ENTITY_COLLECTIONS[entity]
                    key_field = ENTITY_KEYS[entity]
                    records = [self._node_payload(record, key_field) for record in snapshot.get(entity, [])]
                    result = await self.graph_store.upsert_nodes(ctx, collection, records, key_field)
                    report.nodes_upserted[collection] = getattr(result, "inserted", 0) + getattr(result, "updated", 0)
                for entity, collection in ENTITY_COLLECTIONS.items():
                    key_field = ENTITY_KEYS[entity]
                    intended = {record[key_field] for record in snapshot.get(entity, [])}
                    existing = await self.graph_store.get_all_nodes(ctx, collection)
                    obsolete = sorted((node.get(key_field) or node.get("_key")) for node in existing if (node.get(key_field) or node.get("_key")) not in intended)
                    if obsolete:
                        await self.graph_store.soft_delete_nodes(ctx, collection, obsolete)
                        report.deactivated[collection] = obsolete
                desired = self.desired_edges(snapshot)
                await self._reconcile_edges(ctx, desired, report)
                await self._verify(ctx, snapshot, desired, report)
                await self._relink_changed_manuals(ctx, existing_manuals, report)
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"publication failed: {exc}")
            report.published = report.complete()
        return report

    async def _relink_changed_manuals(self, ctx: TenantContext, existing: Mapping[str, Any], report: GraphPublicationReport) -> None:
        """Relink tips for changed revisions that have a previous stored card snapshot."""
        combined = RelinkReport(manual_id="*")
        for card in await self.catalog.list_cards(active_only=False):
            if existing.get(card.manual_id) in (None, card.revision) or len(card.versions) < 2:
                continue
            previous = ManualCard.model_validate(card.versions[-2].card_snapshot)
            previous_steps = [step for procedure in previous.procedures for step in procedure.steps]
            current_steps = [step for procedure in card.procedures for step in procedure.steps]
            relink = await relink_tips(self.graph_store, ctx, manual_id=card.manual_id, previous_steps=previous_steps, current_steps=current_steps)
            combined.relinked.extend(relink.relinked)
            combined.orphaned.extend(relink.orphaned)
            combined.candidates.extend(relink.candidates)
            combined.failed.extend(relink.failed)
        if combined.relinked or combined.orphaned or combined.candidates or combined.failed:
            report.tip_relink = combined

    async def _reconcile_edges(self, ctx: TenantContext, wanted: Sequence[EdgeSpec], report: GraphPublicationReport) -> None:
        """Reconcile only owned edges, treating list properties as order-insensitive."""
        by_collection: dict[str, list[EdgeSpec]] = {}
        for edge in wanted:
            by_collection.setdefault(edge.collection, []).append(edge)
        for collection in OWNED_EDGE_COLLECTIONS:
            indexed = {(edge.source_id, edge.target_id): edge for edge in by_collection.get(collection, [])}
            existing = await self.graph_store.get_all_edges(ctx, collection)
            removed = 0
            for edge in existing:
                source = edge.get("source_id") or edge.get("_from")
                target = edge.get("target_id") or edge.get("_to")
                desired = indexed.get((source, target))
                stale = desired is None or not edge.get("source_id") or any(
                    sorted(edge.get(name, [])) != sorted(value) if name in LIST_PROPERTIES else edge.get(name) != value
                    for name, value in (desired.properties.items() if desired else ())
                )
                if stale:
                    await self.graph_store.remove_edge_by_triple(ctx, collection, source, target, edge.get("kind") or collection)
                    removed += 1
            report.edges_removed += removed
            documents = [edge.document() for edge in indexed.values()]
            if documents:
                await self.graph_store.create_edges(ctx, collection, documents)
                report.edges_created += len(documents)

    async def _verify(self, ctx: TenantContext, snapshot: Mapping[str, Any], wanted: Sequence[EdgeSpec], report: GraphPublicationReport) -> None:
        """Read intended owned vertices and edges back from the graph."""
        for entity, collection in ENTITY_COLLECTIONS.items():
            key_field = ENTITY_KEYS[entity]
            intended = {record[key_field] for record in snapshot.get(entity, [])}
            present = {node.get(key_field) or node.get("_key") for node in await self.graph_store.get_all_nodes(ctx, collection)}
            report.missing_nodes.extend(f"{collection}/{key}" for key in sorted(intended - present))
        by_collection: dict[str, list[EdgeSpec]] = {}
        for edge in wanted:
            by_collection.setdefault(edge.collection, []).append(edge)
        for collection, edges in by_collection.items():
            present = {(edge.get("source_id") or edge.get("_from"), edge.get("target_id") or edge.get("_to")) for edge in await self.graph_store.get_all_edges(ctx, collection)}
            report.missing_edges.extend(f"{collection}: {edge.source_id} -> {edge.target_id}" for edge in edges if (edge.source_id, edge.target_id) not in present)

    async def publish(self, card: ManualCard) -> GraphPublicationReport:
        """Publish through full-catalog reconciliation so other manuals are retained."""
        logger.info("Publishing manual %s via a full-catalog reconciliation", card.manual_id)
        return await self.publish_all()

    async def retract(self, manual_id: str) -> GraphPublicationReport:
        """Soft-delete a manual's projected owned vertices and their owned incident edges."""
        report = GraphPublicationReport()
        async with self._lock:
            try:
                ctx = self.context()
                snapshot = await self.datasource.snapshot(filters={"manual_id": manual_id})
                node_ids: list[str] = []
                for entity, collection in ENTITY_COLLECTIONS.items():
                    key_field = ENTITY_KEYS[entity]
                    keys = [record[key_field] for record in snapshot.get(entity, [])]
                    if keys:
                        await self.graph_store.soft_delete_nodes(ctx, collection, keys)
                        report.deactivated[collection] = keys
                        node_ids.extend(f"{collection}/{key}" for key in keys)
                for collection in OWNED_EDGE_COLLECTIONS:
                    for node_id in node_ids:
                        for edge in await self.graph_store.edges_incident(ctx, collection, node_id):
                            await self.graph_store.remove_edge_by_triple(ctx, collection, edge.get("source_id") or edge.get("_from"), edge.get("target_id") or edge.get("_to"), edge.get("kind") or collection)
                            report.edges_removed += 1
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"retraction failed: {exc}")
            report.published = report.complete()
        return report
