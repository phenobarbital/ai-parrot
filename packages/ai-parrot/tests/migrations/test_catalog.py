"""Behavioral tests for packaged migration discovery and local authoring."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from parrot.migrations import catalog
from parrot.migrations.catalog import discover_sets, load_migrations, render_sql, scaffold
from parrot.migrations.models import (
    MigrationConfigurationError,
    MigrationFile,
    MigrationItem,
    MigrationReport,
    MigrationSet,
)


def _migration_set() -> MigrationSet:
    """Return a local resource owner used by catalog tests."""
    return MigrationSet(name="bots", package="test.migrations", resource_dir="sql/bots", tables=("nav.bots",))


def _resource_directory(tmp_path: Path) -> Path:
    """Create the explicit source directory expected by a migration set."""
    directory = tmp_path / "sql" / "bots"
    directory.mkdir(parents=True)
    return directory


def _write_pair(directory: Path, sequence: int, name: str, body: bytes = b"SELECT 1;\n") -> None:
    """Write one migration body/check pair using exact body bytes."""
    stem = f"{sequence:03d}_{name}"
    (directory / f"{stem}.sql").write_bytes(body)
    (directory / f"{stem}.check.sql").write_bytes(b"SELECT TRUE;\n")


def _use_resources(monkeypatch: pytest.MonkeyPatch, directory: Path) -> None:
    """Map one package resource path to the temporary test resource tree."""
    monkeypatch.setattr(catalog.resources, "files", lambda package: directory.parents[1])


def test_discovery_is_sorted_and_rejects_invalid_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Discover providers by name and reject duplicate or mismatched registrations."""
    alpha = MigrationSet(name="alpha", package="a", resource_dir="sql/alpha", tables=("nav.alpha",))
    zeta = MigrationSet(name="zeta", package="z", resource_dir="sql/zeta", tables=("nav.zeta",))
    monkeypatch.setattr(
        catalog,
        "_entry_points",
        lambda: (
            SimpleNamespace(name="zeta", load=lambda: lambda: zeta),
            SimpleNamespace(name="alpha", load=lambda: lambda: alpha),
        ),
    )
    assert tuple(item.name for item in discover_sets()) == ("alpha", "zeta")

    monkeypatch.setattr(
        catalog,
        "_entry_points",
        lambda: (
            SimpleNamespace(name="alpha", load=lambda: lambda: alpha),
            SimpleNamespace(name="alpha", load=lambda: lambda: alpha),
        ),
    )
    with pytest.raises(MigrationConfigurationError, match="Duplicate"):
        discover_sets()

    monkeypatch.setattr(
        catalog,
        "_entry_points",
        lambda: (SimpleNamespace(name="alpha", load=lambda: lambda: zeta),),
    )
    with pytest.raises(MigrationConfigurationError, match="mismatch"):
        discover_sets()


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ({"001_first.sql": b"SELECT 1;\n"}, "incomplete"),
        ({"001_first.check.sql": b"SELECT TRUE;\n"}, "no SQL bodies"),
        (
            {
                "001_first.sql": b"SELECT 1;\n",
                "001_first.check.sql": b"SELECT TRUE;\n",
                "003_third.sql": b"SELECT 3;\n",
                "003_third.check.sql": b"SELECT TRUE;\n",
            },
            "gap",
        ),
        (
            {
                "001_first.sql": b"SELECT 1;\n",
                "001_first.check.sql": b"SELECT TRUE;\n",
                "001_second.sql": b"SELECT 2;\n",
                "001_second.check.sql": b"SELECT TRUE;\n",
            },
            "Duplicate",
        ),
        (
            {
                "001_first.sql": b"SELECT 1;\n",
                "001_first.check.sql": b"SELECT TRUE;\n",
                "002_orphan.check.sql": b"SELECT TRUE;\n",
            },
            "incomplete",
        ),
        ({"001_first.sql": b"\xff", "001_first.check.sql": b"SELECT TRUE;\n"}, "not UTF-8"),
    ],
)
def test_load_rejects_invalid_resource_sets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, files: dict[str, bytes], message: str
) -> None:
    """Reject absent pairs, gaps, duplicate sequences, and invalid encodings."""
    directory = _resource_directory(tmp_path)
    for filename, contents in files.items():
        (directory / filename).write_bytes(contents)
    _use_resources(monkeypatch, directory)

    with pytest.raises(MigrationConfigurationError, match=message):
        load_migrations(_migration_set())


