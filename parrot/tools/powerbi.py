"""
Power BI Dataset tools for Parrot (execute DAX queries; inspect table info).

Implements:
- PowerBIDatasetClient: thin client over Power BI ExecuteQueries REST API
- PowerBIQueryTool: Parrot tool to run DAX and return structured results
- PowerBITableInfoTool: Parrot tool to preview table "schemas" via TOPN sampling
"""
from __future__ import annotations

import os
import asyncio
import logging
from typing import Any, Dict, List, Optional, Union, Iterable

import aiohttp
import requests
from pydantic import BaseModel, Field, model_validator

from .abstract import AbstractTool, AbstractToolArgsSchema, ToolResult  # noqa: F401

logger = logging.getLogger(__name__)

# --------- Constants ----------
POWERBI_BASE_URL = os.getenv("POWERBI_BASE_URL", "https://api.powerbi.com/v1.0/myorg")
PBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"  # MS-recommended resource scope

# --------- Utilities ----------

def _fix_table_name(table: str) -> str:
    """Add single quotes around table names that contain spaces (DAX)."""
    t = table.strip()
    if " " in t and not (t.startswith("'") and t.endswith("'")):
        return f"'{t}'"
    return t

def _json_rows_to_markdown(rows: List[Dict[str, Any]], table_name: Optional[str] = None) -> str:
    """Convert Power BI ExecuteQueries rows to Markdown table."""
    if not rows:
        return ""
    # Headers (keep original column order from first row)
    headers = list(rows[0].keys())
    # Normalize header text (remove [] and optional table prefix)
    def clean(h: str) -> str:
        h2 = h.replace("[", ".").replace("]", "")
        if table_name:
            # only strip leading "<table_name>."
            pref = f"{table_name}."
            if h2.startswith(pref):
                return h2[len(pref):]
        return h2
    hdrs = [clean(h) for h in headers]
    out = "|" + "|".join(f" {h} " for h in hdrs) + "|\n"
    out += "|" + "|".join("---" for _ in hdrs) + "|\n"
    for row in rows:
        out += "|" + "|".join(f" {row.get(h, '')} " for h in headers) + "|\n"
    return out

# --------- Low-level client ----------

