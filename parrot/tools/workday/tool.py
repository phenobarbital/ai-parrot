"""
Workday Toolkit - A unified toolkit for Workday SOAP operations with multi-service support.

This toolkit wraps common Workday operations across multiple services (Human Resources,
Absence Management, Time Tracking, Staffing, Financial Management, and Recruiting) as
async tools, extending AbstractToolkit and using SOAPClient for SOAP/WSDL handling.

Features:
    - Multi-service WSDL support with automatic client routing
    - OAuth2 authentication with refresh_token grant
    - Redis token caching for performance
    - Automatic tool generation from public async methods
    - Lazy client initialization for optimal resource usage

Dependencies:
    - zeep
    - httpx
    - redis
    - pydantic

Example usage:
    # Single service (Human Resources only)
    toolkit = WorkdayToolkit(
        credentials={
            "client_id": "your-client-id",
            "client_secret": "your-client-secret",
            "token_url": "https://wd2-impl.workday.com/ccx/oauth2/token",
            "wsdl_path": "https://wd2-impl.workday.com/ccx/service/tenant/Human_Resources/v44.2?wsdl",
            "refresh_token": "your-refresh-token"
        },
        tenant_name="your_tenant"
    )

    # Multiple services with explicit WSDL paths
    toolkit = WorkdayToolkit(
        credentials={
            "client_id": "your-client-id",
            "client_secret": "your-client-secret",
            "token_url": "https://wd2-impl.workday.com/ccx/oauth2/token",
            "refresh_token": "your-refresh-token"
        },
        tenant_name="your_tenant",
        wsdl_paths={
            "human_resources": "https://wd2-impl.workday.com/ccx/service/tenant/Human_Resources/v44.2?wsdl",
            "absence_management": "https://wd2-impl.workday.com/ccx/service/tenant/Absence_Management/v45?wsdl",
            "time_tracking": "https://wd2-impl.workday.com/ccx/service/tenant/Time_Tracking/v44.2?wsdl",
            "staffing": "https://wd2-impl.workday.com/ccx/service/tenant/Staffing/v44.2?wsdl",
            "financial_management": "https://wd2-impl.workday.com/ccx/service/tenant/Financial_Management/v45?wsdl",
            "recruiting": "https://wd2-impl.workday.com/ccx/service/tenant/Recruiting/v44.2?wsdl"
        }
    )

    # Initialize the connection
    await toolkit.wd_start()

    # Use methods - appropriate client is selected automatically
    worker = await toolkit.wd_get_worker(worker_id="12345")
    time_off = await toolkit.wd_get_time_off_balance(worker_id="12345")
"""
from __future__ import annotations

import asyncio
import contextlib
from enum import Enum
from typing import Any, Dict, List, Optional, Type, Union
from datetime import datetime
from pathlib import PurePath
from pydantic import BaseModel, Field
from zeep import helpers
from ..toolkit import AbstractToolkit
from ..decorators import tool_schema
from ...interfaces.soap import SOAPClient
from .models import (
    WorkdayReference,
    WorkerModel,
    OrganizationModel,
    WorkdayResponseParser
)
from ...conf import (
    WORKDAY_DEFAULT_TENANT,
    WORKDAY_CLIENT_ID,
    WORKDAY_CLIENT_SECRET,
    WORKDAY_TOKEN_URL,
    WORKDAY_WSDL_PATH,
    WORKDAY_REFRESH_TOKEN,
    WORKDAY_WSDL_PATHS
)

# -----------------------------
# Workday Service Types
# -----------------------------
class WorkdayService(str, Enum):
    """Enumeration of Workday SOAP service types."""
    HUMAN_RESOURCES = "human_resources"
    ABSENCE_MANAGEMENT = "absence_management"
    TIME_TRACKING = "time_tracking"
    STAFFING = "staffing"
    FINANCIAL_MANAGEMENT = "financial_management"
    RECRUITING = "recruiting"