def test_load_rejects_missing_resource_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Reject a provider whose declared package resource directory is absent."""
    monkeypatch.setattr(catalog.resources, "files", lambda package: tmp_path)

    with pytest.raises(MigrationConfigurationError, match="directory is missing"):
        load_migrations(_migration_set())


def test_load_uses_exact_bytes_for_hashes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Hash shipped byte content without normalizing platform line endings."""
    directory = _resource_directory(tmp_path)
    body = b"SELECT 1;\r\n"
    check = b"SELECT TRUE;\r\n"
    (directory / "001_first.sql").write_bytes(body)
    (directory / "001_first.check.sql").write_bytes(check)
    _use_resources(monkeypatch, directory)

    migration = load_migrations(_migration_set())[0]
    assert migration.sql == "SELECT 1;\r\n"
    assert migration.checksum == sha256(body).hexdigest()
    assert migration.check_checksum == sha256(check).hexdigest()


def test_models_are_immutable() -> None:
    """Prevent loaded migration metadata from being altered after validation."""
    migration = MigrationFile(
        migration_set="bots",
        filename="001_first.sql",
        sequence=1,
        sql="SELECT 1;",
        check_sql="SELECT TRUE;",
        checksum="body",
        check_checksum="check",
    )

    with pytest.raises(ValidationError):
        migration.filename = "002_second.sql"

    item = MigrationItem(
        migration_set="bots",
        filename="001_first.sql",
        state="PENDING",
        postcondition_ok=None,
        diagnostic=None,
    )
    report = MigrationReport(items=[item], applied=[], failed=[], skipped=[], diagnostics=[], exit_code=1)
    with pytest.raises(ValidationError):
        _migration_set().name = "other"
    with pytest.raises(ValidationError):
        item.state = "APPLIED"
    with pytest.raises(ValidationError):
        report.exit_code = 0


def test_render_replaces_only_identifier_tokens_and_preserves_json_braces() -> None:
    """Quote configured identifiers without treating JSON braces as formatting syntax."""
    rendered = render_sql(
        "INSERT INTO {schema}.{bots_table} (config) VALUES ('{\"key\": {\"nested\": true}}');",
        schema="navigator",
        bots_table="ai_bots",
    )

    assert rendered == "INSERT INTO \"navigator\".\"ai_bots\" (config) VALUES ('{\"key\": {\"nested\": true}}');"
    for identifier in ("Navigator", "ai-bots", "a" * 64):
        with pytest.raises(MigrationConfigurationError, match="Invalid"):
            render_sql("SELECT * FROM {schema}.{bots_table}", schema=identifier, bots_table="ai_bots")


def test_scaffold_uses_next_sequence_and_never_overwrites(tmp_path: Path) -> None:
    """Allocate max plus one with exclusive files in the selected source directory."""
    directory = _resource_directory(tmp_path)
    _write_pair(directory, 1, "first")
    _write_pair(directory, 3, "third")

    body_path, check_path = scaffold("bots", "add_column", directory=directory)
    assert body_path.name == "004_add_column.sql"
    assert check_path.name == "004_add_column.check.sql"
    assert body_path.read_text(encoding="utf-8") == "-- bots migration: add_column\n"
    assert check_path.read_text(encoding="utf-8").endswith("SELECT FALSE;\n")

    with pytest.raises(MigrationConfigurationError, match="lowercase identifiers"):
        scaffold("bots", "../escape", directory=directory)
    with pytest.raises(MigrationConfigurationError, match="match the migration set"):
        scaffold("other", "add_column", directory=directory)


def test_scaffold_retains_body_when_check_creation_fails(tmp_path: Path) -> None:
    """Leave a visible partial pair if the second exclusive creation cannot proceed."""
    directory = _resource_directory(tmp_path)
    (directory / "001_partial.check.sql").write_text("existing", encoding="utf-8")

    with pytest.raises(MigrationConfigurationError, match="Partial migration scaffold") as error:
        scaffold("bots", "partial", directory=directory)

    assert (directory / "001_partial.sql").exists()
    assert "001_partial.sql" in str(error.value)
    assert "001_partial.check.sql" in str(error.value)
