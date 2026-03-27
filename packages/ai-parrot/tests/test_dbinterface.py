"""Integration test for DBInterface.

Requires a running PostgreSQL server reachable via the real ``default_dsn``
from ``navigator.conf``.  The test creates a temporary table in the ``test``
schema, exercises every DBInterface method, and drops the table in a
``finally`` block so cleanup always happens even if a test step fails.

Run with:
    source .venv/bin/activate && python -m pytest tests/test_dbinterface.py -v -s
"""
from __future__ import annotations

import sys

# ---------------------------------------------------------------------------
# Override the conftest navigation stubs with the real module so we get the
# actual PostgreSQL DSN.  This must happen *before* importing parrot.conf.
# The conftest installs lightweight stubs for navconfig/navigator.conf;
# we replace *only* navigator.conf (and parrot.conf which caches
# the stub's default_dsn) with the real module.
# ---------------------------------------------------------------------------
try:
    # Pop the stubs so the real module gets imported
    sys.modules.pop("navigator.conf", None)
    sys.modules.pop("navigator", None)
    sys.modules.pop("parrot.conf", None)

    # navconfig stub may lack attributes the real navigator.conf needs;
    # pop it too and let the real one load
    for _k in list(sys.modules):
        if _k == "navconfig" or _k.startswith("navconfig."):
            sys.modules.pop(_k, None)

    import navigator.conf  # noqa: E402 – reimport real module
except ImportError as _e:
    print(f"WARNING: Could not import real navigator.conf: {_e}")

import pytest
import pytest_asyncio
from pydantic import BaseModel as PydanticModel
from typing import Optional

from parrot.conf import default_dsn
from parrot.interfaces.database import DBInterface


# ---------------------------------------------------------------------------
# Test pydantic model (renamed to avoid pytest collection warning)
# ---------------------------------------------------------------------------

class SampleRecord(PydanticModel):
    """Pydantic model representing a row in our test table."""
    id: int
    name: str
    category: str
    score: float
    active: bool = True
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SCHEMA = "test"
TABLE = "dbinterface_test"
QUALIFIED = f"{SCHEMA}.{TABLE}"

SAMPLE_RECORDS = [
    SampleRecord(id=1, name="Alice",   category="engineering", score=95.5, notes="senior"),
    SampleRecord(id=2, name="Bob",     category="engineering", score=88.0, notes="mid-level"),
    SampleRecord(id=3, name="Charlie", category="marketing",   score=72.3, notes=None),
    SampleRecord(id=4, name="Diana",   category="marketing",   score=91.1, active=False),
    SampleRecord(id=5, name="Eve",     category="engineering", score=84.7, notes="junior"),
]


