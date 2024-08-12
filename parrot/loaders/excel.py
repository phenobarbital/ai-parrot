from collections.abc import Callable
from pathlib import PurePath
from typing import Union
from io import StringIO
import mimetypes
import magic
import xlrd
import numpy as np
import pandas
from pandas._libs.parsers import STR_NA_VALUES  # pylint: disable=E0611
from langchain.text_splitter import (
    RecursiveCharacterTextSplitter
)
from langchain.docstore.document import Document
from navigator.libs.json import JSONContent
from .abstract import AbstractLoader


excel_based = (
    "application/vnd.ms-excel.sheet.binary.macroEnabled.12",
    "application/vnd.ms-excel.sheet.macroEnabled.12",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel"
)

supported_extensions = (
    ".xls",
    ".xlsx",
    ".xlsm",
    ".xlsb"
)

class ExcelLoader(AbstractLoader):
    """
    Loader for Excel files using Pandas (preserving Table structure).
    """

    _extension = supported_extensions

    def __init__(
        self,
        path: Union[list[PurePath], PurePath],
        tokenizer: Callable = None,
        text_splitter: Callable = None,
        source_type: str = 'Excel',
        **kwargs
    ):
        self.path = path
        # Index Key:
        self._index_keys: list = kwargs.pop('index', [])
        self._type: str = kwargs.pop('document_type', 'Excel')
        self.sheet_name = kwargs.pop('sheet_name', "Sheet 1")
        self.skiprows = kwargs.pop('skiprows', 0)
        self._pdargs = kwargs.pop('pd_args', {})
        self._magic = magic.Magic(mime=True)
        self.mimetype = kwargs.pop('mimetype', None)
        self.filter_nan: bool = kwargs.pop('filter_nan', True)
        self.na_values: list = ["NULL", "TBD"]
        # Operations over dataframe:
        self._drop_empty = kwargs.pop('drop_empty', False)
        self._trim = kwargs.pop('trim', False)
        self._infer_types = kwargs.pop('infer_types', True)
        self._fillna: bool = kwargs.pop('fillna', False)
        self._rename_cols = kwargs.pop('rename_cols', {})
        self._to_integer: list = kwargs.pop('to_integer', [])
        super().__init__(
            tokenizer=tokenizer,
            text_splitter=text_splitter,
            source_type=source_type,
            **kwargs
        )
        # JSON encoder:
        self._encoder = JSONContent()

    def clean_empty(self, df: pandas.DataFrame, columns: list = None) -> pandas.DataFrame:
        """
        Clean empty rows and columns from a DataFrame.

        Args:
            df (pd.DataFrame): The DataFrame to clean.

        Returns:
            pd.DataFrame: The cleaned DataFrame.
        """
        df.dropna(axis=1, how="all", inplace=True)
        df.dropna(axis=0, how="all", inplace=True)
        if columns:
            for column in columns:
                condition = df[
                    (df[column].empty)
                    | (df[column] == "")
                    | (df[column].isna())
                ].index
                df.drop(condition, inplace=True)
        return df

    def open_excel(self, filename: PurePath) -> pandas.DataFrame:
        self.logger.debug(
            f"Opening Excel file {filename}"
        )
        ## Define NA Values:
        default_missing = STR_NA_VALUES.copy()
        for val in self.na_values:  # pylint: disable=E0203
            default_missing.add(val)
            default_missing.add(val)
        self.na_values = default_missing
        if filename.suffix not in supported_extensions:
            raise ValueError(
                f"Unsupported Excel file format: {filename.suffix}"
            )
        if not filename.exists():
            raise FileNotFoundError(
                f"Excel file not found: {filename}"
            )
        if not self.mimetype:
            try:
                self.mimetype = self._magic.from_file(str(filename))
                self.logger.debug(f":: Detected MIME IS: {self.mimetype}")
            except Exception as exc:
                self.logger.error(f":: Error detecting MIME: {exc}")
                self.mimetype = mimetypes.guess_type(str(filename))[0]
            if not self.mimetype:
                # Cannot Detect Mime type:
                ext = filename.suffix
                if ext == ".xlsx" or ext == ".xls":
                    self.mimetype = "application/vnd.ms-excel"
                elif ext == ".csv" or ext == ".txt":
                    self.mimetype = "text/csv"
        if (
            self.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ):
            # xlsx or any openxml based document
            file_engine = "openpyxl"
        elif self.mimetype == "application/vnd.ms-excel.sheet.binary.macroEnabled.12":
            # xlsb
            file_engine = "pyxlsb"
        else:
            # Using extension:
            ext = filename.suffix
            if ext == ".xlsx":
                file_engine = "openpyxl"
            elif ext == ".xls":
                file_engine = "xlrd"
            elif ext == ".xlsb":
                file_engine = "pyxlsb"
            else:
                raise ValueError(
                    f"Unsupported Excel file format: {filename.suffix}"
                )
        # Build Arguments:
        pd_args = self._pdargs.copy()
        pd_args['sheet_name'] = self.sheet_name
        pd_args['skiprows'] = self.skiprows
        pd_args['engine'] = file_engine
        pd_args['na_values'] = self.na_values
        pd_args['na_filter'] = self.filter_nan
        try:
            df = pandas.read_excel(
                filename,
                keep_default_na=False,
                **pd_args
            )
        except (IndexError, xlrd.biffh.XLRDError) as err:
            raise ValueError(
                f"Excel Index error on File {filename}: {err}"
            ) from err
        except pandas.errors.EmptyDataError as err:
            raise ValueError(f"Empty File {filename}: {err}") from err
        except pandas.errors.ParserError as err:
            raise ValueError(f"Error Parsing File {filename}: {err}") from err
        except Exception as err:
            self.logger.exception(str(err), stack_info=True)
            raise
        # Post-Processing the DataFrame:
        if self._infer_types is True:
            df.infer_objects()
        # rename cols:
        if self._rename_cols:
            try:
                # Renaming Pandas Columns:
                df.rename(columns=self._rename_cols, inplace=True)
            except Exception as err:
                self.logger.error(
                    f"Error Renaming Columns: {err}"
                )
        # Clean Empty Rows:
        df = self.clean_empty(df, self._index_keys)
        if self._drop_empty:
            df.dropna(axis=1, how="all", inplace=True)
            df.dropna(axis=0, how="all", inplace=True)
            df = df.loc[:, ~df.columns.str.contains("^Unnamed")]
        if self._trim:
            cols = df.select_dtypes(include=["object", "string"])
            for col in cols:
                df[col] = df[col].astype(str).str.strip()
            # Trim whitespace from all string columns
            # df = df.applymap(lambda x: x.strip() if isinstance(x, str) else x)
        if self._to_integer:
            for column in self._to_integer:
                df[column] = df[column].fillna(0)
                try:
                    df[column] = pandas.to_numeric(df[column], errors="coerce")
                    df[column] = df[column].astype('Int64')
                except Exception:
                    continue
        if self._fillna:
            # Select all integer columns (both nullable and non-nullable)
            int_columns = df.select_dtypes(
                include=['int64', 'Int64', 'int32', 'Int32']
            ).columns  # Add other integer types if necessary
            # Fill NaN values with zeros in those columns
            df[int_columns] = df[int_columns].fillna(0)
            # Select the Strings:
            str_columns = df.select_dtypes(include=["object", "string"]).columns
            df[str_columns] = df[str_columns].astype(str).replace(["nan", np.nan], "", regex=True)
        print(df)
        print("::: Printing Column Information === ")
        for column, t in df.dtypes.items():
            print(column, "->", t, "->", df[column].iloc[0])
        return df

    def unique_columns(self, df: pandas.DataFrame) -> pandas.DataFrame:
        """
        Rename duplicate columns in the DataFrame to ensure they are unique.

        Args:
            df (pd.DataFrame): The DataFrame with potential duplicate column names.

        Returns:
            pd.DataFrame: A DataFrame with unique column names.
        """
        seen = {}
        new_columns = []
        for col in df.columns:
            new_col = col
            count = seen.get(col, 0)
            while new_col in new_columns:
                count += 1
                new_col = f"{col}_{count}"
            new_columns.append(new_col)
            seen[col] = count
        df.columns = new_columns
        return df

    def get_json(self, df: pandas.DataFrame) -> str:
        """
        Convert a DataFrame to a JSON string.

        Args:
            df (pd.DataFrame): The DataFrame to convert.

        Returns:
            str: The JSON string.
        """
        buffer = StringIO()
        df = self.unique_columns(df)
        df.to_json(buffer, orient='records')
        buffer.seek(0)
        return buffer.getvalue()

    def row_to_json(self, data) -> str:
        return self._encoder.dumps(data)

    def row_to_string(self, data: dict) -> str:
        results = []
        for key, val in data.items():
            results.append(f'{key}: "{val!s}"')
        return ', '.join(results)

    def _load_excel(self, path: PurePath) -> list:
        """
        Load an Excel file using the Pandas library.

        Args:
            path (Path): The path to the Excel file.

        Returns:
            list: A list of Langchain Documents.
        """
        if self._check_path(path):
            self.logger.info(f"Loading Excel file: {path}")
            df = self.open_excel(path)
            # Check for row unicity:
            df = self.unique_columns(df)
            metadata = {
                "url": '',
                "index": '',
                "source": str(path.name),
                "filename": path.name,
                "question": '',
                "answer": '',
                "summary": '',
                "source_type": self._source_type,
                "type": self._type,
            }
            document_meta = {
                "columns": df.columns.tolist(),
                "rows": str(len(df)),
                "sheet": self.sheet_name,
            }
            documents = []
            # remove NaN values:
            df.fillna('', axis=1, inplace=True)
            for idx, row in df.iterrows():
                idk = ''
                rw = row.to_dict()
                for col in self._index_keys:
                    if col in row:
                        idk = row[col]
                        break
                _data = {
                    "index": idk,
                    "data": rw,
                    "document_meta": {
                        "row_index": idx,
                        **document_meta,
                        **rw
                    }
                }
                _meta = {**metadata, **_data}
                row_data = self.row_to_string(rw)
                doc = Document(
                    page_content=row_data,
                    metadata=_meta
                )
                documents.append(doc)
            return documents
        return []

    def load(self, max_tokens: int = 768) -> list:
        documents = []
        if self.path.is_file():
            # single File:
            documents = self._load_excel(self.path)
        elif self.path.is_dir():
            documents = []
            # iterate over the files in the directory
            for ext in self._extension:
                for item in self.path.glob(f'*{ext}'):
                    documents.extend(self._load_excel(item))
        elif isinstance(self.path, list):
            pass
        # Split Table Data:
        return self.split_documents(documents)

    def parse(self, source):
        raise NotImplementedError(
            "Parser method is not implemented for ExcelLoader."
        )