# Mapping of toolkit methods to required Workday services
METHOD_TO_SERVICE_MAP = {
    # Human Resources service methods
    "wd_get_worker": WorkdayService.HUMAN_RESOURCES,
    "wd_search_workers": WorkdayService.HUMAN_RESOURCES,
    "wd_get_worker_contact": WorkdayService.HUMAN_RESOURCES,
    "wd_get_worker_job_data": WorkdayService.HUMAN_RESOURCES,
    "wd_get_organization": WorkdayService.HUMAN_RESOURCES,
    "wd_get_workers_by_organization": WorkdayService.HUMAN_RESOURCES,
    "wd_get_workers_by_ids": WorkdayService.HUMAN_RESOURCES,
    "wd_search_workers_by_name": WorkdayService.HUMAN_RESOURCES,
    "wd_get_workers_by_manager": WorkdayService.HUMAN_RESOURCES,
    "wd_get_inactive_workers": WorkdayService.HUMAN_RESOURCES,
    "wd_get_worker_time_off_balance": WorkdayService.HUMAN_RESOURCES,
    # Absence Management service methods
    "wd_get_time_off_balance": WorkdayService.ABSENCE_MANAGEMENT,
    # Time Tracking service methods (placeholder for future implementation)
    # "wd_get_time_entry": WorkdayService.TIME_TRACKING,
    # "wd_submit_timesheet": WorkdayService.TIME_TRACKING,

    # Staffing service methods (placeholder for future implementation)
    # "wd_get_position": WorkdayService.STAFFING,
    # "wd_create_position": WorkdayService.STAFFING,

    # Financial Management service methods (placeholder for future implementation)
    # "wd_get_spend_category": WorkdayService.FINANCIAL_MANAGEMENT,
    # "wd_get_worktags": WorkdayService.FINANCIAL_MANAGEMENT,

    # Recruiting service methods (placeholder for future implementation)
    # "wd_get_job_requisition": WorkdayService.RECRUITING,
    # "wd_get_candidates": WorkdayService.RECRUITING,
}


# -----------------------------
# Input models (schemas)
# -----------------------------
class WorkdayToolkitInput(BaseModel):
    """Default configuration for Workday toolkit operations."""

    tenant_name: str = Field(
        description="Workday tenant name (e.g., 'acme_impl', 'company_prod')"
    )
    include_reference: bool = Field(
        default=True,
        description="Include reference data in responses"
    )


class GetWorkerInput(BaseModel):
    """Input for retrieving a single worker by ID."""

    worker_id: str = Field(
        description="Worker ID (Employee ID, Contingent Worker ID, or WID)"
    )
    output_format: Optional[Type[BaseModel]] = Field(
        default=None,
        description="Optional Pydantic model to format the output"
    )


class SearchWorkersInput(BaseModel):
    """Input for searching workers with filters."""

    search_text: Optional[str] = Field(
        default=None,
        description="Text to search in worker names, emails, or IDs"
    )
    manager_id: Optional[str] = Field(
        default=None,
        description="Filter by manager's worker ID"
    )
    location_id: Optional[str] = Field(
        default=None,
        description="Filter by location ID"
    )
    job_profile_id: Optional[str] = Field(
        default=None,
        description="Filter by job profile ID"
    )
    hire_date_from: Optional[str] = Field(
        default=None,
        description="Filter by hire date (YYYY-MM-DD format) - from"
    )
    hire_date_to: Optional[str] = Field(
        default=None,
        description="Filter by hire date (YYYY-MM-DD format) - to"
    )
    max_results: int = Field(
        default=100,
        description="Maximum number of results to return"
    )


class GetWorkerContactInput(BaseModel):
    """Input for retrieving worker contact information."""

    worker_id: str = Field(
        description="Worker ID to get contact info for"
    )
    include_personal: bool = Field(
        default=True,
        description="Include personal contact information"
    )
    include_work: bool = Field(
        default=True,
        description="Include work contact information"
    )


class GetOrganizationInput(BaseModel):
    """Input for retrieving organization information."""

    org_id: str = Field(
        description="Organization ID or reference ID"
    )
    include_hierarchy: bool = Field(
        default=False,
        description="Include organizational hierarchy"
    )


class GetWorkerJobDataInput(BaseModel):
    """Input for retrieving worker's job-related data."""

    worker_id: str = Field(
        description="Worker ID to get job data for"
    )
    effective_date: Optional[str] = Field(
        default=None,
        description="Effective date for job data (YYYY-MM-DD). Defaults to today."
    )


class GetTimeOffBalanceInput(BaseModel):
    """Input for retrieving time off balance information."""

    worker_id: str = Field(
        description="Worker ID to get time off balance for"
    )
    time_off_plan_id: Optional[str] = Field(
        default=None,
        description="Optional specific time off plan ID to filter by"
    )
    output_format: Optional[Type[BaseModel]] = Field(
        default=None,
        description="Optional Pydantic model to format the output"
    )


