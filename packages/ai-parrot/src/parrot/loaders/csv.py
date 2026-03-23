from typing import List, Union, Optional, Dict, Any
from collections.abc import Callable
from pathlib import PurePath
import json
import pandas as pd
from ..stores.models import Document
from .abstract import AbstractLoader


class CSVLoader(AbstractLoader):
    """
    CSV Loader that creates one JSON Document per row using pandas.

    This loader reads CSV files with pandas and converts each row into a separate
    Document with JSON content. Perfect for creating searchable knowledge bases
    from tabular data where each row represents an entity or record.

    Features:
    - One document per CSV row
    - JSON serialization of row data
    - Configurable pandas read options
    - Row indexing and metadata
    - Header preservation
    - Data type inference
    - Error handling for malformed data
    """

    extensions: List[str] = ['.csv', '.tsv']

    def __init__(
        self,
        source: Optional[Union[pd.DataFrame, PurePath, List[PurePath]]] = None,
        *,
        tokenizer: Union[str, Callable] = None,
        text_splitter: Union[str, Callable] = None,
        source_type: str = 'file',

        # CSV reading options (pandas parameters)
        separator: Optional[str] = None,  # Auto-detect if None
        encoding: str = 'utf-8',
        header: Union[int, List[int], str] = 0,  # Use first row as header
        index_col: Union[int, str, List, bool] = False,
        usecols: Optional[List] = None,
        dtype: Optional[Dict] = None,

        # Data processing options
        skip_empty_rows: bool = True,
        skip_na_rows: bool = False,  # Keep rows with some NaN values
        fill_na_value: Optional[str] = None,  # Fill NaN with this value

        # JSON formatting
        json_ensure_ascii: bool = False,
        json_indent: Optional[int] = 2,

        # Row filtering
        max_rows: Optional[int] = None,
        skip_rows: Optional[int] = None,

        # Content options
        include_row_index: bool = True,
        include_headers_in_content: bool = False,
        row_prefix: str = "Row",

        **kwargs
    ):
        super().__init__(
            source,
            tokenizer=tokenizer,
            text_splitter=text_splitter,
            source_type=source_type,
            **kwargs
        )

        # CSV reading configuration
        self.separator = separator
        self.encoding = encoding
        self.header = header
        self.index_col = index_col
        self.usecols = usecols
        self.dtype = dtype

        # Data processing
        self.skip_empty_rows = skip_empty_rows
        self.skip_na_rows = skip_na_rows
        self.fill_na_value = fill_na_value

        # JSON formatting
        self.json_ensure_ascii = json_ensure_ascii
        self.json_indent = json_indent

        # Row filtering
        self.max_rows = max_rows
        self.skip_rows = skip_rows

        # Content options
        self.include_row_index = include_row_index
        self.include_headers_in_content = include_headers_in_content
        self.row_prefix = row_prefix

    def _detect_separator(self, file_path: str, sample_size: int = 1024) -> str:
        """Auto-detect CSV separator by sampling the file."""
        try:
            with open(file_path, 'r', encoding=self.encoding) as f:
                sample = f.read(sample_size)

            # Try common separators
            separators = [',', ';', '\t', '|']
            separator_counts = {}

            for sep in separators:
                # Count occurrences in first few lines
                lines = sample.split('\n')[:3]
                count = sum(line.count(sep) for line in lines)
                if count > 0:
                    separator_counts[sep] = count

            if separator_counts:
                # Return separator with highest count
                return max(separator_counts.keys(), key=separator_counts.get)
            else:
                return ','  # Default fallback

        except Exception as e:
            self.logger.warning(f"Could not auto-detect separator: {e}, using comma")
            return ','

    def _prepare_pandas_kwargs(self, path: str) -> Dict[str, Any]:
        """Prepare pandas read_csv arguments."""
        kwargs = {
            'encoding': self.encoding,
            'header': self.header,
            'index_col': self.index_col,
        }

        # Auto-detect separator if not specified
        if self.separator is None:
            kwargs['sep'] = self._detect_separator(path)
        else:
            kwargs['sep'] = self.separator

        # Add optional parameters
        if self.usecols is not None:
            kwargs['usecols'] = self.usecols
        if self.dtype is not None:
            kwargs['dtype'] = self.dtype
        if self.max_rows is not None:
            kwargs['nrows'] = self.max_rows
        if self.skip_rows is not None:
            kwargs['skiprows'] = self.skip_rows

        # Handle empty rows
        if self.skip_empty_rows:
            kwargs['skip_blank_lines'] = True

        return kwargs

    def _clean_row_data(self, row_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Clean and process row data."""
        cleaned = {}

        for key, value in row_dict.items():
            # Clean column names (keys)
            clean_key = str(key).strip()

            # Handle NaN values
            if pd.isna(value):
                if self.fill_na_value is not None:
                    clean_value = self.fill_na_value
                else:
                    clean_value = None
            else:
                # Convert to appropriate type for JSON serialization
                if isinstance(value, (pd.Timestamp, pd.Period)):
                    clean_value = str(value)
                elif isinstance(value, (int, float, str, bool)):
                    clean_value = value
                else:
                    clean_value = str(value)

            cleaned[clean_key] = clean_value

        return cleaned

    def _should_skip_row(self, row_dict: Dict[str, Any]) -> bool:
        """Determine if a row should be skipped."""
        # Skip if all values are NaN and skip_na_rows is True
        if self.skip_na_rows:
            non_null_values = [v for v in row_dict.values() if not pd.isna(v) and v is not None]
            if not non_null_values:
                return True

        # Skip if row is effectively empty after cleaning
        if self.skip_empty_rows:
            cleaned = self._clean_row_data(row_dict)
            non_empty_values = [v for v in cleaned.values() if v is not None and str(v).strip()]
            if not non_empty_values:
                return True

        return False

    def _format_row_as_json(self, row_dict: Dict[str, Any], row_index: int, headers: List[str]) -> str:
        """Convert row data to JSON string."""
        cleaned_data = self._clean_row_data(row_dict)

        # Create structured JSON document
        json_doc = {
            "data": cleaned_data
        }

        # Add row metadata if requested
        if self.include_row_index:
            json_doc["row_index"] = row_index

        # Add headers information if requested
        if self.include_headers_in_content:
            json_doc["headers"] = headers
            json_doc["row_name"] = f"{self.row_prefix} {row_index + 1}"

        return json.dumps(
            json_doc,
            ensure_ascii=self.json_ensure_ascii,
            indent=self.json_indent,
            default=str  # Handle any remaining non-serializable objects
        )

    async def _load(self, path: Union[str, PurePath, List[PurePath]], **kwargs) -> List[Document]:
        """
        Load CSV file and create one Document per row.

        Args:
            path: Path to the CSV file

        Returns:
            List of Document objects, one per CSV row
        """
        if isinstance(path, PurePath):
            self.logger.info(f"Loading CSV From: {path}")
        elif isinstance(path, pd.DataFrame):
            self.logger.info(
                f"Loading CSV From DataFrame with {len(path)} rows and {len(path.columns)} columns"
            )
        docs = []

        try:
            # Prepare pandas arguments
            pandas_kwargs = self._prepare_pandas_kwargs(str(path))

            # Read CSV with pandas
            if isinstance(path, pd.DataFrame):
                df = path
            else:
                df = pd.read_csv(str(path), **pandas_kwargs)

            if df.empty:
                self.logger.warning(f"CSV file {path} is empty or has no valid data")
                return docs

            self.logger.info(f"Loaded CSV with {len(df)} rows and {len(df.columns)} columns")

            # Get column headers
            headers = df.columns.tolist()

            # Create CSV metadata
            csv_metadata = {
                "total_rows": len(df),
                "total_columns": len(df.columns),
                "column_headers": headers,
                "data_types": df.dtypes.astype(str).to_dict(),
                "separator_used": pandas_kwargs.get('sep', ','),
                "encoding_used": self.encoding,
            }

            # Add basic statistics if numeric columns exist
            numeric_columns = df.select_dtypes(include=['number']).columns.tolist()
            if numeric_columns:
                csv_metadata["numeric_columns"] = numeric_columns
                csv_metadata["has_numeric_data"] = True
            else:
                csv_metadata["has_numeric_data"] = False

            # Process each row
            processed_rows = 0
            skipped_rows = 0

            for row_index, (_, row) in enumerate(df.iterrows()):
                row_dict = row.to_dict()

                # Skip row if it meets skip criteria
                if self._should_skip_row(row_dict):
                    skipped_rows += 1
                    continue

                # Convert row to JSON
                json_content = self._format_row_as_json(row_dict, row_index, headers)

                # Create row metadata
                row_metadata = {
                    "row_index": row_index,
                    "row_number": row_index + 1,  # Human-friendly numbering
                    "column_count": len([v for v in row_dict.values() if not pd.isna(v)]),
                    "empty_columns": len([v for v in row_dict.values() if pd.isna(v)]),
                }

                # Create document metadata
                metadata = self.create_metadata(
                    path=path,
                    doctype="csv_row",
                    source_type="csv",
                    doc_metadata={
                        **row_metadata,
                        "csv_info": csv_metadata,
                        "content_type": "application/json",
                        "processing_options": {
                            "skip_empty_rows": self.skip_empty_rows,
                            "skip_na_rows": self.skip_na_rows,
                            "fill_na_value": self.fill_na_value,
                        }
                    },
                )

                # Create document
                doc = Document(
                    page_content=json_content,
                    metadata=metadata
                )
                docs.append(doc)
                processed_rows += 1

            self.logger.info(f"Processed {processed_rows} rows, skipped {skipped_rows} rows")

        except Exception as e:
            self.logger.error(f"Failed to load CSV file {path}: {e}")
            raise

        return docs

    def get_csv_info(self, path: Union[str, PurePath]) -> Dict[str, Any]:
        """Get information about a CSV file without loading all data."""
        try:
            pandas_kwargs = self._prepare_pandas_kwargs(str(path))

            # Read just the first few rows to get info
            sample_df = pd.read_csv(str(path), nrows=5, **pandas_kwargs)

            # Get full row count (more efficient than loading all data)
            with open(str(path), 'r', encoding=self.encoding) as f:
                total_rows = sum(1 for line in f) - (1 if self.header == 0 else 0)

            return {
                "total_rows": total_rows,
                "total_columns": len(sample_df.columns),
                "column_headers": sample_df.columns.tolist(),
                "data_types": sample_df.dtypes.astype(str).to_dict(),
                "separator_detected": pandas_kwargs.get('sep', ','),
                "sample_data": sample_df.head(3).to_dict('records'),
                "numeric_columns": sample_df.select_dtypes(include=['number']).columns.tolist(),
            }

        except Exception as e:
            self.logger.error(f"Could not analyze CSV file {path}: {e}")
            return {"error": str(e)}

    def estimate_documents_count(self, path: Union[str, PurePath]) -> int:
        """Estimate how many documents will be created from a CSV file."""
        try:
            info = self.get_csv_info(path)
            if "error" in info:
                return 0

            total_rows = info["total_rows"]

            # Apply filtering estimates
            if self.max_rows is not None:
                total_rows = min(total_rows, self.max_rows)

            if self.skip_rows is not None:
                total_rows = max(0, total_rows - self.skip_rows)

            # Rough estimate for empty row filtering (assume 5% empty rows)
            if self.skip_empty_rows:
                total_rows = int(total_rows * 0.95)

            return total_rows

        except Exception:
            return 0

    def get_configuration_summary(self) -> Dict[str, Any]:
        """Get current loader configuration."""
        return {
            "csv_options": {
                "separator": self.separator or "auto-detect",
                "encoding": self.encoding,
                "header": self.header,
                "max_rows": self.max_rows,
                "skip_rows": self.skip_rows,
            },
            "processing": {
                "skip_empty_rows": self.skip_empty_rows,
                "skip_na_rows": self.skip_na_rows,
                "fill_na_value": self.fill_na_value,
            },
            "output": {
                "json_indent": self.json_indent,
                "include_row_index": self.include_row_index,
                "include_headers_in_content": self.include_headers_in_content,
                "row_prefix": self.row_prefix,
            }
        }