class PowerBIDatasetClient(BaseModel):
    """
    Minimal client around Power BI ExecuteQueries REST API.
    Mirrors core behavior of LangChain's PowerBIDataset, but decoupled for Parrot use.
    """
    dataset_id: str
    table_names: List[str] = Field(default_factory=list)  # optional; helps table validation
    group_id: Optional[str] = None
    # Auth: either token or azure TokenCredential (lazy import)
    token: Optional[str] = None
    credential: Optional[Any] = None  # azure.core.credentials.TokenCredential
    impersonated_user_name: Optional[str] = None
    sample_rows_in_table_info: int = Field(default=1, gt=0, le=10)
    aiosession: Optional[aiohttp.ClientSession] = None

    # internal cache of table "schemas" (markdown previews)
    _schemas: Dict[str, str] = Field(default_factory=dict, repr=False)

    @model_validator(mode="before")
    def _validate_auth(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if not v.get("token") and not v.get("credential"):
            raise ValueError("Please provide either a credential or a token.")
        return v

    @property
    def request_url(self) -> str:
        if self.group_id:
            return f"{POWERBI_BASE_URL}/groups/{self.group_id}/datasets/{self.dataset_id}/executeQueries"
        return f"{POWERBI_BASE_URL}/datasets/{self.dataset_id}/executeQueries"

    def _headers(self) -> Dict[str, str]:
        if self.token:
            return {"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"}
        # Fetch a token from the azure credential
        try:
            token = self.credential.get_token(PBI_SCOPE).token  # type: ignore[attr-defined]
            return {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
        except Exception as exc:
            raise RuntimeError("Could not get a token from the supplied credentials") from exc

    def _payload(self, command: str) -> Dict[str, Any]:
        return {
            "queries": [{"query": command}],
            "impersonatedUserName": self.impersonated_user_name,
            "serializerSettings": {"includeNulls": True},
        }

    # ---- Sync ----
    def run(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """
        Execute a DAX query synchronously. Returns Power BI JSON result.
        Docs: Execute Queries REST API. See Microsoft Learn.
        """
        resp = requests.post(self.request_url, json=self._payload(command), headers=self._headers(), timeout=timeout)
        if resp.status_code == 403:
            return {"error": "TokenError: Could not login to Power BI (403)."}
        try:
            return resp.json()
        except Exception as exc:
            raise RuntimeError(f"Invalid JSON from Power BI: {exc}") from exc

    # ---- Async ----
    async def arun(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """
        Execute a DAX query asynchronously. Returns Power BI JSON result.
        """
        headers = self._headers()
        payload = self._payload(command)
        if self.aiosession:
            async with self.aiosession.post(self.request_url, headers=headers, json=payload, timeout=timeout) as resp:
                if resp.status == 403:
                    return {"error": "TokenError: Could not login to Power BI (403)."}
                return await resp.json(content_type=resp.content_type)

        async with aiohttp.ClientSession() as session:
            async with session.post(self.request_url, headers=headers, json=payload, timeout=timeout) as resp:
                if resp.status == 403:
                    return {"error": "TokenError: Could not login to Power BI (403)."}
                return await resp.json(content_type=resp.content_type)

    # ---- Helpers for “schema-like” info via TOPN sampling ----
    def get_table_info(self, tables: Optional[Union[str, List[str]]] = None) -> str:
        """Return markdown preview for requested tables (uses TOPN sampling)."""
        requested = self._normalize_tables(tables)
        if not requested:
            return "No (valid) tables requested."
        todo = [t for t in requested if t not in self._schemas]
        for t in todo:
            try:
                js = self.run(f"EVALUATE TOPN({self.sample_rows_in_table_info}, {t})")
                rows = (js or {}).get("results", [{}])[0].get("tables", [{}])[0].get("rows", [])
                self._schemas[t] = _json_rows_to_markdown(rows, table_name=t.strip("'"))
            except Exception as exc:
                logger.warning("Error while getting table info for %s: %s", t, exc)
                self._schemas[t] = "unknown"
        return ", ".join([self._schemas.get(t, "unknown") for t in requested])

    async def aget_table_info(self, tables: Optional[Union[str, List[str]]] = None) -> str:
        """Async version of get_table_info."""
        requested = self._normalize_tables(tables)
        if not requested:
            return "No (valid) tables requested."
        todo = [t for t in requested if t not in self._schemas]

        async def _fetch(t: str) -> None:
            try:
                js = await self.arun(f"EVALUATE TOPN({self.sample_rows_in_table_info}, {t})")
                rows = (js or {}).get("results", [{}])[0].get("tables", [{}])[0].get("rows", [])
                self._schemas[t] = _json_rows_to_markdown(rows, table_name=t.strip("'"))
            except Exception as exc:
                logger.warning("Error while getting table info for %s: %s", t, exc)
                self._schemas[t] = "unknown"

        await asyncio.gather(*[_fetch(t) for t in todo])
        return ", ".join([self._schemas.get(t, "unknown") for t in requested])

    def _normalize_tables(self, tables: Optional[Union[str, List[str]]]) -> Optional[List[str]]:
        """Validate requested table names against known list (if provided)."""
        if tables is None:
            return [*_fix_table_name(t) for t in self.table_names] if self.table_names else None
        if isinstance(tables, str):
            t = _fix_table_name(tables)
            if self.table_names and t not in [_fix_table_name(x) for x in self.table_names]:
                logger.warning("Table %s not found in dataset.", tables)
                return None
            return [t]
        if isinstance(tables, list):
            fixed = [_fix_table_name(x) for x in tables if x]
            if self.table_names:
                known = set(_fix_table_name(x) for x in self.table_names)
                fixed = [t for t in fixed if t in known]
                if not fixed:
                    logger.warning("No valid tables found in requested list.")
                    return None
            return fixed or None
        return None


# --------- Parrot Tools ----------

class _BasePowerBIToolArgs(AbstractToolArgsSchema):
    dataset_id: str = Field(..., description="Power BI dataset (semantic model) ID")
    group_id: Optional[str] = Field(None, description="Workspace (group) ID; omit for My workspace")
    token: Optional[str] = Field(None, description="Bearer token (if not using Azure TokenCredential)")
    impersonated_user_name: Optional[str] = Field(
        None,
        description="UPN to impersonate (RLS-enabled datasets only)"
    )
    table_names: Optional[List[str]] = Field(
        default=None,
        description="Optional known table names for validation and schema preview"
    )
    sample_rows_in_table_info: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Number of sample rows when previewing table info"
    )
    timeout: int = Field(default=30, ge=1, le=300, description="HTTP timeout in seconds")


class PowerBIQueryArgs(_BasePowerBIToolArgs):
    command: str = Field(..., description="DAX command to execute, e.g., EVALUATE TOPN(10, 'Sales')")


class PowerBIQueryTool(AbstractTool):
    """
    Execute a DAX query against a Power BI dataset using the ExecuteQueries REST API.
    Returns rows as JSON plus a Markdown rendering for quick inspection.
    """
    name = "powerbi_query"
    description = "Execute DAX against a Power BI dataset and return rows"
    args_schema = PowerBIQueryArgs

    async def _execute(self, **kwargs) -> Any:
        # Build client (prefer TokenCredential if present in kwargs)
        cred = kwargs.get("credential", None)
        client = PowerBIDatasetClient(
            dataset_id=kwargs["dataset_id"],
            group_id=kwargs.get("group_id"),
            token=kwargs.get("token"),
            credential=cred,
            impersonated_user_name=kwargs.get("impersonated_user_name"),
            table_names=kwargs.get("table_names") or [],
            sample_rows_in_table_info=kwargs.get("sample_rows_in_table_info", 1),
        )
        js = await client.arun(kwargs["command"], timeout=kwargs.get("timeout", 30))
        if "error" in js:
            return ToolResult(status="error", result=None, error=js["error"])
        # Expect: {"results":[{"tables":[{"rows":[{...},{...}], "name": "..."}]}]}
        rows = (js or {}).get("results", [{}])[0].get("tables", [{}])[0].get("rows", [])
        md = _json_rows_to_markdown(rows)
        return {
            "status": "success",
            "result": {
                "rows": rows,
                "markdown": md,
                "raw": js
            }
        }


class PowerBITableInfoArgs(_BasePowerBIToolArgs):
    tables: Optional[Union[str, List[str]]] = Field(
        default=None,
        description="Specific table or list of tables to preview; defaults to known list if provided"
    )


class PowerBITableInfoTool(AbstractTool):
    """
    Preview dataset tables by sampling rows via TOPN to produce a compact, human-readable schema snapshot.
    """
    name = "powerbi_table_info"
    description = "Preview table info (sample rows) for a Power BI dataset"
    args_schema = PowerBITableInfoArgs

    async def _execute(self, **kwargs) -> Any:
        cred = kwargs.get("credential", None)
        client = PowerBIDatasetClient(
            dataset_id=kwargs["dataset_id"],
            group_id=kwargs.get("group_id"),
            token=kwargs.get("token"),
            credential=cred,
            impersonated_user_name=kwargs.get("impersonated_user_name"),
            table_names=kwargs.get("table_names") or [],
            sample_rows_in_table_info=kwargs.get("sample_rows_in_table_info", 1),
        )
        md = await client.aget_table_info(kwargs.get("tables"))
        return {
            "status": "success",
            "result": {
                "markdown": md
            }
        }
