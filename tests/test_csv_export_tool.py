"""
Tests for CSVExportTool.
"""
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import pytest

from parrot.tools.csv_export import CSVExportTool, DataFrameToCSVTool, CSVExportArgs


@pytest.fixture
def sample_data() -> List[Dict[str, Any]]:
    """Sample data for testing."""
    return [
        {"name": "Alice", "age": 30, "city": "New York"},
        {"name": "Bob", "age": 25, "city": "Los Angeles"},
        {"name": "Charlie", "age": 35, "city": "Chicago"},
    ]


@pytest.fixture
def sample_dataframe(sample_data) -> pd.DataFrame:
    """Sample DataFrame for testing."""
    return pd.DataFrame(sample_data)


@pytest.fixture
def csv_tool(tmp_path) -> CSVExportTool:
    """Create a CSVExportTool with temp output directory."""
    return CSVExportTool(output_dir=tmp_path)


class TestCSVExportArgs:
    """Tests for CSVExportArgs validation."""

    def test_valid_args_with_list(self, sample_data):
        """Test valid arguments with list of dicts."""
        args = CSVExportArgs(content=sample_data)
        assert args.content == sample_data
        assert args.delimiter == ","
        assert args.encoding == "utf-8"

    def test_valid_args_with_dataframe(self, sample_dataframe):
        """Test valid arguments with DataFrame."""
        args = CSVExportArgs(content=sample_dataframe)
        assert args.include_header is True
        assert args.include_index is False

    def test_empty_list_raises_error(self):
        """Test that empty list raises ValueError."""
        with pytest.raises(ValueError, match="Content list cannot be empty"):
            CSVExportArgs(content=[])

    def test_empty_dataframe_raises_error(self):
        """Test that empty DataFrame raises ValueError."""
        with pytest.raises(ValueError, match="DataFrame content cannot be empty"):
            CSVExportArgs(content=pd.DataFrame())

    def test_invalid_delimiter(self, sample_data):
        """Test that multi-character delimiter raises ValueError."""
        with pytest.raises(ValueError, match="Delimiter must be a single character"):
            CSVExportArgs(content=sample_data, delimiter=",,")

    def test_invalid_quote_char(self, sample_data):
        """Test that multi-character quote_char raises ValueError."""
        with pytest.raises(ValueError, match="Quote character must be a single character"):
            CSVExportArgs(content=sample_data, quote_char="''")


