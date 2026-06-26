"""Unit tests for WikiBookkeeper (TASK-1630)."""

from pathlib import Path

import pytest

from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper


class TestWikiBookkeeper:
    """Tests for WikiBookkeeper."""

    def test_log_operation_creates_file(self, tmp_path: Path):
        """log_operation creates log.md when it does not exist."""
        bk = WikiBookkeeper()
        bk.log_operation(tmp_path, "INGEST", "source: article.md, pages: 3")
        log_path = tmp_path / "log.md"
        assert log_path.exists()

    def test_log_operation_format(self, tmp_path: Path):
        """Log entries have the expected [TS] [OP] details format."""
        bk = WikiBookkeeper()
        bk.log_operation(tmp_path, "INGEST", "source: article.md, pages: 3")
        content = (tmp_path / "log.md").read_text()
        assert "[INGEST]" in content
        assert "article.md" in content
        # Timestamp bracket present
        assert content.startswith("[")

    def test_log_operation_case_insensitive_op(self, tmp_path: Path):
        """Operation tag is normalised to uppercase."""
        bk = WikiBookkeeper()
        bk.log_operation(tmp_path, "ingest", "test")
        content = (tmp_path / "log.md").read_text()
        assert "[INGEST]" in content

    def test_log_operation_append_only(self, tmp_path: Path):
        """Multiple log_operation calls append rather than overwrite."""
        bk = WikiBookkeeper()
        bk.log_operation(tmp_path, "INGEST", "first")
        bk.log_operation(tmp_path, "QUERY", "second")
        lines = (tmp_path / "log.md").read_text().splitlines()
        assert len(lines) == 2
        assert "[INGEST]" in lines[0]
        assert "[QUERY]" in lines[1]

    def test_log_ten_entries(self, tmp_path: Path):
        """Writing 10 entries results in 10 log lines."""
        bk = WikiBookkeeper()
        for i in range(10):
            bk.log_operation(tmp_path, "OP", f"entry {i}")
        lines = (tmp_path / "log.md").read_text().splitlines()
        assert len(lines) == 10

    def test_read_log_empty_when_no_file(self, tmp_path: Path):
        """read_log returns empty string when log.md does not exist."""
        bk = WikiBookkeeper()
        assert bk.read_log(tmp_path) == ""

    def test_read_log_all_entries(self, tmp_path: Path):
        """read_log with default last_n returns all entries when <= 50."""
        bk = WikiBookkeeper()
        for i in range(5):
            bk.log_operation(tmp_path, "OP", f"entry {i}")
        log = bk.read_log(tmp_path)
        for i in range(5):
            assert f"entry {i}" in log

    def test_read_log_last_n(self, tmp_path: Path):
        """read_log with last_n=3 returns only the last 3 entries."""
        bk = WikiBookkeeper()
        for i in range(10):
            bk.log_operation(tmp_path, "OP", f"entry {i}")
        last3 = bk.read_log(tmp_path, last_n=3)
        assert "entry 9" in last3
        assert "entry 7" in last3
        assert "entry 6" not in last3
        assert "entry 0" not in last3

    def test_read_log_returns_last_lines_by_count(self, tmp_path: Path):
        """read_log last_n=3 returns exactly 3 non-empty lines."""
        bk = WikiBookkeeper()
        for i in range(10):
            bk.log_operation(tmp_path, "OP", f"entry {i}")
        last3 = bk.read_log(tmp_path, last_n=3)
        non_empty = [l for l in last3.splitlines() if l.strip()]
        assert len(non_empty) == 3

    def test_generate_index_produces_header(self, tmp_path: Path):
        """generate_index produces a non-empty markdown string."""
        bk = WikiBookkeeper()
        content = bk.generate_index({}, "test-wiki")
        assert "# Wiki Index" in content
        assert "Last updated" in content

    def test_generate_index_includes_source_count(self, tmp_path: Path):
        """generate_index shows the correct source count."""
        bk = WikiBookkeeper()
        content = bk.generate_index({}, "wiki", sources=["s1", "s2"])
        assert "Sources ingested**: 2" in content

    def test_generate_index_categories_listed(self, tmp_path: Path):
        """generate_index lists provided categories."""
        bk = WikiBookkeeper()
        content = bk.generate_index(
            {}, "wiki", categories=["concept", "summary"]
        )
        assert "concept" in content
        assert "summary" in content

    def test_write_index_creates_file(self, tmp_path: Path):
        """write_index creates index.md in wiki_dir."""
        bk = WikiBookkeeper()
        bk.write_index(tmp_path)
        assert (tmp_path / "index.md").exists()

    def test_rebuild_index_returns_content(self, tmp_path: Path):
        """rebuild_index writes and returns the index.md content."""
        bk = WikiBookkeeper()
        content = bk.rebuild_index(tmp_path, tree_name="test-wiki")
        assert isinstance(content, str)
        assert "Last updated" in content
        assert (tmp_path / "index.md").exists()

    def test_custom_timestamp_in_log(self, tmp_path: Path):
        """log_operation respects an explicit timestamp argument."""
        bk = WikiBookkeeper()
        bk.log_operation(
            tmp_path, "TEST", "custom ts",
            timestamp="2026-01-01T00:00:00Z",
        )
        content = (tmp_path / "log.md").read_text()
        assert "2026-01-01T00:00:00Z" in content
