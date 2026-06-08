import asyncio
import math
from typing import List
import pandas as pd

from .base import WorkdayTypeBase
from ..models.job_posting import JobPosting
from ..parsers.job_posting_parsers import parse_job_posting_data


class JobPostingType(WorkdayTypeBase):
    """Handler for the Workday Get_Job_Postings operation."""

    def _get_default_payload(self) -> dict:
        """
        Payload base específico para job postings.
        """
        return {
            "Response_Filter": {},
            "Response_Group": {
                "Include_Reference": True,
                "Include_Job_Requisition_Restrictions_Data": True,
                "Include_Job_Requisition_Definition_Data": True,
                "Include_Qualifications": True,
                "Include_Job_Requisition_Attachments": False,
            },
        }

    async def execute(self, **kwargs) -> pd.DataFrame:
        """
        Execute the Get_Job_Postings operation and return a pandas DataFrame.

        Supported parameters:
        - job_posting_id: Specific job posting ID to fetch (uses Request_References)
        - job_posting_id_type: Type of job posting ID (WID, Job_Posting_ID, etc.)
        - job_requisition_id: Filter by job requisition
        - job_posting_site_id: Filter by posting site
        - posting_status: Filter by status (e.g., "Posted", "Removed")
        - posted_from_date: Filter by posting date from
        - posted_to_date: Filter by posting date to
        """
        # Extract parameters
        job_posting_id = kwargs.pop("job_posting_id", None)
        job_posting_id_type = kwargs.pop("job_posting_id_type", "Job_Posting_ID")
        job_requisition_id = kwargs.pop("job_requisition_id", None)
        job_posting_site_id = kwargs.pop("job_posting_site_id", None)
        posting_status = kwargs.pop("posting_status", None)
        posted_from_date = kwargs.pop("posted_from_date", None)
        posted_to_date = kwargs.pop("posted_to_date", None)

        # Build request payload
        payload = {**self.request_payload}

        # Add Request_References for specific job posting
        if job_posting_id:
            payload["Request_References"] = {
                "Job_Posting_Reference": [
                    {
                        "ID": [
                            {
                                "type": job_posting_id_type,
                                "_value_1": job_posting_id
                            }
                        ]
                    }
                ]
            }

        # Add Request_Criteria for filtering
        criteria = {}

        # Job Requisition filter
        if job_requisition_id:
            criteria["Job_Requisition_Reference"] = {
                "ID": [
                    {
                        "type": "Job_Requisition_ID",
                        "_value_1": job_requisition_id
                    }
                ]
            }

        # Job Posting Site filter
        if job_posting_site_id:
            criteria["Job_Posting_Site_Reference"] = {
                "ID": [
                    {
                        "type": "Job_Posting_Site_ID",
                        "_value_1": job_posting_site_id
                    }
                ]
            }

        # Status filter
        if posting_status:
            criteria["Job_Posting_Status_Reference"] = {
                "ID": [
                    {
                        "type": "Job_Posting_Status_ID",
                        "_value_1": posting_status
                    }
                ]
            }

        # Date filters
        if posted_from_date or posted_to_date:
            date_filter = {}
            if posted_from_date:
                date_filter["Posting_Date_From"] = posted_from_date
            if posted_to_date:
                date_filter["Posting_Date_To"] = posted_to_date
            criteria["Posting_Date_Range_Data"] = [date_filter]

        if criteria:
            payload["Request_Criteria"] = criteria

        try:
            # If fetching a specific job posting, just fetch it directly
            if job_posting_id:
                self._logger.info(f"Fetching specific job posting: {job_posting_id}")

                # Execute the SOAP call with retry logic
                response = None
                for attempt in range(1, self.max_retries + 1):
                    try:
                        response = await self.service.call_operation(
                            operation="Get_Job_Postings",
                            **payload
                        )
                        self._logger.info(f"✅ Successfully fetched job posting {job_posting_id}")
                        break
                    except Exception as exc:
                        self._logger.warning(
                            f"[Get_Job_Postings] Error fetching job posting {job_posting_id} "
                            f"(attempt {attempt}/{self.max_retries}): {exc}"
                        )
                        if attempt == self.max_retries:
                            self._logger.error(
                                f"[Get_Job_Postings] Failed to fetch job posting {job_posting_id} after "
                                f"{self.max_retries} attempts."
                            )
                            raise
                        delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                        self._logger.info(f"⏳ Waiting {delay:.1f}s before retry...")
                        await asyncio.sleep(delay)

                serialized = self.service.serialize_object(response)
                response_data = serialized.get("Response_Data", {})

                # Extract Job_Posting elements
                if "Job_Posting" in response_data:
                    job_posting_data = response_data["Job_Posting"]
                    job_postings_raw = [job_posting_data] if isinstance(job_posting_data, dict) else job_posting_data
                else:
                    job_postings_raw = []

                self._logger.info(f"Retrieved {len(job_postings_raw)} job posting(s)")

            else:
                # For all job postings, use pagination
                self._logger.info("🔍 Fetching first page to determine total job postings and pages...")

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
                        raw1 = await self.service.call_operation(operation="Get_Job_Postings", **first_payload)
                        self._logger.info("✅ Successfully fetched first page")
                        break
                    except Exception as exc:
                        self._logger.warning(
                            f"[Get_Job_Postings] Error on first page "
                            f"(attempt {attempt}/{self.max_retries}): {exc}"
                        )
                        if attempt == self.max_retries:
                            self._logger.error(
                                f"[Get_Job_Postings] Failed first page after "
                                f"{self.max_retries} attempts."
                            )
                            raise
                        delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                        self._logger.info(f"⏳ Waiting {delay:.1f}s before retry...")
                        await asyncio.sleep(delay)

                data1 = self.service.serialize_object(raw1)

                # Extract job postings from first page
                page1 = data1.get("Response_Data", {}).get("Job_Posting", [])
                if isinstance(page1, dict):
                    page1 = [page1]

                # Extract pagination info from Response_Results
                response_results = data1.get("Response_Results", {})
                total_pages = int(float(response_results.get("Total_Pages", 1)))
                total_results = int(float(response_results.get("Total_Results", 0)))
                page_results = int(float(response_results.get("Page_Results", 0)))

                # Log pagination summary
                self._logger.info(
                    f"📊 Workday Pagination Info: Total Job Postings={total_results}, "
                    f"Total Pages={total_pages}, Job Postings per Page={page_results}"
                )
                self._logger.info(f"📄 Page 1/{total_pages} fetched: {len(page1)} job postings")

                all_job_postings: List[dict] = list(page1)

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
                            self._fetch_job_posting_page(page_num, payload)
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
                                all_job_postings.extend(result)
                                self._logger.debug(
                                    f"✅ Page {page_num} completed: {len(result)} job postings"
                                )

                        self._logger.info(
                            f"✅ Batch {batch_idx}/{num_batches} complete. "
                            f"Total job postings so far: {len(all_job_postings)}"
                        )

                job_postings_raw = all_job_postings
                self._logger.info(f"📦 Total job postings fetched: {len(job_postings_raw)}")

            # Process each job posting
            job_postings_processed = []
            for i, jp in enumerate(job_postings_raw):
                try:
                    # Parse the job posting data
                    parsed_jp = parse_job_posting_data(jp)

                    # Create JobPosting model instance for validation
                    job_posting_model = JobPosting(**parsed_jp)

                    # Convert to dict for DataFrame
                    job_postings_processed.append(job_posting_model.dict())

                except Exception as e:
                    self._logger.warning(f"⚠️ Error parsing job posting {i}: {e}")
                    self._logger.debug("Traceback: ", exc_info=True)
                    continue

            # Convert to DataFrame
            if job_postings_processed:
                df = pd.DataFrame(job_postings_processed)

                # Log DataFrame info
                self._logger.info(f"✅ Created DataFrame with {len(df)} rows and {len(df.columns)} columns")
                self._logger.debug(f"DataFrame columns: {list(df.columns)}")

                return df
            else:
                self._logger.warning("No job postings found or processed successfully")
                # Return empty DataFrame with expected columns
                return pd.DataFrame(columns=[
                    'job_posting_id', 'job_posting_wid', 'job_posting_name',
                    'job_requisition_id', 'job_posting_status', 'job_posting_title',
                    'posting_date', 'removal_date', 'external_url', 'location_name',
                    'job_posting_sites', 'is_posted'
                ])

        except Exception as e:
            self._logger.error(f"Error in Get_Job_Postings operation: {e}")
            self._logger.error("Traceback: ", exc_info=True)
            raise

    async def _fetch_job_posting_page(self, page_num: int, base_payload: dict) -> List[dict]:
        """
        Fetch a single page of Get_Job_Postings. Returns list of job posting dicts.
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
                raw = await self.service.call_operation(operation="Get_Job_Postings", **payload)
                break
            except Exception as exc:
                self._logger.warning(
                    f"[Get_Job_Postings] Error on page {page_num} "
                    f"(attempt {attempt}/{self.max_retries}): {exc}"
                )
                if attempt == self.max_retries:
                    self._logger.error(
                        f"[Get_Job_Postings] Failed page {page_num} after "
                        f"{self.max_retries} attempts."
                    )
                    raise
                delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                await asyncio.sleep(delay)

        data = self.service.serialize_object(raw)
        items = data.get("Response_Data", {}).get("Job_Posting", [])
        if isinstance(items, dict):
            items = [items]

        job_postings_count = len(items) if items else 0
        self._logger.debug(f"✅ Page {page_num} completed: {job_postings_count} job postings fetched")

        return items or []
