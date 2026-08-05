import asyncio
import json
import math

import pandas as pd

from ..models.cost_center import CostCenter
from ..parsers.cost_center_parsers import merge_org_enrichment, parse_cost_center_data
from ..utils import extract_by_type, first
from .base import WorkdayTypeBase
from .organizations import OrganizationType


class CostCenterType(WorkdayTypeBase):
    """Handler for the Workday Get_Cost_Centers operation."""

    def _get_default_payload(self) -> dict:
        """
        Payload base específico para cost centers.
        """
        return {
            "Response_Filter": {},
            "Response_Group": {
                "Include_Reference": True,
                "Include_Cost_Center_Data": True,
                "Include_Simple_Cost_Center_Data": False,
            },
        }

    async def execute(self, **kwargs) -> pd.DataFrame:
        """
        Execute the Get_Cost_Centers operation and return a pandas DataFrame.

        Supported parameters:
        - cost_center_id: Specific cost center ID to fetch (uses Request_References)
        - cost_center_id_type: Type of cost center ID (WID, Cost_Center_Reference_ID, etc.)
        - updated_from_date: Filter by updates from this date
        - updated_to_date: Filter by updates to this date
        - include_inactive: Include inactive cost centers (True/False)
        """
        # Extract parameters
        cost_center_id = kwargs.pop("cost_center_id", None)
        cost_center_id_type = kwargs.pop("cost_center_id_type", "Cost_Center_Reference_ID")
        updated_from_date = kwargs.pop("updated_from_date", None)
        updated_to_date = kwargs.pop("updated_to_date", None)
        include_inactive = kwargs.pop("include_inactive", None)
        # Organization enrichment always runs; this only controls whether
        # the recursive Cost_Center_Hierarchy chain is also built.
        include_hierarchy_chain = kwargs.pop("include_hierarchy_chain", False)

        # Build request payload
        payload = {**self.request_payload}

        # Add Request_References for specific cost center
        if cost_center_id:
            payload["Request_References"] = {
                "Cost_Center_Reference": [
                    {
                        "ID": [
                            {
                                "type": cost_center_id_type,
                                "_value_1": cost_center_id
                            }
                        ]
                    }
                ]
            }

        # Add Request_Criteria for filtering
        criteria = {}
        
        if updated_from_date or updated_to_date:
            criteria["Updated_From_Date"] = updated_from_date
            criteria["Updated_To_Date"] = updated_to_date
            
        if include_inactive is not None:
            criteria["Include_Inactive"] = include_inactive

        if criteria:
            payload["Request_Criteria"] = criteria

        try:
            # If fetching a specific cost center, just fetch it directly
            if cost_center_id:
                self._logger.info(f"Fetching specific cost center: {cost_center_id}")
                
                # Execute the SOAP call with retry logic
                response = None
                for attempt in range(1, self.max_retries + 1):
                    try:
                        response = await self.service.call_operation(
                            operation="Get_Cost_Centers",
                            **payload
                        )
                        self._logger.info(f"✅ Successfully fetched cost center {cost_center_id}")
                        break
                    except Exception as exc:
                        self._logger.warning(
                            f"[Get_Cost_Centers] Error fetching cost center {cost_center_id} "
                            f"(attempt {attempt}/{self.max_retries}): {exc}"
                        )
                        if attempt == self.max_retries:
                            self._logger.error(
                                f"[Get_Cost_Centers] Failed to fetch cost center {cost_center_id} after "
                                f"{self.max_retries} attempts."
                            )
                            raise
                        delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                        self._logger.info(f"⏳ Waiting {delay:.1f}s before retry...")
                        await asyncio.sleep(delay)
                
                serialized = self.service.serialize_object(response)
                response_data = serialized.get("Response_Data", {})
                
                # Extract Cost_Center elements
                if "Cost_Center" in response_data:
                    cost_center_data = response_data["Cost_Center"]
                    cost_centers_raw = [cost_center_data] if isinstance(cost_center_data, dict) else cost_center_data
                else:
                    cost_centers_raw = []
                
                self._logger.info(f"Retrieved {len(cost_centers_raw)} cost center(s)")
                
            else:
                # For all cost centers, use pagination
                self._logger.info("🔍 Fetching first page to determine total cost centers and pages...")
                
                # Build first page payload
                first_payload = {
                    **payload,
                    "Response_Filter": {
                        **payload.get("Response_Filter", {}),
                        "Page": 1,
                        "Count": 100
                    }
                }
                
                # Fetch first page with retry logic
                raw1 = None
                for attempt in range(1, self.max_retries + 1):
                    try:
                        self._logger.info(f"📡 Attempting to fetch first page (attempt {attempt}/{self.max_retries})...")
                        raw1 = await self.service.call_operation(operation="Get_Cost_Centers", **first_payload)
                        self._logger.info("✅ Successfully fetched first page")
                        break
                    except Exception as exc:
                        self._logger.warning(
                            f"[Get_Cost_Centers] Error on first page "
                            f"(attempt {attempt}/{self.max_retries}): {exc}"
                        )
                        if attempt == self.max_retries:
                            self._logger.error(
                                f"[Get_Cost_Centers] Failed first page after "
                                f"{self.max_retries} attempts."
                            )
                            raise
                        # Use exponential backoff: 0.2s, 0.4s, 0.8s, 1.6s, 3.2s
                        delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                        self._logger.info(f"⏳ Waiting {delay:.1f}s before retry...")
                        await asyncio.sleep(delay)
                
                data1 = self.service.serialize_object(raw1)
                
                # Extract cost centers from first page
                page1 = data1.get("Response_Data", {}).get("Cost_Center", [])
                if isinstance(page1, dict):
                    page1 = [page1]
                
                # Extract pagination info from Response_Results
                response_results = data1.get("Response_Results", {})
                total_pages = int(float(response_results.get("Total_Pages", 1)))
                total_results = int(float(response_results.get("Total_Results", 0)))
                page_results = int(float(response_results.get("Page_Results", 0)))
                
                # Log pagination summary
                self._logger.info(
                    f"📊 Workday Pagination Info: Total Cost Centers={total_results}, "
                    f"Total Pages={total_pages}, Cost Centers per Page={page_results}"
                )
                self._logger.info(f"📄 Page 1/{total_pages} fetched: {len(page1)} cost centers")
                
                all_cost_centers: list[dict] = list(page1)
                
                # If more pages, batch them (max 10 parallel requests)
                max_parallel = 10
                if total_pages > 1:
                    pages = list(range(2, total_pages + 1))
                    num_batches = math.ceil(len(pages) / max_parallel)
                    batches = self.service.split_parts(pages, num_parts=num_batches)
                    
                    for batch_idx, batch in enumerate(batches, start=1):
                        self._logger.info(
                            f"🚀 Fetching batch {batch_idx}/{num_batches} "
                            f"(pages {batch[0]}-{batch[-1]}, total {len(batch)} pages)..."
                        )
                        
                        # Fetch pages in parallel
                        tasks = [
                            self._fetch_cost_center_page(page_num, payload)
                            for page_num in batch
                        ]
                        
                        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                        
                        # Process results and handle exceptions
                        for page_num, result in zip(batch, batch_results):
                            if isinstance(result, Exception):
                                self._logger.error(
                                    f"❌ Page {page_num} failed with error: {result}"
                                )
                            elif result:
                                all_cost_centers.extend(result)
                                self._logger.debug(
                                    f"✅ Page {page_num} completed: {len(result)} cost centers"
                                )
                        
                        self._logger.info(
                            f"✅ Batch {batch_idx}/{num_batches} complete. "
                            f"Total cost centers so far: {len(all_cost_centers)}"
                        )
                
                cost_centers_raw = all_cost_centers
                self._logger.info(f"📦 Total cost centers fetched: {len(cost_centers_raw)}")

            # Process each cost center
            cost_centers_processed = []
            for i, cc in enumerate(cost_centers_raw):
                try:
                    # Parse the cost center data
                    parsed_cc = parse_cost_center_data(cc)
                    
                    # Create CostCenter model instance for validation
                    cost_center_model = CostCenter(**parsed_cc)
                    
                    # Convert to dict for DataFrame
                    cost_centers_processed.append(cost_center_model.dict())
                    
                except Exception as e:
                    self._logger.warning(f"⚠️ Error parsing cost center {i}: {e}")
                    self._logger.debug("Traceback: ", exc_info=True)
                    continue

            # Convert to DataFrame
            if cost_centers_processed:
                # Organization enrichment ALWAYS runs (batch path and
                # single-ID path alike) — graceful degradation on failure.
                cost_centers_processed = await self._enrich_with_organizations(
                    cost_centers_processed,
                    cost_center_id=cost_center_id,
                    include_hierarchy_chain=include_hierarchy_chain,
                )

                df = pd.DataFrame(cost_centers_processed)

                # Log DataFrame info
                self._logger.info(f"✅ Created DataFrame with {len(df)} rows and {len(df.columns)} columns")
                self._logger.debug(f"DataFrame columns: {list(df.columns)}")
                
                return df
            else:
                self._logger.warning("No cost centers found or processed successfully")
                # Return empty DataFrame with expected columns
                return pd.DataFrame(columns=[
                    'cost_center_id', 'cost_center_wid', 'cost_center_name', 'cost_center_code',
                    'organization_id', 'organization_name', 'organization_code', 'organization_type',
                    'effective_date', 'availability_date', 'inactive'
                ])

        except Exception as e:
            self._logger.error(f"Error in Get_Cost_Centers operation: {e}")
            self._logger.exception("Traceback: ")
            raise

    async def _fetch_cost_center_page(self, page_num: int, base_payload: dict) -> list[dict]:
        """
        Fetch a single page of Get_Cost_Centers. Returns list of cost center dicts.
        Similar to candidates.py _fetch_candidate_page method.
        """
        self._logger.debug(f"📄 Starting fetch for page {page_num}")
        
        # Build payload for this page
        payload = {
            **base_payload,
            "Response_Filter": {
                **base_payload.get("Response_Filter", {}),
                "Page": page_num,
                "Count": 100
            }
        }
        
        # Use retry mechanism with exponential backoff
        raw = None
        for attempt in range(1, self.max_retries + 1):
            try:
                raw = await self.service.call_operation(operation="Get_Cost_Centers", **payload)
                break
            except Exception as exc:
                self._logger.warning(
                    f"[Get_Cost_Centers] Error on page {page_num} "
                    f"(attempt {attempt}/{self.max_retries}): {exc}"
                )
                if attempt == self.max_retries:
                    self._logger.error(
                        f"[Get_Cost_Centers] Failed page {page_num} after "
                        f"{self.max_retries} attempts."
                    )
                    raise
                # Use exponential backoff: 0.2s, 0.4s, 0.8s, 1.6s, 3.2s
                delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                await asyncio.sleep(delay)
        
        data = self.service.serialize_object(raw)
        items = data.get("Response_Data", {}).get("Cost_Center", [])
        if isinstance(items, dict):
            items = [items]
        
        cost_centers_count = len(items) if items else 0
        self._logger.debug(f"✅ Page {page_num} completed: {cost_centers_count} cost centers fetched")

        return items or []

    # ------------------------------------------------------------------
    # Organization enrichment orchestration
    # ------------------------------------------------------------------

    async def _enrich_with_organizations(
        self,
        cost_centers_processed: list[dict],
        cost_center_id: str | None = None,
        include_hierarchy_chain: bool = False,
    ) -> list[dict]:
        """
        Enrich already-parsed cost center rows with organization data.
        Always runs — batch path and single-ID path alike. On any failure,
        logs a WARNING and returns the rows unchanged (graceful degradation).

        Args:
            cost_centers_processed: List of `CostCenter.dict()` rows (already
                built from the base `Get_Cost_Centers` fetch).
            cost_center_id: When set, enrich via the single-ID direct lookup
                path instead of the batch path.
            include_hierarchy_chain: When True, also build the recursive
                `org_hierarchy_chain` JSON column.

        Returns:
            The same rows with the seven `org_*` keys populated (or the
            original rows unchanged if enrichment fails).
        """
        try:
            if cost_center_id:
                # Single-ID path: exactly one extra SOAP call, direct lookup
                # by Cost_Center_Reference_ID.
                org_type = OrganizationType(self.service)
                org_df = await org_type.execute(
                    organization_id=cost_center_id,
                    organization_id_type="Cost_Center_Reference_ID",
                )
            else:
                # Batch path: one Get_Organizations call filtered to
                # Cost_Center-type orgs, Include_Inactive=True (required for
                # the join to close 1:1 on the live tenant).
                org_df = await self._fetch_org_enrichment(include_inactive=True)

            org_lookup: dict[str, dict] = {}
            if org_df is not None and not org_df.empty and "organization_id" in org_df.columns:
                for record in org_df.to_dict(orient="records"):
                    key = record.get("organization_id")
                    if key:
                        # OrganizationType.execute() pre-serializes list
                        # columns to JSON strings for the DataFrame (its own
                        # existing behaviour, organizations.py) — deserialize
                        # back so merge_org_enrichment() (which expects
                        # Organization.dict()-shaped plain lists) receives
                        # the right type.
                        for list_col in ("roles", "external_ids"):
                            value = record.get(list_col)
                            if isinstance(value, str):
                                try:
                                    record[list_col] = json.loads(value) if value else []
                                except (TypeError, ValueError):
                                    record[list_col] = []
                        org_lookup[str(key)] = record

            container_ids: set[str] = set()
            for row in cost_centers_processed:
                # Primary join key: cost_center_id == organization_id
                # (Reference_ID) — verified 1:1 on the live tenant.
                org_row = org_lookup.get(str(row.get("cost_center_id")))
                if org_row is None:
                    self._logger.debug(
                        f"No matching organization found for cost center "
                        f"{row.get('cost_center_id')!r}; org_* columns left None."
                    )
                merged = merge_org_enrichment(row, org_row)
                row.update(merged)
                parent_id = merged.get("org_parent_organization_id")
                if parent_id:
                    container_ids.add(parent_id)

            if container_ids:
                container_cache = await self._resolve_container_orgs(container_ids)
                for row in cost_centers_processed:
                    parent_id = row.get("org_parent_organization_id")
                    if parent_id and parent_id in container_cache:
                        info = container_cache[parent_id]
                        row["org_parent_organization_name"] = info.get("name")
                        row["org_parent_organization_type"] = info.get("type")

                if include_hierarchy_chain:
                    for row in cost_centers_processed:
                        parent_id = row.get("org_parent_organization_id")
                        if not parent_id:
                            continue
                        chain = await self._build_hierarchy_chain(parent_id, container_cache)
                        row["org_hierarchy_chain"] = json.dumps(chain) if chain else None

            return cost_centers_processed

        except Exception as exc:
            self._logger.warning(
                f"⚠️ Organization enrichment failed, returning base cost center "
                f"data unchanged: {exc}"
            )
            self._logger.debug("Traceback: ", exc_info=True)
            return cost_centers_processed

    async def _fetch_org_enrichment(self, include_inactive: bool = True) -> pd.DataFrame:
        """
        Batch-fetch Cost_Center-type organizations for enrichment. Uses
        `organization_type="Cost_Center"` (underscore form — calling
        `execute()` directly with the explicit kwarg avoids the space-form
        bug in the `get_cost_centers()` convenience method) and
        `include_inactive=True` (required for the join to close 1:1 on the
        live tenant).

        Args:
            include_inactive: Whether to include inactive organizations.

        Returns:
            DataFrame of organizations (as produced by
            `OrganizationType.execute()`).
        """
        org_type = OrganizationType(self.service)
        return await org_type.execute(
            organization_type="Cost_Center",
            include_inactive=include_inactive,
        )

    async def _resolve_container_orgs(self, container_ids: set[str]) -> dict[str, dict]:
        """
        Resolve the `Cost_Center_Hierarchy` container orgs referenced by
        cost centers' `org_parent_organization_id` (in-run cache, one
        `Get_Organizations` lookup each).

        Args:
            container_ids: Distinct `org_parent_organization_id` values to
                resolve.

        Returns:
            `{container_id: {"name": ..., "type": ..., "superior_id": ...}}`.
            `superior_id` is the container's own `Included_In`/`Superior`
            parent (used by `_build_hierarchy_chain`); `None` for roots or
            on lookup failure.
        """
        cache: dict[str, dict] = {}
        for container_id in container_ids:
            if not container_id or container_id in cache:
                continue
            try:
                cache[container_id] = await self._fetch_container_org_info(container_id)
            except Exception as exc:  # noqa: BLE001 — graceful degradation, never raise
                self._logger.warning(
                    f"Failed to resolve container organization {container_id!r}: {exc}"
                )
                cache[container_id] = {"name": None, "type": None, "superior_id": None}
        return cache

    async def _build_hierarchy_chain(self, parent_id: str, cache: dict) -> list:
        """
        Walk `Superior_Organization_Reference` of `Cost_Center_Hierarchy`
        container orgs from `parent_id` up to the root (JSON array of
        `{id, name}`, parent → root order).

        Ancestors not already present in `cache` are resolved on demand and
        memoized into `cache` (bounded by the small number of total
        container orgs in the tenant, regardless of how many cost center
        rows are walked). Capped at 10 levels with a WARNING (cycle guard);
        live depth is typically shallow.

        Args:
            parent_id: The cost center's `org_parent_organization_id` to
                start the walk from.
            cache: The in-run container cache (from `_resolve_container_orgs`,
                extended in place as ancestors are resolved).

        Returns:
            List of `{"id": ..., "name": ...}` dicts, immediate parent first.
        """
        chain: list[dict] = []
        current_id = parent_id
        seen: set[str] = set()
        max_depth = 10

        while current_id and len(chain) < max_depth:
            if current_id in seen:
                self._logger.warning(
                    f"Cycle detected while walking hierarchy chain at "
                    f"{current_id!r} (started from {parent_id!r}); stopping."
                )
                break
            seen.add(current_id)

            if current_id not in cache:
                try:
                    cache[current_id] = await self._fetch_container_org_info(current_id)
                except Exception as exc:  # noqa: BLE001 — graceful degradation, never raise
                    self._logger.warning(
                        f"Failed to resolve container organization {current_id!r} "
                        f"during chain walk: {exc}"
                    )
                    cache[current_id] = {"name": None, "type": None, "superior_id": None}

            info = cache[current_id]
            chain.append({"id": current_id, "name": info.get("name")})
            current_id = info.get("superior_id")

        if current_id and len(chain) >= max_depth:
            self._logger.warning(
                f"Hierarchy chain starting at {parent_id!r} exceeded "
                f"{max_depth} levels; capped."
            )

        return chain

    async def _fetch_container_org_info(self, organization_id: str) -> dict:
        """
        Fetch a single organization by `Organization_Reference_ID` and parse
        `name`, `type` and `superior_id` directly from the raw response.

        Bypasses the `Organization` pydantic model (`OrganizationType.execute()`)
        because it does not expose `Hierarchy_Data.Superior_Organization_Reference`
        — only `Included_In_Organization_Reference` (mapped to
        `parent_organization_id`). Container/hierarchy orgs use the
        `Superior_Organization_Reference` field instead (verified: always
        null for cost-center orgs, populated for `Cost_Center_Hierarchy` orgs).

        Args:
            organization_id: `Organization_Reference_ID` of the container org.

        Returns:
            `{"name": ..., "type": ..., "superior_id": ...}` — any of which
            may be `None` if absent in the response.
        """
        org_type = OrganizationType(self.service)
        payload = {**org_type.request_payload}
        payload["Request_References"] = {
            "Organization_Reference": [
                {"ID": [{"type": "Organization_Reference_ID", "_value_1": organization_id}]}
            ]
        }

        # Retry with exponential backoff — same idiom as the page fetches above.
        # Without it, a single transient SOAP error would permanently null the
        # parent name/type (and chain) for every cost center under this container.
        raw = None
        for attempt in range(1, self.max_retries + 1):
            try:
                raw = await self.service.call_operation(operation="Get_Organizations", **payload)
                break
            except Exception as exc:
                self._logger.warning(
                    f"[Get_Organizations] Error fetching container org {organization_id} "
                    f"(attempt {attempt}/{self.max_retries}): {exc}"
                )
                if attempt == self.max_retries:
                    self._logger.error(
                        f"[Get_Organizations] Failed container org {organization_id} after "
                        f"{self.max_retries} attempts."
                    )
                    raise
                delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                await asyncio.sleep(delay)
        data = self.service.serialize_object(raw)
        items = data.get("Response_Data", {}).get("Organization", [])
        item = items[0] if isinstance(items, list) and items else (items if isinstance(items, dict) else {})

        org_data = item.get("Organization_Data", {}) if isinstance(item, dict) else {}
        if not isinstance(org_data, dict):
            org_data = {}

        name = org_data.get("Name")

        type_ref = org_data.get("Organization_Type_Reference", {}) or {}
        org_type_id = extract_by_type(type_ref.get("ID", []), "Organization_Type_ID")

        hierarchy = org_data.get("Hierarchy_Data", {}) or {}
        superior_ref = first(hierarchy.get("Superior_Organization_Reference"))
        superior_id = (
            extract_by_type(superior_ref.get("ID", []), "Organization_Reference_ID")
            if superior_ref
            else None
        )

        return {"name": name, "type": org_type_id, "superior_id": superior_id} 