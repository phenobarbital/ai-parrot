# parrot/tools/powerbi.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Union
import os
import asyncio
import random
import logging
import io
import csv
import time
import requests
import aiohttp
import pyarrow as pa
import pyarrow.parquet as pq
import pandas as pd
from pydantic import BaseModel, Field, model_validator, PrivateAttr, ConfigDict
from .abstract import AbstractTool, AbstractToolArgsSchema, ToolResult

POWERBI_BASE_URL = os.getenv("POWERBI_BASE_URL", "https://api.powerbi.com/v1.0/myorg")
PBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"

# ---------------- Utilities ----------------

def _fix_table_name(table: str) -> str:
    """Add single quotes around table names that contain spaces (DAX)."""
    t = (table or "").strip()
    if " " in t and not (t.startswith("'") and t.endswith("'")):
        return f"'{t}'"
    return t

def _json_rows_to_markdown(rows: List[Dict[str, Any]], table_name: Optional[str] = None) -> str:
    if not rows:
        return ""
    headers = list(rows[0].keys())

    def clean(h: str) -> str:
        h2 = h.replace("[", ".").replace("]", "")
        if table_name:
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

def _rows_to_csv_string(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()

def _rows_to_dataframe(rows: List[Dict[str, Any]]):
    return pd.DataFrame(rows)

# near other helpers at the top
def _rows_to_arrow_table(rows: List[Dict[str, Any]]):
    # pyarrow infers schema well from pylist of dicts
    return pa.Table.from_pylist(rows)

def _write_parquet(rows: List[Dict[str, Any]], path: str) -> str:
    # prefer pyarrow directly; fallback to pandas if pyarrow not available
    try:
        table = pa.Table.from_pylist(rows)
        pq.write_table(table, path)
        return path
    except ImportError:
        # fallback via pandas (requires pandas + either pyarrow or fastparquet installed)
        df = pd.DataFrame(rows)
        df.to_parquet(path)  # pandas will pick available parquet engine
        return path


# ---------------- Core Client ----------------
class PowerBIDatasetClient(BaseModel):
    """Client for executing DAX queries against a Power BI dataset."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _logger: logging.Logger = PrivateAttr(default=logging.getLogger("PowerBIDatasetClient"))

    dataset_id: str
    table_names: List[str] = Field(default_factory=list)
    group_id: Optional[str] = None

    # Auth
    token: Optional[str] = None
    credential: Optional[Any] = None  # azure.core.credentials.TokenCredential
    impersonated_user_name: Optional[str] = None

    # Sampling for table info
    sample_rows_in_table_info: int = Field(default=1, gt=0, le=10)

    # Retry settings (NEW)
    max_attempts: int = Field(default=5, ge=1, le=10)
    base_backoff: float = Field(default=0.5, ge=0.0)  # seconds
    max_backoff: float = Field(default=10.0, ge=0.0)  # seconds

    _schemas: Dict[str, str] = PrivateAttr(default_factory=dict)
    _aiosession: Optional[aiohttp.ClientSession] = PrivateAttr(default=None)

    @model_validator(mode="before")
    @classmethod
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

    # ---------- Retry helpers (NEW) ----------

    def _compute_sleep(self, attempt: int, retry_after: Optional[float]) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_backoff)
        # exponential backoff with jitter
        backoff = min(self.base_backoff * (2 ** (attempt - 1)), self.max_backoff)
        jitter = random.uniform(0, backoff / 2)
        return backoff + jitter

    # ---------- Sync ----------

    def run(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        headers = self._headers()
        payload = self._payload(command)

        attempt = 1
        while True:
            resp = requests.post(self.request_url, json=payload, headers=headers, timeout=timeout)
            status = resp.status_code
            if status == 403:
                return {"error": "TokenError: Could not login to Power BI (403)."}

            if status < 400:
                try:
                    return resp.json()
                except Exception as exc:
                    raise RuntimeError(f"Invalid JSON from Power BI: {exc}") from exc

            # retry on 429/5xx
            if status in {429, 500, 502, 503, 504} and attempt < self.max_attempts:
                retry_after_header = resp.headers.get("Retry-After")
                retry_after = None
                if retry_after_header:
                    try:
                        retry_after = float(retry_after_header)
                    except ValueError:
                        retry_after = None
                sleep_s = self._compute_sleep(attempt, retry_after)
                self._logger.warning(
                    "PowerBI %s; retrying in %.2fs (attempt %d/%d)", status, sleep_s, attempt, self.max_attempts
                )
                time.sleep(sleep_s)
                attempt += 1
                continue

            # give up
            try:
                err = resp.json()
            except Exception:
                err = {"message": resp.text}
            return {"error": f"HTTP {status}", "details": err}

    # ---------- Async ----------
    async def arun(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        headers = self._headers()
        payload = self._payload(command)

        attempt = 1
        while True:
            if self._aiosession:
                async with self._aiosession.post(
                    self.request_url, headers=headers, json=payload, timeout=timeout
                ) as resp:
                    status = resp.status
                    if status == 403:
                        return {"error": "TokenError: Could not login to Power BI (403)."}
                    if status < 400:
                        return await resp.json(content_type=resp.content_type)
                    # retry on 429/5xx
                    if status in (429, 500, 502, 503, 504) and attempt < self.max_attempts:
                        retry_after_header = resp.headers.get("Retry-After")
                        retry_after = None
                        if retry_after_header:
                            try:
                                retry_after = float(retry_after_header)
                            except ValueError:
                                retry_after = None
                        sleep_s = self._compute_sleep(attempt, retry_after)
                        self._logger.warning(
                            "PowerBI %s; retrying in %.2fs (attempt %d/%d)", status, sleep_s, attempt, self.max_attempts
                        )
                        await asyncio.sleep(sleep_s)
                        attempt += 1
                        continue

                    try:
                        err = await resp.json(content_type=resp.content_type)
                    except Exception:
                        err = {"message": await resp.text()}
                    return {"error": f"HTTP {status}", "details": err}

            async with aiohttp.ClientSession() as session:
                async with session.post(self.request_url, headers=headers, json=payload, timeout=timeout) as resp:
                    status = resp.status
                    if status == 403:
                        return {"error": "TokenError: Could not login to Power BI (403)."}
                    if status < 400:
                        return await resp.json(content_type=resp.content_type)
                    if status in (429, 500, 502, 503, 504) and attempt < self.max_attempts:
                        retry_after_header = resp.headers.get("Retry-After")
                        retry_after = None
                        if retry_after_header:
                            try:
                                retry_after = float(retry_after_header)
                            except ValueError:
                                retry_after = None
                        sleep_s = self._compute_sleep(attempt, retry_after)
                        self._logger.warning("PowerBI %s; retrying in %.2fs (attempt %d/%d)", status, sleep_s, attempt, self.max_attempts)
                        await asyncio.sleep(sleep_s)
                        attempt += 1
                        continue
                    try:
                        err = await resp.json(content_type=resp.content_type)
                    except Exception:
                        err = {"message": await resp.text()}
                    return {"error": f"HTTP {status}", "details": err}

    # ---------- Schema-like preview (TOPN sampling) ----------
    def get_table_info(self, tables: Optional[Union[str, List[str]]] = None) -> str:
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
                self._logger.warning("Error while getting table info for %s: %s", t, exc)
                self._schemas[t] = "unknown"
        return ", ".join([self._schemas.get(t, "unknown") for t in requested])

    async def aget_table_info(self, tables: Optional[Union[str, List[str]]] = None) -> str:
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
                self._logger.warning("Error while getting table info for %s: %s", t, exc)
                self._schemas[t] = "unknown"

        await asyncio.gather(*[_fetch(t) for t in todo])
        return ", ".join([self._schemas.get(t, "unknown") for t in requested])

    def _normalize_tables(self, tables: Optional[Union[str, List[str]]]) -> Optional[List[str]]:
        if tables is None:
            # FIX: no starred-unpack! Just map.
            return [_fix_table_name(t) for t in self.table_names] if self.table_names else None
        if isinstance(tables, str):
            t = _fix_table_name(tables)
            if self.table_names and t not in [_fix_table_name(x) for x in self.table_names]:
                self.logger.warning("Table %s not found in dataset.", tables)
                return None
            return [t]
        if isinstance(tables, list):
            fixed = [_fix_table_name(x) for x in tables if x]
            if self.table_names:
                known = {_fix_table_name(x) for x in self.table_names}
                fixed = [t for t in fixed if t in known]
                if not fixed:
                    self._logger.warning("No valid tables found in requested list.")
                    return None
            return fixed or None
        return None

class _BasePowerBIToolArgs(AbstractToolArgsSchema):
    """Base arguments for Power BI tools."""
    dataset_id: str = Field(..., description="Power BI dataset (semantic model) ID")
    group_id: Optional[str] = Field(None, description="Workspace (group) ID; omit for My workspace")
    token: Optional[str] = Field(None, description="Bearer token (if not using Azure TokenCredential)")
    impersonated_user_name: Optional[str] = Field(None, description="UPN to impersonate for RLS testing")
    table_names: Optional[List[str]] = Field(default=None, description="Known table names for validation/preview")
    sample_rows_in_table_info: int = Field(default=1, ge=1, le=10, description="Rows sampled in table preview")
    timeout: int = Field(default=30, ge=1, le=300, description="HTTP timeout in seconds")

    # Retry knobs
    max_attempts: int = Field(default=5, ge=1, le=10, description="Max HTTP attempts on 429/5xx")
    base_backoff: float = Field(default=0.5, ge=0.0, description="Base backoff seconds")
    max_backoff: float = Field(default=10.0, ge=0.0, description="Max backoff seconds")

    # Export knobs
    export_csv: bool = Field(default=False, description="Write result rows to CSV")
    export_csv_path: Optional[str] = Field(default=None, description="CSV path; if not provided, a temp name is used")
    export_pandas: bool = Field(default=False, description="Return a pandas DataFrame in result (requires pandas)")

    # DAX templating
    template: Optional[str] = Field(default=None, description="DAX template using Python format syntax")
    parameters: Optional[Dict[str, Any]] = Field(default=None, description="Values for template placeholders")

    output_format: Optional[str] = Field(
        default=None,
        description="One of: row|rows|json|csv|dataframe|markdown|parquet|pyarrow.Table"
    )
    parquet_path: Optional[str] = Field(
        default=None,
        description="Where to write parquet if output_format='parquet'. Defaults to /tmp/..."
    )


class PowerBIQueryArgs(_BasePowerBIToolArgs):
    """Arguments for PowerBIQueryTool."""
    command: Optional[str] = Field(
        default=None,
        description="DAX command to execute; ignored if 'template' is provided"
    )


class PowerBIQueryTool(AbstractTool):
    """
    Tool for executing DAX queries against a Power BI dataset.
    """
    name = "powerbi_query"
    description = "Execute DAX against a Power BI dataset and return rows"
    args_schema = PowerBIQueryArgs

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
            max_attempts=kwargs.get("max_attempts", 5),
            base_backoff=kwargs.get("base_backoff", 0.5),
            max_backoff=kwargs.get("max_backoff", 10.0),
        )

        # ---- DAX templating (NEW)
        command = kwargs.get("command")
        template = kwargs.get("template")
        params = kwargs.get("parameters") or {}
        if template:
            try:
                # Users can escape literal braces with {{ and }}
                command = template.format(**params)
            except KeyError as exc:
                return ToolResult(status="error", result=None, error=f"Missing template parameter: {exc}")

        if not command:
            return ToolResult(
                status="error", result=None, error="No DAX command provided (command/template missing)"
            )

        js = await client.arun(command, timeout=kwargs.get("timeout", 30))
        if "error" in js:
            return ToolResult(
                status="error", result=None, error=js["error"]
            )

        rows = (js or {}).get("results", [{}])[0].get("tables", [{}])[0].get("rows", [])
        md = _json_rows_to_markdown(rows)
        fmt_raw = kwargs.get("output_format")
        fmt = (fmt_raw or "").strip().lower() if fmt_raw else None

        # ---- Exports
        if not fmt:
            if kwargs.get("export_csv"):
                fmt = "csv"
            elif kwargs.get("export_pandas"):
                fmt = "dataframe"

        # Normalize a few aliases
        if fmt in ("row", "json"):
            fmt = "rows"
        if fmt in ("pyarrow", "arrow", "pyarrow.table"):
            fmt = "pyarrow.Table"

        result_payload: Dict[str, Any] = {
            "raw": js,
            "format": fmt or "default",
        }

        csv_path = None
        df_obj = None
        parquet_path = None

        if fmt == "rows" or fmt is None:
            # default behavior keeps both rows and markdown available
            result_payload |= {
                "rows": rows,
                "markdown": md,
            }

        elif fmt == "markdown":
            result_payload["markdown"] = md

        elif fmt == "csv":
            csv_text = _rows_to_csv_string(rows)
            path = kwargs.get("export_csv_path") or f"/tmp/powerbi_{client.dataset_id[:8]}_{int(time.time())}.csv"
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(csv_text)
            csv_path = path
            result_payload |= {
                "csv_path": csv_path,
                "csv_text": csv_text,
            }

        elif fmt == "dataframe":
            try:
                df_obj = _rows_to_dataframe(rows)
            except Exception as exc:
                return ToolResult(status="error", result=None, error=str(exc))
            result_payload["dataframe"] = df_obj  # note: not JSON-serializable

        elif fmt == "parquet":
            path = kwargs.get("parquet_path") or f"/tmp/powerbi_{client.dataset_id[:8]}_{int(time.time())}.parquet"
            try:
                parquet_path = _write_parquet(rows, path)
            except Exception as exc:
                return ToolResult(status="error", result=None, error=str(exc))
            result_payload["parquet_path"] = parquet_path

        elif fmt == "pyarrow.Table":
            try:
                table = _rows_to_arrow_table(rows)
            except Exception as exc:
                return ToolResult(status="error", result=None, error=str(exc))
            result_payload["pyarrow_table"] = table  # note: not JSON-serializable

        else:
            # Unknown selector → return a helpful error
            return ToolResult(
                status="error",
                result=None,
                error=f"Unsupported output_format='{fmt_raw}'. Use one of: row|rows|json|csv|dataframe|markdown|parquet|pyarrow.Table"
            )

        return {
            "status": "success",
            "result": result_payload
        }


class PowerBITableInfoArgs(_BasePowerBIToolArgs):
    tables: Optional[Union[str, List[str]]] = Field(
        default=None,
        description="Specific table(s) to preview; defaults to known list if provided"
    )


class PowerBITableInfoTool(AbstractTool):
    """
    Tool for previewing table info (sample rows) from a Power BI dataset.
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
            max_attempts=kwargs.get("max_attempts", 5),
            base_backoff=kwargs.get("base_backoff", 0.5),
            max_backoff=kwargs.get("max_backoff", 10.0),
        )
        md = await client.aget_table_info(kwargs.get("tables"))
        # Optional export of the preview as CSV/DF by stitching rows from TOPN calls is not included here,
        # since get_table_info returns a joined markdown snapshot of multiple tables. If you want,
        # we can extend this tool to return per-table rows to export individually.
        return {
            "status": "success",
            "result": {
                "markdown": md
            }
        }
