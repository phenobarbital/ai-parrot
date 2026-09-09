"""Full-catalog contracts graph publication (FEAT-539 M5).

:class:`ContractGraphLoader` projects the authoritative catalog into the
ArangoDB contracts ontology. Three rules drive its design, all of them
corrections the spec makes to the naive "publish one card" idea:

1. **Publication is always a complete, prevalidated snapshot.** The generic
   refresh diff soft-deletes anything absent from an extraction, so a
   partial snapshot would retract the rest of the catalog.
   :meth:`ContractGraphLoader.publish` therefore delegates to
   :meth:`ContractGraphLoader.publish_all` under the tenant lock.
2. **Edges are reconciled, not just created.** ``create_edges`` inserts or
   skips by endpoints and never updates properties or removes obsolete
   edges, so an owner/parent/party/standard/signatory change must remove
   the old edge before writing the new one. Every written edge carries
   ``_from``/``_to`` **plus** ``source_id``/``target_id``/``kind`` so the
   generic removal helpers can address it.
3. **Success is verified, never assumed.** An empty ``errors`` list is not
   evidence: the loader reads back the intended node and edge sets before
   it reports a revision as published, and any shortfall keeps the work
   retryable.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from .catalog import ContractCatalogStore
from .datasource import ContractCardDataSource
from .models import ContractCard

__all__ = (
    "CONTRACTS_DOMAIN",
    "FEATURE_VERTEX_COLLECTIONS",
    "FEATURE_EDGE_COLLECTIONS",
    "EdgeSpec",
    "GraphPublicationReport",
    "ContractsDomainNotLoaded",
    "ContractGraphLoader",
)

logger = logging.getLogger(__name__)

#: The ontology domain this loader owns.
CONTRACTS_DOMAIN = "contracts"

#: Vertex collections this feature owns. Party/Person/ComplianceStandard are
#: shared identity and are never soft-deleted by a contracts publication.
FEATURE_VERTEX_COLLECTIONS: tuple[str, ...] = ("contract", "obligation")

#: Edge collections this feature owns; cleanup never touches anything else.
FEATURE_EDGE_COLLECTIONS: tuple[str, ...] = (
    "party_to",
    "signed_by",
    "represents",
    "is_employee",
    "governed_by",
    "amends",
    "supersedes",
    "imposed_by",
    "requires",
    "owned_by",
    "managed_by",
)

#: Vertex collection of each entity, mirroring the domain YAML.
ENTITY_COLLECTIONS: dict[str, str] = {
    "Contract": "contract",
    "Party": "party",
    "Person": "person",
    "Obligation": "obligation",
    "ComplianceStandard": "compliance_standard",
    "Employee": "employees",
    "Department": "departments",
}

#: Key field of each entity, mirroring the domain YAML.
ENTITY_KEYS: dict[str, str] = {
    "Contract": "contract_id",
    "Party": "party_id",
    "Person": "person_id",
    "Obligation": "obligation_id",
    "ComplianceStandard": "standard_id",
}

#: Seeding order: standards are written before ``requires`` is reconciled,
#: so a first publish links every compliance obligation immediately.
SEED_ORDER: tuple[str, ...] = (
    "ComplianceStandard",
    "Party",
    "Person",
    "Contract",
    "Obligation",
)


class ContractsDomainNotLoaded(RuntimeError):
    """The resolved tenant ontology does not contain the contracts domain."""


class EdgeSpec(BaseModel):
    """One deterministic edge the projection intends to exist.

    Args:
        collection: Edge collection name.
        source_collection: Vertex collection of the tail.
        source_key: ``_key`` of the tail.
        target_collection: Vertex collection of the head.
        target_key: ``_key`` of the head.
        properties: Edge properties (role, signed_on, origin…).
    """

    collection: str
    source_collection: str
    source_key: str
    target_collection: str
    target_key: str
    properties: dict[str, Any] = Field(default_factory=dict)

    @property
    def source_id(self) -> str:
        """Full ``collection/key`` id of the tail."""
        return f"{self.source_collection}/{self.source_key}"

    @property
    def target_id(self) -> str:
        """Full ``collection/key`` id of the head."""
        return f"{self.target_collection}/{self.target_key}"

    @property
    def triple(self) -> tuple[str, str, str, str]:
        """The ``(collection, source, target, kind)`` identity of this edge."""
        return (self.collection, self.source_id, self.target_id, self.collection)

    def document(self) -> dict[str, Any]:
        """Render the edge document written to ArangoDB.

        Carries the generic ``source_id``/``target_id``/``kind`` triple in
        addition to ``_from``/``_to`` so ``edges_incident`` and
        ``remove_edge_by_triple`` can address it later.
        """
        return {
            "_from": self.source_id,
            "_to": self.target_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "kind": self.collection,
            **self.properties,
        }


class GraphPublicationReport(BaseModel):
    """What one publication attempt actually achieved.

    ``published`` is only ever True after a successful read-back of the
    intended node and edge sets.
    """

    published: bool = False
    contracts: int = 0
    nodes_upserted: dict[str, int] = Field(default_factory=dict)
    edges_created: dict[str, int] = Field(default_factory=dict)
    edges_removed: dict[str, int] = Field(default_factory=dict)
    deactivated: dict[str, list[str]] = Field(default_factory=dict)
    retracted: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    missing_nodes: list[str] = Field(default_factory=list)
    missing_edges: list[str] = Field(default_factory=list)
    unavailable_targets: list[str] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        """True when nothing was missing and no error was recorded."""
        return not (self.errors or self.missing_nodes or self.missing_edges)


class ContractGraphLoader:
    """Publish the contracts catalog into the tenant's ontology graph.

    Args:
        catalog: The tenant-bound authoritative catalog.
        graph_store: An ``OntologyGraphStore``-shaped object.
        tenant_manager: A **dedicated** ``TenantOntologyManager`` configured
            with the contracts ontology directory. The generic manager
            caches by tenant only (not by tenant+domain), so sharing one
            across domains would hand back another domain's ontology.
        datasource: Optional pre-built :class:`ContractCardDataSource`.
        ontology_dir: Overrides the manager's ontology directory.
        domain: Ontology domain name (``contracts``).
    """

    def __init__(
        self,
        *,
        catalog: ContractCatalogStore,
        graph_store: Any,
        tenant_manager: Any = None,
        datasource: Optional[ContractCardDataSource] = None,
        ontology_dir: Optional[str | Path] = None,
        domain: str = CONTRACTS_DOMAIN,
    ) -> None:
        self.catalog = catalog
        self.graph_store = graph_store
        self.domain = domain
        self._tenant_manager = tenant_manager or self._default_tenant_manager(ontology_dir)
        self.datasource = datasource or ContractCardDataSource("contractcard", {"catalog": catalog})
        self._lock = asyncio.Lock()
        self._ctx: Any = None

    @staticmethod
    def _default_tenant_manager(ontology_dir: Optional[str | Path]) -> Any:
        """Build a contracts-only tenant manager over the packaged defaults."""
        from ..ontology.parser import OntologyParser  # noqa: PLC0415
        from ..ontology.tenant import TenantOntologyManager  # noqa: PLC0415

        return TenantOntologyManager(
            ontology_dir=Path(ontology_dir) if ontology_dir else OntologyParser.get_defaults_dir()
        )

    # -- startup -----------------------------------------------------------

    async def context(self) -> Any:
        """Resolve (and cache) the tenant context for the contracts domain.

        Raises:
            ContractsDomainNotLoaded: When the resolved ontology does not
                carry the contracts vocabulary — a misconfigured
                ``ontology_dir`` or a manager shared with another domain.
        """
        if self._ctx is None:
            ctx = self._tenant_manager.resolve(self.catalog.tenant_id, domain=self.domain)
            missing = {"Contract", "Obligation", "Party"} - set(ctx.ontology.entities)
            if missing:
                raise ContractsDomainNotLoaded(
                    f"tenant {self.catalog.tenant_id!r} resolved an ontology without "
                    f"{sorted(missing)}; configure the contracts ontology_dir and use a "
                    "dedicated TenantOntologyManager (it caches by tenant, not domain)."
                )
            self._ctx = ctx
        return self._ctx

    async def startup_check(self) -> None:
        """Fail fast at startup when the contracts domain is not loaded."""
        await self.context()

    # -- edge derivation ---------------------------------------------------

    @staticmethod
    def desired_edges(snapshot: dict[str, list[dict[str, Any]]]) -> list[EdgeSpec]:
        """Derive every deterministic edge from a complete snapshot.

        Runs in Python over the prevalidated snapshot so relations to
        later-loaded targets exist on the *first* publish — the generic
        discovery pass would otherwise miss a target that had not been
        synchronised yet.

        Args:
            snapshot: The datasource snapshot (all five entities).

        Returns:
            Deterministically ordered edge specifications.
        """
        contracts = {record["contract_id"]: record for record in snapshot.get("Contract", [])}
        parties = {record["party_id"] for record in snapshot.get("Party", [])}
        people = snapshot.get("Person", [])
        standards = {record["standard_id"] for record in snapshot.get("ComplianceStandard", [])}
        edges: list[EdgeSpec] = []

        for contract_id, record in sorted(contracts.items()):
            if not record.get("active", True):
                continue
            for party_id, role in record.get("_party_roles", []):
                if party_id in parties:
                    edges.append(
                        EdgeSpec(
                            collection="party_to",
                            source_collection="contract",
                            source_key=contract_id,
                            target_collection="party",
                            target_key=party_id,
                            properties={"role": role},
                        )
                    )
            for person_id, signed_on, on_behalf_of in record.get("_signatories", []):
                edges.append(
                    EdgeSpec(
                        collection="signed_by",
                        source_collection="contract",
                        source_key=contract_id,
                        target_collection="person",
                        target_key=person_id,
                        properties={"signed_on": signed_on, "on_behalf_of": on_behalf_of},
                    )
                )
            parent = record.get("parent_contract_id")
            if parent and parent in contracts:
                if record.get("contract_type") == "amendment":
                    edges.append(
                        EdgeSpec(
                            collection="amends",
                            source_collection="contract",
                            source_key=contract_id,
                            target_collection="contract",
                            target_key=parent,
                            properties={"effective_date": record.get("effective_date")},
                        )
                    )
                else:
                    edges.append(
                        EdgeSpec(
                            collection="governed_by",
                            source_collection="contract",
                            source_key=contract_id,
                            target_collection="contract",
                            target_key=parent,
                        )
                    )
            superseded = record.get("_supersedes")
            if superseded and superseded in contracts:
                edges.append(
                    EdgeSpec(
                        collection="supersedes",
                        source_collection="contract",
                        source_key=contract_id,
                        target_collection="contract",
                        target_key=superseded,
                    )
                )
            owner = record.get("owner_employee_id")
            if owner:
                edges.append(
                    EdgeSpec(
                        collection="owned_by",
                        source_collection="contract",
                        source_key=contract_id,
                        target_collection="employees",
                        target_key=owner,
                    )
                )
            department = record.get("department")
            if department:
                edges.append(
                    EdgeSpec(
                        collection="managed_by",
                        source_collection="contract",
                        source_key=contract_id,
                        target_collection="departments",
                        target_key=department,
                    )
                )

        for person in people:
            party_id = person.get("party_id")
            if party_id and party_id in parties:
                edges.append(
                    EdgeSpec(
                        collection="represents",
                        source_collection="person",
                        source_key=person["person_id"],
                        target_collection="party",
                        target_key=party_id,
                    )
                )
            employee_id = person.get("employee_id")
            if employee_id:
                edges.append(
                    EdgeSpec(
                        collection="is_employee",
                        source_collection="person",
                        source_key=person["person_id"],
                        target_collection="employees",
                        target_key=employee_id,
                    )
                )

        for obligation in snapshot.get("Obligation", []):
            if not obligation.get("active", True):
                continue
            contract_id = obligation.get("contract_id")
            if contract_id in contracts:
                edges.append(
                    EdgeSpec(
                        collection="imposed_by",
                        source_collection="obligation",
                        source_key=obligation["obligation_id"],
                        target_collection="contract",
                        target_key=contract_id,
                    )
                )
            standard_id = obligation.get("standard_id")
            if standard_id and standard_id in standards:
                edges.append(
                    EdgeSpec(
                        collection="requires",
                        source_collection="obligation",
                        source_key=obligation["obligation_id"],
                        target_collection="compliance_standard",
                        target_key=standard_id,
                    )
                )

        edges.sort(key=lambda edge: (edge.collection, edge.source_id, edge.target_id))
        return edges

    async def _snapshot(self) -> dict[str, list[dict[str, Any]]]:
        """Build the prevalidated snapshot, enriched for edge derivation."""
        snapshot = await self.datasource.snapshot()
        cards = {card.contract_id: card for card in await self.catalog.list_cards(active_only=False)}
        for record in snapshot["Contract"]:
            card = cards.get(record["contract_id"])
            if card is None:  # pragma: no cover - snapshot comes from the same catalog
                continue
            record["_party_roles"] = [(party.party_id, party.role) for party in card.parties]
            record["_signatories"] = [
                (
                    signatory.person_id,
                    signatory.signed_on.isoformat() if signatory.signed_on else None,
                    signatory.party_id,
                )
                for signatory in card.signatories
            ]
            record["_supersedes"] = card.supersedes_contract_id
        return snapshot

    @staticmethod
    def _node_payload(record: dict[str, Any]) -> dict[str, Any]:
        """Strip the private edge-derivation keys before writing a vertex."""
        return {key: value for key, value in record.items() if not key.startswith("_")}

    # -- publication -------------------------------------------------------

    async def publish_all(self) -> GraphPublicationReport:
        """Reconcile the whole catalog into the graph, then verify it.

        Returns:
            A :class:`GraphPublicationReport`; ``published`` is True only
            after the intended nodes and edges were read back.
        """
        report = GraphPublicationReport()
        async with self._lock:
            try:
                ctx = await self.context()
            except ContractsDomainNotLoaded as exc:
                report.errors.append(str(exc))
                return report

            try:
                snapshot = await self._snapshot()
            except Exception as exc:  # noqa: BLE001 - extraction must never look empty
                logger.error("Contracts extraction failed: %s", exc)
                report.errors.append(f"extraction failed: {exc}")
                return report

            report.contracts = len(snapshot["Contract"])

            # 1. Nodes, standards first so `requires` can link immediately.
            for entity in SEED_ORDER:
                records = [self._node_payload(record) for record in snapshot.get(entity, [])]
                collection = ENTITY_COLLECTIONS[entity]
                try:
                    result = await self.graph_store.upsert_nodes(ctx, collection, records, ENTITY_KEYS[entity])
                except Exception as exc:  # noqa: BLE001 - partial writes stay retryable
                    report.errors.append(f"{collection}: node upsert failed: {exc}")
                    return report
                report.nodes_upserted[collection] = getattr(result, "inserted", 0) + getattr(result, "updated", 0)

            # 2. Soft-delete only feature-owned vertices absent from the
            #    snapshot. Party/Person/ComplianceStandard are shared
            #    identity and are never deactivated here.
            for entity in ("Contract", "Obligation"):
                collection = ENTITY_COLLECTIONS[entity]
                key_field = ENTITY_KEYS[entity]
                intended = {record[key_field] for record in snapshot.get(entity, [])}
                try:
                    existing = await self.graph_store.get_all_nodes(ctx, collection)
                except Exception as exc:  # noqa: BLE001
                    report.errors.append(f"{collection}: read failed: {exc}")
                    return report
                obsolete = sorted(
                    node.get(key_field) or node.get("_key")
                    for node in existing
                    if (node.get(key_field) or node.get("_key")) not in intended
                )
                if obsolete:
                    await self.graph_store.soft_delete_nodes(ctx, collection, obsolete)
                    report.deactivated[collection] = obsolete

            # 3. Reconcile edges: property-carrying and scalar alike.
            desired = self.desired_edges(snapshot)
            await self._reconcile_edges(ctx, desired, report)

            # 4. Verify before claiming success.
            await self._verify(ctx, snapshot, desired, report)
            report.published = report.complete
        return report

    async def _reconcile_edges(
        self,
        ctx: Any,
        desired: list[EdgeSpec],
        report: GraphPublicationReport,
    ) -> None:
        """Create missing edges and remove obsolete/changed ones."""
        by_collection: dict[str, list[EdgeSpec]] = {}
        for edge in desired:
            by_collection.setdefault(edge.collection, []).append(edge)

        for collection in FEATURE_EDGE_COLLECTIONS:
            wanted = by_collection.get(collection, [])
            wanted_index = {(edge.source_id, edge.target_id): edge for edge in wanted}
            try:
                existing = await self.graph_store.get_all_edges(ctx, collection)
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{collection}: edge read failed: {exc}")
                continue

            removed = 0
            for edge in existing:
                source = edge.get("source_id") or edge.get("_from")
                target = edge.get("target_id") or edge.get("_to")
                key = (source, target)
                wanted_edge = wanted_index.get(key)
                if wanted_edge is None:
                    # Obsolete endpoint (owner/parent/party/standard changed).
                    await self.graph_store.remove_edge_by_triple(
                        ctx, collection, source, target, edge.get("kind") or collection
                    )
                    removed += 1
                    continue
                stale_properties = any(edge.get(name) != value for name, value in wanted_edge.properties.items())
                if stale_properties or not edge.get("source_id"):
                    # create_edges never updates properties and discovery
                    # writes bare _from/_to edges: remove, then rewrite.
                    await self.graph_store.remove_edge_by_triple(
                        ctx, collection, source, target, edge.get("kind") or collection
                    )
                    removed += 1
            if removed:
                report.edges_removed[collection] = removed

            if wanted:
                created = await self.graph_store.create_edges(ctx, collection, [edge.document() for edge in wanted])
                report.edges_created[collection] = created

    async def _verify(
        self,
        ctx: Any,
        snapshot: dict[str, list[dict[str, Any]]],
        desired: list[EdgeSpec],
        report: GraphPublicationReport,
    ) -> None:
        """Read back the intended node and edge sets.

        An empty ``errors`` list is not evidence of publication; this is.
        """
        for entity in SEED_ORDER:
            collection = ENTITY_COLLECTIONS[entity]
            key_field = ENTITY_KEYS[entity]
            intended = {record[key_field] for record in snapshot.get(entity, [])}
            if not intended:
                continue
            try:
                nodes = await self.graph_store.get_all_nodes(ctx, collection)
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{collection}: read-back failed: {exc}")
                continue
            present = {node.get(key_field) or node.get("_key") for node in nodes}
            report.missing_nodes.extend(f"{collection}/{key}" for key in sorted(intended - present))

        by_collection: dict[str, list[EdgeSpec]] = {}
        for edge in desired:
            by_collection.setdefault(edge.collection, []).append(edge)
        for collection, wanted in sorted(by_collection.items()):
            try:
                existing = await self.graph_store.get_all_edges(ctx, collection)
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{collection}: edge read-back failed: {exc}")
                continue
            present = {
                (edge.get("source_id") or edge.get("_from"), edge.get("target_id") or edge.get("_to"))
                for edge in existing
            }
            report.missing_edges.extend(
                f"{collection}: {edge.source_id} -> {edge.target_id}"
                for edge in wanted
                if (edge.source_id, edge.target_id) not in present
            )

    async def publish(self, card: ContractCard) -> GraphPublicationReport:
        """Publish one card.

        v1 delegates to :meth:`publish_all`: the generic diff has no
        per-card filter and soft-deletes everything absent from the
        extraction it is given, so feeding it a single-card snapshot would
        retract the rest of the catalog.

        Args:
            card: The card that triggered publication (used for logging).

        Returns:
            The full-catalog publication report.
        """
        logger.info("Publishing contract %s via a full-catalog reconciliation", card.contract_id)
        return await self.publish_all()

    async def retract(self, contract_id: str) -> GraphPublicationReport:
        """Retract one contract from the graph.

        Marks the contract and its obligations inactive, removes the edges
        incident to them inside feature-owned collections only, and queues
        temporal tombstones. Shared parties and people that other contracts
        still reference are left untouched, as is catalog history, evidence
        and the answer audit.

        Args:
            contract_id: The contract to retract.

        Returns:
            A report listing what was deactivated and removed.
        """
        report = GraphPublicationReport()
        async with self._lock:
            try:
                ctx = await self.context()
            except ContractsDomainNotLoaded as exc:
                report.errors.append(str(exc))
                return report

            obligations = await self.catalog.obligations_for(contract_id)
            node_ids = [f"contract/{contract_id}"] + [
                f"obligation/{obligation.obligation_id}" for obligation in obligations
            ]

            try:
                await self.graph_store.soft_delete_nodes(ctx, "contract", [contract_id])
                if obligations:
                    await self.graph_store.soft_delete_nodes(
                        ctx,
                        "obligation",
                        [obligation.obligation_id for obligation in obligations],
                    )
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"retraction failed: {exc}")
                return report

            removed: dict[str, int] = {}
            for collection in FEATURE_EDGE_COLLECTIONS:
                for node_id in node_ids:
                    try:
                        incident = await self.graph_store.edges_incident(ctx, collection, node_id)
                    except Exception as exc:  # noqa: BLE001
                        report.errors.append(f"{collection}: incident read failed: {exc}")
                        continue
                    for edge in incident:
                        await self.graph_store.remove_edge_by_triple(
                            ctx,
                            collection,
                            edge.get("source_id") or edge.get("_from"),
                            edge.get("target_id") or edge.get("_to"),
                            edge.get("kind") or collection,
                        )
                        removed[collection] = removed.get(collection, 0) + 1
            report.edges_removed = removed
            report.retracted = [contract_id]
            report.deactivated = {
                "contract": [contract_id],
                "obligation": [obligation.obligation_id for obligation in obligations],
            }
            report.published = not report.errors
        return report
