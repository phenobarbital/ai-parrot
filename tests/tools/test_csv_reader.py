"""Unit tests for CSV-to-markdown converter."""
import pytest
from parrot.tools.dataset_manager.csv_reader import (
    csv_to_markdown, csv_to_structural_summary
)


@pytest.fixture
def simple_csv(tmp_path):
    path = tmp_path / "simple.csv"
    path.write_text("Name,Age,City\nAlice,30,NYC\nBob,25,LA\n", encoding="utf-8")
    return path


@pytest.fixture
def large_csv(tmp_path):
    path = tmp_path / "large.csv"
    lines = ["Id,Value\n"] + [f"{i},{i*10}\n" for i in range(500)]
    path.write_text("".join(lines), encoding="utf-8")
    return path


@pytest.fixture
def latin1_csv(tmp_path):
    path = tmp_path / "latin1.csv"
    path.write_bytes("Nombre,Ciudad\nJosé,São Paulo\nMaría,Córdoba\n".encode("latin-1"))
    return path


@pytest.fixture
def tsv_file(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("Name\tAge\nAlice\t30\nBob\t25\n", encoding="utf-8")
    return path


class TestCsvToMarkdown:
    def test_simple_csv(self, simple_csv):
        result = csv_to_markdown(simple_csv)
        assert "Name" in result
        assert "Alice" in result
        assert "Bob" in result

    def test_truncation(self, large_csv):
        result = csv_to_markdown(large_csv, max_rows=10)
        assert "Showing first 10 of 500" in result

    def test_no_truncation_when_small(self, simple_csv):
        result = csv_to_markdown(simple_csv, max_rows=200)
        assert "Showing first" not in result

    def test_latin1_encoding(self, latin1_csv):
        result = csv_to_markdown(latin1_csv)
        assert "José" in result or "Nombre" in result

    def test_custom_separator(self, tsv_file):
        result = csv_to_markdown(tsv_file, separator="\t")
        assert "Name" in result
        assert "Alice" in result

    def test_file_header(self, simple_csv):
        result = csv_to_markdown(simple_csv)
        assert "simple.csv" in result
        assert "2 rows" in result


class TestCsvStructuralSummary:
    def test_summary(self, simple_csv):
        result = csv_to_structural_summary(simple_csv)
        assert "simple.csv" in result
        assert "Name" in result
        assert "Columns: 3" in result