# -----------------------------
# Workday SOAP Client
# -----------------------------
class WorkdaySOAPClient(SOAPClient):
    """
    Specialized SOAPClient for Workday operations.

    Handles Workday-specific SOAP envelope construction and response parsing.
    """

    def __init__(self, tenant_name: str, **kwargs):
        """
        Initialize Workday SOAP client.

        Args:
            tenant_name: Workday tenant identifier
            **kwargs: Additional arguments passed to SOAPClient
        """
        super().__init__(**kwargs)
        self.tenant_name = tenant_name

    def _build_worker_reference(self, worker_id: str, id_type: str = "Employee_ID") -> Dict[str, Any]:
        """
        Build a Workday worker reference object.

        Args:
            worker_id: Worker identifier
            id_type: Type of ID (Employee_ID, Contingent_Worker_ID, WID, etc.)

        Returns:
            Worker reference dictionary for SOAP request
        """
        return {
            "ID": [
                {
                    "type": id_type,
                    "_value_1": worker_id
                }
            ]
        }

    def _build_request_criteria(
        self,
        **filters: Any
    ) -> Dict[str, Any]:
        """
        Build request criteria for Workday queries.

        Args:
            **filters: Filter parameters

        Returns:
            Request criteria dictionary
        """
        criteria = {}

        if "search_text" in filters and filters["search_text"]:
            criteria["Search_Text"] = filters["search_text"]

        if "manager_id" in filters and filters["manager_id"]:
            criteria["Manager_Reference"] = self._build_worker_reference(
                filters["manager_id"]
            )

        return criteria

    def _parse_worker_response(self, response: Any) -> Dict[str, Any]:
        """
        Parse Workday worker response into a clean dictionary.

        Args:
            response: Raw SOAP response

        Returns:
            Parsed worker data
        """
        # This is a simplified parser - adjust based on actual Workday response structure
        return helpers.serialize_object(response) if response else {}

    def _build_organization_reference(
        self,
        org_id: str,
        id_type: str = "Organization_Reference_ID"
    ) -> Dict[str, Any]:
        """Build organization reference."""
        return {
            "ID": [
                {
                    "type": id_type,
                    "_value_1": org_id
                }
            ]
        }

    def _build_field_criteria(
        self,
        field_name: str,
        field_value: str,
        operator: str = "Equals"
    ) -> Dict[str, Any]:
        """
        Build field and parameter criteria for advanced searches.

        Args:
            field_name: Workday field name (e.g., "Legal_Name", "Email")
            field_value: Value to search for
            operator: Comparison operator (Equals, Contains, Starts_With, etc.)

        Returns:
            Field criteria dictionary
        """
        return {
            "Field_And_Parameter_Criteria_Data": [
                {
                    "Field_Name": field_name,
                    "Operator": operator,
                    "Value": field_value
                }
            ]
        }


