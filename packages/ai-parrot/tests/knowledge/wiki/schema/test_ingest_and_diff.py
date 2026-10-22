"""Focused integration tests for DDL ingestion and live-versus-DDL reporting."""

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from parrot.bots.database.models import Completeness, TableMetadata
from parrot.knowledge.wiki.schema.models import SchemaPlaneConfig, SchemaSourceConfig
from parrot.knowledge.wiki.schema.service import SchemaPlaneService


@pytest.fixture
def svc(plane_dir: Path) -> SchemaPlaneService:
    """Return a writable schema plane configured for PostgreSQL DDL."""
    return SchemaPlaneService.from_dir(
        plane_dir,
        config=SchemaPlaneConfig(
            sources={"pg": SchemaSourceConfig(alias="pg", dialect="postgres", dsn_env="TEST_DSN")}
        ),
        read_only=False,
    )


async def test_ddl_fills_gap(svc: SchemaPlaneService, tmp_path: Path) -> None:
    """DDL creates a page when the plane has no live table page."""
    migration = tmp_path / "001.sql"
    migration.write_text("CREATE TABLE public.users (id int PRIMARY KEY, name text);", encoding="utf-8")

    report = await svc.ingest_ddl([migration], origin="pg", dialect="postgres", root=tmp_path)

    assert report.created == ["table:pg/public.users"]
    page = await svc.store.get_page("table:pg/public.users")
    assert page is not None
    assert '"source": "ddl"' in page["body"]


async def test_live_wins_and_adds_defined_in(svc: SchemaPlaneService, tmp_path: Path) -> None:
    """DDL leaves a live page unchanged while retaining its migration edge."""
    live = TableMetadata(
        schema="epson",
        tablename="sales",
        table_type="BASE TABLE",
        full_name="epson.sales",
        columns=[{"name": "id", "type": "BIGINT", "nullable": False}],
        primary_keys=["id"],
        completeness=Completeness.FULL,
        source="information_schema",
    )
    await svc.put_table("pg", "postgres", live)
    page_before = await svc.store.get_page("table:pg/epson.sales")
    migration = tmp_path / "001.sql"
    migration.write_text("CREATE TABLE epson.sales (id int);", encoding="utf-8")

    report = await svc.ingest_ddl([migration], origin="pg", dialect="postgres", root=tmp_path)

    page_after = await svc.store.get_page("table:pg/epson.sales")
    assert report.unchanged == ["table:pg/epson.sales"]
    assert page_before is not None and page_after is not None
    assert page_after["body"] == page_before["body"]
    assert await svc.store.neighbors("table:pg/epson.sales", rel="defined_in")


async def test_ingest_ddl_check_and_write_share_one_transaction(
    svc: SchemaPlaneService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live sync that commits just before the DDL write is never overwritten."""
    live = TableMetadata(
        schema="public",
        tablename="users",
        table_type="BASE TABLE",
        full_name="public.users",
        columns=[{"name": "id", "type": "BIGINT", "nullable": False}],
        primary_keys=["id"],
        completeness=Completeness.FULL,
        source="information_schema",
    )
    store = svc.store
    original_write = store._write
    operations: list[str] = []

    @asynccontextmanager
    async def racing_write(operation: str):
        operations.append(operation)
        if operation == "fold_ddl_table":
            # The concurrent `schema sync` lands after ingest_ddl started, before its write.
            await svc.put_table("pg", "postgres", live)
        async with original_write(operation) as conn:
            yield conn

    async def forbidden_read(*_args, **_kwargs):
        raise AssertionError("ingest_ddl must not read pages outside its write transaction")

    migration = tmp_path / "001.sql"
    migration.write_text("CREATE TABLE public.users (id int, name text);", encoding="utf-8")
    monkeypatch.setattr(store, "_write", racing_write)
    monkeypatch.setattr(store, "get_page", forbidden_read)

    report = await svc.ingest_ddl([migration], origin="pg", dialect="postgres", root=tmp_path)

    monkeypatch.undo()
    page = await store.get_page("table:pg/public.users")
    assert report.unchanged == ["table:pg/public.users"]
    assert page is not None and '"source": "ddl"' not in page["body"]
    assert [column.name for column in await store.columns_for("table:pg/public.users")] == ["id"]
    assert await store.neighbors("table:pg/public.users", rel="defined_in")
    assert operations.count("fold_ddl_table") == 1


async def test_ingest_ddl_created_updated_unchanged(svc: SchemaPlaneService, tmp_path: Path) -> None:
    """DDL pages report created, unchanged under changed_only, then updated on edit."""
    migration = tmp_path / "001.sql"
    migration.write_text("CREATE TABLE public.users (id int);", encoding="utf-8")
    kwargs = {"origin": "pg", "dialect": "postgres", "root": tmp_path}

    first = await svc.ingest_ddl([migration], **kwargs)
    second = await svc.ingest_ddl([migration], changed_only=True, **kwargs)
    migration.write_text("CREATE TABLE public.users (id int, email text);", encoding="utf-8")
    third = await svc.ingest_ddl([migration], changed_only=True, **kwargs)

    assert first.created == ["table:pg/public.users"]
    assert second.unchanged == ["table:pg/public.users"]
    assert third.updated == ["table:pg/public.users"]
    columns = await svc.store.columns_for("table:pg/public.users")
    assert [column.name for column in columns] == ["id", "email"]


async def test_ingest_ddl_reports_parse_errors(svc: SchemaPlaneService, tmp_path: Path) -> None:
    """A malformed statement is reported without preventing a valid table write."""
    migration = tmp_path / "broken.sql"
    migration.write_text("nonsense !!!; CREATE TABLE public.users (id int);", encoding="utf-8")

    report = await svc.ingest_ddl([migration], origin="pg", dialect="postgres", root=tmp_path)

    assert report.parse_errors
    assert report.created == ["table:pg/public.users"]


async def test_diff_reports_type_mismatch_and_identical_schema(
    svc: SchemaPlaneService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Diff reports structural drift but returns no rows for identical facts."""
    migration = tmp_path / "001.sql"
    migration.write_text("CREATE TABLE public.users (id int PRIMARY KEY, name text);", encoding="utf-8")
    svc.config.sources["pg"].ddl_paths = ["001.sql"]
    monkeypatch.chdir(tmp_path)
    live = TableMetadata(
        schema="public",
        tablename="users",
        table_type="BASE TABLE",
        full_name="public.users",
        columns=[{"name": "id", "type": "bigint", "nullable": False}, {"name": "name", "type": "text"}],
        primary_keys=["id"],
        completeness=Completeness.FULL,
        source="information_schema",
    )
    await svc.put_table("pg", "postgres", live)

    differences = await svc.diff("pg")

    assert {row["field"] for row in differences} == {"column:id.type"}
    assert differences[0]["live"] == "bigint"
    assert differences[0]["ddl"] == "INT"

    live.columns[0]["type"] = "INT"
    await svc.put_table("pg", "postgres", live)
    assert await svc.diff("pg") == []
