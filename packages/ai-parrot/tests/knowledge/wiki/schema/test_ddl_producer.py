"""Tests for the FEAT-600 offline DDL producer."""

import shutil
import subprocess
from pathlib import Path

import pytest

from parrot.bots.database.models import Completeness
from parrot.knowledge.wiki.schema.producers.ddl import fold_ddl, split_statements

REPO_ROOT = Path(__file__).resolve().parents[6]
DDL_CORPUS = Path("packages/ai-parrot/src/parrot/tools/working_memory/task_memory/migrations/001_task_memory.sql")


def test_split_statements_preserves_dollar_quoted_bodies() -> None:
    """Semicolons in strings, comments, and dollar bodies are not boundaries."""
    statements = split_statements(
        "CREATE TABLE t (value TEXT DEFAULT ';'); DO $$ BEGIN PERFORM 1; END $$; CREATE TABLE u (id INT);"
    )
    assert len(statements) == 3
    assert "DEFAULT ';'" in statements[0]
    assert "PERFORM 1;" in statements[1]


def test_fold_ddl_handles_inline_constraints_and_alter(tmp_path: Path) -> None:
    """Inline keys and supported ALTER actions are folded in lexical order."""
    migration = tmp_path / "001.sql"
    migration.write_text(
        "CREATE TABLE parent (id INT PRIMARY KEY);"
        "CREATE TABLE child (id INT, parent_id INT REFERENCES parent(id));"
        "ALTER TABLE child ADD COLUMN label TEXT NOT NULL;"
        "ALTER TABLE child ADD CONSTRAINT child_parent FOREIGN KEY (id) REFERENCES parent(id);"
        "ALTER TABLE child DROP COLUMN label;",
        encoding="utf-8",
    )

    records, errors = fold_ddl([migration], origin="test", dialect="postgres", root=tmp_path)

    assert errors == {}
    child = next(record for record in records if record.metadata.tablename == "child")
    assert child.metadata.primary_keys == []
    assert [column["name"] for column in child.metadata.columns] == ["id", "parent_id"]
    assert len(child.metadata.foreign_keys) == 2
    assert child.metadata.source == "ddl"
    assert child.metadata.completeness == Completeness.FULL
    assert child.defined_in == ["file:001.sql"]


def test_fold_ddl_isolates_bad_statements(tmp_path: Path) -> None:
    """A parse failure does not prevent later statements from being folded."""
    migration = tmp_path / "broken.sql"
    migration.write_text("CREATE TABLE first (id INT); nonsense !!!; CREATE TABLE second (id INT);", encoding="utf-8")

    records, errors = fold_ddl([migration], origin="test", dialect="postgres", root=tmp_path)

    assert {record.metadata.tablename for record in records} == {"first", "second"}
    assert list(errors) == ["broken.sql#1"]


def test_fold_ddl_task_memory_corpus() -> None:
    """The repository corpus folds to the expected table, column, and FK counts."""
    records, errors = fold_ddl([DDL_CORPUS], origin="task-memory", dialect="postgres", root=Path.cwd())

    assert errors == {}
    assert len(records) == 6
    assert sum(len(record.metadata.columns) for record in records) == 70
    # 3 SQL-level FOREIGN KEY constraints in the corpus, but foreign_keys is a
    # per-column model (matching the live-introspection convention in
    # producers/live.py): the composite (artifact_id, version) constraint on
    # artifact_evidence decomposes into 2 entries, so 1 + 1 + 2 = 4.
    assert sum(len(record.metadata.foreign_keys) for record in records) == 4
    assert all(record.metadata.source == "ddl" for record in records)
    assert all(
        record.defined_in
        == ["file:packages/ai-parrot/src/parrot/tools/working_memory/task_memory/migrations/001_task_memory.sql"]
        for record in records
    )


def test_fold_ddl_dedupes_repeated_foreign_keys(tmp_path: Path) -> None:
    """One relationship stated inline, table-level and via ALTER folds to a single FK entry."""
    migration = tmp_path / "001.sql"
    migration.write_text(
        "CREATE TABLE p (id INT PRIMARY KEY);"
        "CREATE TABLE c (pid INT REFERENCES p(id), FOREIGN KEY (pid) REFERENCES p(id));"
        "ALTER TABLE c ADD CONSTRAINT c_fk FOREIGN KEY (pid) REFERENCES p(id);",
        encoding="utf-8",
    )

    records, errors = fold_ddl([migration], origin="test", dialect="postgres", root=tmp_path)

    assert errors == {}
    child = next(record for record in records if record.metadata.tablename == "c")
    assert child.metadata.foreign_keys == [
        {"column": "pid", "ref_schema": "public", "ref_table": "p", "ref_column": "id"}
    ]


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git to enumerate the tracked corpus")
def test_fold_ddl_repo_corpus_baseline() -> None:
    """FEAT-600 AC4: every git-tracked .sql file folds to >= 20 tables and >= 329 columns."""
    listed = subprocess.run(["git", "ls-files", "*.sql"], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    if listed.returncode != 0:
        pytest.skip("not running inside a git checkout")
    files = [REPO_ROOT / name for name in listed.stdout.split()]
    assert len(files) >= 32

    records, _errors = fold_ddl(files, origin="repo", dialect="postgres", root=REPO_ROOT)

    assert len(records) >= 20
    assert sum(len(record.metadata.columns) for record in records) >= 329
