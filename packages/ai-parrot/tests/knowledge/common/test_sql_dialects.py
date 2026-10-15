"""Dialect map relocation (FEAT-540 M4)."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from parrot.bots.database.models import Completeness, TableMetadata
from parrot.knowledge.common.sql_dialects import _SQLGLOT_DIALECT_MAP
from parrot.knowledge.wiki.schema.models import TableRecord
from parrot.knowledge.wiki.schema.producers.ddl import fold_ddl
from parrot.knowledge.wiki.schema.render import content_hash, render_ddl


def _stable(metadata: TableMetadata) -> dict:
    """Return the metadata fields minus the wall-clock ``loaded_at`` stamp."""
    return {key: value for key, value in asdict(metadata).items() if key != "loaded_at"}


def _record(dialect: str) -> TableRecord:
    """Build a deterministic table record for the requested dialect."""
    metadata = TableMetadata(
        schema="public",
        tablename="example",
        table_type="BASE TABLE",
        full_name="public.example",
        columns=[{"name": "id", "type": "INT", "nullable": False}],
        primary_keys=["id"],
        completeness=Completeness.FULL,
        source="ddl",
    )
    return TableRecord(
        origin="test",
        dialect=dialect,
        metadata=metadata,
        content_hash=content_hash(metadata),
        introspected_at="2026-10-15T00:00:00+00:00",
    )


def test_same_object() -> None:
    """The compatibility path exposes the neutral module's exact map object."""
    from parrot.knowledge.common.sql_dialects import _SQLGLOT_DIALECT_MAP as new
    from parrot.tools.sql_dialects import _SQLGLOT_DIALECT_MAP as old

    assert old is new


def test_wiki_consumers_do_not_load_tools_dialect_module() -> None:
    """The wiki consumers reach the dialect map without going through ``parrot.tools.sql_dialects``.

    Only the dialect module is asserted: importing ``parrot.bots.database.models`` (still used by the renderer for
    ``TableMetadata``) boots ``parrot.tools`` transitively, which is outside this task's scope.
    """
    source_root = Path(__file__).resolve().parents[3] / "src"
    environment = os.environ | {"PYTHONPATH": os.pathsep.join((str(source_root), os.environ.get("PYTHONPATH", "")))}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import parrot.knowledge.wiki.schema.render, parrot.knowledge.wiki.schema.producers.ddl; "
            "assert 'parrot.tools.sql_dialects' not in sys.modules",
        ],
        capture_output=True,
        env=environment,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_render_and_ddl_output_match_mapped_dialect_for_every_alias(tmp_path: Path) -> None:
    """Every alias preserves renderer and DDL-producer behavior of its sqlglot dialect."""
    migration = tmp_path / "example.sql"
    migration.write_text("CREATE TABLE example (id INT PRIMARY KEY);", encoding="utf-8")

    for alias, dialect in _SQLGLOT_DIALECT_MAP.items():
        # render_ddl looks the record's dialect up in the alias map, so a mapped target that is not itself a key
        # (e.g. ``tsql``) renders generically while its aliases (``mssql``) render with that sqlglot dialect.
        # That is pre-existing behaviour; only keys that map to themselves are interchangeable with their target.
        if dialect in _SQLGLOT_DIALECT_MAP:
            assert render_ddl(_record(alias)) == render_ddl(_record(dialect))
        else:
            # Aliases sharing a target must render identically to one another.
            siblings = [other for other, target in _SQLGLOT_DIALECT_MAP.items() if target == dialect]
            assert {render_ddl(_record(other)) for other in siblings} == {render_ddl(_record(alias))}
        alias_records, alias_errors = fold_ddl([migration], origin="test", dialect=alias, root=tmp_path)
        dialect_records, dialect_errors = fold_ddl([migration], origin="test", dialect=dialect, root=tmp_path)
        assert alias_errors == dialect_errors
        # loaded_at is stamped with the wall clock at fold time, so two separate folds never match exactly.
        assert [_stable(record.metadata) for record in alias_records] == [
            _stable(record.metadata) for record in dialect_records
        ]
