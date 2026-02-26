"""
CSV Export Tool - Export DataFrames and structured data to CSV format.

This tool provides functionality to export pandas DataFrames, lists of dictionaries,
or JSON data to CSV files with various formatting options.
"""
import io
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

import pandas as pd
from pydantic import ConfigDict, Field, field_validator

from .document import AbstractDocumentTool, DocumentGenerationArgs


class CSVExportArgs(DocumentGenerationArgs):
    """Arguments schema for CSV export."""

    content: Union[pd.DataFrame, List[Dict[str, Any]], str] = Field(
        ...,
        description="Data to export: pandas DataFrame, list of dictionaries, or JSON string"
    )
    delimiter: str = Field(
        ",",
        description="Field delimiter character (default: comma)"
    )
    encoding: str = Field(
        "utf-8",
        description="File encoding (utf-8, latin-1, etc.)"
    )
    include_header: bool = Field(
        True,
        description="Whether to include column headers in the output"
    )
    include_index: bool = Field(
        False,
        description="Whether to include the DataFrame index as a column"
    )
    quoting: Literal["minimal", "all", "none", "nonnumeric"] = Field(
        "minimal",
        description="Quoting behavior: minimal, all, none, or nonnumeric"
    )
    quote_char: str = Field(
        '"',
        description="Character used to quote fields"
    )
    escape_char: Optional[str] = Field(
        None,
        description="Character used to escape the quote character"
    )
    date_format: Optional[str] = Field(
        None,
        description="Format string for datetime objects (e.g., '%Y-%m-%d')"
    )
    float_format: Optional[str] = Field(
        None,
        description="Format string for floating point numbers (e.g., '%.2f')"
    )
    na_rep: str = Field(
        "",
        description="String representation of missing/NA values"
    )
    columns: Optional[List[str]] = Field(
        None,
        description="Subset of columns to export (None exports all)"
    )
    line_terminator: Optional[str] = Field(
        None,
        description="Line terminator character(s). Defaults to OS-specific (\\n or \\r\\n)"
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator('content')
    @classmethod
    def validate_content(cls, v):
        """Validate that content is not empty."""
        if isinstance(v, pd.DataFrame):
            if v.empty:
                raise ValueError("DataFrame content cannot be empty")
        elif isinstance(v, list):
            if not v:
                raise ValueError("Content list cannot be empty")
            if not all(isinstance(item, dict) for item in v):
                raise ValueError("Content list must contain only dictionaries")
        elif isinstance(v, str):
            if not v.strip():
                raise ValueError("Content string cannot be empty")
        elif v is None:
            raise ValueError("Content cannot be None")
        return v

    @field_validator('delimiter')
    @classmethod
    def validate_delimiter(cls, v):
        """Validate delimiter is a single character."""
        if len(v) != 1:
            raise ValueError("Delimiter must be a single character")
        return v

    @field_validator('quote_char')
    @classmethod
    def validate_quote_char(cls, v):
        """Validate quote_char is a single character."""
        if len(v) != 1:
            raise ValueError("Quote character must be a single character")
        return v


class CSVExportTool(AbstractDocumentTool):
    """
    CSV Export Tool for exporting structured data to CSV files.

    This tool exports pandas DataFrames, lists of dictionaries, or JSON data
    to CSV files with configurable formatting options.

    Features:
    - Export DataFrames to CSV with custom delimiters
    - Support for various encodings (UTF-8, Latin-1, etc.)
    - Configurable quoting behavior
    - Date and float formatting options
    - Column selection and filtering
    - Missing value representation
    - BOM support for Excel compatibility

    Example:
        tool = CSVExportTool()
        result = await tool.export_data(
            data=[{"name": "John", "age": 30}, {"name": "Jane", "age": 25}],
            delimiter=";",
            encoding="utf-8-sig"  # With BOM for Excel
        )
    """

    name = "csv_export"
    description = (
        "Export pandas DataFrames or structured data (list of dictionaries, JSON) "
        "to CSV files with configurable formatting. Supports custom delimiters, "
        "encodings, quoting, and date/number formatting."
    )
    args_schema = CSVExportArgs

    # Document type configuration
    document_type = "csv"
    default_extension = "csv"
    supported_extensions = [".csv", ".tsv", ".txt"]

    # Quoting mode mapping
    QUOTING_MODES = {
        "minimal": 0,    # csv.QUOTE_MINIMAL
        "all": 1,        # csv.QUOTE_ALL
        "nonnumeric": 2, # csv.QUOTE_NONNUMERIC
        "none": 3,       # csv.QUOTE_NONE
    }

    def __init__(
        self,
        default_encoding: str = "utf-8",
        default_delimiter: str = ",",
        add_bom: bool = False,
        **kwargs
    ):
        """
        Initialize the CSV Export Tool.

        Args:
            default_encoding: Default file encoding
            default_delimiter: Default field delimiter
            add_bom: Whether to add BOM for Excel compatibility by default
            **kwargs: Additional arguments for AbstractDocumentTool
        """
        super().__init__(**kwargs)
        self.default_encoding = default_encoding
        self.default_delimiter = default_delimiter
        self.add_bom = add_bom

    def _parse_content_to_dataframe(
        self,
        content: Union[str, List[Dict], pd.DataFrame]
    ) -> pd.DataFrame:
        """
        Parse content into a pandas DataFrame.

        Args:
            content: Can be a DataFrame, list of dictionaries, or JSON string

        Returns:
            pandas DataFrame
        """
        if isinstance(content, pd.DataFrame):
            return content
        elif isinstance(content, dict):
            # Single dictionary - convert to single-row DataFrame
            return pd.DataFrame([content])
        elif isinstance(content, list):
            if not content:
                raise ValueError("Content list cannot be empty")
            if not all(isinstance(item, dict) for item in content):
                raise ValueError("Content list must contain only dictionaries")
            return pd.DataFrame(content)
        elif isinstance(content, str):
            try:
                # Try to parse as JSON
                data = self._json_decoder(content)
                if isinstance(data, list):
                    return pd.DataFrame(data)
                elif isinstance(data, dict):
                    return pd.DataFrame([data])
                else:
                    raise ValueError(
                        "JSON content must be a list of objects or a single object"
                    )
            except (TypeError, ValueError) as e:
                raise ValueError(f"Invalid JSON content: {e}")
        else:
            raise ValueError(
                "Content must be a pandas DataFrame, list of dictionaries, "
                "or JSON string"
            )

    def _get_extension_for_delimiter(self, delimiter: str) -> str:
        """
        Get appropriate file extension based on delimiter.

        Args:
            delimiter: The field delimiter character

        Returns:
            File extension (without dot)
        """
        if delimiter == "\t":
            return "tsv"
        return "csv"

    async def _generate_document_content(
        self,
        content: Union[str, List[Dict], pd.DataFrame],
        **kwargs
    ) -> str:
        """
        Generate CSV content from structured data.

        Args:
            content: Structured data - DataFrame, list of dicts, or JSON string
            **kwargs: CSV formatting options

        Returns:
            CSV content as string
        """
        try:
            # Extract arguments with defaults
            delimiter = kwargs.get('delimiter', self.default_delimiter)
            encoding = kwargs.get('encoding', self.default_encoding)
            include_header = kwargs.get('include_header', True)
            include_index = kwargs.get('include_index', False)
            quoting = kwargs.get('quoting', 'minimal')
            quote_char = kwargs.get('quote_char', '"')
            escape_char = kwargs.get('escape_char')
            date_format = kwargs.get('date_format')
            float_format = kwargs.get('float_format')
            na_rep = kwargs.get('na_rep', '')
            columns = kwargs.get('columns')
            line_terminator = kwargs.get('line_terminator')

            # Parse content to DataFrame
            dataframe = self._parse_content_to_dataframe(content)

            # Filter columns if specified
            if columns:
                missing_cols = set(columns) - set(dataframe.columns)
                if missing_cols:
                    self.logger.warning(
                        f"Columns not found in data: {missing_cols}"
                    )
                available_cols = [c for c in columns if c in dataframe.columns]
                dataframe = dataframe[available_cols]

            self.logger.info(
                f"Generating CSV with {len(dataframe)} rows and "
                f"{len(dataframe.columns)} columns"
            )

            # Prepare CSV options
            csv_options = {
                'sep': delimiter,
                'header': include_header,
                'index': include_index,
                'quoting': self.QUOTING_MODES.get(quoting, 0),
                'quotechar': quote_char,
                'na_rep': na_rep,
            }

            # Optional parameters
            if escape_char:
                csv_options['escapechar'] = escape_char
            if date_format:
                csv_options['date_format'] = date_format
            if float_format:
                csv_options['float_format'] = float_format
            if line_terminator:
                csv_options['lineterminator'] = line_terminator

            # Generate CSV string
            csv_buffer = io.StringIO()
            dataframe.to_csv(csv_buffer, **csv_options)
            csv_content = csv_buffer.getvalue()

            # Add BOM if using utf-8-sig encoding or if add_bom is True
            if encoding == 'utf-8-sig' or (self.add_bom and encoding == 'utf-8'):
                csv_content = '\ufeff' + csv_content

            return csv_content

        except Exception as e:
            self.logger.error(f"Error generating CSV content: {e}")
            raise

    async def _execute(
        self,
        content: Union[str, List[Dict], pd.DataFrame],
        delimiter: str = ",",
        encoding: str = "utf-8",
        include_header: bool = True,
        include_index: bool = False,
        quoting: Literal["minimal", "all", "none", "nonnumeric"] = "minimal",
        quote_char: str = '"',
        escape_char: Optional[str] = None,
        date_format: Optional[str] = None,
        float_format: Optional[str] = None,
        na_rep: str = "",
        columns: Optional[List[str]] = None,
        line_terminator: Optional[str] = None,
        output_filename: Optional[str] = None,
        file_prefix: str = "export",
        output_dir: Optional[str] = None,
        overwrite_existing: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute CSV export (AbstractTool interface).

        Args:
            content: Data to export - DataFrame, list of dicts, or JSON string
            delimiter: Field delimiter character
            encoding: File encoding
            include_header: Whether to include column headers
            include_index: Whether to include DataFrame index
            quoting: Quoting behavior
            quote_char: Quote character
            escape_char: Escape character for quotes
            date_format: Format string for dates
            float_format: Format string for floats
            na_rep: Representation for missing values
            columns: Subset of columns to export
            line_terminator: Line terminator character(s)
            output_filename: Custom filename (without extension)
            file_prefix: Prefix for auto-generated filenames
            output_dir: Custom output directory
            overwrite_existing: Whether to overwrite existing files
            **kwargs: Additional arguments

        Returns:
            Dictionary with export results
        """
        try:
            # Parse content to DataFrame for metadata
            dataframe = self._parse_content_to_dataframe(content)

            # Determine extension based on delimiter
            extension = self._get_extension_for_delimiter(delimiter)

            self.logger.info(
                f"Starting CSV export with {len(dataframe)} rows and "
                f"{len(dataframe.columns)} columns"
            )

            # Use the safe document creation workflow
            result = await self._create_document_safely(
                content=content,
                output_filename=output_filename,
                file_prefix=file_prefix,
                output_dir=output_dir,
                overwrite_existing=overwrite_existing or self.overwrite_existing,
                extension=extension,
                delimiter=delimiter,
                encoding=encoding,
                include_header=include_header,
                include_index=include_index,
                quoting=quoting,
                quote_char=quote_char,
                escape_char=escape_char,
                date_format=date_format,
                float_format=float_format,
                na_rep=na_rep,
                columns=columns,
                line_terminator=line_terminator,
            )

            if result['status'] == 'success':
                # Determine actual columns exported
                if columns:
                    exported_columns = [c for c in columns if c in dataframe.columns]
                else:
                    exported_columns = list(dataframe.columns)

                # Add CSV-specific metadata
                result['metadata'].update({
                    'format': 'csv',
                    'delimiter': delimiter,
                    'encoding': encoding,
                    'rows': len(dataframe),
                    'columns': len(exported_columns),
                    'column_names': exported_columns,
                    'has_header': include_header,
                    'has_index': include_index,
                })

                self.logger.info(
                    f"CSV export completed successfully: "
                    f"{result['metadata']['filename']}"
                )

            return result

        except Exception as e:
            self.logger.error(f"Error in CSV export: {e}")
            raise

    # Convenience methods

    async def export_dataframe(
        self,
        dataframe: pd.DataFrame,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Convenience method to directly export a DataFrame.

        Args:
            dataframe: DataFrame to export
            **kwargs: Additional arguments for _execute

        Returns:
            Dictionary with export results
        """
        return await self._execute(content=dataframe, **kwargs)

    async def export_data(
        self,
        data: Union[List[Dict], pd.DataFrame, str],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Convenience method to export various data formats.

        Args:
            data: Data to export (DataFrame, list of dicts, or JSON string)
            **kwargs: Additional arguments for _execute

        Returns:
            Dictionary with export results
        """
        return await self._execute(content=data, **kwargs)

    async def export_to_tsv(
        self,
        data: Union[List[Dict], pd.DataFrame, str],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Export data to TSV (Tab-Separated Values) format.

        Args:
            data: Data to export
            **kwargs: Additional arguments for _execute

        Returns:
            Dictionary with export results
        """
        kwargs['delimiter'] = '\t'
        return await self._execute(content=data, **kwargs)

    async def export_for_excel(
        self,
        data: Union[List[Dict], pd.DataFrame, str],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Export data to CSV with Excel-compatible settings.

        Uses UTF-8 with BOM and semicolon delimiter for European Excel.

        Args:
            data: Data to export
            **kwargs: Additional arguments for _execute

        Returns:
            Dictionary with export results
        """
        kwargs.setdefault('encoding', 'utf-8-sig')
        kwargs.setdefault('delimiter', ';')
        return await self._execute(content=data, **kwargs)

    async def quick_export(
        self,
        data: Union[pd.DataFrame, List[Dict], str],
        filename: Optional[str] = None,
    ) -> str:
        """
        Quick export method that returns just the file path.

        Args:
            data: Data to export
            filename: Optional filename

        Returns:
            Path to the created file
        """
        result = await self.export_data(data=data, output_filename=filename)

        if result['status'] == 'success':
            return result['metadata']['file_path']
        else:
            raise Exception(f"Export failed: {result.get('error', 'Unknown error')}")

    def get_format_info(self) -> Dict[str, Any]:
        """Get information about supported CSV options."""
        return {
            "supported_formats": ["csv", "tsv"],
            "extensions": self.supported_extensions,
            "default_encoding": self.default_encoding,
            "default_delimiter": self.default_delimiter,
            "quoting_modes": list(self.QUOTING_MODES.keys()),
            "features": {
                "custom_delimiter": True,
                "multiple_encodings": True,
                "column_selection": True,
                "date_formatting": True,
                "float_formatting": True,
                "excel_compatibility": True,
            }
        }


class DataFrameToCSVTool(CSVExportTool):
    """
    Simplified CSV tool focused on DataFrame export.

    This is a convenience wrapper around CSVExportTool for users who
    primarily need to export DataFrames without complex configuration.
    """

    name = "dataframe_to_csv"
    description = (
        "Simple tool to export pandas DataFrames to CSV files. "
        "Focused on quick DataFrame export with minimal configuration."
    )

    async def simple_export(
        self,
        data: Union[pd.DataFrame, List[Dict], str],
        filename: Optional[str] = None,
        delimiter: str = ","
    ) -> str:
        """
        Simple export method with minimal options.

        Args:
            data: Data to export
            filename: Optional filename
            delimiter: Field delimiter (default: comma)

        Returns:
            Path to the created file
        """
        result = await self.export_data(
            data=data,
            output_filename=filename,
            delimiter=delimiter
        )

        if result['status'] == 'success':
            return result['metadata']['file_path']
        else:
            raise Exception(f"Export failed: {result.get('error', 'Unknown error')}")