# -----------------------------
# Toolkit implementation
# -----------------------------
class WorkdayToolkit(AbstractToolkit):
    """
    Toolkit for interacting with Workday via SOAP/WSDL with multi-service support.

    This toolkit provides async tools for Workday operations across multiple services:
    - Human Resources: Worker management, organization queries, employment data
    - Absence Management: Time off balances, leave requests
    - Time Tracking: Timesheet operations (placeholder for future implementation)
    - Staffing: Position management (placeholder for future implementation)
    - Financial Management: Spend categories, worktags (placeholder for future implementation)
    - Recruiting: Job requisitions, candidates (placeholder for future implementation)

    The toolkit automatically routes method calls to the appropriate WSDL service
    based on the METHOD_TO_SERVICE_MAP configuration. Clients are lazily initialized
    on first use and cached for performance.

    All public async methods automatically become tools via AbstractToolkit.
    """

    def __init__(
        self,
        tenant_name: str = None,
        credentials: Dict[str, str] = None,
        wsdl_paths: Optional[Dict[str, str]] = None,
        redis_url: Optional[str] = None,
        redis_key: str = "workday:access_token",
        timeout: int = 30,
        **kwargs
    ):
        """
        Initialize Workday toolkit with support for multiple service WSDLs.

        Args:
            credentials: Dict with OAuth2 credentials (client_id, client_secret, token_url, refresh_token)
                        and default wsdl_path (typically Human Resources)
            tenant_name: Workday tenant name
            wsdl_paths: Optional dict mapping service names to WSDL URLs, e.g.:
                       {
                           "human_resources": "https://.../Human_Resources/v44.2?wsdl",
                           "absence_management": "https://.../Absence_Management/v45?wsdl",
                           "time_tracking": "https://.../Time_Tracking/v44.2?wsdl",
                           "staffing": "https://.../Staffing/v44.2?wsdl",
                           "financial_management": "https://.../Financial_Management/v45?wsdl",
                           "recruiting": "https://.../Recruiting/v44.2?wsdl"
                       }
            redis_url: Redis connection URL for token caching
            redis_key: Redis key for storing access token
            timeout: HTTP timeout in seconds
            **kwargs: Additional toolkit configuration
        """
        super().__init__(**kwargs)

        # Store credentials and settings for creating clients
        self.credentials = credentials or self._default_credentials()
        self.redis_url = redis_url
        self.redis_key = redis_key
        self.timeout = timeout
        self.tenant_name = tenant_name or WORKDAY_DEFAULT_TENANT

        # Initialize WSDL paths mapping
        self.wsdl_paths: Dict[WorkdayService, str] = {}

        # Process wsdl_paths parameter or use legacy approach
        if wsdl_paths:
            # Map service names to enum values
            for service_name, wsdl_url in wsdl_paths.items():
                try:
                    service_enum = WorkdayService(service_name)
                    self.wsdl_paths[service_enum] = wsdl_url
                except ValueError:
                    # Skip unknown service names
                    continue
        else:
            for service_name, wsdl_url in WORKDAY_WSDL_PATHS.items():
                if isinstance(wsdl_url, PurePath) and not wsdl_url.is_file():
                    print('Warning: WSDL path does not exist:', wsdl_url)
                try:
                    service_enum = WorkdayService(service_name)
                    self.wsdl_paths[service_enum] = wsdl_url
                except ValueError:
                    # Skip unknown service names
                    continue

        # Fallback: Use default wsdl_path from credentials for Human Resources
        if WorkdayService.HUMAN_RESOURCES not in self.wsdl_paths:
            if default_wsdl := credentials.get("wsdl_path"):
                self.wsdl_paths[WorkdayService.HUMAN_RESOURCES] = default_wsdl

        # Dictionary to store initialized clients per service
        self._clients: Dict[WorkdayService, WorkdaySOAPClient] = {}

        # For backward compatibility, keep soap_client as primary client
        self.soap_client: Optional[WorkdaySOAPClient] = None

        self._initialized = False

    def _default_credentials(self) -> Dict[str, str]:
        """Generate default credentials from configuration."""
        return {
            "client_id": WORKDAY_CLIENT_ID,
            "client_secret": WORKDAY_CLIENT_SECRET,
            "token_url": WORKDAY_TOKEN_URL,
            "wsdl_path": WORKDAY_WSDL_PATH,
            "refresh_token": WORKDAY_REFRESH_TOKEN
        }

    async def wd_start(self) -> str:
        """
        Initialize the primary SOAP client connection.
        Must be called before using any tools.

        Returns:
            Success message
        """
        if not self._initialized:
            # Initialize primary client (Human Resources by default)
            primary_service = WorkdayService.HUMAN_RESOURCES
            self.soap_client = await self._get_client_for_service(primary_service)
            self._initialized = True
            return "Workday toolkit initialized successfully. Ready to process requests."
        return "Workday toolkit already initialized."

    async def start(self) -> str:
        """Compatibility wrapper for toolkit lifecycle start."""
        return await self.wd_start()

    async def _get_client_for_service(
        self,
        service: WorkdayService
    ) -> WorkdaySOAPClient:
        """
        Get or create a SOAP client for the specified service.

        This method implements lazy initialization - clients are only created
        when first needed and then cached for reuse.

        Args:
            service: The Workday service enum (e.g., HUMAN_RESOURCES, ABSENCE_MANAGEMENT)

        Returns:
            Initialized WorkdaySOAPClient for the requested service

        Raises:
            RuntimeError: If WSDL path for the service is not configured
        """
        # Return cached client if already initialized
        if service in self._clients:
            return self._clients[service]

        # Check if WSDL path is configured for this service
        if service not in self.wsdl_paths:
            raise RuntimeError(
                f"WSDL path for service '{service.value}' is not configured. "
                f"Pass it in 'wsdl_paths' parameter when initializing WorkdayToolkit. "
                f"Example: wsdl_paths={{'{service.value}': 'https://...?wsdl'}}"
            )

        # Create credentials with service-specific WSDL
        service_credentials = self.credentials.copy()
        service_credentials["wsdl_path"] = self.wsdl_paths[service]

        # Create and initialize the client
        client = WorkdaySOAPClient(
            tenant_name=self.tenant_name,
            credentials=service_credentials,
            redis_url=self.redis_url,
            redis_key=self.redis_key,
            timeout=self.timeout
        )
        await client.start()

        # Cache the client
        self._clients[service] = client

        return client

    async def _get_client_for_method(self, method_name: str) -> WorkdaySOAPClient:
        """
        Get the appropriate SOAP client for a given toolkit method.

        Args:
            method_name: Name of the toolkit method

        Returns:
            Initialized WorkdaySOAPClient for the method's required service

        Raises:
            RuntimeError: If method is not mapped to a service or WSDL not configured
        """
        if method_name not in METHOD_TO_SERVICE_MAP:
            # Default to Human Resources for unmapped methods
            service = WorkdayService.HUMAN_RESOURCES
        else:
            service = METHOD_TO_SERVICE_MAP[method_name]

        return await self._get_client_for_service(service)

    async def wd_close(self) -> None:
        """
        Close all SOAP client connections.
        """
        # Close all cached clients
        for client in self._clients.values():
            await client.close()

        self._clients.clear()
        self.soap_client = None
        self._initialized = False

    # -----------------------------
    # Tool methods (automatically become tools)
    # -----------------------------

    @tool_schema(GetWorkerInput)
    async def wd_get_worker(
        self,
        worker_id: str,
        output_format: Optional[Type[BaseModel]] = None,
    ) -> Union[WorkerModel, BaseModel]:
        """
        Get detailed information about a specific worker by ID.

        Retrieves comprehensive worker data including personal information,
        job details, compensation, and organizational relationships.

        Args:
            worker_id: Worker identifier (Employee ID, Contingent Worker ID, or WID)

        Returns:
            Worker data dictionary with all available fields
        """
        if not self._initialized:
            await self.wd_start()

        # Get the appropriate client for this method
        client = await self._get_client_for_method("wd_get_worker")

        # Build the Get_Workers request
        request = {
            "Request_References": {
                "Worker_Reference": client._build_worker_reference(worker_id)
            },
            "Response_Filter": {
                "As_Of_Effective_Date": datetime.now().strftime("%Y-%m-%d"),
                "As_Of_Entry_DateTime": datetime.now().isoformat()
            },
            "Response_Group": {
                "Include_Reference": True,
                "Include_Personal_Information": True,
                "Include_Employment_Information": True,
                "Include_Compensation": True,
                "Include_Organizations": True,
                "Include_Roles": True,
                "Include_Management_Chain_Data": True
            }
        }

        result = await client.run("Get_Workers", **request)
        # Use parser for structured output
        return WorkdayResponseParser.parse_worker_response(
            result,
            output_format=output_format
        )
        # return client._parse_worker_response(result)

    @tool_schema(SearchWorkersInput)
    async def wd_search_workers(
        self,
        search_text: Optional[str] = None,
        manager_id: Optional[str] = None,
        location_id: Optional[str] = None,
        job_profile_id: Optional[str] = None,
        hire_date_from: Optional[str] = None,
        hire_date_to: Optional[str] = None,
        max_results: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Search for workers based on various criteria.

        Supports searching by text, manager, location, job profile, and hire date range.
        Returns a list of workers matching the specified criteria.

        Args:
            search_text: Text to search in names, emails, or IDs
            manager_id: Filter by manager's worker ID
            location_id: Filter by location ID
            job_profile_id: Filter by job profile ID
            hire_date_from: Start of hire date range (YYYY-MM-DD)
            hire_date_to: End of hire date range (YYYY-MM-DD)
            max_results: Maximum number of results (default 100)

        Returns:
            List of worker dictionaries matching the search criteria
        """
        if not self._initialized:
            await self.wd_start()

        # Get the appropriate client for this method
        client = await self._get_client_for_method("wd_search_workers")

        # Build request criteria
        request = {
            "Request_Criteria": client._build_request_criteria(
                search_text=search_text,
                manager_id=manager_id,
                location_id=location_id,
                job_profile_id=job_profile_id
            ),
            "Response_Filter": {
                "Page": 1,
                "Count": max_results
            },
            "Response_Group": {
                "Include_Reference": True,
                "Include_Personal_Information": True,
                "Include_Employment_Information": True
            }
        }

        # Add hire date filters if provided
        if hire_date_from or hire_date_to:
            request["Request_Criteria"]["Hire_Date_Range"] = {}
        if hire_date_from:
            request["Request_Criteria"]["Hire_Date_Range"]["From"] = hire_date_from
        if hire_date_to:
            request["Request_Criteria"]["Hire_Date_Range"]["To"] = hire_date_to

        result = await client.run("Get_Workers", **request)

        # Parse multiple workers from response
        workers = []
        if result and hasattr(result, "Worker"):
            workers.extend(
                client._parse_worker_response(worker)
                for worker in result.Worker
            )

        return workers

    @tool_schema(GetWorkerContactInput)
    async def wd_get_worker_contact(
        self,
        worker_id: str,
        include_personal: bool = True,
        include_work: bool = True,
        output_format: Optional[Type[BaseModel]] = None,
    ) -> Dict[str, Any]:
        """
        Get contact information for a specific worker.

        Retrieves email addresses, phone numbers, addresses, and other
        contact details for the specified worker.

        Args:
            worker_id: Worker identifier
            include_personal: Include personal contact information
            include_work: Include work contact information

        Returns:
            Dictionary containing all contact information
        """
        if not self._initialized:
            await self.wd_start()

        # Get the appropriate client for this method
        client = await self._get_client_for_method("wd_get_worker_contact")

        request = {
            "Request_References": {
                "Worker_Reference": client._build_worker_reference(worker_id)
            },
            "Response_Group": {
                "Include_Personal_Information": include_personal,
                "Include_Employment_Information": include_work,
                # "Include_Contact_Information": True
            }
        }

        result = await client.run("Get_Workers", **request)
        # parsed = client._parse_worker_response(result)
        return WorkdayResponseParser.parse_contact_response(
            result,
            worker_id=worker_id,
            output_format=output_format
        )

    @tool_schema(GetWorkerJobDataInput)
    async def wd_get_worker_job_data(
        self,
        worker_id: str,
        effective_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get job-related data for a worker.

        Retrieves position, job profile, location, manager, compensation,
        and other employment details for the specified worker.

        Args:
            worker_id: Worker identifier
            effective_date: Date for which to retrieve data (YYYY-MM-DD). Defaults to today.

        Returns:
            Dictionary containing job data
        """
        if not self._initialized:
            await self.wd_start()

        # Get the appropriate client for this method
        client = await self._get_client_for_method("wd_get_worker_job_data")

        if not effective_date:
            effective_date = datetime.now().strftime("%Y-%m-%d")

        request = {
            "Request_References": {
                "Worker_Reference": client._build_worker_reference(worker_id)
            },
            "Response_Filter": {
                "As_Of_Effective_Date": effective_date
            },
            "Response_Group": {
                "Include_Employment_Information": True,
                "Include_Compensation": True,
                "Include_Organizations": True,
                "Include_Management_Chain_Data": True
            }
        }

        result = await client.run("Get_Workers", **request)
        parsed = client._parse_worker_response(result)

        # Extract job-specific data
        if parsed and "Worker_Data" in parsed:
            worker_data = parsed["Worker_Data"]
            employment_data = worker_data.get("Employment_Data", {})

            return {
                "worker_id": worker_id,
                "effective_date": effective_date,
                "position": employment_data.get("Position_Data", {}),
                "job_profile": employment_data.get("Position_Data", {}).get("Job_Profile_Summary_Data", {}),
                "business_title": employment_data.get("Position_Data", {}).get("Business_Title", ""),
                "manager": employment_data.get("Worker_Job_Data", {}).get("Manager_Reference", {}),
                "location": employment_data.get("Position_Data", {}).get("Business_Site_Summary_Data", {}),
                "organizations": worker_data.get("Organization_Data", []),
                "compensation": worker_data.get("Compensation_Data", {})
            }

        return {"worker_id": worker_id, "job_data": parsed}

    @tool_schema(GetOrganizationInput)
    async def wd_get_organization(
        self,
        org_id: str,
        include_hierarchy: bool = False
    ) -> Dict[str, Any]:
        """
        Get organization information by ID.

        Retrieves details about an organizational unit including its
        name, type, manager, and optionally its hierarchical structure.

        Args:
            org_id: Organization ID or reference
            include_hierarchy: Include organizational hierarchy

        Returns:
            Dictionary containing organization data
        """
        if not self._initialized:
            await self.wd_start()

        # Get the appropriate client for this method
        client = await self._get_client_for_method("wd_get_organization")

        request = {
            "Request_References": {
                "Organization_Reference": {
                    "ID": [{"type": "Organization_Reference_ID", "_value_1": org_id}]
                }
            },
            "Response_Group": {
                "Include_Reference": True,
                "Include_Organization_Support_Role_Data": True,
                "Include_Hierarchy_Data": include_hierarchy
            }
        }

        result = await client.run("Get_Organizations", **request)
        # Parse organization response
        return helpers.serialize_object(result) if result else {}

    async def wd_get_worker_time_off_balance(
        self,
        worker_id: str,
        output_format: Optional[Type[BaseModel]] = None
    ) -> Dict[str, Any]:
        """
        Get time off balance for a worker.

        Retrieves available time off balances for all time off types
        assigned to the worker.

        Args:
            worker_id: Worker identifier

        Returns:
            Dictionary containing time off balances by type
        """
        if not self._initialized:
            await self.wd_start()

        # Get the appropriate client for this method
        client = await self._get_client_for_method("wd_get_worker_time_off_balance")

        request = {
            "Request_References": {
                "Worker_Reference": client._build_worker_reference(worker_id)
            },
            "Response_Group": {
                # Some Workday tenants/WSDL versions do not expose
                # Include_Time_Off_Balance on the Worker response group.  Keep
                # the response group minimal to avoid zeep TypeError for
                # unsupported fields while still returning the worker payload
                # (which may contain Time_Off_Balance_Data when the tenant is
                # licensed for Absence Management).
                "Include_Reference": True
            }
        }

        result = await client.run("Get_Workers", **request)
        print('RESULT > ', result)
        return WorkdayResponseParser.parse_time_off_balance_response(
            result,
            worker_id=worker_id,
            output_format=output_format
        )

    @tool_schema(GetTimeOffBalanceInput)
    async def wd_get_time_off_balance(
        self,
        worker_id: str,
        time_off_plan_id: Optional[str] = None,
        output_format: Optional[Type[BaseModel]] = None
    ) -> Union[Dict[str, Any], BaseModel]:
        """
        Get time off plan balances for a worker using Absence Management API.

        This method uses the Get_Time_Off_Plan_Balances operation from the
        Workday Absence Management WSDL, which provides more detailed balance
        information than the Get_Workers operation.

        Args:
            worker_id: Worker identifier (Employee_ID)
            time_off_plan_id: Optional specific time off plan ID to filter
            output_format: Optional Pydantic model to format the output

        Returns:
            Time off balance information formatted according to output_format
            or default TimeOffBalanceModel
        """
        if not self._initialized:
            await self.wd_start()

        # Get the Absence Management client
        absence_client = await self._get_client_for_method("wd_get_time_off_balance")

        # Build the request payload
        payload = {
            "Response_Filter": {
                "As_Of_Entry_DateTime": datetime.now().replace(microsecond=0).isoformat() + "Z"
            },
            "Response_Group": {
                "Include_Reference": True,
                "Include_Time_Off_Plan_Balance_Data": True,
            },
        }

        # Build Request_Criteria
        request_criteria = {
            "Employee_Reference": {
                "ID": [
                    {
                        "_value_1": worker_id,
                        "type": "Employee_ID"
                    }
                ]
            }
        }

        # Add time off plan filter if provided
        if time_off_plan_id:
            request_criteria["Time_Off_Plan_Reference"] = {
                "ID": [
                    {
                        "_value_1": time_off_plan_id,
                        "type": "Time_Off_Plan_ID"
                    }
                ]
            }

        payload["Request_Criteria"] = request_criteria

        # Execute the SOAP operation
        result = await absence_client._service.Get_Time_Off_Plan_Balances(**payload)

        # Parse the response using the dedicated parser
        return WorkdayResponseParser.parse_time_off_plan_balances_response(
            result,
            worker_id=worker_id,
            output_format=output_format
        )

    async def wd_get_workers_by_organization(
        self,
        org_id: str,
        output_format: Optional[Type[BaseModel]] = None,
        include_subordinate: bool = True,
        exclude_inactive: bool = True,
        max_results: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get all workers in an organization.

        This is the most common way to "search" workers in Workday -
        by filtering on organizational membership.

        Args:
            org_id: Organization ID or reference
            include_subordinate: Include workers from sub-organizations
            exclude_inactive: Exclude terminated/inactive workers
            max_results: Maximum results to return

        Returns:
            List of worker dictionaries
        """
        if not self._initialized:
            await self.wd_start()

        # Get the appropriate client for this method
        client = await self._get_client_for_method("wd_get_workers_by_organization")

        request = {
            "Request_Criteria": {
                "Organization_Reference": [
                    client._build_organization_reference(org_id)
                ],
                "Include_Subordinate_Organizations": include_subordinate,
                "Exclude_Inactive_Workers": exclude_inactive
            },
            "Response_Filter": {
                "Page": 1,
                "Count": max_results,
                "As_Of_Effective_Date": datetime.now().strftime("%Y-%m-%d")
            },
            "Response_Group": {
                "Include_Reference": True,
                "Include_Personal_Information": True,
                "Include_Employment_Information": True,
                "Include_Organizations": True
            }
        }

        result = await client.run("Get_Workers", **request)
        # Use parser for structured output
        return WorkdayResponseParser.parse_workers_response(
            result,
            output_format=output_format
        )

    async def wd_get_workers_by_ids(
        self,
        worker_ids: List[str],
        id_type: str = "Employee_ID"
    ) -> List[Dict[str, Any]]:
        """
        Get multiple workers by their IDs.

        This is the most efficient way to retrieve specific workers.

        Args:
            worker_ids: List of worker identifiers
            id_type: Type of ID (Employee_ID, WID, etc.)

        Returns:
            List of worker dictionaries
        """
        if not self._initialized:
            await self.wd_start()

        # Get the appropriate client for this method
        client = await self._get_client_for_method("wd_get_workers_by_ids")

        request = {
            "Request_References": {
                "Worker_Reference": [
                    client._build_worker_reference(wid, id_type)
                    for wid in worker_ids
                ]
            },
            "Response_Filter": {
                "As_Of_Effective_Date": datetime.now().strftime("%Y-%m-%d")
            },
            "Response_Group": {
                "Include_Reference": True,
                "Include_Personal_Information": True,
                "Include_Employment_Information": True
            }
        }

        result = await client.run("Get_Workers", **request)
        return self._parse_workers_response(result)

    async def wd_search_workers_by_name(
        self,
        name: str,
        max_results: int = 100,
        search_type: str = "Contains"  # Contains, Equals, Starts_With
    ) -> List[Dict[str, Any]]:
        """
        Search workers by name using Field_And_Parameter_Criteria.

        Note: This is less efficient than organizational searches.
        Consider combining with organizational filters for better performance.

        Args:
            name: Name to search for
            max_results: Maximum results
            search_type: Type of search (Contains, Equals, Starts_With)

        Returns:
            List of matching workers
        """
        if not self._initialized:
            await self.wd_start()

        # Get the appropriate client for this method
        client = await self._get_client_for_method("wd_search_workers_by_name")

        request = {
            "Request_Criteria": {
                "Field_And_Parameter_Criteria_Data": {
                    "Field_Name": "Legal_Name",  # Or "Preferred_Name"
                    "Operator": search_type,
                    "Value": name
                },
                "Exclude_Inactive_Workers": True
            },
            "Response_Filter": {
                "Page": 1,
                "Count": max_results
            },
            "Response_Group": {
                "Include_Reference": True,
                "Include_Personal_Information": True,
                "Include_Employment_Information": True
            }
        }

        result = await client.run("Get_Workers", **request)
        return self._parse_workers_response(result)

    async def wd_get_workers_by_manager(
        self,
        manager_id: str,
        include_indirect_reports: bool = False,
        max_results: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get all workers reporting to a manager.

        Note: Workday doesn't have a direct "manager filter" in Get_Workers.
        This implementation gets the manager's position and then finds
        all workers in that supervisory organization.

        For true hierarchical reporting, you may need to:
        1. Get the manager's position
        2. Get the supervisory organization
        3. Query workers in that organization

        Args:
            manager_id: Manager's worker ID
            include_indirect_reports: Include indirect reports
            max_results: Maximum results

        Returns:
            List of direct/indirect reports
        """
        if not self._initialized:
            await self.wd_start()

        # First, get the manager's data to find their supervisory org
        manager_data = await self.wd_get_worker(manager_id)

        # Extract supervisory organization from manager's position
        # This structure varies by Workday configuration
        supervisory_org_id = None
        if "Worker_Data" in manager_data:
            employment = manager_data["Worker_Data"].get("Employment_Data", {})
            position = employment.get("Position_Data", {})

            # Look for supervisory organization
            for org in position.get("Organization_Data", []):
                if org.get("Organization_Type_Reference", {}).get("ID", [{}])[0].get("_value_1") == "SUPERVISORY":
                    supervisory_org_id = org.get("Organization_Reference", {}).get("ID", [{}])[0].get("_value_1")
                    break

        if not supervisory_org_id:
            return []

        # Now get all workers in that supervisory org
        return await self.wd_get_workers_by_organization(
            org_id=supervisory_org_id,
            include_subordinate=include_indirect_reports,
            max_results=max_results
        )

    async def wd_get_inactive_workers(
        self,
        org_id: Optional[str] = None,
        termination_date_from: Optional[str] = None,
        termination_date_to: Optional[str] = None,
        max_results: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get terminated/inactive workers.

        Args:
            org_id: Optional organization filter
            termination_date_from: Start of termination date range (YYYY-MM-DD)
            termination_date_to: End of termination date range (YYYY-MM-DD)
            max_results: Maximum results

        Returns:
            List of inactive workers
        """
        if not self._initialized:
            await self.wd_start()

        # Get the appropriate client for this method
        client = await self._get_client_for_method("wd_get_inactive_workers")

        request = {
            "Request_Criteria": {
                "Exclude_Inactive_Workers": False,  # We want inactive workers!
                "Exclude_Employees": False,
                "Exclude_Contingent_Workers": False
            },
            "Response_Filter": {
                "Page": 1,
                "Count": max_results
            },
            "Response_Group": {
                "Include_Reference": True,
                "Include_Personal_Information": True,
                "Include_Employment_Information": True
            }
        }

        # Add org filter if provided
        if org_id:
            request["Request_Criteria"]["Organization_Reference"] = [
                client._build_organization_reference(org_id)
            ]

        # Note: Termination date filtering might require Transaction_Log_Criteria_Data
        # depending on your Workday configuration

        result = await client.run("Get_Workers", **request)

        # Post-process to filter by termination date if needed
        workers = self._parse_workers_response(result)

        if termination_date_from or termination_date_to:
            filtered = []
            for worker in workers:
                if (term_date := self._extract_termination_date(worker)):
                    if termination_date_from and term_date < termination_date_from:
                        continue
                    if termination_date_to and term_date > termination_date_to:
                        continue
                    filtered.append(worker)
            return filtered

        return workers

    def _parse_workers_response(self, response: Any) -> List[Dict[str, Any]]:
        """
        Parse Get_Workers response into list of worker dictionaries.
        """
        workers = []

        if not response:
            return workers

        # Response structure: Get_Workers_Response -> Response_Data -> Worker[]
        serialized = helpers.serialize_object(response)

        # Navigate the response structure
        response_data = serialized.get("Response_Data", {})
        worker_data = response_data.get("Worker", [])

        # Handle single worker vs array
        if not isinstance(worker_data, list):
            worker_data = [worker_data] if worker_data else []
        workers.extend(iter(worker_data))
        return workers

    def _extract_termination_date(self, worker_data: Dict[str, Any]) -> Optional[str]:
        """Extract termination date from worker data."""
        with contextlib.suppress(Exception):
            employment = worker_data.get("Worker_Data", {}).get("Employment_Data", {})
            status_data = employment.get("Worker_Status_Data", {})
            if status_data.get("Terminated"):
                return status_data.get("Termination_Date")
        return None