@pytest_asyncio.fixture
async def db():
    """Provide a DBInterface instance and ensure the test schema + table exist."""
    iface = DBInterface()

    # Ensure the schema exists
    await iface.execute(
        f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}",
        driver="pg",
        dsn=default_dsn,
    )

    # Create the test table (drop first to avoid stale data between runs)
    await iface.execute(
        f"DROP TABLE IF EXISTS {QUALIFIED}",
        driver="pg",
        dsn=default_dsn,
    )

    create_sql = f"""
    CREATE TABLE {QUALIFIED} (
        id        INTEGER PRIMARY KEY,
        name      VARCHAR(100) NOT NULL,
        category  VARCHAR(50)  NOT NULL,
        score     DOUBLE PRECISION NOT NULL DEFAULT 0,
        active    BOOLEAN NOT NULL DEFAULT TRUE,
        notes     TEXT
    )
    """
    await iface.execute(create_sql, driver="pg", dsn=default_dsn)

    yield iface

    # Cleanup: drop the table no matter what
    try:
        await iface.execute(
            f"DROP TABLE IF EXISTS {QUALIFIED}",
            driver="pg",
            dsn=default_dsn,
        )
    except Exception as exc:
        print(f"WARNING: Failed to drop test table: {exc}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ensure_indexes(db: DBInterface):
    """Create btree indexes on two search columns."""
    ddl1 = await db.ensure_indexes(
        table=TABLE,
        schema=SCHEMA,
        fields=["category", "active"],
        index_type="btree",
        driver="pg",
        dsn=default_dsn,
    )
    assert "CREATE INDEX" in ddl1
    assert "idx_test_dbinterface_test_category" in ddl1

    ddl2 = await db.ensure_indexes(
        table=TABLE,
        schema=SCHEMA,
        fields=["name"],
        index_type="btree",
        driver="pg",
        dsn=default_dsn,
    )
    assert "idx_test_dbinterface_test_name" in ddl2
    print(f"✓ Indexes created:\n  {ddl1}\n  {ddl2}")


@pytest.mark.asyncio
async def test_insert_records(db: DBInterface):
    """Insert 5 test records using pydantic objects."""
    for rec in SAMPLE_RECORDS:
        result = await db.insert(
            table=TABLE,
            schema=SCHEMA,
            obj=rec,
            driver="pg",
            dsn=default_dsn,
        )
        print(f"  inserted id={rec.id}: {result}")

    # Verify count
    rows = await db.filter(
        table=TABLE,
        schema=SCHEMA,
        conditions={},
        fields=["id"],
        driver="pg",
        dsn=default_dsn,
    )
    assert rows is not None
    assert len(rows) == 5, f"Expected 5 rows, got {len(rows)}"
    print(f"✓ Inserted {len(rows)} records")


@pytest.mark.asyncio
async def test_filter_records(db: DBInterface):
    """Filter records by category='engineering'."""
    # First insert all records
    for rec in SAMPLE_RECORDS:
        await db.insert(
            table=TABLE, schema=SCHEMA, obj=rec,
            driver="pg", dsn=default_dsn,
        )

    # Filter for engineering
    rows = await db.filter(
        table=TABLE,
        schema=SCHEMA,
        conditions={"category": "engineering"},
        fields=["id", "name", "score"],
        driver="pg",
        dsn=default_dsn,
    )
    assert rows is not None
    assert len(rows) == 3, f"Expected 3 engineering rows, got {len(rows)}"
    names = {dict(r)["name"] for r in rows}
    assert names == {"Alice", "Bob", "Eve"}
    print(f"✓ Filtered {len(rows)} engineering records: {names}")


@pytest.mark.asyncio
async def test_get_single_record(db: DBInterface):
    """Get a single record by id."""
    for rec in SAMPLE_RECORDS:
        await db.insert(
            table=TABLE, schema=SCHEMA, obj=rec,
            driver="pg", dsn=default_dsn,
        )

    row = await db.get(
        table=TABLE,
        schema=SCHEMA,
        conditions={"id": 1},
        fields=["id", "name", "score", "notes"],
        driver="pg",
        dsn=default_dsn,
    )
    assert row is not None
    row_dict = dict(row)
    assert row_dict["name"] == "Alice"
    assert row_dict["score"] == 95.5
    print(f"✓ Got record: {row_dict}")


@pytest.mark.asyncio
async def test_update_record(db: DBInterface):
    """Update a record and verify the change."""
    # Insert
    for rec in SAMPLE_RECORDS:
        await db.insert(
            table=TABLE, schema=SCHEMA, obj=rec,
            driver="pg", dsn=default_dsn,
        )

    # Get original
    original = await db.get(
        table=TABLE, schema=SCHEMA,
        conditions={"id": 1},
        driver="pg", dsn=default_dsn,
    )
    assert original is not None
    assert dict(original)["name"] == "Alice"

    # Update: change name and score
    updated_obj = SampleRecord(
        id=1, name="Alice Updated", category="engineering",
        score=99.0, notes="promoted",
    )
    await db.update(
        table=TABLE,
        schema=SCHEMA,
        obj=updated_obj,
        unique_fields=["id"],
        driver="pg",
        dsn=default_dsn,
    )

    # Verify
    after = await db.get(
        table=TABLE, schema=SCHEMA,
        conditions={"id": 1},
        driver="pg", dsn=default_dsn,
    )
    assert after is not None
    after_dict = dict(after)
    assert after_dict["name"] == "Alice Updated"
    assert after_dict["score"] == 99.0
    assert after_dict["notes"] == "promoted"
    print(f"✓ Updated record verified: {after_dict}")


@pytest.mark.asyncio
async def test_delete_record(db: DBInterface):
    """Delete a record and verify it's gone."""
    for rec in SAMPLE_RECORDS:
        await db.insert(
            table=TABLE, schema=SCHEMA, obj=rec,
            driver="pg", dsn=default_dsn,
        )

    # Delete Charlie (id=3)
    target = SampleRecord(
        id=3, name="Charlie", category="marketing", score=72.3,
    )
    await db.delete(
        table=TABLE,
        schema=SCHEMA,
        obj=target,
        unique_fields=["id"],
        driver="pg",
        dsn=default_dsn,
    )

    # Verify deleted
    row = await db.get(
        table=TABLE, schema=SCHEMA,
        conditions={"id": 3},
        driver="pg", dsn=default_dsn,
    )
    assert row is None, "Expected record to be deleted"
    print("✓ Record deleted successfully")


@pytest.mark.asyncio
async def test_full_lifecycle(db: DBInterface):
    """End-to-end lifecycle: create indexes, insert, filter, get, update, verify."""
    # 1. Create indexes
    await db.ensure_indexes(
        table=TABLE, schema=SCHEMA,
        fields=["category", "active"],
        driver="pg", dsn=default_dsn,
    )
    await db.ensure_indexes(
        table=TABLE, schema=SCHEMA,
        fields=["name"],
        driver="pg", dsn=default_dsn,
    )
    print("  [1] Indexes created")

    # 2. Insert 5 records
    for rec in SAMPLE_RECORDS:
        await db.insert(
            table=TABLE, schema=SCHEMA, obj=rec,
            driver="pg", dsn=default_dsn,
        )
    print("  [2] Inserted 5 records")

    # 3. Filter: get engineering records
    eng_rows = await db.filter(
        table=TABLE, schema=SCHEMA,
        conditions={"category": "engineering"},
        fields=["id", "name"],
        driver="pg", dsn=default_dsn,
    )
    assert eng_rows is not None
    assert len(eng_rows) == 3
    print(f"  [3] Filtered {len(eng_rows)} engineering records")

    # 4. Get single record by id
    alice = await db.get(
        table=TABLE, schema=SCHEMA,
        conditions={"id": 1},
        driver="pg", dsn=default_dsn,
    )
    assert alice is not None
    assert dict(alice)["name"] == "Alice"
    print(f"  [4] Got Alice: {dict(alice)}")

    # 5. Update Alice
    updated = SampleRecord(
        id=1, name="Alice Updated", category="engineering",
        score=99.9, notes="promoted to lead",
    )
    await db.update(
        table=TABLE, schema=SCHEMA,
        obj=updated, unique_fields=["id"],
        driver="pg", dsn=default_dsn,
    )
    print("  [5] Updated Alice")

    # 6. Verify the update
    alice_after = await db.get(
        table=TABLE, schema=SCHEMA,
        conditions={"id": 1},
        driver="pg", dsn=default_dsn,
    )
    assert alice_after is not None
    a = dict(alice_after)
    assert a["name"] == "Alice Updated"
    assert a["score"] == 99.9
    assert a["notes"] == "promoted to lead"
    print(f"  [6] Verified update: {a}")
    print("✓ Full lifecycle test passed!")
