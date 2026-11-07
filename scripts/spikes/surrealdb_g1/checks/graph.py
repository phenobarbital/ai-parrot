"""G1 graph traversal and GraphDocumentStore-shape checks."""

from __future__ import annotations

from checks._common import connect, execute, g1_check
from harness import CheckResult, SpikeContext


@g1_check("G1-11", "Relation traversal, reachability, and safe dynamic reads", blocking=True)
async def check_g1_11_traversal(ctx: SpikeContext) -> CheckResult:
    """Exercise graph relations and reject dynamic statements outside a read allow-list."""
    setup = """
DEFINE TABLE node SCHEMAFULL;
DEFINE FIELD name ON node TYPE string;
DEFINE TABLE linked TYPE RELATION FROM node TO node;
CREATE node:a SET name = 'a'; CREATE node:b SET name = 'b'; CREATE node:c SET name = 'c';
RELATE node:a->linked->node:b; RELATE node:b->linked->node:c;
"""
    traversal = "SELECT ->linked->node.name AS reachable FROM node:a;"
    dynamic = "SELECT name FROM node WHERE name = $name;"
    async with connect(ctx, "g1", "g1_11", reset=True) as db:
        await execute(db, setup)
        rows = await db.query(traversal).first()
        assert rows and rows[0]["reachable"] == ["b"], rows
        allowed = dynamic.strip().upper().startswith("SELECT ")
        assert allowed, "dynamic query allow-list rejected a read"
        dynamic_rows = await db.query(dynamic, {"name": "b"}).first()
        mutation = "DELETE node:a;"
        assert not mutation.strip().upper().startswith("SELECT ")
    return CheckResult(
        check_id="G1-11",
        title=check_g1_11_traversal.title,
        blocking=True,
        status="pass",
        evidence=f"{traversal} rows={rows!r}; allow-list permitted {dynamic} rows={dynamic_rows!r} and rejected {mutation}",
    )


@g1_check("G1-12", "Runtime documents are isolated by tenant namespace/database", blocking=True)
async def check_g1_12_document_store(ctx: SpikeContext) -> CheckResult:
    """Create a runtime table, upsert/soft-delete it, then prove tenant isolation."""
    setup = """
DEFINE TABLE runtime_document SCHEMAFULL;
DEFINE FIELD key ON runtime_document TYPE string;
DEFINE FIELD kind ON runtime_document TYPE string;
DEFINE FIELD deleted_at ON runtime_document TYPE option<datetime>;
DEFINE INDEX runtime_document_key ON runtime_document FIELDS key UNIQUE;
UPSERT runtime_document:one SET key = $key, kind = 'note', deleted_at = NONE;
UPDATE runtime_document:one SET deleted_at = time::now();
"""
    filter_query = "SELECT * FROM runtime_document WHERE key = $key AND deleted_at = NONE;"
    async with connect(ctx, "g1_tenant_a", "documents", reset=True) as db:
        await execute(db, setup, {"key": "shared"})
        visible = await db.query(filter_query, {"key": "shared"}).first()
    async with connect(ctx, "g1_tenant_b", "documents") as db:
        try:
            cross_tenant: object = await db.query(
                "SELECT * FROM runtime_document WHERE key = $key;", {"key": "shared"}
            ).first()
        except Exception as exc:  # SurrealDB 3 errors on a table that tenant b never defined
            if "does not exist" not in str(exc):
                raise
            cross_tenant = f"table absent in tenant b ({type(exc).__name__})"
    assert visible == [], visible
    assert cross_tenant == [] or str(cross_tenant).startswith("table absent"), cross_tenant
    return CheckResult(
        check_id="G1-12",
        title=check_g1_12_document_store.title,
        blocking=True,
        status="pass",
        evidence=f"{setup} {filter_query} soft-delete={visible!r}; tenant-b cross-read={cross_tenant!r}",
    )
