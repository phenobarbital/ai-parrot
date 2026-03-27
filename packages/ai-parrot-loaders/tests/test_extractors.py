"""Tests for ExtractDataSource implementations."""
import csv
import json
import tempfile
from pathlib import Path

import pytest

from parrot.loaders.extractors import (
    CSVDataSource,
    JSONDataSource,
    RecordsDataSource,
    SQLDataSource,
)
from parrot.knowledge.ontology.exceptions import DataSourceValidationError


# ── Fixtures ──


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    """Create a temporary CSV file with sample data."""
    p = tmp_path / "employees.csv"
    with open(p, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "name", "dept", "age"])
        writer.writeheader()
        writer.writerow({"id": "1", "name": "Alice", "dept": "eng", "age": "30"})
        writer.writerow({"id": "2", "name": "Bob", "dept": "sales", "age": "25"})
        writer.writerow({"id": "3", "name": "Carol", "dept": "eng", "age": "35"})
    return p


@pytest.fixture
def json_file_flat(tmp_path: Path) -> Path:
    """Create a flat JSON array file."""
    p = tmp_path / "records.json"
    p.write_text(json.dumps([
        {"id": 1, "name": "Alice", "role": "engineer"},
        {"id": 2, "name": "Bob", "role": "manager"},
    ]))
    return p


@pytest.fixture
def json_file_nested(tmp_path: Path) -> Path:
    """Create a nested JSON file."""
    p = tmp_path / "nested.json"
    p.write_text(json.dumps({
        "status": "ok",
        "data": {
            "employees": [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
            ]
        }
    }))
    return p


@pytest.fixture
def sample_records() -> list[dict]:
    """Sample in-memory records."""
    return [
        {"id": 1, "name": "Alice", "dept": "eng"},
        {"id": 2, "name": "Bob", "dept": "sales"},
        {"id": 3, "name": "Carol", "dept": "eng"},
    ]


# ── CSVDataSource Tests ──


