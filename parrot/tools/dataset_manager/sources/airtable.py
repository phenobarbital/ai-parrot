"""Airtable DataSource implementation."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional
from urllib.parse import quote

import aiohttp
import pandas as pd

from .base import DataSource


class AirtableSource(DataSource):
    """Datasource backed by an Airtable table."""

    def __init__(
        self,
        base_id: str,
        table: str,
        api_key: Optional[str] = None,
        view: Optional[str] = None,
    ) -> None:
        self.base_id = base_id
        self.table = table
        self.api_key = api_key or os.getenv("AIRTABLE_API_KEY")
        self.view = view
        self._schema: Dict[str, str] = {}

    @property
    def cache_key(self) -> str:
        return f"airtable:{self.base_id}:{self.table}"

    def describe(self) -> str:
        return f"Airtable base '{self.base_id}', table '{self.table}'"

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise ValueError("Airtable API key is required")
        token = self.api_key
        if not token.startswith("Bearer "):
            token = f"Bearer {token}"
        return {"Authorization": token}

    async def _fetch_records(self, max_records: Optional[int] = None) -> list[dict[str, Any]]:
        url = f"https://api.airtable.com/v0/{self.base_id}/{quote(self.table, safe='')}"
        params: Dict[str, Any] = {"pageSize": 100}
        if self.view:
            params["view"] = self.view
        if max_records:
            params["maxRecords"] = max_records

        records: list[dict[str, Any]] = []
        async with aiohttp.ClientSession(headers=self._headers()) as session:
            offset: Optional[str] = None
            while True:
                local_params = params.copy()
                if offset:
                    local_params["offset"] = offset
                async with session.get(url, params=local_params) as response:
                    if response.status >= 400:
                        text = await response.text()
                        raise RuntimeError(f"Airtable request failed ({response.status}): {text}")
                    payload = await response.json()
                records.extend(payload.get("records", []))
                offset = payload.get("offset")
                if not offset:
                    break
                if max_records and len(records) >= max_records:
                    return records[:max_records]

        return records

    async def prefetch_schema(self) -> Dict[str, str]:
        records = await self._fetch_records(max_records=1)
        if not records:
            self._schema = {}
            return self._schema

        fields = records[0].get("fields", {})
        self._schema = {k: type(v).__name__ for k, v in fields.items()}
        return self._schema

    async def fetch(self, max_records: Optional[int] = None, **params) -> pd.DataFrame:
        if params.get("view"):
            self.view = params["view"]
        records = await self._fetch_records(max_records=max_records)
        data = [r.get("fields", {}) for r in records]
        df = pd.DataFrame(data)
        if self._schema == {} and not df.empty:
            self._schema = {col: str(dtype) for col, dtype in df.dtypes.items()}
        return df
