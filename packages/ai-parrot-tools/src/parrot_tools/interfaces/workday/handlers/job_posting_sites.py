import asyncio
import math
from typing import List
import pandas as pd

from .base import WorkdayTypeBase
from ..models.job_posting_site import JobPostingSite
from ..parsers.job_posting_site_parsers import parse_job_posting_site_data


class JobPostingSiteType(WorkdayTypeBase):
    """Handler for the Workday Get_Job_Posting_Sites operation."""

    def _get_default_payload(self) -> dict:
        """
        Payload base específico para job posting sites.
        """
        return {
            "Response_Filter": {},
            "Response_Group": {
                "Include_Reference": True,
            },
        }

    async def execute(self, **kwargs) -> pd.DataFrame:
        """
        Execute the Get_Job_Posting_Sites operation and return a pandas DataFrame.

        Supported parameters:
        - job_posting_site_id: Specific job posting site ID to fetch (uses Request_References)
        - job_posting_site_id_type: Type of job posting site ID (WID, Job_Posting_Site_ID, etc.)
        - is_active: Filter by active status
        """
        # Extract parameters
        job_posting_site_id = kwargs.pop("job_posting_site_id", None)
        job_posting_site_id_type = kwargs.pop("job_posting_site_id_type", "Job_Posting_Site_ID")
        is_active = kwargs.pop("is_active", None)

        # Build request payload
        payload = {**self.request_payload}

        # Add Request_References for specific job posting site
        if job_posting_site_id:
            payload["Request_References"] = {
                "Job_Posting_Site_Reference": [
                    {
                        "ID": [
                            {
                                "type": job_posting_site_id_type,
                                "_value_1": job_posting_site_id
                            }
                        ]
                    }
                ]
            }

        # Add Request_Criteria for filtering
        criteria = {}

        # Active status filter
        if is_active is not None:
            criteria["Is_Active"] = is_active

        if criteria:
            payload["Request_Criteria"] = criteria

        try:
            # If fetching a specific job posting site, just fetch it directly
            if job_posting_site_id:
                self._logger.info(f"Fetching specific job posting site: {job_posting_site_id}")

                # Execute the SOAP call with retry logic
                response = None
                for attempt in range(1, self.max_retries + 1):
                    try:
                        response = await self.service.call_operation(
                            operation="Get_Job_Posting_Sites",
                            **payload
                        )
                        self._logger.info(f"✅ Successfully fetched job posting site {job_posting_site_id}")
                        break
                    except Exception as exc:
                        self._logger.warning(
                            f"[Get_Job_Posting_Sites] Error fetching job posting site {job_posting_site_id} "
                            f"(attempt {attempt}/{self.max_retries}): {exc}"
                        )
                        if attempt == self.max_retries:
                            self._logger.error(
                                f"[Get_Job_Posting_Sites] Failed to fetch job posting site {job_posting_site_id} after "
                                f"{self.max_retries} attempts."
                            )
                            raise
                        delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                        self._logger.info(f"⏳ Waiting {delay:.1f}s before retry...")
                        await asyncio.sleep(delay)

                serialized = self.service.serialize_object(response)
                response_data = serialized.get("Response_Data", {})

                # Extract Job_Posting_Site elements
                if "Job_Posting_Site" in response_data:
                    job_posting_site_data = response_data["Job_Posting_Site"]
                    job_posting_sites_raw = [job_posting_site_data] if isinstance(job_posting_site_data, dict) else job_posting_site_data
                else:
                    job_posting_sites_raw = []

                self._logger.info(f"Retrieved {len(job_posting_sites_raw)} job posting site(s)")

            else:
                # For all job posting sites, use pagination
                self._logger.info("🔍 Fetching first page to determine total job posting sites and pages...")

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
                        raw1 = await self.service.call_operation(operation="Get_Job_Posting_Sites", **first_payload)
                        self._logger.info("✅ Successfully fetched first page")
                        break
                    except Exception as exc:
                        self._logger.warning(
                            f"[Get_Job_Posting_Sites] Error on first page "
                            f"(attempt {attempt}/{self.max_retries}): {exc}"
                        )
                        if attempt == self.max_retries:
                            self._logger.error(
                                f"[Get_Job_Posting_Sites] Failed first page after "
                                f"{self.max_retries} attempts."
                            )
                            raise
                        delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                        self._logger.info(f"⏳ Waiting {delay:.1f}s before retry...")
                        await asyncio.sleep(delay)

                data1 = self.service.serialize_object(raw1)

                # Extract job posting sites from first page
                page1 = data1.get("Response_Data", {}).get("Job_Posting_Site", [])
                if isinstance(page1, dict):
                    page1 = [page1]

                # Extract pagination info from Response_Results
                response_results = data1.get("Response_Results", {})
                total_pages = int(float(response_results.get("Total_Pages", 1)))
                total_results = int(float(response_results.get("Total_Results", 0)))
                page_results = int(float(response_results.get("Page_Results", 0)))

                # Log pagination summary
                self._logger.info(
                    f"📊 Workday Pagination Info: Total Job Posting Sites={total_results}, "
                    f"Total Pages={total_pages}, Job Posting Sites per Page={page_results}"
                )
                self._logger.info(f"📄 Page 1/{total_pages} fetched: {len(page1)} job posting sites")

                all_job_posting_sites: List[dict] = list(page1)

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
                            self._fetch_job_posting_site_page(page_num, payload)
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
                                all_job_posting_sites.extend(result)
                                self._logger.debug(
                                    f"✅ Page {page_num} completed: {len(result)} job posting sites"
                                )

                        self._logger.info(
                            f"✅ Batch {batch_idx}/{num_batches} complete. "
                            f"Total job posting sites so far: {len(all_job_posting_sites)}"
                        )

                job_posting_sites_raw = all_job_posting_sites
                self._logger.info(f"📦 Total job posting sites fetched: {len(job_posting_sites_raw)}")

            # Process each job posting site
            job_posting_sites_processed = []
            for i, site in enumerate(job_posting_sites_raw):
                try:
                    # Parse the job posting site data
                    parsed_site = parse_job_posting_site_data(site)

                    # Create JobPostingSite model instance for validation
                    job_posting_site_model = JobPostingSite(**parsed_site)

                    # Convert to dict for DataFrame
                    job_posting_sites_processed.append(job_posting_site_model.dict())

                except Exception as e:
                    self._logger.warning(f"⚠️ Error parsing job posting site {i}: {e}")
                    self._logger.debug("Traceback: ", exc_info=True)
                    continue

            # Convert to DataFrame
            if job_posting_sites_processed:
                df = pd.DataFrame(job_posting_sites_processed)

                # Log DataFrame info
                self._logger.info(f"✅ Created DataFrame with {len(df)} rows and {len(df.columns)} columns")
                self._logger.debug(f"DataFrame columns: {list(df.columns)}")

                return df
            else:
                self._logger.warning("No job posting sites found or processed successfully")
                # Return empty DataFrame with expected columns
                return pd.DataFrame(columns=[
                    'job_posting_site_id', 'job_posting_site_wid', 'job_posting_site_name',
                    'site_type', 'external_url', 'is_active', 'is_internal', 'is_external',
                    'display_order', 'description'
                ])

        except Exception as e:
            self._logger.error(f"Error in Get_Job_Posting_Sites operation: {e}")
            self._logger.error("Traceback: ", exc_info=True)
            raise

    async def _fetch_job_posting_site_page(self, page_num: int, base_payload: dict) -> List[dict]:
        """
        Fetch a single page of Get_Job_Posting_Sites. Returns list of job posting site dicts.
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
                raw = await self.service.call_operation(operation="Get_Job_Posting_Sites", **payload)
                break
            except Exception as exc:
                self._logger.warning(
                    f"[Get_Job_Posting_Sites] Error on page {page_num} "
                    f"(attempt {attempt}/{self.max_retries}): {exc}"
                )
                if attempt == self.max_retries:
                    self._logger.error(
                        f"[Get_Job_Posting_Sites] Failed page {page_num} after "
                        f"{self.max_retries} attempts."
                    )
                    raise
                delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                await asyncio.sleep(delay)

        data = self.service.serialize_object(raw)
        items = data.get("Response_Data", {}).get("Job_Posting_Site", [])
        if isinstance(items, dict):
            items = [items]

        job_posting_sites_count = len(items) if items else 0
        self._logger.debug(f"✅ Page {page_num} completed: {job_posting_sites_count} job posting sites fetched")

        return items or []