class TestCSVExportTool:
    """Tests for CSVExportTool."""

    def test_tool_attributes(self):
        """Test tool has correct attributes."""
        tool = CSVExportTool()
        assert tool.name == "csv_export"
        assert tool.document_type == "csv"
        assert tool.default_extension == "csv"
        assert ".csv" in tool.supported_extensions

    def test_get_format_info(self):
        """Test get_format_info returns expected structure."""
        tool = CSVExportTool()
        info = tool.get_format_info()

        assert "supported_formats" in info
        assert "csv" in info["supported_formats"]
        assert "tsv" in info["supported_formats"]
        assert "quoting_modes" in info
        assert "features" in info

    @pytest.mark.asyncio
    async def test_export_list_of_dicts(self, csv_tool, sample_data, tmp_path):
        """Test exporting list of dictionaries."""
        result = await csv_tool.export_data(
            data=sample_data,
            output_filename="test_list",
            output_dir=str(tmp_path),
            overwrite_existing=True
        )

        assert result["status"] == "success"
        assert result["metadata"]["rows"] == 3
        assert result["metadata"]["columns"] == 3

        # Verify file content
        file_path = Path(result["metadata"]["file_path"])
        assert file_path.exists()

        content = file_path.read_text()
        assert "name,age,city" in content
        assert "Alice,30,New York" in content

    @pytest.mark.asyncio
    async def test_export_dataframe(self, csv_tool, sample_dataframe, tmp_path):
        """Test exporting pandas DataFrame."""
        result = await csv_tool.export_dataframe(
            dataframe=sample_dataframe,
            output_filename="test_df",
            output_dir=str(tmp_path),
            overwrite_existing=True
        )

        assert result["status"] == "success"
        assert result["metadata"]["format"] == "csv"
        assert "column_names" in result["metadata"]

    @pytest.mark.asyncio
    async def test_export_with_semicolon_delimiter(self, csv_tool, sample_data, tmp_path):
        """Test exporting with semicolon delimiter."""
        result = await csv_tool.export_data(
            data=sample_data,
            delimiter=";",
            output_filename="test_semicolon",
            output_dir=str(tmp_path),
            overwrite_existing=True
        )

        assert result["status"] == "success"

        file_path = Path(result["metadata"]["file_path"])
        content = file_path.read_text()
        assert "name;age;city" in content
        assert "Alice;30;New York" in content

    @pytest.mark.asyncio
    async def test_export_to_tsv(self, csv_tool, sample_data, tmp_path):
        """Test exporting to TSV format."""
        result = await csv_tool.export_to_tsv(
            data=sample_data,
            output_filename="test_tsv",
            output_dir=str(tmp_path),
            overwrite_existing=True
        )

        assert result["status"] == "success"
        assert result["metadata"]["file_extension"] == "tsv"
        assert result["metadata"]["delimiter"] == "\t"

    @pytest.mark.asyncio
    async def test_export_without_header(self, csv_tool, sample_data, tmp_path):
        """Test exporting without header row."""
        result = await csv_tool.export_data(
            data=sample_data,
            include_header=False,
            output_filename="test_no_header",
            output_dir=str(tmp_path),
            overwrite_existing=True
        )

        assert result["status"] == "success"

        file_path = Path(result["metadata"]["file_path"])
        content = file_path.read_text()
        # Should not contain header
        assert "name,age,city" not in content
        # Should contain data
        assert "Alice,30,New York" in content

    @pytest.mark.asyncio
    async def test_export_with_index(self, csv_tool, sample_dataframe, tmp_path):
        """Test exporting with index column."""
        result = await csv_tool.export_dataframe(
            dataframe=sample_dataframe,
            include_index=True,
            output_filename="test_with_index",
            output_dir=str(tmp_path),
            overwrite_existing=True
        )

        assert result["status"] == "success"

        file_path = Path(result["metadata"]["file_path"])
        content = file_path.read_text()
        lines = content.strip().split("\n")
        # First line should have extra column for index
        assert lines[0].count(",") >= 3

    @pytest.mark.asyncio
    async def test_export_with_column_selection(self, csv_tool, sample_data, tmp_path):
        """Test exporting with column selection."""
        result = await csv_tool.export_data(
            data=sample_data,
            columns=["name", "city"],
            output_filename="test_columns",
            output_dir=str(tmp_path),
            overwrite_existing=True
        )

        assert result["status"] == "success"
        assert result["metadata"]["columns"] == 2

        file_path = Path(result["metadata"]["file_path"])
        content = file_path.read_text()
        assert "name,city" in content
        assert "age" not in content

    @pytest.mark.asyncio
    async def test_export_with_na_rep(self, csv_tool, tmp_path):
        """Test exporting with custom NA representation."""
        data_with_na = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": None},
        ]

        result = await csv_tool.export_data(
            data=data_with_na,
            na_rep="N/A",
            output_filename="test_na",
            output_dir=str(tmp_path),
            overwrite_existing=True
        )

        assert result["status"] == "success"

        file_path = Path(result["metadata"]["file_path"])
        content = file_path.read_text()
        assert "N/A" in content

    @pytest.mark.asyncio
    async def test_export_for_excel(self, csv_tool, sample_data, tmp_path):
        """Test Excel-compatible export."""
        result = await csv_tool.export_for_excel(
            data=sample_data,
            output_filename="test_excel",
            output_dir=str(tmp_path),
            overwrite_existing=True
        )

        assert result["status"] == "success"
        assert result["metadata"]["delimiter"] == ";"
        assert result["metadata"]["encoding"] == "utf-8-sig"

    @pytest.mark.asyncio
    async def test_quick_export(self, csv_tool, sample_data, tmp_path):
        """Test quick_export method."""
        csv_tool.output_dir = tmp_path
        file_path = await csv_tool.quick_export(
            data=sample_data,
            filename="quick_test"
        )

        assert Path(file_path).exists()
        assert file_path.endswith(".csv")

    @pytest.mark.asyncio
    async def test_parse_json_content(self, csv_tool, tmp_path):
        """Test parsing JSON string content."""
        import json
        data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        json_str = json.dumps(data)

        result = await csv_tool.export_data(
            data=json_str,
            output_filename="test_json",
            output_dir=str(tmp_path),
            overwrite_existing=True
        )

        assert result["status"] == "success"
        assert result["metadata"]["rows"] == 2

    @pytest.mark.asyncio
    async def test_auto_filename_generation(self, csv_tool, sample_data, tmp_path):
        """Test automatic filename generation with timestamp."""
        result = await csv_tool.export_data(
            data=sample_data,
            file_prefix="auto",
            output_dir=str(tmp_path),
            overwrite_existing=True
        )

        assert result["status"] == "success"
        filename = result["metadata"]["filename"]
        assert filename.startswith("auto_")
        assert filename.endswith(".csv")

    @pytest.mark.asyncio
    async def test_overwrite_protection(self, csv_tool, sample_data, tmp_path):
        """Test overwrite protection when file exists."""
        # First export
        await csv_tool.export_data(
            data=sample_data,
            output_filename="protected",
            output_dir=str(tmp_path),
            overwrite_existing=True
        )

        # Second export without overwrite should fail
        result = await csv_tool.export_data(
            data=sample_data,
            output_filename="protected",
            output_dir=str(tmp_path),
            overwrite_existing=False
        )

        assert result["status"] == "error"
        assert "already exists" in result["error"]


class TestDataFrameToCSVTool:
    """Tests for DataFrameToCSVTool."""

    def test_tool_attributes(self):
        """Test tool has correct attributes."""
        tool = DataFrameToCSVTool()
        assert tool.name == "dataframe_to_csv"
        assert "simplified" in tool.description.lower()

    @pytest.mark.asyncio
    async def test_simple_export(self, sample_data, tmp_path):
        """Test simple_export method."""
        tool = DataFrameToCSVTool(output_dir=tmp_path)

        file_path = await tool.simple_export(
            data=sample_data,
            filename="simple_test"
        )

        assert Path(file_path).exists()
        content = Path(file_path).read_text()
        assert "Alice" in content

    @pytest.mark.asyncio
    async def test_simple_export_with_delimiter(self, sample_data, tmp_path):
        """Test simple_export with custom delimiter."""
        tool = DataFrameToCSVTool(output_dir=tmp_path)

        file_path = await tool.simple_export(
            data=sample_data,
            filename="simple_semicolon",
            delimiter=";"
        )

        content = Path(file_path).read_text()
        assert ";" in content
