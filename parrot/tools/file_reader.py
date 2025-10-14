"""FileReaderTool implementation for reading various file formats."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import aiofiles
import pandas as pd
from pydantic import Field

from markitdown import MarkItDown

from .abstract import AbstractTool, AbstractToolArgsSchema


class FileReaderToolArgs(AbstractToolArgsSchema):
    """Arguments for :class:`FileReaderTool`."""

    file_path: str = Field(description="Path to the file to read")
    encoding: Optional[str] = Field(
        default="utf-8",
        description="Text encoding to use for textual files",
    )
    sheet_name: Optional[str] = Field(
        default=None,
        description="Optional sheet name for Excel workbooks",
    )


class FileReaderTool(AbstractTool):
    """Tool that reads a file and returns its textual representation."""

    name = "FileReaderTool"
    description = "Read text, document, or tabular files into structured content"
    args_schema = FileReaderToolArgs

    _TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".log", ".csv"}
    _MARKITDOWN_EXTENSIONS = {".pdf", ".ppt", ".pptx", ".doc", ".docx"}
    _TABULAR_EXTENSIONS = {".csv", ".tsv", ".xls", ".xlsx", ".xlsm", ".xlsb"}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._markitdown = MarkItDown()

    async def _execute(
        self,
        file_path: str,
        encoding: Optional[str] = "utf-8",
        sheet_name: Optional[str] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        path = Path(file_path).expanduser().resolve()

        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        if path.is_dir():
            raise IsADirectoryError(f"Expected a file but received directory: {path}")

        extension = path.suffix.lower()

        if extension in self._TABULAR_EXTENSIONS:
            content, metadata = await self._read_tabular_file(path, extension, sheet_name, encoding)
            content_type = "tabular_json"
        elif extension in self._MARKITDOWN_EXTENSIONS:
            content, metadata = await self._read_markitdown_file(path)
            content_type = "markdown"
        elif extension in self._TEXT_EXTENSIONS:
            content = await self._read_text_file(path, encoding=encoding)
            metadata = {"encoding": encoding}
            content_type = "text"
        else:
            raise ValueError(f"Unsupported file extension: {extension}")

        return {
            "file_path": str(path),
            "content_type": content_type,
            "content": content,
            "metadata": {
                "extension": extension,
                **(metadata or {}),
            },
        }

    async def _read_text_file(self, path: Path, encoding: Optional[str]) -> str:
        async with aiofiles.open(path, mode="r", encoding=encoding or "utf-8") as file:
            return await file.read()

    async def _read_markitdown_file(self, path: Path) -> Tuple[str, Dict[str, Any]]:
        loop = asyncio.get_running_loop()

        def convert() -> Tuple[str, Dict[str, Any]]:
            result = self._markitdown.convert(str(path))
            text_content = getattr(result, "text_content", "")
            metadata = getattr(result, "metadata", None)
            if text_content is None:
                text_content = ""
            return text_content, metadata or {}

        return await loop.run_in_executor(None, convert)

    async def _read_tabular_file(
        self,
        path: Path,
        extension: str,
        sheet_name: Optional[str],
        encoding: Optional[str],
    ) -> Tuple[str, Dict[str, Any]]:
        loop = asyncio.get_running_loop()

        def load_dataframe() -> Tuple[str, Dict[str, Any]]:
            if extension == ".csv" or extension == ".tsv":
                sep = "\t" if extension == ".tsv" else ","
                df = pd.read_csv(path, sep=sep, encoding=encoding or "utf-8")
            else:
                df = pd.read_excel(path, sheet_name=sheet_name)

            json_content = df.to_json(orient="records", date_format="iso")
            metadata: Dict[str, Any] = {
                "rows": len(df.index),
                "columns": list(df.columns),
            }
            if sheet_name is not None and extension != ".csv" and extension != ".tsv":
                metadata["sheet_name"] = sheet_name

            return json_content, metadata

        return await loop.run_in_executor(None, load_dataframe)
