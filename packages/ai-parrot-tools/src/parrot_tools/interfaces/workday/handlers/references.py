import asyncio
from typing import List

import pandas as pd

from .base import WorkdayTypeBase
from ..models.reference import WorkdayReference
from ..parsers.reference_parsers import parse_reference_data


class ReferencesType(WorkdayTypeBase):
    """
    Handler for the Workday ``Get_References`` operation (Integrations service).

    Returns the full catalog of instances for a given Reference_ID_Type
    (e.g. ``Time_Calculation_Tag_ID``, ``Cost_Center_Reference_ID``).
    """

    DEFAULT_REFERENCE_TYPE = "Time_Calculation_Tag_ID"
    PAGE_SIZE = 200

    def _get_default_payload(self) -> dict:
        return {
            "Response_Filter": {},
        }

    async def execute(self, **kwargs) -> pd.DataFrame:
        """
        Supported parameters:
            - reference_id_type: Workday Reference_ID_Type to query
              (default: ``Time_Calculation_Tag_ID``).
            - count: page size (default 200).
            - max_parallel: parallel page fetches after page 1 (default 5).
        """
        reference_id_type = kwargs.pop(
            "reference_id_type", self.DEFAULT_REFERENCE_TYPE
        )
        count = int(kwargs.pop("count", self.PAGE_SIZE))
        max_parallel = int(kwargs.pop("max_parallel", 5))

        base_payload = {
            **self.request_payload,
            "Request_Criteria": {"Reference_ID_Type": reference_id_type},
        }

        self._logger.info(
            f"🔍 Get_References: Reference_ID_Type={reference_id_type}, page_size={count}"
        )

        first_page = await self._fetch_page(base_payload, page=1, count=count)
        page1_items = first_page["items"]
        total_pages = first_page["total_pages"]
        total_results = first_page["total_results"]

        self._logger.info(
            f"📊 Get_References pagination: total_results={total_results}, "
            f"total_pages={total_pages}, page1_items={len(page1_items)}"
        )

        all_items: List[dict] = list(page1_items)

        if total_pages > 1:
            remaining = list(range(2, total_pages + 1))
            for batch_start in range(0, len(remaining), max_parallel):
                batch = remaining[batch_start: batch_start + max_parallel]
                self._logger.info(
                    f"🚀 Fetching pages {batch[0]}-{batch[-1]} "
                    f"({len(batch)} pages in parallel)"
                )
                results = await asyncio.gather(
                    *[self._fetch_page(base_payload, page=p, count=count) for p in batch],
                    return_exceptions=True,
                )
                for page_num, res in zip(batch, results):
                    if isinstance(res, Exception):
                        self._logger.error(f"❌ Page {page_num} failed: {res}")
                    else:
                        all_items.extend(res["items"])

        parsed: List[dict] = []
        for raw in all_items:
            try:
                row = parse_reference_data(raw)
                if not row.get("reference_id_type"):
                    row["reference_id_type"] = reference_id_type
                parsed.append(WorkdayReference(**row).dict())
            except Exception as exc:  # pragma: no cover - defensive
                self._logger.warning(f"⚠️ Failed to parse reference: {exc}")

        if not parsed:
            self._logger.warning("Get_References returned no rows")
            return pd.DataFrame(columns=[
                "reference_type", "reference_id_type", "reference_id", "wid", "descriptor",
            ])

        df = pd.DataFrame(parsed)
        self._logger.info(
            f"✅ Get_References: {len(df)} rows for {reference_id_type}"
        )
        return df

    async def _fetch_page(self, base_payload: dict, page: int, count: int) -> dict:
        """Fetch a single page and return {'items', 'total_pages', 'total_results'}."""
        payload = {
            **base_payload,
            "Response_Filter": {
                **base_payload.get("Response_Filter", {}),
                "Page": page,
                "Count": count,
            },
        }

        raw = None
        for attempt in range(1, self.max_retries + 1):
            try:
                raw = await self.service.call_operation(operation="Get_References", **payload)
                break
            except Exception as exc:
                self._logger.warning(
                    f"[Get_References] Error on page {page} "
                    f"(attempt {attempt}/{self.max_retries}): {exc}"
                )
                if attempt == self.max_retries:
                    raise
                delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                await asyncio.sleep(delay)

        data = self.service.serialize_object(raw)
        items = data.get("Response_Data", {}).get("Reference_ID", [])
        if isinstance(items, dict):
            items = [items]

        results = data.get("Response_Results", {}) or {}
        total_pages = int(float(results.get("Total_Pages", 1) or 1))
        total_results = int(float(results.get("Total_Results", len(items)) or len(items)))

        return {
            "items": items or [],
            "total_pages": total_pages,
            "total_results": total_results,
        }
