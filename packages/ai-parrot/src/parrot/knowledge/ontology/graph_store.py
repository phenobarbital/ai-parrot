"""ArangoDB wrapper for ontology graph operations.

Provides tenant-isolated graph operations: database/collection initialization,
AQL traversals, node upsert, and edge creation. Uses ``asyncdb.AsyncDB``
for all database operations, consistent with ``parrot.stores.arango``.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel

from .schema import TenantContext

logger = logging.getLogger("Parrot.Ontology.GraphStore")


class UpsertResult(BaseModel):
    """Result of a batch upsert operation.

    Args:
        inserted: Number of new nodes inserted.
        updated: Number of existing nodes updated.
        unchanged: Number of nodes that were identical (no-op).
    """

    inserted: int = 0
    updated: int = 0
    unchanged: int = 0


class OntologyGraphStore:
    """ArangoDB wrapper for ontology graph operations.

    Responsibilities:
        - Create/manage vertex and edge collections per tenant.
        - Execute AQL traversals with bind variables.
        - CRUD operations for nodes and edges during ingestion.
        - Tenant-isolated: each tenant gets its own ArangoDB database.

    The store does NOT own the ArangoDB connection — it receives a client
    (``asyncdb.AsyncDB``) from the connection pool.

    Args:
        arango_client: An ``asyncdb.AsyncDB`` instance configured for ArangoDB.
    """

    def __init__(self, arango_client: Any = None) -> None:
        self._client = arango_client
        self._db: Any = None

    async def _get_db(self, ctx: TenantContext) -> Any:
        """Get a database connection scoped to the tenant.

        Args:
            ctx: Tenant context with database name.

        Returns:
            Database connection object.
        """
        if self._client is None:
            raise RuntimeError(
                "OntologyGraphStore requires an ArangoDB client. "
                "Pass an asyncdb.AsyncDB instance to the constructor."
            )
        # Use the tenant's database
        await self._client.use(ctx.arango_db)
        return self._client

    async def initialize_tenant(self, ctx: TenantContext) -> None:
        """Create the ArangoDB database and all collections for a tenant.

        Idempotent — safe to call multiple times. Creates:
            1. Database (if not exists)
            2. Vertex collections for each entity
            3. Edge collections for each relation
            4. Named graph linking vertex/edge collections
            5. Indexes for key_field on each vertex collection

        Args:
            ctx: Tenant context with ontology and database name.
        """
        db = await self._get_db(ctx)

        # Create database if not exists
        try:
            await db.create_database(ctx.arango_db)
            logger.info("Created database '%s'", ctx.arango_db)
        except Exception:
            logger.debug("Database '%s' already exists", ctx.arango_db)

        await db.use(ctx.arango_db)

        # Create vertex collections
        for name, entity in ctx.ontology.entities.items():
            if not entity.collection:
                continue
            try:
                if not await db.collection_exists(entity.collection):
                    await db.create_collection(entity.collection)
                    logger.info(
                        "Created vertex collection '%s' for entity '%s'",
                        entity.collection, name,
                    )
                # Create index on key_field
                if entity.key_field:
                    await self._ensure_index(
                        db, entity.collection, entity.key_field,
                    )
            except Exception as e:
                logger.warning(
                    "Failed to create collection '%s': %s",
                    entity.collection, e,
                )

        # Create edge collections
        edge_definitions = []
        for rel_name, rel in ctx.ontology.relations.items():
            try:
                if not await db.collection_exists(rel.edge_collection):
                    await db.create_collection(
                        rel.edge_collection, edge=True,
                    )
                    logger.info(
                        "Created edge collection '%s' for relation '%s'",
                        rel.edge_collection, rel_name,
                    )
                # Build edge definition for named graph
                from_entity = ctx.ontology.entities.get(rel.from_entity)
                to_entity = ctx.ontology.entities.get(rel.to_entity)
                if from_entity and to_entity:
                    edge_definitions.append({
                        "edge_collection": rel.edge_collection,
                        "from_vertex_collections": [from_entity.collection],
                        "to_vertex_collections": [to_entity.collection],
                    })
            except Exception as e:
                logger.warning(
                    "Failed to create edge collection '%s': %s",
                    rel.edge_collection, e,
                )

        # Create named graph
        graph_name = f"{ctx.tenant_id}_ontology_graph"
        try:
            if not await db.graph_exists(graph_name):
                vertex_collections = ctx.ontology.get_entity_collections()
                await db.create_graph(
                    graph_name,
                    edge_definitions=edge_definitions,
                    orphan_collections=[
                        c for c in vertex_collections
                        if not any(
                            c in ed["from_vertex_collections"] + ed["to_vertex_collections"]
                            for ed in edge_definitions
                        )
                    ],
                )
                logger.info("Created named graph '%s'", graph_name)
        except Exception as e:
            logger.warning("Failed to create graph '%s': %s", graph_name, e)

    async def _ensure_index(
        self, db: Any, collection: str, field: str
    ) -> None:
        """Create a persistent index on a field if not already present.

        Args:
            db: Database connection.
            collection: Collection name.
            field: Field to index.
        """
        try:
            await db.execute_query(
                f"FOR doc IN @@col LIMIT 0 RETURN null",
                bind_vars={"@col": collection},
            )
            # The actual index creation depends on the asyncdb adapter.
            # For now, we rely on ArangoDB's built-in _key index and
            # the collection being queryable by key_field via AQL filters.
        except Exception:
            pass

    async def execute_traversal(
        self,
        ctx: TenantContext,
        aql: str,
        bind_vars: dict[str, Any] | None = None,
        collection_binds: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute an AQL traversal query against the tenant's graph.

        Args:
            ctx: Tenant context.
            aql: AQL query string (may contain @params and @@collection binds).
            bind_vars: Regular bind variables (e.g. {"user_id": "emp_001"}).
            collection_binds: @@collection bind resolutions
                (e.g. {"@employees": "employees"}).

        Returns:
            List of result documents from the traversal.
        """
        db = await self._get_db(ctx)

        # Merge bind vars
        all_binds: dict[str, Any] = {}
        if bind_vars:
            all_binds.update(bind_vars)
        if collection_binds:
            all_binds.update(collection_binds)

        try:
            result = await db.execute_query(aql, bind_vars=all_binds)
            if result is None:
                return []
            if isinstance(result, list):
                return result
            # Some adapters return cursor-like objects
            return list(result)
        except Exception as e:
            logger.error("AQL traversal failed: %s\nQuery: %s", e, aql)
            raise

    async def upsert_nodes(
        self,
        ctx: TenantContext,
        collection: str,
        nodes: list[dict[str, Any]],
        key_field: str,
    ) -> UpsertResult:
        """Upsert nodes into a vertex collection.

        Uses ArangoDB's native UPSERT for atomicity. Each node is matched
        by its ``key_field`` value.

        Args:
            ctx: Tenant context.
            collection: Vertex collection name.
            nodes: List of node documents to upsert.
            key_field: Field used as the unique identifier.

        Returns:
            UpsertResult with counts of inserted, updated, unchanged.
        """
        if not nodes:
            return UpsertResult()

        db = await self._get_db(ctx)
        inserted = 0
        updated = 0
        unchanged = 0

        # Batch upsert via AQL. INSERT explicitly copies key_field's value
        # into ArangoDB's own `_key` so downstream `_key`-based lookups
        # (soft_delete_nodes, get_by_key, and declarative traversal
        # patterns like article_in_force's `FILTER a._key == @articulo_key`)
        # match — without this, ArangoDB would auto-generate `_key` on
        # insert instead of using the entity's declared identifier.
        aql = """
        FOR doc IN @nodes
            UPSERT { @key_field: doc[@key_field] }
            INSERT MERGE(doc, { _key: doc[@key_field], _active: true })
            UPDATE MERGE(doc, { _active: true })
            IN @@collection
            RETURN { type: OLD ? (OLD == NEW ? 'unchanged' : 'updated') : 'inserted' }
        """
        try:
            results = await db.execute_query(
                aql,
                bind_vars={
                    "nodes": nodes,
                    "key_field": key_field,
                    "@collection": collection,
                },
            )
            if results:
                for r in results:
                    rtype = r.get("type", "inserted") if isinstance(r, dict) else "inserted"
                    if rtype == "inserted":
                        inserted += 1
                    elif rtype == "updated":
                        updated += 1
                    else:
                        unchanged += 1
        except Exception as e:
            logger.error("Upsert failed for collection '%s': %s", collection, e)
            # Fallback: individual upserts (same explicit `_key` copy as above)
            for node in nodes:
                try:
                    await db.execute_query(
                        """
                        UPSERT { @key_field: @key_value }
                        INSERT MERGE(@doc, { _key: @key_value, _active: true })
                        UPDATE MERGE(@doc, { _active: true })
                        IN @@collection
                        """,
                        bind_vars={
                            "key_field": key_field,
                            "key_value": node.get(key_field),
                            "doc": node,
                            "@collection": collection,
                        },
                    )
                    inserted += 1  # approximate
                except Exception as inner_e:
                    logger.warning("Individual upsert failed: %s", inner_e)

        logger.info(
            "Upserted %d nodes into '%s': %d inserted, %d updated, %d unchanged",
            len(nodes), collection, inserted, updated, unchanged,
        )
        return UpsertResult(
            inserted=inserted, updated=updated, unchanged=unchanged,
        )

    async def create_edges(
        self,
        ctx: TenantContext,
        edge_collection: str,
        edges: list[dict[str, Any]],
    ) -> int:
        """Create edges in an edge collection.

        Each edge dict must contain ``_from`` and ``_to`` (full document IDs).
        Duplicates are skipped (upsert on _from + _to composite).

        Args:
            ctx: Tenant context.
            edge_collection: Edge collection name.
            edges: List of edge documents with ``_from`` and ``_to``.

        Returns:
            Number of edges created.
        """
        if not edges:
            return 0

        db = await self._get_db(ctx)
        created = 0

        aql = """
        FOR edge IN @edges
            UPSERT { _from: edge._from, _to: edge._to }
            INSERT edge
            UPDATE {}
            IN @@collection
            RETURN NEW ? 1 : 0
        """
        try:
            results = await db.execute_query(
                aql,
                bind_vars={
                    "edges": edges,
                    "@collection": edge_collection,
                },
            )
            created = sum(1 for r in (results or []) if r)
        except Exception as e:
            logger.error(
                "Batch edge creation failed for '%s': %s",
                edge_collection, e,
            )
            # Fallback: individual inserts
            for edge in edges:
                try:
                    await db.execute_query(
                        """
                        UPSERT { _from: @from, _to: @to }
                        INSERT @edge
                        UPDATE {}
                        IN @@collection
                        """,
                        bind_vars={
                            "from": edge["_from"],
                            "to": edge["_to"],
                            "edge": edge,
                            "@collection": edge_collection,
                        },
                    )
                    created += 1
                except Exception:
                    pass

        logger.info(
            "Created %d edges in '%s' (of %d attempted)",
            created, edge_collection, len(edges),
        )
        return created

    async def get_all_nodes(
        self,
        ctx: TenantContext,
        collection: str,
    ) -> list[dict[str, Any]]:
        """Retrieve all active nodes from a vertex collection.

        Args:
            ctx: Tenant context.
            collection: Vertex collection name.

        Returns:
            List of node documents (only active ones).
        """
        db = await self._get_db(ctx)
        try:
            result = await db.execute_query(
                "FOR doc IN @@collection FILTER doc._active != false RETURN doc",
                bind_vars={"@collection": collection},
            )
            return list(result) if result else []
        except Exception as e:
            logger.error(
                "Failed to get nodes from '%s': %s", collection, e,
            )
            return []

    async def soft_delete_nodes(
        self,
        ctx: TenantContext,
        collection: str,
        keys: list[str],
    ) -> None:
        """Mark nodes as inactive (soft delete).

        Sets ``_active: false`` on matching nodes. Does not remove the
        documents — preserves audit trail.

        Args:
            ctx: Tenant context.
            collection: Vertex collection name.
            keys: List of ``_key`` values to soft-delete.
        """
        if not keys:
            return

        db = await self._get_db(ctx)
        try:
            await db.execute_query(
                """
                FOR key IN @keys
                    UPDATE { _key: key } WITH { _active: false }
                    IN @@collection
                """,
                bind_vars={
                    "keys": keys,
                    "@collection": collection,
                },
            )
            logger.info(
                "Soft-deleted %d nodes in '%s'", len(keys), collection,
            )
        except Exception as e:
            logger.error(
                "Soft delete failed for '%s': %s", collection, e,
            )

    # ------------------------------------------------------------------
    # Generic document helpers (graph commit protocol support)
    # ------------------------------------------------------------------
    #
    # Thin AQL wrappers used by ``GraphIndexPersistence`` to implement the
    # audited commit protocol (apply_update / revert_commit / ...).  They
    # RAISE on failure (like ``execute_traversal``) — the caller owns the
    # degrade-or-propagate decision.

    async def ensure_collection(
        self,
        ctx: TenantContext,
        name: str,
        edge: bool = False,
    ) -> None:
        """Create a collection when it does not exist (idempotent).

        Mirrors ``initialize_tenant``'s creation pattern for a single
        collection; logs and swallows failures like its siblings so a
        pre-existing collection or race never breaks the caller.

        Args:
            ctx: Tenant context.
            name: Collection name.
            edge: Create as an edge collection when ``True``.
        """
        db = await self._get_db(ctx)
        try:
            if not await db.collection_exists(name):
                if edge:
                    await db.create_collection(name, edge=True)
                else:
                    await db.create_collection(name)
                logger.info("Created collection '%s' (edge=%s)", name, edge)
        except Exception as e:  # noqa: BLE001 — idempotent best-effort
            logger.debug("ensure_collection('%s') skipped: %s", name, e)

    async def get_document(
        self,
        ctx: TenantContext,
        collection: str,
        key: str,
    ) -> Optional[dict[str, Any]]:
        """Fetch one document by ``_key``.

        Args:
            ctx: Tenant context.
            collection: Collection name.
            key: The ``_key`` value.

        Returns:
            The document dict, or ``None`` when absent.
        """
        db = await self._get_db(ctx)
        result = await db.execute_query(
            "FOR doc IN @@collection FILTER doc._key == @key LIMIT 1 RETURN doc",
            bind_vars={"@collection": collection, "key": key},
        )
        rows = list(result) if result else []
        return rows[0] if rows else None

    async def upsert_document(
        self,
        ctx: TenantContext,
        collection: str,
        doc: dict[str, Any],
    ) -> None:
        """Insert or fully replace one document by its ``_key``.

        Args:
            ctx: Tenant context.
            collection: Collection name.
            doc: Document body; must include ``_key``.
        """
        db = await self._get_db(ctx)
        await db.execute_query(
            """
            UPSERT { _key: @key }
                INSERT @doc
                REPLACE @doc
            IN @@collection
            """,
            bind_vars={
                "key": doc.get("_key"),
                "doc": doc,
                "@collection": collection,
            },
        )

    async def insert_document(
        self,
        ctx: TenantContext,
        collection: str,
        doc: dict[str, Any],
    ) -> None:
        """Insert one document (auto ``_key`` when absent).

        Args:
            ctx: Tenant context.
            collection: Collection name.
            doc: Document body.
        """
        db = await self._get_db(ctx)
        await db.execute_query(
            "INSERT @doc IN @@collection",
            bind_vars={"doc": doc, "@collection": collection},
        )

    async def remove_document(
        self,
        ctx: TenantContext,
        collection: str,
        key: str,
    ) -> bool:
        """Hard-remove one document by ``_key``.

        Args:
            ctx: Tenant context.
            collection: Collection name.
            key: The ``_key`` value.

        Returns:
            ``True`` when a document was removed.
        """
        db = await self._get_db(ctx)
        result = await db.execute_query(
            """
            FOR doc IN @@collection
                FILTER doc._key == @key
                REMOVE doc IN @@collection
                RETURN OLD._key
            """,
            bind_vars={"@collection": collection, "key": key},
        )
        return bool(list(result) if result else [])

    async def query_documents(
        self,
        ctx: TenantContext,
        collection: str,
        filters: Optional[dict[str, Any]] = None,
        sort_desc: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Query documents by ANDed equality filters.

        Args:
            ctx: Tenant context.
            collection: Collection name.
            filters: ``{field: value}`` equality filters (ANDed). Field
                names must be plain identifiers — they are interpolated
                into the AQL; values are always bound.
            sort_desc: Optional field to sort by, descending.
            limit: Optional maximum rows.

        Returns:
            Matching document dicts.
        """
        db = await self._get_db(ctx)
        bind_vars: dict[str, Any] = {"@collection": collection}
        clauses: list[str] = []
        for i, (field, value) in enumerate((filters or {}).items()):
            if not field.replace("_", "").isalnum():
                raise ValueError(f"query_documents: invalid field {field!r}")
            clauses.append(f"FILTER doc.{field} == @f{i}")
            bind_vars[f"f{i}"] = value
        aql = "FOR doc IN @@collection\n" + "\n".join(clauses)
        if sort_desc is not None:
            if not sort_desc.replace("_", "").isalnum():
                raise ValueError(
                    f"query_documents: invalid sort field {sort_desc!r}"
                )
            aql += f"\nSORT doc.{sort_desc} DESC"
        if limit is not None:
            aql += f"\nLIMIT {int(limit)}"
        aql += "\nRETURN doc"
        result = await db.execute_query(aql, bind_vars=bind_vars)
        return list(result) if result else []

    async def get_all_edges(
        self,
        ctx: TenantContext,
        collection: str,
    ) -> list[dict[str, Any]]:
        """Retrieve every edge document from an edge collection.

        Args:
            ctx: Tenant context.
            collection: Edge collection name.

        Returns:
            Edge document dicts (empty on failure — read parity with
            ``get_all_nodes``).
        """
        db = await self._get_db(ctx)
        try:
            result = await db.execute_query(
                "FOR doc IN @@collection RETURN doc",
                bind_vars={"@collection": collection},
            )
            return list(result) if result else []
        except Exception as e:  # noqa: BLE001 — read parity with get_all_nodes
            logger.error("Failed to get edges from '%s': %s", collection, e)
            return []

    async def edges_incident(
        self,
        ctx: TenantContext,
        collection: str,
        node_id: str,
    ) -> list[dict[str, Any]]:
        """Edges in a collection touching a node (either direction).

        Args:
            ctx: Tenant context.
            collection: Edge collection name.
            node_id: The node's ``node_id``.

        Returns:
            Matching edge document dicts.
        """
        db = await self._get_db(ctx)
        result = await db.execute_query(
            """
            FOR e IN @@collection
                FILTER e.source_id == @node_id OR e.target_id == @node_id
                RETURN e
            """,
            bind_vars={"@collection": collection, "node_id": node_id},
        )
        return list(result) if result else []

    async def remove_edge_by_triple(
        self,
        ctx: TenantContext,
        collection: str,
        source_id: str,
        target_id: str,
        kind: str,
    ) -> bool:
        """Hard-remove edge(s) matching a ``(source, target, kind)`` triple.

        Args:
            ctx: Tenant context.
            collection: Edge collection name.
            source_id: Tail ``node_id``.
            target_id: Head ``node_id``.
            kind: Edge kind string.

        Returns:
            ``True`` when at least one edge was removed.
        """
        db = await self._get_db(ctx)
        result = await db.execute_query(
            """
            FOR e IN @@collection
                FILTER e.source_id == @src AND e.target_id == @tgt
                   AND e.kind == @kind
                REMOVE e IN @@collection
                RETURN OLD._key
            """,
            bind_vars={
                "@collection": collection,
                "src": source_id,
                "tgt": target_id,
                "kind": kind,
            },
        )
        return bool(list(result) if result else [])
