import asyncio
import math
from typing import List
import pandas as pd

from .base import WorkdayTypeBase
from ..models.cost_center import CostCenter
from ..parsers.cost_center_parsers import parse_cost_center_data


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
                
                all_cost_centers: List[dict] = list(page1)
                
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
            self._logger.error("Traceback: ", exc_info=True)
            raise

    async def _fetch_cost_center_page(self, page_num: int, base_payload: dict) -> List[dict]:
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