"""
TROCOperationsToolkit - KPI computation tools for TROC vending operations.

Provides specialized tools for computing operational KPIs across
TROC's kiosk fleet: burn rate, fill rate, LRW, KMR, merchandiser
workload, growth feasibility, and burn rate forecasting.

All tools accept a QuerySource-style filter dict and a group_by list,
delegating filtering logic to the toolkit rather than requiring the LLM
to generate Pandas code.

Usage:
    toolkit = TROCOperationsToolkit(dataset_manager=dm)
    tools = toolkit.get_tools()
    # Each async method becomes a ToolkitTool automatically.

YAML registration:
    toolkits:
      - name: troc_operations
        class: TROCOperationsToolkit
        params:
          dataset_manager: "{dataset_manager}"
"""
import operator as _op
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from parrot.tools import AbstractToolkit, ToolResult
from parrot.tools.dataset_manager import DatasetManager

# Module-level operator map — defined once, no lambda closure hazard
_FILTER_COMPARISON_OPS: Dict[str, Any] = {
    "gte": _op.ge,
    "lte": _op.le,
    "gt": _op.gt,
    "lt": _op.lt,
    "not": _op.ne,
}


class TROCOperationsToolkit(AbstractToolkit):
    """TROC vending operations KPI toolkit.

    Computes operational KPIs over pre-loaded DataFrames managed by
    a DatasetManager instance. All heavy joins (e.g., restock_cycles)
    are pre-computed in BigQuery/FlowTask — this toolkit only filters
    and aggregates.

    Args:
        dataset_manager: DatasetManager with the following datasets registered:
            - kiosks_daily_summary
            - fso_daily_summary
            - restock_cycles
            - employees_weekly (or active_employees_monthly)
            - warehouse_summary
    """

    # Dataset name constants
    DS_KIOSK_DAILY = "kiosks_daily_summary"
    DS_FSO_DAILY = "fso_daily_summary"
    DS_RESTOCK_CYCLES = "restock_cycles"
    DS_EMPLOYEES = "employees_weekly"
    DS_EMPLOYEES_MONTHLY = "active_employees_monthly"
    DS_WAREHOUSE = "warehouse_summary"

    def __init__(self, dataset_manager: DatasetManager, **kwargs):
        self.dm = dataset_manager
        super().__init__(**kwargs)

    # ─────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────

    async def _get_df(
        self, dataset_name: str, sql: Optional[str] = None
    ) -> pd.DataFrame:
        """Materialize and return a DataFrame via DatasetManager's public API.

        Delegates to ``DatasetManager.materialize()`` which handles alias
        resolution, in-memory caching, and Redis Parquet caching. Raises
        ``ValueError`` if the dataset name (or alias) is not registered.

        For TableSource-backed datasets, a ``sql`` argument with a WHERE
        clause is required to avoid unbounded full-table scans.

        Args:
            dataset_name: Registered dataset name or alias.
            sql: SQL query for TableSource datasets.  Must include a WHERE
                clause unless the source has a permanent_filter configured.

        Returns:
            Materialized DataFrame.

        Raises:
            ValueError: If the dataset is not registered or SQL is missing
                for a TableSource.
        """
        params: Dict[str, Any] = {}
        if sql is not None:
            params['sql'] = sql
        return await self.dm.materialize(dataset_name, **params)

    def _apply_filters(
        self, df: pd.DataFrame, filters: Optional[Dict[str, Any]] = None
    ) -> pd.DataFrame:
        """Apply a QuerySource-style filter dict to a DataFrame.

        Supported filter patterns:
            - {'column': value}              → exact match
            - {'column': [v1, v2]}           → isin
            - {'column__gte': value}         → >=
            - {'column__lte': value}         → <=
            - {'column__gt': value}          → >
            - {'column__lt': value}          → <
            - {'date_range': [start, end]}   → filters on the primary date column

        Args:
            df: DataFrame to filter.
            filters: Dictionary of filter conditions.

        Returns:
            Filtered DataFrame.
        """
        if not filters:
            return df

        mask = pd.Series(True, index=df.index)

        for key, value in filters.items():
            # Special case: date_range applies to the detected date column
            if key == "date_range":
                date_col = self._detect_date_column(df)
                if date_col and isinstance(value, (list, tuple)) and len(value) == 2:
                    start, end = pd.to_datetime(value[0]), pd.to_datetime(value[1])
                    col = pd.to_datetime(df[date_col])
                    mask &= (col >= start) & (col <= end)
                continue

            # Operator suffixes
            if "__" in key:
                col_name, op_name = key.rsplit("__", 1)
                if col_name not in df.columns:
                    continue
                if op_name in _FILTER_COMPARISON_OPS:
                    # Use stdlib operator functions — no lambda closure hazard
                    mask &= _FILTER_COMPARISON_OPS[op_name](df[col_name], value)
                elif op_name == "in":
                    mask &= df[col_name].isin(value)
                elif op_name == "contains":
                    mask &= df[col_name].astype(str).str.contains(
                        str(value), case=False, na=False
                    )
                continue

            # Simple exact match or isin
            if key in df.columns:
                if isinstance(value, (list, tuple)):
                    mask &= df[key].isin(value)
                else:
                    mask &= df[key] == value

        return df[mask].copy()

    def _detect_date_column(self, df: pd.DataFrame) -> Optional[str]:
        """Detect the primary date column in a DataFrame.

        Checks common TROC date column names in priority order.

        Args:
            df: DataFrame to inspect.

        Returns:
            Column name or None.
        """
        candidates = [
            "kiosk_history_date", "empty_date", "visit_date",
            "completed_date", "worked_date", "month",
        ]
        for col in candidates:
            if col in df.columns:
                return col
        # Fallback: first datetime column
        dt_cols = df.select_dtypes(include=["datetime64", "datetimetz"]).columns
        return dt_cols[0] if len(dt_cols) > 0 else None

    def _aggregate(
        self,
        df: pd.DataFrame,
        group_by: Optional[List[str]],
        agg_dict: Dict[str, Any],
    ) -> pd.DataFrame:
        """Group and aggregate a DataFrame.

        Args:
            df: Filtered DataFrame.
            group_by: Columns to group by. If None or empty, aggregate globally.
            agg_dict: Aggregation spec for pandas .agg().

        Returns:
            Aggregated DataFrame.
        """
        if not group_by:
            # Global aggregation — return single row
            result = {}
            for col, funcs in agg_dict.items():
                if col not in df.columns:
                    continue
                if isinstance(funcs, list):
                    for func_spec in funcs:
                        if isinstance(func_spec, tuple):
                            name, func = func_spec
                            result[name] = df[col].agg(func)
                        else:
                            result[f"{col}_{func_spec}"] = df[col].agg(func_spec)
                elif isinstance(funcs, str):
                    result[f"{col}_{funcs}"] = df[col].agg(funcs)
                elif isinstance(funcs, tuple):
                    name, func = funcs
                    result[name] = df[col].agg(func)
            return pd.DataFrame([result])

        # Validate group_by columns exist
        valid_cols = [c for c in group_by if c in df.columns]
        if not valid_cols:
            raise ValueError(
                f"None of group_by columns {group_by} found in DataFrame. "
                f"Available: {list(df.columns)}"
            )

        # Build named aggregation
        named_agg = {}
        for col, funcs in agg_dict.items():
            if col not in df.columns:
                continue
            if isinstance(funcs, list):
                for func_spec in funcs:
                    if isinstance(func_spec, tuple):
                        name, func = func_spec
                        named_agg[name] = (col, func)
                    else:
                        named_agg[f"{col}_{func_spec}"] = (col, func_spec)
            elif isinstance(funcs, str):
                named_agg[f"{col}_{funcs}"] = (col, funcs)
            elif isinstance(funcs, tuple):
                name, func = funcs
                named_agg[name] = (col, func)

        return df.groupby(valid_cols, as_index=False).agg(**named_agg)

    # ─────────────────────────────────────────────────────────────
    # Public tools — each becomes a ToolkitTool via AbstractToolkit
    # ─────────────────────────────────────────────────────────────

    async def compute_burn_rate(
        self,
        filters: Optional[Dict[str, Any]] = None,
        group_by: Optional[List[str]] = None,
    ) -> ToolResult:
        """Compute inventory burn rate (units depleted per day) for kiosks.

        Burn rate measures how quickly a kiosk consumes inventory.
        High burn rate indicates strong demand (a positive business signal)
        but also means the kiosk needs more frequent replenishment visits.

        Only days with actual depletion (inventory_depletion > 0) are
        considered to avoid diluting the average with restock days.

        Args:
            filters: QuerySource-style filter dict. Supported keys include
                warehouse_alias, warehouse_id, kiosk_id, region_id,
                date_range (list of [start, end] date strings).
                Example: {"warehouse_alias": "PHONX", "date_range": ["2026-03-01", "2026-03-31"]}
            group_by: Columns to aggregate by.
                Example: ["warehouse_alias"] for per-warehouse burn rate.
                Default: per-kiosk aggregation ["kiosk_id"].

        Returns:
            ToolResult with DataFrame containing avg_burn_rate, median_burn_rate,
            max_burn_rate, and days_with_depletion per group.
        """
        try:
            df = await self._get_df(self.DS_KIOSK_DAILY)
            df = self._apply_filters(df, filters)

            # Only consider days where inventory actually decreased
            active_df = df[df["inventory_depletion"] > 0].copy()

            if active_df.empty:
                return ToolResult(
                    status="success",
                    result="No depletion events found for the given filters.",
                    metadata={"filters": filters, "rows": 0},
                )

            if group_by is None:
                group_by = ["kiosk_id"]

            result = self._aggregate(
                active_df,
                group_by=group_by,
                agg_dict={
                    "inventory_depletion": [
                        ("avg_burn_rate", "mean"),
                        ("median_burn_rate", "median"),
                        ("max_burn_rate", "max"),
                        ("total_depleted", "sum"),
                    ],
                    "kiosk_id": [("days_with_depletion", "count")],
                },
            )

            return ToolResult(
                status="success",
                result=result,
                metadata={
                    "filters": filters,
                    "group_by": group_by,
                    "rows": len(result),
                },
            )
        except Exception as e:
            self.logger.error("Error in compute_burn_rate: %s", e, exc_info=True)
            return ToolResult(success=False, status="error", error=str(e), result=None)

    async def compute_fill_rate(
        self,
        filters: Optional[Dict[str, Any]] = None,
        group_by: Optional[List[str]] = None,
    ) -> ToolResult:
        """Compute fill rate statistics for kiosks.

        Fill rate is the ratio of stocked slots to total slots (0.0 to 1.0).
        A fill rate below 0.15 is functionally empty; above 0.70 is healthy.

        Args:
            filters: QuerySource-style filter dict.
                Example: {"warehouse_alias": "ATLAN", "date_range": ["2026-03-01", "2026-03-15"]}
            group_by: Aggregation columns.
                Example: ["warehouse_alias"] for per-warehouse, ["kiosk_id"] for per-kiosk.
                Default: ["warehouse_alias"].

        Returns:
            ToolResult with DataFrame containing avg_fill_rate, min_fill_rate,
            pct_critically_low (fill_rate < 0.15), and total_kiosks per group.
        """
        try:
            df = await self._get_df(self.DS_KIOSK_DAILY)
            df = self._apply_filters(df, filters)

            if df.empty:
                return ToolResult(
                    status="success",
                    result="No data found for the given filters.",
                    metadata={"filters": filters, "rows": 0},
                )

            if group_by is None:
                group_by = ["warehouse_alias"]

            # Add critical flag before aggregation
            df["is_critically_low"] = df["fill_rate"] < 0.15

            result = self._aggregate(
                df,
                group_by=group_by,
                agg_dict={
                    "fill_rate": [
                        ("avg_fill_rate", "mean"),
                        ("median_fill_rate", "median"),
                        ("min_fill_rate", "min"),
                    ],
                    "is_critically_low": [("pct_critically_low", "mean")],
                    "kiosk_id": [("total_observations", "count")],
                },
            )

            # Convert pct to percentage
            if "pct_critically_low" in result.columns:
                result["pct_critically_low"] = (
                    result["pct_critically_low"] * 100
                ).round(2)

            return ToolResult(
                status="success",
                result=result,
                metadata={
                    "filters": filters,
                    "group_by": group_by,
                    "rows": len(result),
                },
            )
        except Exception as e:
            self.logger.error("Error in compute_fill_rate: %s", e, exc_info=True)
            return ToolResult(success=False, status="error", error=str(e), result=None)

    async def compute_lrw(
        self,
        filters: Optional[Dict[str, Any]] = None,
        group_by: Optional[List[str]] = None,
        exclude_abandoned: bool = True,
    ) -> ToolResult:
        """Compute Lost Revenue Window (LRW) statistics.

        LRW measures the hours between a kiosk becoming empty and being
        restocked. Every hour a kiosk is empty represents lost revenue.
        This is the strongest signal of understaffing.

        Args:
            filters: QuerySource-style filter dict.
                Example: {"warehouse_alias": "PHONX", "date_range": ["2026-01-01", "2026-03-31"]}
            group_by: Aggregation columns.
                Example: ["warehouse_alias"] for per-warehouse LRW.
                Default: ["warehouse_id"].
            exclude_abandoned: If True (default), exclude kiosks with no restock
                (is_abandoned = True). Set False to include them in analysis.

        Returns:
            ToolResult with DataFrame containing avg_lrw_hours, median_lrw_hours,
            max_lrw_hours, total_cycles, abandoned_count, and
            total_estimated_revenue_loss per group.
        """
        try:
            df = await self._get_df(self.DS_RESTOCK_CYCLES)
            df = self._apply_filters(df, filters)

            if df.empty:
                return ToolResult(
                    status="success",
                    result="No restock cycles found for the given filters.",
                    metadata={"filters": filters, "rows": 0},
                )

            # Count abandoned before filtering them out (global + per-group)
            has_abandoned_col = "is_abandoned" in df.columns
            abandoned_count = int(df["is_abandoned"].sum()) if has_abandoned_col else 0

            if group_by is None:
                group_by = ["warehouse_id"]

            if exclude_abandoned and has_abandoned_col:
                active_df = df[~df["is_abandoned"]].copy()
            else:
                active_df = df.copy()

            if active_df.empty:
                return ToolResult(
                    status="success",
                    result=f"All {abandoned_count} cycles are abandoned (no FSO match within 60 days).",
                    metadata={"filters": filters, "abandoned_count": abandoned_count},
                )

            result = self._aggregate(
                active_df,
                group_by=group_by,
                agg_dict={
                    "lrw_hours": [
                        ("avg_lrw_hours", "mean"),
                        ("median_lrw_hours", "median"),
                        ("max_lrw_hours", "max"),
                        ("p90_lrw_hours", lambda x: np.percentile(x.dropna(), 90)),
                    ],
                    "lrw_days": [
                        ("avg_lrw_days", "mean"),
                    ],
                    "kiosk_id": [("total_cycles", "count")],
                    "estimated_revenue_loss": [
                        ("total_estimated_revenue_loss", "sum"),
                    ],
                },
            )

            # Add per-group abandoned count (not the global total)
            if has_abandoned_col and group_by:
                valid_group_cols = [c for c in group_by if c in df.columns]
                if valid_group_cols:
                    abandoned_by_group = (
                        df[df["is_abandoned"]]
                        .groupby(valid_group_cols, as_index=False)
                        .agg(abandoned_count=("kiosk_id", "count"))
                    )
                    result = result.merge(abandoned_by_group, on=valid_group_cols, how="left")
                    result["abandoned_count"] = result["abandoned_count"].fillna(0).astype(int)
                else:
                    result["abandoned_count"] = abandoned_count
            else:
                result["abandoned_count"] = abandoned_count

            # Round for readability
            for col in result.select_dtypes(include=["float64"]).columns:
                result[col] = result[col].round(2)

            return ToolResult(
                status="success",
                result=result,
                metadata={
                    "filters": filters,
                    "group_by": group_by,
                    "rows": len(result),
                    "abandoned_excluded": exclude_abandoned,
                },
            )
        except Exception as e:
            self.logger.error("Error in compute_lrw: %s", e, exc_info=True)
            return ToolResult(success=False, status="error", error=str(e), result=None)

    async def compute_kmr(
        self,
        filters: Optional[Dict[str, Any]] = None,
        group_by: Optional[List[str]] = None,
        period: str = "latest",
    ) -> ToolResult:
        """Compute Kiosk-Merchandiser Ratio (KMR) per warehouse.

        KMR = active_kiosks / active_merchandisers (FIELDPOK only).

        IMPORTANT: KMR alone is meaningless. Always pair with LRW and burn_rate
        for actionable insight. A warehouse with KMR=40 and LRW=12h is efficient.
        A warehouse with KMR=25 and LRW=96h has a non-staffing problem.

        Args:
            filters: QuerySource-style filter dict.
                Example: {"warehouse_alias": "PHONX"}
            group_by: Aggregation columns. Default: ["warehouse_alias"].
            period: Time period for headcount calculation.
                "latest" (default) uses the most recent employee snapshot.
                A date string "YYYY-MM-DD" uses headcount as of that date.

        Returns:
            ToolResult with DataFrame containing active_kiosks, active_headcount,
            kmr (ratio), and warehouse identifiers per group.
        """
        try:
            # Get kiosk data — count distinct active kiosks
            kiosk_df = await self._get_df(self.DS_KIOSK_DAILY)
            kiosk_df = self._apply_filters(kiosk_df, filters)

            # Get the most recent date in kiosk data for snapshot
            date_col = "kiosk_history_date"
            if period == "latest":
                latest_date = pd.to_datetime(kiosk_df[date_col]).max()
            else:
                latest_date = pd.to_datetime(period)

            # Filter kiosks to the snapshot date
            kiosk_snapshot = kiosk_df[
                pd.to_datetime(kiosk_df[date_col]) == latest_date
            ]

            if group_by is None:
                group_by = ["warehouse_alias"]

            # Count active kiosks per warehouse (non-error kiosks)
            kiosk_group = group_by if group_by else ["warehouse_alias"]
            kiosk_counts = (
                kiosk_snapshot[kiosk_snapshot["has_errors"] == 0]
                .groupby(kiosk_group, as_index=False)
                .agg(active_kiosks=("kiosk_id", "nunique"))
            )

            # Get headcount — try monthly first, fall back to weekly
            try:
                emp_df = await self._get_df(self.DS_EMPLOYEES_MONTHLY)
                # Use the month matching our snapshot
                snapshot_month = latest_date.to_period("M").to_timestamp()
                emp_filtered = emp_df[
                    pd.to_datetime(emp_df["month"]) == snapshot_month
                ]
                if emp_filtered.empty:
                    # Fall back to closest month — copy first to avoid mutating the cache
                    emp_work = emp_df.copy()
                    emp_work["month_dt"] = pd.to_datetime(emp_work["month"])
                    closest_idx = (emp_work["month_dt"] - latest_date).abs().idxmin()
                    emp_filtered = emp_work.loc[[closest_idx]]
            except (ValueError, KeyError) as fallback_exc:
                # Log the fallback so operators know which source is being used
                self.logger.warning(
                    "Dataset '%s' unavailable (%s), falling back to '%s'",
                    self.DS_EMPLOYEES_MONTHLY,
                    fallback_exc,
                    self.DS_EMPLOYEES,
                )
                emp_df = await self._get_df(self.DS_EMPLOYEES)
                # Copy before filtering/mutating — boolean indexing may return a view
                # of the cached DataFrame; we must not add columns to the live object.
                emp_work = emp_df[
                    (emp_df["status"] == "Active")
                    & (emp_df["job_code"] == "FIELDPOK")
                ].copy()
                # Most recent record per employee up to snapshot date
                emp_work["worked_dt"] = pd.to_datetime(emp_work["worked_date"])
                emp_filtered = emp_work[emp_work["worked_dt"] <= latest_date]
                emp_filtered = emp_filtered.sort_values("worked_dt").drop_duplicates(
                    subset=["associate_id"], keep="last"
                )

            # Apply all filters consistently to employee data (handles warehouse_alias,
            # warehouse_id, and any other dimension filters transparently).
            # _apply_filters skips columns not present in the DataFrame, so it is safe
            # to pass the same filters dict used for kiosk data.
            emp_filtered = self._apply_filters(emp_filtered, filters)

            # Count headcount per warehouse
            # Determine the headcount column based on source
            if "active_headcount" in emp_filtered.columns:
                headcount = emp_filtered[kiosk_group + ["active_headcount"]].copy()
                headcount = headcount.rename(
                    columns={"active_headcount": "active_merchandisers"}
                )
            else:
                headcount = (
                    emp_filtered.groupby(kiosk_group, as_index=False)
                    .agg(active_merchandisers=("associate_id", "nunique"))
                )

            # Merge kiosk counts with headcount
            result = kiosk_counts.merge(headcount, on=kiosk_group, how="left")
            result["active_merchandisers"] = result["active_merchandisers"].fillna(0)

            # Compute KMR
            result["kmr"] = np.where(
                result["active_merchandisers"] > 0,
                (result["active_kiosks"] / result["active_merchandisers"]).round(1),
                np.inf,  # No merchandisers = infinite ratio (red flag)
            )

            return ToolResult(
                status="success",
                result=result,
                metadata={
                    "filters": filters,
                    "group_by": group_by,
                    "period": period,
                    "snapshot_date": str(latest_date),
                    "rows": len(result),
                },
            )
        except Exception as e:
            self.logger.error("Error in compute_kmr: %s", e, exc_info=True)
            return ToolResult(success=False, status="error", error=str(e), result=None)

    async def merchandiser_workload(
        self,
        filters: Optional[Dict[str, Any]] = None,
        group_by: Optional[List[str]] = None,
    ) -> ToolResult:
        """Compute merchandiser workload metrics.

        Workload goes beyond simple KMR by factoring in demand intensity
        (burn rate of assigned kiosks) and actual visit metrics (FSO count,
        visit duration). A merchandiser with 30 high-burn kiosks has more
        real work than one with 40 low-burn kiosks.

        Args:
            filters: QuerySource-style filter dict.
                Example: {"warehouse_alias": "CMBUS", "date_range": ["2026-03-01", "2026-03-15"]}
            group_by: Aggregation columns.
                Default: ["visitor_username"] for per-merchandiser breakdown.
                Use ["warehouse_alias"] for warehouse-level summary.

        Returns:
            ToolResult with DataFrame containing fso_count, avg_visit_length,
            total_delivered, avg_delivered_per_visit per group.
        """
        try:
            fso_df = await self._get_df(self.DS_FSO_DAILY)
            fso_df = self._apply_filters(fso_df, filters)

            if fso_df.empty:
                return ToolResult(
                    status="success",
                    result="No FSO data found for the given filters.",
                    metadata={"filters": filters, "rows": 0},
                )

            if group_by is None:
                group_by = ["visitor_username"]

            # Ensure visit_length is numeric
            fso_df["visit_length"] = pd.to_numeric(
                fso_df["visit_length"], errors="coerce"
            )
            fso_df["total_delivered"] = pd.to_numeric(
                fso_df["total_delivered"], errors="coerce"
            )

            result = self._aggregate(
                fso_df,
                group_by=group_by,
                agg_dict={
                    "name_fso": [("fso_count", "count")],
                    "visit_length": [
                        ("avg_visit_length_min", "mean"),
                        ("total_visit_time_min", "sum"),
                    ],
                    "total_delivered": [
                        ("total_units_delivered", "sum"),
                        ("avg_delivered_per_visit", "mean"),
                    ],
                    "kiosk_id": [("unique_kiosks_visited", "nunique")],
                },
            )

            # Compute efficiency metric: units delivered per minute
            if (
                "total_units_delivered" in result.columns
                and "total_visit_time_min" in result.columns
            ):
                result["units_per_minute"] = np.where(
                    result["total_visit_time_min"] > 0,
                    (
                        result["total_units_delivered"]
                        / result["total_visit_time_min"]
                    ).round(2),
                    0,
                )

            # Round float columns
            for col in result.select_dtypes(include=["float64"]).columns:
                result[col] = result[col].round(2)

            return ToolResult(
                status="success",
                result=result,
                metadata={
                    "filters": filters,
                    "group_by": group_by,
                    "rows": len(result),
                },
            )
        except Exception as e:
            self.logger.error("Error in merchandiser_workload: %s", e, exc_info=True)
            return ToolResult(success=False, status="error", error=str(e), result=None)

    async def growth_feasibility(
        self,
        warehouse_alias: str,
        additional_kiosks: int = 10,
        target_max_lrw_hours: float = 48.0,
    ) -> ToolResult:
        """Simulate growth feasibility for a warehouse.

        Analyzes whether a warehouse can absorb additional kiosks without
        hiring, and if not, how many merchandisers would be needed.

        Presents three scenarios:
        - Optimistic: current efficiency maintained, slack capacity absorbed
        - Moderate: LRW increases proportionally with load
        - Conservative: LRW increases faster than load (diminishing returns)

        Args:
            warehouse_alias: Warehouse to analyze (e.g., "PHONX").
            additional_kiosks: Number of kiosks to simulate adding. Default: 10.
            target_max_lrw_hours: Maximum acceptable LRW in hours. Default: 48.

        Returns:
            ToolResult with scenario analysis including current state,
            projected KMR, projected LRW, and hiring recommendations.
        """
        try:
            # Current KMR
            kmr_result = await self.compute_kmr(
                filters={"warehouse_alias": warehouse_alias}
            )
            if kmr_result.status == "error":
                return kmr_result

            kmr_df = kmr_result.result
            if isinstance(kmr_df, str) or kmr_df.empty:
                return ToolResult(
                    success=False,
                    status="error",
                    error=f"No KMR data for warehouse '{warehouse_alias}'",
                    result=None,
                )
            if len(kmr_df) > 1:
                return ToolResult(
                    success=False,
                    status="error",
                    error=(
                        f"warehouse_alias '{warehouse_alias}' matched {len(kmr_df)} warehouses; "
                        "expected exactly 1. Use a more specific alias."
                    ),
                    result=None,
                )

            current_kiosks = int(kmr_df["active_kiosks"].iloc[0])
            current_merch = int(kmr_df["active_merchandisers"].iloc[0])
            current_kmr = float(kmr_df["kmr"].iloc[0])

            # Current LRW
            lrw_result = await self.compute_lrw(
                filters={"warehouse_alias": warehouse_alias},
                group_by=["warehouse_id"],
            )
            current_lrw = 0.0
            if lrw_result.status == "success" and isinstance(lrw_result.result, pd.DataFrame):
                if not lrw_result.result.empty:
                    current_lrw = float(
                        lrw_result.result["avg_lrw_hours"].iloc[0]
                    )

            # Projected state
            new_total_kiosks = current_kiosks + additional_kiosks
            new_kmr_no_hire = (
                new_total_kiosks / current_merch if current_merch > 0 else float("inf")
            )

            # Scenario modeling
            scenarios = []

            # Optimistic: LRW scales linearly with KMR increase
            kmr_increase_pct = (new_kmr_no_hire - current_kmr) / current_kmr if current_kmr > 0 else 0
            optimistic_lrw = current_lrw * (1 + kmr_increase_pct * 0.5)

            # Moderate: LRW scales 1:1 with KMR increase
            moderate_lrw = current_lrw * (1 + kmr_increase_pct)

            # Conservative: LRW scales quadratically
            conservative_lrw = current_lrw * (1 + kmr_increase_pct) ** 1.5

            for name, projected_lrw, description in [
                ("optimistic", optimistic_lrw, "Efficiency maintained, slack absorbed"),
                ("moderate", moderate_lrw, "LRW scales proportionally with load"),
                ("conservative", conservative_lrw, "Diminishing returns on capacity"),
            ]:
                # How many merchandisers needed to keep LRW at target?
                if projected_lrw > target_max_lrw_hours and current_lrw > 0:
                    # Estimate: to halve LRW, double capacity
                    ratio_needed = projected_lrw / target_max_lrw_hours
                    merch_needed = int(np.ceil(current_merch * ratio_needed))
                    hires_needed = max(0, merch_needed - current_merch)
                else:
                    merch_needed = current_merch
                    hires_needed = 0

                scenarios.append({
                    "scenario": name,
                    "description": description,
                    "projected_kmr": round(new_kmr_no_hire, 1),
                    "projected_lrw_hours": round(projected_lrw, 1),
                    "exceeds_target": projected_lrw > target_max_lrw_hours,
                    "merchandisers_needed": merch_needed,
                    "hires_needed": hires_needed,
                })

            result = {
                "warehouse": warehouse_alias,
                "current_state": {
                    "active_kiosks": current_kiosks,
                    "active_merchandisers": current_merch,
                    "current_kmr": round(current_kmr, 1),
                    "current_avg_lrw_hours": round(current_lrw, 1),
                },
                "simulation": {
                    "additional_kiosks": additional_kiosks,
                    "new_total_kiosks": new_total_kiosks,
                    "target_max_lrw_hours": target_max_lrw_hours,
                },
                "scenarios": scenarios,
            }

            return ToolResult(
                status="success",
                result=result,
                metadata={
                    "warehouse": warehouse_alias,
                    "additional_kiosks": additional_kiosks,
                },
            )
        except Exception as e:
            self.logger.error("Error in growth_feasibility: %s", e, exc_info=True)
            return ToolResult(success=False, status="error", error=str(e), result=None)

    async def burn_rate_forecast(
        self,
        filters: Optional[Dict[str, Any]] = None,
        group_by: Optional[List[str]] = None,
        forecast_days: int = 7,
    ) -> ToolResult:
        """Forecast when kiosks will reach empty based on current burn rate.

        Uses the average daily depletion rate to project days until each
        kiosk reaches zero inventory. Enables proactive replenishment
        scheduling instead of reactive response to emptiness notifications.

        Args:
            filters: QuerySource-style filter dict.
                Example: {"warehouse_alias": "PHONX"}
            group_by: Aggregation columns. Default: ["kiosk_id", "warehouse_alias"].
            forecast_days: Number of days to look ahead. Default: 7.
                Kiosks predicted to empty within this window are flagged as urgent.

        Returns:
            ToolResult with DataFrame containing current_count, avg_burn_rate,
            estimated_days_to_empty, is_urgent, and projected_empty_date per kiosk.
        """
        try:
            df = await self._get_df(self.DS_KIOSK_DAILY)
            df = self._apply_filters(df, filters)

            if df.empty:
                return ToolResult(
                    status="success",
                    result="No kiosk data found for the given filters.",
                    metadata={"filters": filters, "rows": 0},
                )

            # Get the latest snapshot per kiosk
            date_col = "kiosk_history_date"
            df[date_col] = pd.to_datetime(df[date_col])
            latest_date = df[date_col].max()
            latest_snapshot = df[df[date_col] == latest_date].copy()

            # Compute average burn rate over recent period (last 14 days)
            lookback_start = latest_date - pd.Timedelta(days=14)
            recent_df = df[
                (df[date_col] >= lookback_start) & (df["inventory_depletion"] > 0)
            ]

            if recent_df.empty:
                return ToolResult(
                    status="success",
                    result="No recent depletion data to forecast from.",
                    metadata={"filters": filters},
                )

            avg_burn = (
                recent_df.groupby("kiosk_id", as_index=False)
                .agg(avg_daily_burn=("inventory_depletion", "mean"))
            )

            # Merge burn rate with current snapshot
            forecast = latest_snapshot.merge(avg_burn, on="kiosk_id", how="left")
            forecast["avg_daily_burn"] = forecast["avg_daily_burn"].fillna(0)

            # Estimate days to empty
            forecast["estimated_days_to_empty"] = np.where(
                forecast["avg_daily_burn"] > 0,
                (forecast["total_count"] / forecast["avg_daily_burn"]).round(1),
                np.inf,  # No burn = won't empty
            )

            # Flag urgent kiosks
            forecast["is_urgent"] = forecast["estimated_days_to_empty"] <= forecast_days
            forecast["projected_empty_date"] = pd.NaT
            mask = forecast["avg_daily_burn"] > 0
            forecast.loc[mask, "projected_empty_date"] = (
                latest_date
                + pd.to_timedelta(
                    forecast.loc[mask, "estimated_days_to_empty"], unit="D"
                )
            )

            # Select output columns
            output_cols = [
                "kiosk_id", "kiosk_name", "warehouse_alias",
                "total_count", "fill_rate", "avg_daily_burn",
                "estimated_days_to_empty", "is_urgent", "projected_empty_date",
            ]
            result = forecast[[c for c in output_cols if c in forecast.columns]]
            result = result.sort_values("estimated_days_to_empty", ascending=True)

            # Summary stats
            urgent_count = int(result["is_urgent"].sum())
            total_kiosks = len(result)

            return ToolResult(
                status="success",
                result=result,
                metadata={
                    "filters": filters,
                    "forecast_days": forecast_days,
                    "snapshot_date": str(latest_date),
                    "urgent_kiosks": urgent_count,
                    "total_kiosks": total_kiosks,
                    "rows": len(result),
                },
            )
        except Exception as e:
            self.logger.error("Error in burn_rate_forecast: %s", e, exc_info=True)
            return ToolResult(success=False, status="error", error=str(e), result=None)