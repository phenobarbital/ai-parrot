import asyncio
import math
from typing import List
import pandas as pd

from .base import WorkdayTypeBase
from ..models.job_requisition import JobRequisition
from ..parsers.job_requisition_parsers import parse_job_requisition_data


class JobRequisitionType(WorkdayTypeBase):
    """Handler for the Workday Get_Job_Requisitions operation."""

    def _get_default_payload(self) -> dict:
        """
        Payload base específico para job requisitions.
        """
        return {
            "Response_Filter": {},
            "Response_Group": {
                "Include_Reference": True,
                "Include_Job_Requisition_Definition_Data": True,
                "Include_Job_Requisition_Restrictions_Data": True,
                "Include_Qualifications": True,
                "Include_Job_Requisition_Attachments": False,
                "Include_Organizations": True,
                "Include_Roles": True,
            },
        }

    async def execute(self, **kwargs) -> pd.DataFrame:
        """
        Execute the Get_Job_Requisitions operation and return a pandas DataFrame.

        Supported parameters:
        - job_requisition_id: Specific job requisition ID to fetch (uses Request_References)
        - job_requisition_id_type: Type of job requisition ID (WID, Job_Requisition_ID, etc.)
        - job_requisition_status: Filter by status (e.g., "Open", "Filled", "Closed")
        - supervisory_organization_id: Filter by supervisory organization
        - location_id: Filter by location
        - updated_from_date: Filter by updates from this date
        - updated_to_date: Filter by updates to this date
        """
        # Extract parameters
        job_requisition_id = kwargs.pop("job_requisition_id", None)
        job_requisition_id_type = kwargs.pop("job_requisition_id_type", "Job_Requisition_ID")
        job_requisition_status = kwargs.pop("job_requisition_status", None)
        supervisory_organization_id = kwargs.pop("supervisory_organization_id", None)
        location_id = kwargs.pop("location_id", None)
        updated_from_date = kwargs.pop("updated_from_date", None)
        updated_to_date = kwargs.pop("updated_to_date", None)

        # Build request payload
        payload = {**self.request_payload}

        # Add Request_References for specific job requisition
        if job_requisition_id:
            payload["Request_References"] = {
                "Job_Requisition_Reference": [
                    {
                        "ID": [
                            {
                                "type": job_requisition_id_type,
                                "_value_1": job_requisition_id
                            }
                        ]
                    }
                ]
            }

        # Add Request_Criteria for filtering
        criteria = {}

        # Status filter
        if job_requisition_status:
            criteria["Job_Requisition_Status_Reference"] = {
                "ID": [
                    {
                        "type": "Job_Requisition_Status_ID",
                        "_value_1": job_requisition_status
                    }
                ]
            }

        # Organization filter
        if supervisory_organization_id:
            criteria["Supervisory_Organization_Reference"] = {
                "ID": [
                    {
                        "type": "Organization_Reference_ID",
                        "_value_1": supervisory_organization_id
                    }
                ]
            }

        # Location filter
        if location_id:
            criteria["Location_Reference"] = {
                "ID": [
                    {
                        "type": "Location_ID",
                        "_value_1": location_id
                    }
                ]
            }

        # Date filters
        if updated_from_date or updated_to_date:
            transaction_log = {}
            if updated_from_date:
                transaction_log["Transaction_Date_Range_Start"] = updated_from_date
            if updated_to_date:
                transaction_log["Transaction_Date_Range_End"] = updated_to_date
            criteria["Transaction_Log_Criteria_Data"] = [transaction_log]

        if criteria:
            payload["Request_Criteria"] = criteria

        try:
            # If fetching a specific job requisition, just fetch it directly
            if job_requisition_id:
                self._logger.info(f"Fetching specific job requisition: {job_requisition_id}")

                # Execute the SOAP call with retry logic
                response = None
                for attempt in range(1, self.max_retries + 1):
                    try:
                        response = await self.service.call_operation(
                            operation="Get_Job_Requisitions",
                            **payload
                        )
                        self._logger.info(f"✅ Successfully fetched job requisition {job_requisition_id}")
                        break
                    except Exception as exc:
                        self._logger.warning(
                            f"[Get_Job_Requisitions] Error fetching job requisition {job_requisition_id} "
                            f"(attempt {attempt}/{self.max_retries}): {exc}"
                        )
                        if attempt == self.max_retries:
                            self._logger.error(
                                f"[Get_Job_Requisitions] Failed to fetch job requisition {job_requisition_id} after "
                                f"{self.max_retries} attempts."
                            )
                            raise
                        delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                        self._logger.info(f"⏳ Waiting {delay:.1f}s before retry...")
                        await asyncio.sleep(delay)

                serialized = self.service.serialize_object(response)
                response_data = serialized.get("Response_Data", {})

                # Extract Job_Requisition elements
                if "Job_Requisition" in response_data:
                    job_requisition_data = response_data["Job_Requisition"]
                    job_requisitions_raw = [job_requisition_data] if isinstance(job_requisition_data, dict) else job_requisition_data
                else:
                    job_requisitions_raw = []

                self._logger.info(f"Retrieved {len(job_requisitions_raw)} job requisition(s)")

            else:
                # For all job requisitions, use pagination
                self._logger.info("🔍 Fetching first page to determine total job requisitions and pages...")

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
                        raw1 = await self.service.call_operation(operation="Get_Job_Requisitions", **first_payload)
                        self._logger.info("✅ Successfully fetched first page")
                        break
                    except Exception as exc:
                        self._logger.warning(
                            f"[Get_Job_Requisitions] Error on first page "
                            f"(attempt {attempt}/{self.max_retries}): {exc}"
                        )
                        if attempt == self.max_retries:
                            self._logger.error(
                                f"[Get_Job_Requisitions] Failed first page after "
                                f"{self.max_retries} attempts."
                            )
                            raise
                        # Use exponential backoff: 0.5s, 1.0s, 2.0s, 4.0s, 8.0s
                        delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                        self._logger.info(f"⏳ Waiting {delay:.1f}s before retry...")
                        await asyncio.sleep(delay)

                data1 = self.service.serialize_object(raw1)

                # Extract job requisitions from first page
                page1 = data1.get("Response_Data", {}).get("Job_Requisition", [])
                if isinstance(page1, dict):
                    page1 = [page1]

                # Extract pagination info from Response_Results
                response_results = data1.get("Response_Results", {})
                total_pages = int(float(response_results.get("Total_Pages", 1)))
                total_results = int(float(response_results.get("Total_Results", 0)))
                page_results = int(float(response_results.get("Page_Results", 0)))

                # Log pagination summary
                self._logger.info(
                    f"📊 Workday Pagination Info: Total Job Requisitions={total_results}, "
                    f"Total Pages={total_pages}, Job Requisitions per Page={page_results}"
                )
                self._logger.info(f"📄 Page 1/{total_pages} fetched: {len(page1)} job requisitions")

                all_job_requisitions: List[dict] = list(page1)

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
                            self._fetch_job_requisition_page(page_num, payload)
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
                                all_job_requisitions.extend(result)
                                self._logger.debug(
                                    f"✅ Page {page_num} completed: {len(result)} job requisitions"
                                )

                        self._logger.info(
                            f"✅ Batch {batch_idx}/{num_batches} complete. "
                            f"Total job requisitions so far: {len(all_job_requisitions)}"
                        )

                job_requisitions_raw = all_job_requisitions
                self._logger.info(f"📦 Total job requisitions fetched: {len(job_requisitions_raw)}")

            # Process each job requisition
            job_requisitions_processed = []
            for i, jr in enumerate(job_requisitions_raw):
                try:
                    # Parse the job requisition data
                    parsed_jr = parse_job_requisition_data(jr)

                    # Create JobRequisition model instance for validation
                    job_requisition_model = JobRequisition(**parsed_jr)

                    # Convert to dict for DataFrame
                    job_requisitions_processed.append(job_requisition_model.dict())

                except Exception as e:
                    self._logger.warning(f"⚠️ Error parsing job requisition {i}: {e}")
                    self._logger.debug("Traceback: ", exc_info=True)
                    continue

            # Convert to DataFrame
            if job_requisitions_processed:
                df = pd.DataFrame(job_requisitions_processed)

                # Log DataFrame info
                self._logger.info(f"✅ Created DataFrame with {len(df)} rows and {len(df.columns)} columns")
                self._logger.debug(f"DataFrame columns: {list(df.columns)}")

                return df
            else:
                self._logger.warning("No job requisitions found or processed successfully")
                # Return empty DataFrame with expected columns
                return pd.DataFrame(columns=[
                    'job_requisition_id', 'job_requisition_wid', 'job_requisition_name',
                    'job_requisition_status', 'job_posting_title', 'job_description',
                    'number_of_openings', 'positions_allocated', 'positions_filled', 'positions_available',
                    'recruiting_start_date', 'target_hire_date', 'job_profile_name',
                    'worker_type_name', 'location_name', 'supervisory_organization_name'
                ])

        except Exception as e:
            self._logger.error(f"Error in Get_Job_Requisitions operation: {e}")
            self._logger.error("Traceback: ", exc_info=True)
            raise

    async def _fetch_job_requisition_page(self, page_num: int, base_payload: dict) -> List[dict]:
        """
        Fetch a single page of Get_Job_Requisitions. Returns list of job requisition dicts.
        Similar to cost_centers.py _fetch_cost_center_page method.
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
                raw = await self.service.call_operation(operation="Get_Job_Requisitions", **payload)
                break
            except Exception as exc:
                self._logger.warning(
                    f"[Get_Job_Requisitions] Error on page {page_num} "
                    f"(attempt {attempt}/{self.max_retries}): {exc}"
                )
                if attempt == self.max_retries:
                    self._logger.error(
                        f"[Get_Job_Requisitions] Failed page {page_num} after "
                        f"{self.max_retries} attempts."
                    )
                    raise
                # Use exponential backoff: 0.5s, 1.0s, 2.0s, 4.0s, 8.0s
                delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                await asyncio.sleep(delay)

        data = self.service.serialize_object(raw)
        items = data.get("Response_Data", {}).get("Job_Requisition", [])
        if isinstance(items, dict):
            items = [items]

        job_requisitions_count = len(items) if items else 0
        self._logger.debug(f"✅ Page {page_num} completed: {job_requisitions_count} job requisitions fetched")

        return items or []