class TestCSVDataSource:

    @pytest.mark.asyncio
    async def test_extract_all(self, csv_file: Path):
        ds = CSVDataSource("test_csv", config={"path": str(csv_file)})
        result = await ds.extract()
        assert result.total == 3
        assert result.source_name == "test_csv"
        assert result.records[0].data["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_extract_with_field_projection(self, csv_file: Path):
        ds = CSVDataSource("test_csv", config={"path": str(csv_file)})
        result = await ds.extract(fields=["name", "dept"])
        assert result.total == 3
        for r in result.records:
            assert "id" not in r.data
            assert "name" in r.data
            assert "dept" in r.data

    @pytest.mark.asyncio
    async def test_extract_with_filters(self, csv_file: Path):
        ds = CSVDataSource("test_csv", config={"path": str(csv_file)})
        result = await ds.extract(filters={"dept": "eng"})
        assert result.total == 2
        assert all(r.data["dept"] == "eng" for r in result.records)

    @pytest.mark.asyncio
    async def test_list_fields(self, csv_file: Path):
        ds = CSVDataSource("test_csv", config={"path": str(csv_file)})
        fields = await ds.list_fields()
        assert fields == ["id", "name", "dept", "age"]

    @pytest.mark.asyncio
    async def test_missing_file(self, tmp_path: Path):
        ds = CSVDataSource("missing", config={"path": str(tmp_path / "nope.csv")})
        result = await ds.extract()
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_validate_passes(self, csv_file: Path):
        ds = CSVDataSource("test_csv", config={"path": str(csv_file)})
        assert await ds.validate(["name", "dept"]) is True

    @pytest.mark.asyncio
    async def test_validate_fails(self, csv_file: Path):
        ds = CSVDataSource("test_csv", config={"path": str(csv_file)})
        with pytest.raises(DataSourceValidationError):
            await ds.validate(["name", "nonexistent_field"])

    @pytest.mark.asyncio
    async def test_custom_delimiter(self, tmp_path: Path):
        p = tmp_path / "semicolon.csv"
        with open(p, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["a", "b"], delimiter=";")
            writer.writeheader()
            writer.writerow({"a": "1", "b": "2"})
        ds = CSVDataSource("semi", config={"path": str(p), "delimiter": ";"})
        result = await ds.extract()
        assert result.total == 1
        assert result.records[0].data == {"a": "1", "b": "2"}


# ── JSONDataSource Tests ──


class TestJSONDataSource:

    @pytest.mark.asyncio
    async def test_extract_flat(self, json_file_flat: Path):
        ds = JSONDataSource("flat", config={"path": str(json_file_flat)})
        result = await ds.extract()
        assert result.total == 2
        assert result.records[0].data["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_extract_nested(self, json_file_nested: Path):
        ds = JSONDataSource(
            "nested",
            config={"path": str(json_file_nested), "records_path": "data.employees"},
        )
        result = await ds.extract()
        assert result.total == 2

    @pytest.mark.asyncio
    async def test_extract_with_filters(self, json_file_flat: Path):
        ds = JSONDataSource("flat", config={"path": str(json_file_flat)})
        result = await ds.extract(filters={"role": "manager"})
        assert result.total == 1
        assert result.records[0].data["name"] == "Bob"

    @pytest.mark.asyncio
    async def test_list_fields(self, json_file_flat: Path):
        ds = JSONDataSource("flat", config={"path": str(json_file_flat)})
        fields = await ds.list_fields()
        assert set(fields) == {"id", "name", "role"}

    @pytest.mark.asyncio
    async def test_invalid_json(self, tmp_path: Path):
        p = tmp_path / "bad.json"
        p.write_text("{invalid json")
        ds = JSONDataSource("bad", config={"path": str(p)})
        result = await ds.extract()
        assert result.total == 0
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_bad_records_path(self, json_file_nested: Path):
        ds = JSONDataSource(
            "nested",
            config={"path": str(json_file_nested), "records_path": "data.nonexistent"},
        )
        result = await ds.extract()
        assert result.total == 0
        assert len(result.errors) > 0


# ── RecordsDataSource Tests ──


class TestRecordsDataSource:

    @pytest.mark.asyncio
    async def test_extract_all(self, sample_records):
        ds = RecordsDataSource("inmem", records=sample_records)
        result = await ds.extract()
        assert result.total == 3
        assert result.records[1].data["name"] == "Bob"

    @pytest.mark.asyncio
    async def test_extract_with_filters(self, sample_records):
        ds = RecordsDataSource("inmem", records=sample_records)
        result = await ds.extract(filters={"dept": "eng"})
        assert result.total == 2

    @pytest.mark.asyncio
    async def test_extract_with_projection(self, sample_records):
        ds = RecordsDataSource("inmem", records=sample_records)
        result = await ds.extract(fields=["name"])
        assert result.total == 3
        for r in result.records:
            assert list(r.data.keys()) == ["name"]

    @pytest.mark.asyncio
    async def test_list_fields(self, sample_records):
        ds = RecordsDataSource("inmem", records=sample_records)
        fields = await ds.list_fields()
        assert set(fields) == {"id", "name", "dept"}

    @pytest.mark.asyncio
    async def test_empty_records(self):
        ds = RecordsDataSource("empty", records=[])
        result = await ds.extract()
        assert result.total == 0
        fields = await ds.list_fields()
        assert fields == []

    @pytest.mark.asyncio
    async def test_validate_passes(self, sample_records):
        ds = RecordsDataSource("inmem", records=sample_records)
        assert await ds.validate(["name", "dept"]) is True

    @pytest.mark.asyncio
    async def test_validate_fails(self, sample_records):
        ds = RecordsDataSource("inmem", records=sample_records)
        with pytest.raises(DataSourceValidationError):
            await ds.validate(["name", "missing_field"])


# ── SQLDataSource Tests ──


class TestSQLDataSource:

    @pytest.mark.asyncio
    async def test_rejects_mutation_query(self):
        ds = SQLDataSource(
            "sql_test",
            config={
                "dsn": "postgresql://localhost/test",
                "query": "INSERT INTO users VALUES (1, 'test')",
            },
        )
        with pytest.raises(DataSourceValidationError, match="mutation"):
            await ds.extract()

    @pytest.mark.asyncio
    async def test_rejects_delete(self):
        ds = SQLDataSource(
            "sql_test",
            config={
                "dsn": "postgresql://localhost/test",
                "query": "DELETE FROM users WHERE id = 1",
            },
        )
        with pytest.raises(DataSourceValidationError, match="mutation"):
            await ds.extract()

    @pytest.mark.asyncio
    async def test_no_query_returns_empty(self):
        ds = SQLDataSource("sql_empty", config={"dsn": "x"})
        result = await ds.extract()
        assert result.total == 0
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_no_dsn_returns_empty(self):
        ds = SQLDataSource("sql_empty", config={"query": "SELECT 1"})
        result = await ds.extract()
        assert result.total == 0
        assert len(result.errors) > 0
