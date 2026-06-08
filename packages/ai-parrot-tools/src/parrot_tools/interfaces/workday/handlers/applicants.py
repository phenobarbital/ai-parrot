from typing import Dict, Any, List
import asyncio
import math
import pandas as pd

from ..models.applicant import Applicant
from ..parsers.applicant_parsers import (
    parse_applicant_reference,
    parse_applicant_personal_data,
    parse_applicant_contact_data,
    parse_applicant_recruitment_data,
    parse_applicant_organization_data,
    parse_applicant_education_data,
    parse_applicant_experience_data,
    parse_applicant_skills_data,
    parse_applicant_identification_data,
    parse_applicant_background_check_data,
    parse_applicant_document_data
)
from ..utils import safe_serialize
from .base import WorkdayTypeBase


class ApplicantType(WorkdayTypeBase):
    """
    Handler for the Workday Get_Applicants operation from Recruiting API.
    
    Based on Workday Recruiting API v44.2:
    https://community.workday.com/sites/default/files/file-hosting/productionapi/Recruiting/v44.2/Get_Applicants.html
    
    Returns information for pre-hires/applicants. This is used to get candidates
    that have not been converted to Workers yet (pre-hires with future hire dates).
    """
    
    def _get_default_payload(self) -> Dict[str, Any]:
        """
        Default payload for Get_Applicants operation.
        
        Get_Applicants returns all pre-hires (applicants) by default.
        Note: "pre-hire" was previously called "applicant" in Workday terminology.
        """
        return {
            "Response_Filter": {},
            "Response_Group": {
                "Include_Reference": True,
                "Include_Personal_Information": True,
                #"Show_All_Personal_Information": True,
                "Include_Recruiting_Information": True,
                "Include_Qualification_Profile": True,
                "Include_Resume": True,
                "Include_Background_Check": True,
                "Include_External_Integration_ID_Data": True,
            },
        }
    
    async def execute(self, **kwargs) -> pd.DataFrame:
        """
        Execute the Get_Applicants operation and return a pandas DataFrame.
        
        Args:
            applicant_id: Optional specific applicant ID to fetch
            job_requisition_id: Optional filter by job requisition
            application_date_from: Optional filter by application date from
            application_date_to: Optional filter by application date to
            is_pre_hire: Optional filter for pre-hire status
        """
        # Extract parameters from kwargs
        applicant_id = kwargs.pop("applicant_id", None)
        job_requisition_id = kwargs.pop("job_requisition_id", None)
        application_date_from = kwargs.pop("application_date_from", None)
        application_date_to = kwargs.pop("application_date_to", None)
        is_pre_hire = kwargs.pop("is_pre_hire", None)
        
        payload = {**self.request_payload}
        
        # Build request based on provided parameters
        if applicant_id:
            # Use Request_References for specific applicant ID
            payload["Request_References"] = {
                "Applicant_Reference": [
                    {
                        "ID": [
                            {
                                "_value_1": applicant_id,
                                "type": "Applicant_ID"
                            }
                        ]
                    }
                ]
            }
            self._logger.info(f"Fetching specific applicant: {applicant_id}")
        else:
            # Use Request_Criteria for filtering
            criteria = {}
            
            # Job Requisition filter
            if job_requisition_id:
                criteria["Job_Requisition_Reference"] = [
                    {
                        "ID": [
                            {
                                "_value_1": job_requisition_id,
                                "type": "Job_Requisition_ID"
                            }
                        ]
                    }
                ]
            
            # Application date range
            if application_date_from:
                criteria["Applied_From_Date"] = application_date_from
            if application_date_to:
                criteria["Applied_To_Date"] = application_date_to
            
            # Pre-hire filter
            if is_pre_hire is not None:
                criteria["Include_Pre-Hires_Only"] = is_pre_hire
            
            if criteria:
                payload["Request_Criteria"] = criteria
            
            self._logger.info("Fetching all applicants/pre-hires")
        
        # Execute the operation with pagination (similar to workers.py)
        try:
            # 1) Fetch page 1 to get total_pages
            if applicant_id:
                # For specific applicant, no pagination needed
                self._logger.info(f"Executing Get_Applicants for specific applicant: {applicant_id}")
                
                response = await self.service.call_operation(
                    operation="Get_Applicants",
                    **payload
                )
                
                serialized = self.service.serialize_object(response)
                response_data = serialized.get("Response_Data", {})
                
                # Extract Applicant elements
                if "Applicant" in response_data:
                    applicant_data = response_data["Applicant"]
                    applicants_raw = [applicant_data] if isinstance(applicant_data, dict) else applicant_data
                else:
                    applicants_raw = []
                
                self._logger.info(f"Retrieved {len(applicants_raw)} applicant(s)")
                
            else:
                # For all applicants, use pagination
                self._logger.info("🔍 Fetching first page to determine total applicants and pages...")
                
                # Build first page payload
                first_payload = {
                    **payload,
                    "Response_Filter": {
                        **payload.get("Response_Filter", {}),
                        "Page": 1,
                        "Count": 100
                    }
                }
                
                # Fetch first page
                raw1 = await self.service.call_operation(operation="Get_Applicants", **first_payload)
                data1 = self.service.serialize_object(raw1)
                
                # Extract applicants from first page
                page1 = data1.get("Response_Data", {}).get("Applicant", [])
                if isinstance(page1, dict):
                    page1 = [page1]
                
                # Extract pagination info from Response_Results
                response_results = data1.get("Response_Results", {})
                total_pages = int(float(response_results.get("Total_Pages", 1)))
                total_results = int(float(response_results.get("Total_Results", 0)))
                page_results = int(float(response_results.get("Page_Results", 0)))
                
                # Log pagination summary
                self._logger.info(
                    f"📊 Workday Pagination Info: Total Applicants={total_results}, "
                    f"Total Pages={total_pages}, Applicants per Page={page_results}"
                )
                self._logger.info(f"📄 Page 1/{total_pages} fetched: {len(page1)} applicants")
                
                all_applicants: List[dict] = list(page1)
                
                # 2) If more pages, batch them (max 10 parallel requests)
                max_parallel = 10
                if total_pages > 1:
                    pages = list(range(2, total_pages + 1))
                    num_batches = math.ceil(len(pages) / max_parallel)
                    batches = self.service.split_parts(pages, num_parts=num_batches)
                    
                    for batch in batches:
                        self._logger.info(f"🔄 Processing batch of {len(batch)} pages: {batch}")
                        tasks = [self._fetch_applicant_page(p, payload) for p in batch]
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                        for res in results:
                            if isinstance(res, Exception):
                                self._logger.error(f"❌ Error fetching page: {res}")
                            else:
                                all_applicants.extend(res)
                        
                        # Log progress after each batch
                        self._logger.info(
                            f"✅ Progress: {len(all_applicants)}/{total_results} applicants fetched "
                            f"({len(all_applicants)/total_results*100:.1f}%)"
                        )
                
                applicants_raw = all_applicants
                
                # Final summary log
                self._logger.info(
                    f"✨ Completed fetching all pages: {len(applicants_raw)} applicants retrieved "
                    f"(Expected: {total_results})"
                )
                
                # Add metrics
                self.service.add_metric("EXPECTED_APPLICANTS", total_results)
                self.service.add_metric("TOTAL_PAGES", total_pages)
                if len(applicants_raw) != total_results:
                    self._logger.warning(
                        f"⚠️  Mismatch: Expected {total_results} applicants but got {len(applicants_raw)}"
                    )
            
        except Exception as e:
            self._logger.error(f"Error fetching applicants: {e}")
            import traceback
            self._logger.error(f"Traceback: {traceback.format_exc()}")
            raise
        
        # Parse into Pydantic models
        parsed: List[Applicant] = []
        for applicant_raw in applicants_raw:
            try:
                # Extract applicant data from response
                applicant_data = applicant_raw.get("Applicant_Data", {}) if isinstance(applicant_raw, dict) else {}
                
                # Parse all data sections
                record = {
                    **parse_applicant_reference(applicant_raw),
                    **parse_applicant_personal_data(applicant_data),
                    **parse_applicant_contact_data(applicant_data),
                    **parse_applicant_recruitment_data(applicant_data),
                    **parse_applicant_organization_data(applicant_data),
                    **parse_applicant_education_data(applicant_data),
                    **parse_applicant_experience_data(applicant_data),
                    **parse_applicant_skills_data(applicant_data),
                    **parse_applicant_identification_data(applicant_data),
                    **parse_applicant_background_check_data(applicant_data),
                    **parse_applicant_document_data(applicant_data),
                    "raw_data": applicant_raw
                }
                
                parsed.append(Applicant(**record))
                
            except Exception as e:
                self._logger.warning(f"Error parsing applicant: {e}")
                import traceback
                self._logger.debug(f"Traceback: {traceback.format_exc()}")
                continue
        
        # Build DataFrame
        if parsed:
            df = pd.DataFrame([a.dict() for a in parsed])
            
            # Serialize complex columns
            complex_cols = [
                "emails", "phones", "schools", "previous_employers", 
                "skills", "competencies", "references", "documents",
                "custom_fields"
            ]
            for col in complex_cols:
                if col in df.columns:
                    df[col] = df[col].apply(safe_serialize)
            
            # Add metrics
            self.service.add_metric("NUM_APPLICANTS", len(parsed))
            self.service.add_metric("NUM_PRE_HIRES", len(df[df["is_pre_hire"]]) if "is_pre_hire" in df.columns else 0)
            
            self._logger.info(f"Successfully parsed {len(parsed)} applicants")
            
            return df
        else:
            self._logger.warning("No applicants found or processed successfully")
            # Return empty DataFrame with expected columns
            return pd.DataFrame(columns=[
                'applicant_id', 'applicant_wid', 'first_name', 'last_name', 
                'email', 'status', 'is_pre_hire', 'hire_date'
            ])
    
    async def _fetch_applicant_page(self, page_num: int, base_payload: dict) -> List[dict]:
        """
        Fetch a single page of Get_Applicants. Returns list of applicant dicts.
        Similar to workers.py _fetch_page method.
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
                raw = await self.service.call_operation(operation="Get_Applicants", **payload)
                break
            except Exception as exc:
                self._logger.warning(
                    f"[Get_Applicants] Error on page {page_num} "
                    f"(attempt {attempt}/{self.max_retries}): {exc}"
                )
                if attempt == self.max_retries:
                    self._logger.error(
                        f"[Get_Applicants] Failed page {page_num} after "
                        f"{self.max_retries} attempts."
                    )
                    raise
                # Use exponential backoff: 0.2s, 0.4s, 0.8s, 1.6s, 3.2s
                delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                await asyncio.sleep(delay)
        
        data = self.service.serialize_object(raw)
        items = data.get("Response_Data", {}).get("Applicant", [])
        if isinstance(items, dict):
            items = [items]
        
        applicants_count = len(items) if items else 0
        self._logger.debug(f"✅ Page {page_num} completed: {applicants_count} applicants fetched")
        
        return items or [] 