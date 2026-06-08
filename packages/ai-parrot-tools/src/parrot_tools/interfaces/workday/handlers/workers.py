# types/workers.py

import asyncio
import gc
import math
from typing import List, Dict, Any
import pandas as pd
from datetime import datetime, timedelta, timezone

from .base import WorkdayTypeBase
from ..models import Worker
from ..parsers import (
    parse_worker_reference,
    parse_personal_data,
    parse_contact_data,
    parse_worker_organization_data,
    parse_compensation_data,
    parse_identification_data,
    parse_benefits_and_roles,
    parse_employment_data,
    parse_worker_status,
    parse_business_site,
    parse_management_chain_data,
    parse_position_management_chain_data,
    parse_payroll_and_tax_data,
    parse_position_organizations,
    parse_international_assignment_data,
)
from ..utils import safe_serialize


class WorkerType(WorkdayTypeBase):
    """Handler for the Workday Get_Workers operation, batching pages
       so that no more than `max_parallel` requests run concurrently."""

    def __init__(self, component: Any, max_retries: int = 5, retry_delay: float = 0.2):
        """
        Initialize WorkerType with more robust retry settings for connection issues.
        
        :param component: Component instance
        :param max_retries: Maximum retry attempts (default: 5 for connection resilience)
        :param retry_delay: Base delay between retries in seconds (default: 0.5 for exponential backoff)
        """
        super().__init__(component, max_retries=max_retries, retry_delay=retry_delay)

    def _get_default_payload(self) -> Dict[str, Any]:
        """
        Default payload for Get_Workers operation with worker-specific response groups.
        
        Based on Workday API v44.2 documentation:
        https://community.workday.com/sites/default/files/file-hosting/productionapi/Staffing/v44.2/Get_Workers.html
        
        By default, includes ALL workers (active, inactive, terminated, employees, contingent workers)
        
        As_Of_Effective_Date is set to 1 year in the future to include pre-hire workers
        with future hire dates (workers who will be effective in the future).
        """
        # Calculate date 1 year in the future to include pre-hires
        future_date = datetime.now() + timedelta(days=365)
        as_of_date_str = future_date.strftime("%Y-%m-%d")
        
        return {
            "Request_Criteria": {
                # Include ALL workers: active, inactive, terminated, etc.
                "Exclude_Inactive_Workers": False,
                "Exclude_Employees": False,
                "Exclude_Contingent_Workers": False,
            },
            "Response_Filter": {
                # Use future date as STRING to include pre-hire workers
                "As_Of_Effective_Date": as_of_date_str
            },
            "Response_Group": {
                "Include_Personal_Information": True,
                "Include_Compensation": True,
                "Include_Worker_Documents": True,
                "Include_Photo": True,
                "Include_Roles": True,
                "Include_Employment_Information": True,
                "Include_Management_Chain_Data": True,
                "Include_Organizations": True,
                "Include_Reference": True,
                #"Include_Benefit_Enrollments": True
            },
        }

    async def execute(self, **kwargs) -> pd.DataFrame:
        """
        Execute the Get_Workers operation and return a pandas DataFrame.

        If `worker_id` is provided, fetches only that one; otherwise
        fetches all pages in batches of at most `max_parallel` concurrent requests.

        Args:
            worker_id: Optional specific worker Employee_ID to fetch
            document_directory: Optional base directory to save worker documents (defaults to /tmp/workday_worker_documents)
            start_date: Optional ISO datetime string for incremental load (Transaction_Log_Criteria_Data Updated_From)
            end_date: Optional ISO datetime string for incremental load upper bound; defaults to UTC now minus 5 min
        """
        worker_id = kwargs.pop("worker_id", None)
        document_directory = kwargs.pop("document_directory", None)
        start_date = kwargs.pop("start_date", None)
        end_date = kwargs.pop("end_date", None) or (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

        if document_directory:
            self._logger.info(f"📁 Worker documents will be saved to: {document_directory}")

        # Apply transaction log filter when start_date is provided
        if start_date:
            transaction_log = {
                "Transaction_Date_Range_Data": {
                    "Updated_From": start_date,
                    "Updated_Through": end_date,
                }
            }
            self.request_payload["Request_Criteria"]["Transaction_Log_Criteria_Data"] = [transaction_log]
            self._logger.info(f"🗓️ Filtering workers by transaction date: {start_date} → {end_date}")

        # Track pagination info for metrics
        pagination_info = {"total_results": None, "total_pages": None}

        if worker_id:
            # Detect ID type: Employee_ID (numeric) vs Contingent_Worker_ID (alphanumeric)
            # Employee_ID examples: "889", "12345"
            # Contingent_Worker_ID examples: "TD0ATVE10", "OSVO2HSHP"
            id_type = "Employee_ID" if worker_id.isdigit() else "Contingent_Worker_ID"

            # Single‐worker request
            payload = {
                **self.request_payload,
                "Request_References": {
                    "Worker_Reference": [
                        {"ID": {"type": id_type, "_value_1": worker_id}}
                    ]
                },
            }
            
            # Use retry for single worker request
            raw = None
            self._logger.info(f"🔍 Fetching worker {worker_id} using ID type: {id_type}")
            for attempt in range(1, self.max_retries + 1):
                try:
                    raw = await self.service.call_operation(operation="Get_Workers", **payload)
                    break
                except Exception as exc:
                    self._logger.warning(
                        f"[Get_Workers] Error fetching worker {worker_id} as {id_type} "
                        f"(attempt {attempt}/{self.max_retries}): {exc}"
                    )
                    if attempt == self.max_retries:
                        self._logger.error(
                            f"[Get_Workers] Failed to fetch worker {worker_id} as {id_type} after "
                            f"{self.max_retries} attempts."
                        )
                        raise
                    await asyncio.sleep(self.retry_delay)
            
            data = self.service.serialize_object(raw)
            items = data.get("Response_Data", {}).get("Worker", [])
            workers_raw = [items] if isinstance(items, dict) else items or []
            
            # For single worker request, extract WID from Request_References
            request_refs = data.get("Request_References", {})
            worker_ref_from_request = request_refs.get("Worker_Reference", [])
            
            single_worker_wid = None
            # Worker_Reference is a list, so we need to get the first element
            if isinstance(worker_ref_from_request, list) and len(worker_ref_from_request) > 0:
                worker_ref_dict = worker_ref_from_request[0]
                
                if isinstance(worker_ref_dict, dict):
                    ids = worker_ref_dict.get("ID", [])
                    if isinstance(ids, list):
                        for id_item in ids:
                            if isinstance(id_item, dict) and id_item.get("type") == "WID":
                                single_worker_wid = id_item.get("_value_1")
                                break
                            elif hasattr(id_item, 'type'):
                                item_type = getattr(id_item, 'type', None)
                                if item_type == "WID":
                                    single_worker_wid = getattr(id_item, '_value_1', None)
                                    break
            
            # Add the WID to each worker (only works for single worker requests)
            for worker in workers_raw:
                if isinstance(worker, dict):
                    worker["_extracted_wid"] = single_worker_wid

        else:
            # 1) Fetch page 1 to get total_pages
            self._logger.info("🔍 Fetching first page to determine total workers and pages...")
            
            # Build first page payload
            first_payload = {
                **self.request_payload,
                "Response_Filter": {
                    **self.request_payload.get("Response_Filter", {}),
                    "Page": 1, 
                    "Count": 100
                },
            }
            
            # Log the payload being sent (especially As_Of_Effective_Date)
            as_of_date = first_payload.get("Response_Filter", {}).get("As_Of_Effective_Date")
            if as_of_date:
                self._logger.info(f"📅 Using As_Of_Effective_Date: {as_of_date} to include pre-hires")
            
            # Print payload for debugging (both logger and print for visibility)
            self._logger.info("=" * 80)
            self._logger.info("📋 PAYLOAD BEING SENT TO WORKDAY GET_WORKERS:")
            self._logger.info(f"   Request_Criteria: {first_payload.get('Request_Criteria')}")
            self._logger.info(f"   Response_Filter: {first_payload.get('Response_Filter')}")
            self._logger.info("=" * 80)
            
           
            # Use retry for first page as well
            raw1 = None
            for attempt in range(1, self.max_retries + 1):
                try:
                    raw1 = await self.service.call_operation(operation="Get_Workers", **first_payload, **kwargs)
                    break
                except Exception as exc:
                    self._logger.warning(
                        f"[Get_Workers] Error on first page "
                        f"(attempt {attempt}/{self.max_retries}): {exc}"
                    )
                    if attempt == self.max_retries:
                        self._logger.error(
                            f"[Get_Workers] Failed first page after "
                            f"{self.max_retries} attempts."
                        )
                        raise
                    await asyncio.sleep(self.retry_delay)

            data1 = self.service.serialize_object(raw1)
            # Free SOAP response object immediately to prevent memory leak
            del raw1
            gc.collect()

            page1 = data1.get("Response_Data", {}).get("Worker", [])
            if isinstance(page1, dict):
                page1 = [page1]
            
            # Extract pagination info from Response_Results
            response_results = data1.get("Response_Results", {})
            total_pages = int(float(response_results.get("Total_Pages", 1)))
            total_results = int(float(response_results.get("Total_Results", 0)))
            page_results = int(float(response_results.get("Page_Results", 0)))
            
            # Store for metrics
            pagination_info["total_results"] = total_results
            pagination_info["total_pages"] = total_pages
            
            # Log pagination summary
            self._logger.info(
                f"📊 Workday Pagination Info: Total Workers={total_results}, "
                f"Total Pages={total_pages}, Workers per Page={page_results}"
            )
            self._logger.info(f"📄 Page 1/{total_pages} fetched: {len(page1)} workers")

            all_workers: List[dict] = list(page1)

            # 2) If more pages, batch them so we never exceed max_parallel
            max_parallel = 10
            if total_pages > 1:
                pages = list(range(2, total_pages + 1))
                # calculate how many batches we need
                num_batches = math.ceil(len(pages) / max_parallel)
                batches = self.service.split_parts(pages, num_parts=num_batches)

                for batch in batches:
                    self._logger.info(f"🔄 Processing batch of {len(batch)} pages: {batch}")
                    tasks = [self._fetch_page(p, kwargs) for p in batch]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for res in results:
                        if isinstance(res, Exception):
                            self._logger.error(f"❌ Error fetching page: {res}")
                        else:
                            all_workers.extend(res)

                    # Free memory after processing each batch
                    del results
                    del tasks
                    gc.collect()

                    # Log progress after each batch
                    self._logger.info(
                        f"✅ Progress: {len(all_workers)}/{total_results} workers fetched "
                        f"({len(all_workers)/total_results*100:.1f}%)"
                    )

            workers_raw = all_workers
            
            # Final summary log
            self._logger.info(
                f"✨ Completed fetching all pages: {len(workers_raw)} workers retrieved "
                f"(Expected: {total_results})"
            )

        # 3) Parse into Pydantic models
        parsed: List[Worker] = []
        for w in workers_raw:
            wd = w.get("Worker_Data", {}) or {}
            
            # Try position management chain first (has manager names), fallback to worker management chain
            position_chain_data = parse_position_management_chain_data(wd)
            worker_chain_data = parse_management_chain_data(wd)
            
            # Use position chain data if it has data, otherwise use worker chain data
            management_chain_data = position_chain_data if position_chain_data.get("management_chain") else worker_chain_data
            
            # Parse payroll and tax data
            payroll_data = parse_payroll_and_tax_data(wd)

            # Parse position organizations
            position_orgs_data = parse_position_organizations(wd)

            # Parse international assignment data
            intl_assignment_data = parse_international_assignment_data(wd)

            # If we have management chain data and last_detected_manager_id but no name, try to find it in the chain
            if (management_chain_data.get("management_chain") and 
                payroll_data.get("last_detected_manager_id") and 
                not payroll_data.get("last_detected_manager_name")):
                
                last_detected_manager_id = payroll_data["last_detected_manager_id"]
                
                # Look for the manager in the management chain
                for level in management_chain_data["management_chain"]:
                    if level.get("manager_id") == last_detected_manager_id:
                        payroll_data["last_detected_manager_name"] = level.get("manager_name")
                        break
            
            # NEW: If no last_detected_manager found, use the LAST manager from management chain
            if (not payroll_data.get("last_detected_manager_id") and 
                management_chain_data.get("management_chain")):
                
                # Get the last (highest level) manager from the chain
                management_chain = management_chain_data["management_chain"]
                if management_chain:
                    last_manager = management_chain[-1]  # Last item in the list
                    if last_manager.get("manager_id") and last_manager.get("manager_name"):
                        payroll_data["last_detected_manager_id"] = last_manager.get("manager_id")
                        payroll_data["last_detected_manager_name"] = last_manager.get("manager_name")
            
            # Extract worker_wid using multiple methods
            # 1. First try from Request_References (for single worker requests)
            worker_wid = w.get("_extracted_wid")

            # 2. If not found, try parsing from Worker_Reference (fallback)
            if worker_wid is None:
                worker_ref_data = parse_worker_reference(w)
                worker_wid = worker_ref_data.get("worker_wid")

            # Extract worker_id for organizing saved documents
            current_worker_id = wd.get("Worker_ID")

            record = {
                "worker_id": current_worker_id,
                "worker_wid": worker_wid,
                "user_id": wd.get("User_ID"),
                **parse_personal_data(wd),
                **parse_contact_data(wd),
                **parse_worker_organization_data(wd),
                **parse_compensation_data(wd),
                **parse_identification_data(wd),
                **parse_benefits_and_roles(wd, current_worker_id, document_directory),
                **parse_employment_data(wd),
                **parse_worker_status(wd),
                **parse_business_site(wd),
                **management_chain_data,
                **payroll_data,
                **position_orgs_data,
                **intl_assignment_data,
                # Don't store raw_data to prevent 4.6GB memory leak
                # raw_data defaults to None in the model
            }
            parsed.append(Worker(**record))

        # 4) Build DataFrame and serialize complex columns
        df = pd.DataFrame([w.model_dump() for w in parsed])
        for col in [
            "emails",
            "roles",
            "worker_documents",
            "worker_documents_details",
            "benefit_enrollments",
            "custom_ids",
            "compensation_guidelines",
            "compensation_summary",
            "salary_and_hourly",
            "reason_references",
            "custom_id_shared_references",
            "management_chain",
            "matrix_management_chain",
            "organizations",
            "position_organizations",
            "job_classifications",
            "job_family",
        ]:
            if col in df.columns:
                df[col] = df[col].apply(safe_serialize)

        # 5) Metrics
        self.service.add_metric("NUM_WORKERS", len(parsed))
        
        # Add expected vs actual metrics for bulk requests
        if not worker_id and pagination_info["total_results"] is not None:
            self.service.add_metric("EXPECTED_WORKERS", pagination_info["total_results"])
            self.service.add_metric("TOTAL_PAGES", pagination_info["total_pages"])
            if len(parsed) != pagination_info["total_results"]:
                self._logger.warning(
                    f"⚠️  Mismatch: Expected {pagination_info['total_results']} workers "
                    f"but got {len(parsed)}"
                )
        
        return df

    async def _fetch_page(self, page_num: int, base_kwargs: dict) -> List[dict]:
        """
        Fetch a single page of Get_Workers. Returns list of worker dicts.
        """
        self._logger.debug(f"📄 Starting fetch for page {page_num}")
        
        # Build payload preserving Response_Filter settings like As_Of_Effective_Date
        payload = {
            **self.request_payload,
            "Response_Filter": {
                **self.request_payload.get("Response_Filter", {}),
                "Page": page_num, 
                "Count": 100
            },
        }
        
        # Log what we're sending for this page
        if page_num == 2:  # Log only for page 2 to avoid spam
            self._logger.info(f"🔍 Page {page_num} payload Response_Filter: {payload.get('Response_Filter')}")
        
        # Use the retry mechanism from base class with exponential backoff
        raw = None
        for attempt in range(1, self.max_retries + 1):
            try:
                raw = await self.service.call_operation(operation="Get_Workers", **payload, **base_kwargs)
                break
            except Exception as exc:
                self._logger.warning(
                    f"[Get_Workers] Error on page {page_num} "
                    f"(attempt {attempt}/{self.max_retries}): {exc}"
                )
                if attempt == self.max_retries:
                    self._logger.error(
                        f"[Get_Workers] Failed page {page_num} after "
                        f"{self.max_retries} attempts."
                    )
                    raise
                # Use exponential backoff: 0.5s, 1s, 2s, 4s, 8s
                delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                await asyncio.sleep(delay)


        data = self.service.serialize_object(raw)
        # Free SOAP response object immediately to prevent memory leak
        del raw
        gc.collect()

        items = data.get("Response_Data", {}).get("Worker", [])
        if isinstance(items, dict):
            items = [items]

        workers_count = len(items) if items else 0
        self._logger.debug(f"✅ Page {page_num} completed: {workers_count} workers fetched")

        return items or []
