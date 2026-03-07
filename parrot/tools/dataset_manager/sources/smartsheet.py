"""Smartsheet DataSource implementation."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import aiohttp
import pandas as pd

from .base import DataSource


class SmartsheetSource(DataSource):
    """Datasource backed by a Smartsheet sheet."""

    def __init__(self, sheet_id: str, access_token: Optional[str] = None) -> None:
        self.sheet_id = str(sheet_id)
        self.access_token = access_token or os.getenv("SMARTSHEET_ACCESS_TOKEN")
        self._schema: Dict[str, str] = {}

    @property
    def cache_key(self) -> str:
        return f"smartsheet:{self.sheet_id}"

    def describe(self) -> str:
        return f"Smartsheet sheet '{self.sheet_id}'"

    def _headers(self) -> Dict[str, str]:
        if not self.access_token:
            raise ValueError("Smartsheet access token is required")
        token = self.access_token
        if not token.startswith("Bearer "):
            token = f"Bearer {token}"
        return {"Authorization": token}

    async def _fetch_sheet(self) -> Dict[str, Any]:
        url = f"https://api.smartsheet.com/2.0/sheets/{self.sheet_id}"
        async with aiohttp.ClientSession(headers=self._headers()) as session:
            async with session.get(url) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise RuntimeError(
                        f"Smartsheet request failed ({response.status}): {text}"
                    )
                return await response.json()

    @staticmethod
    def _row_to_dict(row: Dict[str, Any], columns_by_id: Dict[int, str]) -> Dict[str, Any]:
        values: Dict[str, Any] = {}
        for cell in row.get("cells", []):
            column_name = columns_by_id.get(cell.get("columnId"))
            if not column_name:
                continue
            values[column_name] = cell.get("value")
        return values

    async def prefetch_schema(self) -> Dict[str, str]:
        payload = await self._fetch_sheet()
        columns = payload.get("columns", [])
        self._schema = {c.get("title", f"col_{i}"): c.get("type", "unknown") for i, c in enumerate(columns)}
        return self._schema

    async def fetch(self, **params) -> pd.DataFrame:
        payload = await self._fetch_sheet()
        columns = payload.get("columns", [])
        rows = payload.get("rows", [])
        columns_by_id = {int(c["id"]): c.get("title", str(c["id"])) for c in columns if "id" in c}

        records = [self._row_to_dict(row, columns_by_id) for row in rows]
        df = pd.DataFrame(records)

        if not self._schema:
            self._schema = {c.get("title", f"col_{i}"): c.get("type", "unknown") for i, c in enumerate(columns)}
        return df
