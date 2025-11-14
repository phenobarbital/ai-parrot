"""
Workday Response Models and Structured Output Parser

Provides clean Pydantic models for Workday objects with:
1. Default models per object type (Worker, Organization, etc.)
2. Support for custom output formats
3. Automatic parsing from verbose Zeep responses
"""
import contextlib
from typing import Any, Dict, List, Optional, Type, TypeVar, Union
from datetime import date, datetime
from pydantic import BaseModel, Field, field_validator
from zeep import helpers


# ==========================================
# Default Pydantic Models for Workday Objects
# ==========================================

class WorkdayReference(BaseModel):
    """Standard Workday reference object."""
    id: str = Field(description="Primary identifier")
    id_type: Optional[str] = Field(default=None, description="Type of identifier")
    descriptor: Optional[str] = Field(default=None, description="Human-readable name")


class EmailAddress(BaseModel):
    """Email address with metadata."""
    email: str = Field(description="Email address")
    type: Optional[str] = Field(default=None, description="Email type (Work, Home, etc.)")
    primary: bool = Field(default=False, description="Is primary email")
    public: bool = Field(default=True, description="Is public")


class PhoneNumber(BaseModel):
    """Phone number with metadata."""
    phone: str = Field(description="Phone number")
    type: Optional[str] = Field(default=None, description="Phone type (Work, Mobile, etc.)")
    primary: bool = Field(default=False, description="Is primary phone")
    country_code: Optional[str] = Field(default=None, description="Country code")


class Address(BaseModel):
    """Physical address."""
    formatted_address: Optional[str] = Field(default=None, description="Complete formatted address")
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = Field(default=None, description="State/Province")
    postal_code: Optional[str] = None
    country: Optional[str] = None
    type: Optional[str] = Field(default=None, description="Address type (Work, Home, etc.)")


class JobProfile(BaseModel):
    """Job profile information."""
    id: str = Field(description="Job profile ID")
    name: str = Field(description="Job profile name")
    job_family: Optional[str] = None
    management_level: Optional[str] = None


class Position(BaseModel):
    """Worker position information."""
    position_id: str = Field(description="Position ID")
    business_title: str = Field(description="Job title")
    job_profile: Optional[JobProfile] = None
    time_type: Optional[str] = Field(default=None, description="Full-time, Part-time, etc.")
    location: Optional[str] = None
    hire_date: Optional[date] = None
    start_date: Optional[date] = None


class Manager(BaseModel):
    """Manager reference."""
    worker_id: str = Field(description="Manager's worker ID")
    name: str = Field(description="Manager's name")
    email: Optional[str] = None


class Compensation(BaseModel):
    """Compensation information."""
    base_pay: Optional[float] = None
    currency: Optional[str] = Field(default="USD")
    pay_frequency: Optional[str] = Field(default=None, description="Annual, Monthly, etc.")
    effective_date: Optional[date] = None

class TimeOffBalance(BaseModel):
    """Individual time off balance for a specific time off type."""
    time_off_type: str = Field(description="Time off type name (e.g., 'Vacation', 'Sick', 'PTO')")
    time_off_type_id: Optional[str] = Field(default=None, description="Time off type ID")
    # Balance information
    balance: float = Field(description="Current balance in hours or days")
    balance_unit: str = Field(default="Hours", description="Unit of measurement (Hours, Days)")
    # Additional balance details
    scheduled: Optional[float] = Field(default=None, description="Scheduled/pending time off")
    available: Optional[float] = Field(default=None, description="Available balance (balance - scheduled)")
    # Accrual information
    accrued_ytd: Optional[float] = Field(default=None, description="Accrued year-to-date")
    used_ytd: Optional[float] = Field(default=None, description="Used year-to-date")
    # Carryover
    carryover: Optional[float] = Field(default=None, description="Carried over from previous period")
    carryover_limit: Optional[float] = Field(default=None, description="Maximum carryover allowed")
    # Effective dates
    as_of_date: Optional[date] = Field(default=None, description="Balance as of this date")
    plan_year_start: Optional[date] = Field(default=None, description="Plan year start date")
    plan_year_end: Optional[date] = Field(default=None, description="Plan year end date")


class TimeOffBalanceModel(BaseModel):
    """
    Clean Time Off Balance model - Default output for time off information.

    Provides structured view of a worker's time off balances across all types.
    """
    worker_id: str = Field(description="Worker ID")
    as_of_date: date = Field(description="Date these balances are calculated as of")

    # Time off balances by type
    balances: List[TimeOffBalance] = Field(
        default_factory=list,
        description="List of time off balances by type"
    )
    # Quick access to common types
    vacation_balance: Optional[float] = Field(
        default=None,
        description="Vacation/PTO balance if available"
    )
    sick_balance: Optional[float] = Field(
        default=None,
        description="Sick leave balance if available"
    )
    personal_balance: Optional[float] = Field(
        default=None,
        description="Personal time balance if available"
    )
    # Summary
    total_available_hours: Optional[float] = Field(
        default=None,
        description="Total available time off across all types"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "worker_id": "12345",
                "as_of_date": "2025-10-24",
                "vacation_balance": 120.0,
                "sick_balance": 80.0,
                "balances": [
                    {
                        "time_off_type": "Vacation",
                        "balance": 120.0,
                        "balance_unit": "Hours",
                        "available": 112.0,
                        "scheduled": 8.0
                    }
                ]
            }
        }

class WorkerModel(BaseModel):
    """
    Clean, structured Worker model - Default output format.

    This is a simplified, usable representation of a Workday worker
    instead of the deeply nested SOAP response.
    """
    worker_id: str = Field(description="Primary worker ID")
    employee_id: Optional[str] = Field(default=None, description="Employee ID if applicable")

    # Personal Information
    first_name: str
    last_name: str
    preferred_name: Optional[str] = None
    full_name: str = Field(description="Formatted full name")

    # Contact Information
    primary_email: Optional[str] = None
    personal_email: Optional[str] = Field(default=None, description="Personal/HOME email")
    corporate_email: Optional[str] = Field(default=None, description="Corporate/WORK email")
    emails: List[EmailAddress] = Field(default_factory=list)
    primary_phone: Optional[str] = None
    phones: List[PhoneNumber] = Field(default_factory=list)
    addresses: List[Address] = Field(default_factory=list)

    # Employment Information
    is_active: bool = Field(default=True)
    hire_date: Optional[date] = None
    termination_date: Optional[date] = None

    # Position Information
    business_title: Optional[str] = Field(default=None, description="Job title")
    job_profile: Optional[JobProfile] = None
    location: Optional[str] = None
    time_type: Optional[str] = Field(default=None, description="Full-time, Part-time")

    # Organizational Relationships
    manager: Optional[Manager] = None
    organizations: List[str] = Field(default_factory=list, description="Org names")

    # Compensation (optional, might be sensitive)
    compensation: Optional[Compensation] = None

    class Config:
        json_schema_extra = {
            "example": {
                "worker_id": "12345",
                "employee_id": "EMP-001",
                "first_name": "John",
                "last_name": "Doe",
                "full_name": "John Doe",
                "primary_email": "john.doe@company.com",
                "business_title": "Senior Software Engineer",
                "is_active": True
            }
        }


class OrganizationModel(BaseModel):
    """Clean Organization model."""
    org_id: str = Field(description="Organization ID")
    name: str = Field(description="Organization name")
    type: Optional[str] = Field(default=None, description="Org type (Cost Center, Department, etc.)")
    manager: Optional[Manager] = None
    parent_org: Optional[str] = Field(default=None, description="Parent org name")
    superior_org: Optional[str] = None
    is_active: bool = Field(default=True)


class ContactModel(BaseModel):
    """
    Clean Contact model - Default output for contact information.

    Simplified representation of a worker's contact details.
    """
    worker_id: str = Field(description="Worker ID")

    # Email addresses
    primary_email: Optional[str] = None
    work_email: Optional[str] = None
    personal_email: Optional[str] = None
    emails: List[EmailAddress] = Field(default_factory=list, description="All email addresses")

    # Phone numbers
    primary_phone: Optional[str] = None
    work_phone: Optional[str] = None
    mobile_phone: Optional[str] = None
    phones: List[PhoneNumber] = Field(default_factory=list, description="All phone numbers")

    # Addresses
    primary_address: Optional[Address] = None
    work_address: Optional[Address] = None
    home_address: Optional[Address] = None
    addresses: List[Address] = Field(default_factory=list, description="All addresses")

    # Additional contact info
    instant_messengers: List[Dict[str, str]] = Field(default_factory=list, description="IM handles")
    social_networks: List[Dict[str, str]] = Field(default_factory=list, description="Social media")

    class Config:
        json_schema_extra = {
            "example": {
                "worker_id": "12345",
                "primary_email": "john.doe@company.com",
                "work_phone": "+1 (555) 123-4567",
                "mobile_phone": "+1 (555) 987-6543"
            }
        }



# ==========================================
# Response Parser with Structured Outputs
# ==========================================

T = TypeVar('T', bound=BaseModel)


class WorkdayResponseParser:
    """
    Parser that transforms verbose Zeep responses into clean Pydantic models.

    Supports:
    - Default models per object type
    - Custom output formats via output_format parameter
    - Graceful handling of missing fields
    """

    # Map object types to default models
    DEFAULT_MODELS = {
        "worker": WorkerModel,
        "organization": OrganizationModel,
        "contact": ContactModel,
        "time_off_balance": TimeOffBalanceModel,
    }

    @staticmethod
    def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
        """
        Safely get a value from obj[key], handling both dicts and lists.

        If obj is a list, takes first element before getting key.
        Returns default if obj is None, key doesn't exist, or obj is empty list.
        """
        if obj is None:
            return default

        # If it's a list, take first element
        if isinstance(obj, list):
            if not obj:
                return default
            obj = obj[0]

        # Now try to get the key
        return obj.get(key, default) if isinstance(obj, dict) else default

    @staticmethod
    def _safe_navigate(obj: Any, *path: str, default: Any = None) -> Any:
        """
        Safely navigate a deeply nested structure with mixed dicts/lists.

        Example:
            _safe_navigate(data, "Personal_Data", "Contact_Data", "Email_Address_Data")

        Each step handles both dict keys and list indexing (takes [0] if list).
        """
        current = obj
        for key in path:
            if current is None:
                return default

            # Handle list - take first element
            if isinstance(current, list):
                if not current:
                    return default
                current = current[0]

            # Handle dict - get key
            if isinstance(current, dict):
                current = current.get(key)
            else:
                return default

        return current if current is not None else default

    @classmethod
    def parse_worker_response(
        cls,
        response: Any,
        output_format: Optional[Type[T]] = None
    ) -> Union[WorkerModel, T]:
        """
        Parse a worker response into a structured model.

        Args:
            response: Raw Zeep response object (Get_Workers_Response)
            output_format: Optional custom Pydantic model. If None, uses WorkerModel.

        Returns:
            Parsed worker as specified model type
        """
        # Use default if no custom format provided
        model_class = output_format or cls.DEFAULT_MODELS["worker"]

        # Serialize Zeep object to dict
        raw = helpers.serialize_object(response)

        # Navigate to first worker in response
        # Structure: Response_Data.Worker[0]
        response_data = raw.get("Response_Data", {})
        workers = response_data.get("Worker", [])

        if not workers:
            raise ValueError("No worker found in response")

        # Get first worker
        worker_element = workers[0] if isinstance(workers, list) else workers

        # Extract data using the extraction logic
        extracted = cls._extract_worker_data(worker_element)

        # Instantiate the model
        return model_class(**extracted)

    @classmethod
    def parse_workers_response(
        cls,
        response: Any,
        output_format: Optional[Type[T]] = None
    ) -> List[Union[WorkerModel, T]]:
        """
        Parse multiple workers from Get_Workers response.

        Args:
            response: Raw Zeep Get_Workers response
            output_format: Optional custom model for each worker

        Returns:
            List of parsed workers
        """
        model_class = output_format or cls.DEFAULT_MODELS["worker"]

        raw = helpers.serialize_object(response)

        # Navigate to worker array
        response_data = raw.get("Response_Data", {})
        worker_data = response_data.get("Worker", [])

        # Handle single vs array
        if not isinstance(worker_data, list):
            worker_data = [worker_data] if worker_data else []

        # Parse each worker
        workers = []
        for worker_raw in worker_data:
            extracted = cls._extract_worker_data(worker_raw)
            workers.append(model_class(**extracted))

        return workers

    @classmethod
    def parse_contact_response(
        cls,
        response: Any,
        worker_id: str,
        output_format: Optional[Type[T]] = None
    ) -> Union[ContactModel, T]:
        """
        Parse contact information from Get_Workers response.

        Args:
            response: Raw Zeep Get_Workers response
            worker_id: Worker ID for reference
            output_format: Optional custom model. Defaults to ContactModel.

        Returns:
            Parsed contact information
        """
        model_class = output_format or cls.DEFAULT_MODELS["contact"]

        # Get worker element (same navigation as parse_worker_response)
        raw = helpers.serialize_object(response)
        response_data = raw.get("Response_Data", {})
        workers = response_data.get("Worker", [])

        if not workers:
            raise ValueError("No worker found in response")

        worker_element = workers[0] if isinstance(workers, list) else workers

        # Extract contact data
        extracted = cls._extract_contact_data(worker_element, worker_id)

        # Instantiate the model
        return model_class(**extracted)

    @classmethod
    def _extract_contact_data(cls, worker_element: Dict[str, Any], worker_id: str) -> Dict[str, Any]:
        """
        Extract contact information from worker element.

        Args:
            worker_element: Single Worker element
            worker_id: Worker ID for reference

        Returns:
            Dict with contact data for ContactModel
        """
        worker_data = worker_element.get("Worker_Data", {})
        if not isinstance(worker_data, dict):
            # Some Workday tenants return an explicit null for Worker_Data when
            # the response group omits most sections (e.g. only requesting time
            # off balance data).  Treat these the same as an empty payload so
            # downstream parsing logic can continue gracefully.
            worker_data = {}
        personal = worker_data.get("Personal_Data", {})
        contact_data = personal.get("Contact_Data", {})

        # Extract emails, phones, addresses using existing methods
        emails = cls._extract_emails(contact_data)
        phones = cls._extract_phones(contact_data)
        addresses = cls._extract_addresses(contact_data)

        # Determine primary email
        primary_email = next((e.email for e in emails if e.primary), None)
        if not primary_email and emails:
            primary_email = emails[0].email

        # Find work and personal emails
        work_email = None
        personal_email = None
        for email in emails:
            if email.type and "work" in email.type.lower():
                work_email = email.email
            elif email.type and ("home" in email.type.lower() or "personal" in email.type.lower()):
                personal_email = email.email

        # Determine primary phone
        primary_phone = next((p.phone for p in phones if p.primary), None)
        if not primary_phone and phones:
            primary_phone = phones[0].phone

        # Find work and mobile phones
        work_phone = None
        mobile_phone = None
        for phone in phones:
            if phone.type:
                phone_type_lower = phone.type.lower()
                if "work" in phone_type_lower:
                    work_phone = phone.phone
                elif "mobile" in phone_type_lower or "cell" in phone_type_lower:
                    mobile_phone = phone.phone

        # Determine primary address
        primary_address = next((a for a in addresses if a.type and "work" in a.type.lower()), None)
        if not primary_address and addresses:
            primary_address = addresses[0]

        # Find work and home addresses
        work_address = None
        home_address = None
        for addr in addresses:
            if addr.type:
                addr_type_lower = addr.type.lower()
                if "work" in addr_type_lower:
                    work_address = addr
                elif "home" in addr_type_lower:
                    home_address = addr

        # Extract instant messengers (if present)
        instant_messengers = []
        im_data = contact_data.get("Instant_Messenger_Data", [])
        if not isinstance(im_data, list):
            im_data = [im_data] if im_data else []

        for im in im_data:
            if isinstance(im, dict):
                im_address = im.get("Instant_Messenger_Address")
                im_type = cls._safe_navigate(im, "Instant_Messenger_Type_Reference", "descriptor")
                if im_address:
                    instant_messengers.append({
                        "type": im_type or "Unknown",
                        "address": im_address
                    })

        # Extract social networks (if present in Web_Address_Data)
        social_networks = []
        web_data = contact_data.get("Web_Address_Data", [])
        if not isinstance(web_data, list):
            web_data = [web_data] if web_data else []

        for web in web_data:
            if isinstance(web, dict):
                web_address = web.get("Web_Address")
                web_type = cls._safe_navigate(web, "Usage_Data", "Type_Data", "Type_Reference", "descriptor")
                if web_address:
                    social_networks.append({
                        "type": web_type or "Website",
                        "url": web_address
                    })

        return {
            "worker_id": worker_id,
            "primary_email": primary_email,
            "work_email": work_email,
            "personal_email": personal_email,
            "emails": emails,
            "primary_phone": primary_phone,
            "work_phone": work_phone,
            "mobile_phone": mobile_phone,
            "phones": phones,
            "primary_address": primary_address,
            "work_address": work_address,
            "home_address": home_address,
            "addresses": addresses,
            "instant_messengers": instant_messengers,
            "social_networks": social_networks
        }

    @classmethod
    def _extract_worker_data(cls, worker_element: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract and flatten worker data from nested SOAP structure.

        Args:
            worker_element: Single Worker element from Response_Data.Worker array

        This is where we handle Workday's verbose structure.
        """
        # Worker element structure: { Worker_Reference, Worker_Descriptor, Worker_Data }
        worker_data = worker_element.get("Worker_Data", {})

        # References are at the worker_element level, not inside Worker_Data
        worker_ref = worker_element.get("Worker_Reference")

        # Try to extract IDs from Worker_Reference if present
        worker_id = None
        employee_id = None

        if worker_ref and isinstance(worker_ref, (dict, list)):
            # Handle both single reference and array
            refs = worker_ref if isinstance(worker_ref, list) else [worker_ref]
            for ref in refs:
                if ref:
                    worker_id = cls._extract_id(ref, "WID") or worker_id
                    employee_id = cls._extract_id(ref, "Employee_ID") or employee_id

        # Fallback to Worker_ID field in Worker_Data
        if not worker_id and not employee_id:
            worker_id = worker_data.get("Worker_ID")
            employee_id = worker_data.get("Worker_ID")

        # Personal Data
        personal = worker_data.get("Personal_Data", {})
        name_data = personal.get("Name_Data", {})

        # Extract names
        legal_name = name_data.get("Legal_Name_Data", {})
        preferred_name_data = name_data.get("Preferred_Name_Data", {})

        legal_name_detail = legal_name.get("Name_Detail_Data", {})
        preferred_name_detail = preferred_name_data.get("Name_Detail_Data", {})

        first_name = (
            preferred_name_detail.get("First_Name") or
            legal_name_detail.get("First_Name", "")
        )
        last_name = (
            preferred_name_detail.get("Last_Name") or
            legal_name_detail.get("Last_Name", "")
        )
        full_name = (
            preferred_name_detail.get("Formatted_Name") or
            legal_name_detail.get("Formatted_Name") or
            f"{first_name} {last_name}".strip()
        )
        preferred_name = preferred_name_detail.get("Formatted_Name")

        # Contact Data
        contact_data = personal.get("Contact_Data", {})
        emails, personal_email, corporate_email = cls._extract_emails(contact_data)
        phones = cls._extract_phones(contact_data)
        addresses = cls._extract_addresses(contact_data)

        primary_email = next((e.email for e in emails if e.primary), None)
        if not primary_email and emails:
            primary_email = emails[0].email

        primary_phone = next((p.phone for p in phones if p.primary), None)
        if not primary_phone and phones:
            primary_phone = phones[0].phone

        # Employment Data
        employment_data = worker_data.get("Employment_Data", {})
        worker_status = employment_data.get("Worker_Status_Data", {})

        is_active = worker_status.get("Active", True)
        hire_date = worker_status.get("Hire_Date")
        termination_date = worker_status.get("Termination_Date")

        # Position Data
        position_data = employment_data.get("Worker_Job_Data", [])
        if not isinstance(position_data, list):
            position_data = [position_data] if position_data else []

        # Get primary position
        business_title = None
        job_profile = None
        location = None
        time_type = None

        if position_data:
            primary_position = position_data[0].get("Position_Data", {})
            business_title = primary_position.get("Business_Title")

            # Job Profile
            if job_profile_data := primary_position.get("Job_Profile_Summary_Data", {}):
                # Use safe navigation for potentially list-valued fields
                job_profile_ref = job_profile_data.get("Job_Profile_Reference", {})
                profile_id = cls._extract_id(job_profile_ref)

                # Job Family - Based on flowtask, Job_Family_Reference is a list
                job_family = None
                job_family_refs = job_profile_data.get("Job_Family_Reference", [])
                if not isinstance(job_family_refs, list):
                    job_family_refs = [job_family_refs] if job_family_refs else []

                # Extract first Job_Family_ID
                for fam_ref in job_family_refs:
                    if isinstance(fam_ref, dict):
                        job_family = cls._extract_id(fam_ref, "Job_Family_ID")
                        if job_family:
                            break

                job_profile = JobProfile(
                    id=profile_id or "",
                    name=job_profile_data.get("Job_Profile_Name", ""),
                    job_family=job_family,
                    management_level=cls._safe_navigate(job_profile_data, "Management_Level_Reference", "descriptor")
                )

            # Location
            location_data = primary_position.get("Business_Site_Summary_Data", {})
            location = location_data.get("Name") if isinstance(location_data, dict) else None

            # Time type - use safe navigation
            time_type = cls._safe_navigate(primary_position, "Position_Time_Type_Reference", "descriptor")

        # Manager - Extract from Manager_as_of_last_detected_manager_change_Reference
        # This is the direct manager, not the management chain
        manager = None
        manager_data = employment_data.get("Worker_Job_Data", [])
        if manager_data:
            if not isinstance(manager_data, list):
                manager_data = [manager_data]

            # Get manager reference from Position_Data
            position_data = manager_data[0].get("Position_Data", {})
            manager_ref = cls._safe_get(position_data, "Manager_as_of_last_detected_manager_change_Reference")

            if manager_ref and isinstance(manager_ref, dict):
                # Extract Employee_ID specifically (not WID)
                manager_id = cls._extract_id(manager_ref, "Employee_ID")
                # Get Descriptor (manager name) directly
                manager_name = manager_ref.get("Descriptor")

                # Only create Manager object if we have both ID and name
                if manager_id and manager_name:
                    manager = Manager(
                        worker_id=manager_id,
                        name=manager_name,
                        email=None  # Would need separate lookup
                    )

        # Organizations - Based on flowtask structure
        # Organization_Data is a dict containing Worker_Organization_Data list
        organization_data = worker_data.get("Organization_Data", {}) or {}
        worker_orgs = organization_data.get("Worker_Organization_Data", []) or []

        # Ensure worker_orgs is a list
        if not isinstance(worker_orgs, list):
            worker_orgs = [worker_orgs] if worker_orgs else []

        organizations = [
            org.get("Organization_Data", {}).get("Organization_Name", "")
            for org in worker_orgs
            if org.get("Organization_Data", {}).get("Organization_Name")
        ]

        # Compensation (optional)
        comp_data = worker_data.get("Compensation_Data", {})
        compensation = None
        if comp_data:
            compensation = cls._extract_compensation(comp_data)

        return {
            "worker_id": worker_id or employee_id or "",
            "employee_id": employee_id,
            "first_name": first_name,
            "last_name": last_name,
            "preferred_name": preferred_name,
            "full_name": full_name,
            "primary_email": primary_email,
            "personal_email": personal_email,
            "corporate_email": corporate_email,
            "emails": emails,
            "primary_phone": primary_phone,
            "phones": phones,
            "addresses": addresses,
            "is_active": is_active,
            "hire_date": cls._parse_date(hire_date),
            "termination_date": cls._parse_date(termination_date),
            "business_title": business_title,
            "job_profile": job_profile,
            "location": location,
            "time_type": time_type,
            "manager": manager,
            "organizations": organizations,
            "compensation": compensation
        }

    @staticmethod
    def _extract_id(ref_obj: Any, id_type: Optional[str] = None) -> Optional[str]:
        """
        Extract ID from a Workday reference object.

        Handles multiple formats:
        - Single reference with ID array
        - Array of references
        - Dict with nested ID structures
        """
        if not ref_obj:
            return None

        # If ref_obj is a list of references, take the first one
        if isinstance(ref_obj, list):
            if not ref_obj:
                return None
            ref_obj = ref_obj[0]

        # Get the ID array
        ids = ref_obj.get("ID", []) if isinstance(ref_obj, dict) else []
        if not isinstance(ids, list):
            ids = [ids] if ids else []

        # If id_type specified, find matching type
        if id_type:
            for id_obj in ids:
                if isinstance(id_obj, dict) and id_obj.get("type") == id_type:
                    return id_obj.get("_value_1")

        # Otherwise return first ID
        return ids[0].get("_value_1") if ids and isinstance(ids[0], dict) else None

    @staticmethod
    def _extract_emails(contact_data: Dict[str, Any]) -> tuple[List[EmailAddress], Optional[str], Optional[str]]:
        """
        Extract email addresses and separate personal vs corporate emails.

        Returns:
            Tuple of (emails_list, personal_email, corporate_email)
        """
        emails = []
        personal_email = None
        corporate_email = None
        email_data = contact_data.get("Email_Address_Data", [])

        if not isinstance(email_data, list):
            email_data = [email_data] if email_data else []

        for email_obj in email_data:
            if email_addr := email_obj.get("Email_Address"):
                # Safe navigation through Usage_Data -> Type_Data nested lists
                email_type = None
                usage_type_id = None
                is_primary = False
                is_public = True

                usage_data = email_obj.get("Usage_Data", [])
                if usage_data and isinstance(usage_data, list) and len(usage_data) > 0:
                    usage_item = usage_data[0]
                    if isinstance(usage_item, dict):
                        # Extract Type from Type_Data array
                        type_data = usage_item.get("Type_Data", [])
                        if type_data and isinstance(type_data, list) and len(type_data) > 0:
                            type_item = type_data[0]
                            if isinstance(type_item, dict):
                                type_ref = type_item.get("Type_Reference", {})
                                if isinstance(type_ref, dict):
                                    email_type = type_ref.get("descriptor") or type_ref.get("Descriptor")

                                    # Extract Communication_Usage_Type_ID (HOME/WORK) - Based on flowtask
                                    type_ids = type_ref.get("ID", [])
                                    if not isinstance(type_ids, list):
                                        type_ids = [type_ids] if type_ids else []

                                    # Find Communication_Usage_Type_ID
                                    for id_obj in type_ids:
                                        if isinstance(id_obj, dict) and id_obj.get("type") == "Communication_Usage_Type_ID":
                                            usage_type_id = id_obj.get("_value_1")
                                            break

                        # Extract Primary flag (at usage_item level, not type_data)
                        is_primary = usage_item.get("Primary", False)
                        is_public = usage_item.get("Public", True)

                # Separate personal vs corporate emails based on Communication_Usage_Type_ID
                if usage_type_id == "HOME":
                    personal_email = email_addr
                elif usage_type_id == "WORK":
                    corporate_email = email_addr

                emails.append(EmailAddress(
                    email=email_addr,
                    type=email_type,
                    primary=is_primary,
                    public=is_public
                ))

        return emails, personal_email, corporate_email

    @staticmethod
    def _extract_phones(contact_data: Dict[str, Any]) -> List[PhoneNumber]:
        """Extract phone numbers."""
        phones = []
        phone_data = contact_data.get("Phone_Data", [])

        if not isinstance(phone_data, list):
            phone_data = [phone_data] if phone_data else []

        for phone_obj in phone_data:
            if formatted_phone := phone_obj.get("Formatted_Phone"):
                # Safe navigation through Usage_Data -> Type_Data
                phone_type = None
                is_primary = False

                usage_data = phone_obj.get("Usage_Data", [])
                if usage_data and isinstance(usage_data, list) and len(usage_data) > 0:
                    usage_item = usage_data[0]
                    if isinstance(usage_item, dict):
                        type_data = usage_item.get("Type_Data", [])
                        if type_data and isinstance(type_data, list) and len(type_data) > 0:
                            type_item = type_data[0]
                            if isinstance(type_item, dict):
                                type_ref = type_item.get("Type_Reference", {})
                                if isinstance(type_ref, dict):
                                    phone_type = type_ref.get("descriptor") or type_ref.get("Descriptor")

                        is_primary = usage_item.get("Primary", False)

                phones.append(PhoneNumber(
                    phone=formatted_phone,
                    type=phone_type,
                    primary=is_primary,
                    country_code=phone_obj.get("Country_ISO_Code")
                ))

        return phones

    @staticmethod
    def _extract_addresses(contact_data: Dict[str, Any]) -> List[Address]:
        """Extract addresses."""
        addresses = []
        address_data = contact_data.get("Address_Data", [])

        if not isinstance(address_data, list):
            address_data = [address_data] if address_data else []

        for addr_obj in address_data:
            if formatted := addr_obj.get("Formatted_Address"):
                # Extract address lines
                address_line_1 = None
                address_lines = addr_obj.get("Address_Line_Data", [])
                if address_lines and isinstance(address_lines, list) and len(address_lines) > 0:
                    line_item = address_lines[0]
                    if isinstance(line_item, dict):
                        address_line_1 = line_item.get("_value_1")

                # Safe navigation for Usage_Data
                addr_type = None
                usage_data = addr_obj.get("Usage_Data", [])
                if usage_data and isinstance(usage_data, list) and len(usage_data) > 0:
                    usage_item = usage_data[0]
                    if isinstance(usage_item, dict):
                        type_data = usage_item.get("Type_Data", [])
                        if type_data and isinstance(type_data, list) and len(type_data) > 0:
                            type_item = type_data[0]
                            if isinstance(type_item, dict):
                                type_ref = type_item.get("Type_Reference", {})
                                if isinstance(type_ref, dict):
                                    addr_type = type_ref.get("descriptor") or type_ref.get("Descriptor")

                # Extract country
                country = None
                country_ref = addr_obj.get("Country_Reference", {})
                if isinstance(country_ref, dict):
                    country = country_ref.get("descriptor") or country_ref.get("Descriptor")

                addresses.append(Address(
                    formatted_address=formatted,
                    address_line_1=address_line_1,
                    address_line_2=None,  # Would need to check Address_Line_Data[1]
                    city=addr_obj.get("Municipality"),
                    region=addr_obj.get("Country_Region_Descriptor"),
                    postal_code=addr_obj.get("Postal_Code"),
                    country=country,
                    type=addr_type
                ))

        return addresses

    @staticmethod
    def _extract_compensation(comp_data: Dict[str, Any]) -> Optional[Compensation]:
        """Extract compensation data."""
        # This structure varies significantly by configuration
        # Simplified example:
        try:
            return Compensation(
                base_pay=comp_data.get("Total_Base_Pay"),
                currency=comp_data.get("Currency_Reference", {}).get("descriptor", "USD"),
                pay_frequency=comp_data.get("Frequency_Reference", {}).get("descriptor"),
                effective_date=WorkdayResponseParser._parse_date(comp_data.get("Effective_Date"))
            )
        except Exception:
            return None

    @staticmethod
    def _parse_date(date_value: Any) -> Optional[date]:
        """Parse various date formats."""
        if not date_value:
            return None

        if isinstance(date_value, date):
            return date_value

        if isinstance(date_value, datetime):
            return date_value.date()

        if isinstance(date_value, str):
            with contextlib.suppress(Exception):
                return datetime.fromisoformat(date_value.replace('Z', '+00:00')).date()
        return None

    @classmethod
    def parse_time_off_balance_response(
        cls,
        response: Any,
        worker_id: str,
        output_format: Optional[Type[T]] = None
    ) -> Union[TimeOffBalanceModel, T]:
        """
        Parse time off balance information from Get_Workers response.

        Args:
            response: Raw Zeep Get_Workers response
            worker_id: Worker ID for reference
            output_format: Optional custom model. Defaults to TimeOffBalanceModel.

        Returns:
            Parsed time off balance information
        """
        model_class = output_format or cls.DEFAULT_MODELS["time_off_balance"]
        # Get worker element (same navigation as other parsers)
        raw = helpers.serialize_object(response)
        response_data = raw.get("Response_Data", {})
        workers = response_data.get("Worker", [])

        if not workers:
            raise ValueError("No worker found in response")

        worker_element = workers[0] if isinstance(workers, list) else workers
        # Extract time off balance data
        extracted = cls._extract_time_off_balance_data(worker_element, worker_id)
        # Instantiate the model
        return model_class(**extracted)

    @classmethod
    def _extract_time_off_balance_data(
        cls,
        worker_element: Dict[str, Any],
        worker_id: str
    ) -> Dict[str, Any]:
        """
        Extract time off balance information from worker element.

        Args:
            worker_element: Single Worker element
            worker_id: Worker ID for reference

        Returns:
            Dict with time off balance data for TimeOffBalanceModel
        """
        worker_data = worker_element.get("Worker_Data", {})
        if not isinstance(worker_data, dict):
            # Some Workday tenants may explicitly return null for Worker_Data
            # when only a subset of response groups are requested. Treat this
            # as an empty payload so balance parsing can continue.
            worker_data = {}

        # Time off balance data is typically in a dedicated section
        # The exact structure varies by Workday configuration
        time_off_data = worker_data.get("Time_Off_Balance_Data", [])

        if not isinstance(time_off_data, list):
            time_off_data = [time_off_data] if time_off_data else []

        # Parse each time off type balance
        balances = []
        vacation_balance = None
        sick_balance = None
        personal_balance = None
        total_available = 0.0

        for balance_item in time_off_data:
            if not isinstance(balance_item, dict):
                continue

            # Extract time off type
            time_off_type_ref = balance_item.get("Time_Off_Type_Reference", {})
            time_off_type = cls._safe_navigate(time_off_type_ref, "descriptor") or "Unknown"
            time_off_type_id = cls._extract_id(time_off_type_ref)

            # Extract balance values
            balance = balance_item.get("Balance", 0.0)
            if balance and not isinstance(balance, (int, float)):
                try:
                    balance = float(balance)
                except (ValueError, TypeError):
                    balance = 0.0

            # Extract unit
            balance_unit_ref = balance_item.get("Unit_Reference", {})
            balance_unit = cls._safe_navigate(balance_unit_ref, "descriptor") or "Hours"

            # Extract scheduled/pending
            scheduled = balance_item.get("Scheduled_Balance", 0.0)
            if scheduled and not isinstance(scheduled, (int, float)):
                try:
                    scheduled = float(scheduled)
                except (ValueError, TypeError):
                    scheduled = 0.0

            # Calculate available
            available = balance - scheduled if balance and scheduled else balance

            # Extract accrual information
            accrued_ytd = balance_item.get("Accrued_Year_to_Date")
            if accrued_ytd and not isinstance(accrued_ytd, (int, float)):
                try:
                    accrued_ytd = float(accrued_ytd)
                except (ValueError, TypeError):
                    accrued_ytd = None

            used_ytd = balance_item.get("Used_Year_to_Date")
            if used_ytd and not isinstance(used_ytd, (int, float)):
                try:
                    used_ytd = float(used_ytd)
                except (ValueError, TypeError):
                    used_ytd = None

            # Extract carryover
            carryover = balance_item.get("Carryover_Balance")
            if carryover and not isinstance(carryover, (int, float)):
                try:
                    carryover = float(carryover)
                except (ValueError, TypeError):
                    carryover = None

            carryover_limit = balance_item.get("Maximum_Carryover_Balance")
            if carryover_limit and not isinstance(carryover_limit, (int, float)):
                try:
                    carryover_limit = float(carryover_limit)
                except (ValueError, TypeError):
                    carryover_limit = None

            # Extract dates
            as_of_date = cls._parse_date(balance_item.get("As_of_Date"))
            plan_year_start = cls._parse_date(balance_item.get("Plan_Year_Start_Date"))
            plan_year_end = cls._parse_date(balance_item.get("Plan_Year_End_Date"))

            # Create TimeOffBalance object
            time_off_balance = TimeOffBalance(
                time_off_type=time_off_type,
                time_off_type_id=time_off_type_id,
                balance=balance or 0.0,
                balance_unit=balance_unit,
                scheduled=scheduled,
                available=available,
                accrued_ytd=accrued_ytd,
                used_ytd=used_ytd,
                carryover=carryover,
                carryover_limit=carryover_limit,
                as_of_date=as_of_date,
                plan_year_start=plan_year_start,
                plan_year_end=plan_year_end
            )

            balances.append(time_off_balance)

            # Track quick-access balances
            time_off_type_lower = time_off_type.lower()
            if "vacation" in time_off_type_lower or "pto" in time_off_type_lower:
                vacation_balance = available or balance
            elif "sick" in time_off_type_lower:
                sick_balance = available or balance
            elif "personal" in time_off_type_lower:
                personal_balance = available or balance

            # Add to total available
            if available:
                total_available += available

        # Determine as_of_date
        as_of_date = datetime.now().date()
        if balances and balances[0].as_of_date:
            as_of_date = balances[0].as_of_date

        return {
            "worker_id": worker_id,
            "as_of_date": as_of_date,
            "balances": balances,
            "vacation_balance": vacation_balance,
            "sick_balance": sick_balance,
            "personal_balance": personal_balance,
            "total_available_hours": total_available if total_available > 0 else None
        }

    @classmethod
    def parse_time_off_plan_balances_response(
        cls,
        response: Any,
        worker_id: str,
        output_format: Optional[Type[T]] = None
    ) -> Union[TimeOffBalanceModel, T]:
        """
        Parse Get_Time_Off_Plan_Balances response from Absence Management API.

        This parser handles the response from the dedicated Absence Management
        API which has a different structure than Get_Workers.

        Args:
            response: Raw Zeep Get_Time_Off_Plan_Balances response
            worker_id: Worker ID for reference
            output_format: Optional custom model. Defaults to TimeOffBalanceModel.

        Returns:
            Parsed time off balance information
        """
        model_class = output_format or cls.DEFAULT_MODELS["time_off_balance"]

        # Serialize Zeep object to dict
        raw = helpers.serialize_object(response)

        # Navigate to Response_Data
        response_data = raw.get("Response_Data", [])

        # Response_Data is a list of items, each containing Time_Off_Plan_Balance
        balance_items = []
        if isinstance(response_data, list):
            for item in response_data:
                if isinstance(item, dict):
                    # Extract Time_Off_Plan_Balance from each item
                    tof_balance = item.get("Time_Off_Plan_Balance", [])
                    if isinstance(tof_balance, list):
                        balance_items.extend(tof_balance)
                    elif tof_balance:
                        balance_items.append(tof_balance)
        elif isinstance(response_data, dict):
            # Fallback: single dict
            tof_balance = response_data.get("Time_Off_Plan_Balance", [])
            if isinstance(tof_balance, list):
                balance_items.extend(tof_balance)
            elif tof_balance:
                balance_items.append(tof_balance)

        # We'll process all balances for this worker
        all_balances = []
        vacation_balance = None
        sick_balance = None
        personal_balance = None
        total_available = 0.0
        as_of_date = datetime.now().date()

        # Process each Time_Off_Plan_Balance
        for balance_item in balance_items:
            if not isinstance(balance_item, dict):
                continue

            # Extract worker information from Employee_Reference
            employee_ref = balance_item.get("Employee_Reference", {})
            item_worker_id = None
            if employee_ref:
                employee_ids = employee_ref.get("ID", [])
                if isinstance(employee_ids, list):
                    for emp_id in employee_ids:
                        if isinstance(emp_id, dict) and emp_id.get("type") == "Employee_ID":
                            item_worker_id = emp_id.get("_value_1")
                            break

            # Skip if this balance isn't for our worker
            if item_worker_id and item_worker_id != worker_id:
                continue

            # Get the balance data container (note: it's Time_Off_Plan_Balance_Data, not a separate key)
            balance_data_container = balance_item.get("Time_Off_Plan_Balance_Data", {})
            if not isinstance(balance_data_container, dict):
                balance_data_container = {}

            # Get the list of balance records (one per plan)
            balance_records = balance_data_container.get("Time_Off_Plan_Balance_Record", [])
            if not isinstance(balance_records, list):
                balance_records = [balance_records] if balance_records else []

            # Parse each balance record (one per plan)
            for record in balance_records:
                if not isinstance(record, dict):
                    continue

                # Time Off Plan information
                time_off_plan_ref = record.get("Time_Off_Plan_Reference", {})

                # Extract time off plan ID and use it as name if Descriptor is not present
                time_off_type = None
                time_off_type_id = None
                plan_ids = time_off_plan_ref.get("ID", [])
                if isinstance(plan_ids, list):
                    for plan_id in plan_ids:
                        if isinstance(plan_id, dict):
                            if plan_id.get("type") == "Absence_Plan_ID":
                                time_off_type_id = plan_id.get("_value_1")
                                # Use Absence_Plan_ID as the type name if no Descriptor
                                if not time_off_type:
                                    time_off_type = time_off_type_id
                                break
                            elif plan_id.get("type") == "WID" and not time_off_type_id:
                                time_off_type_id = plan_id.get("_value_1")

                # Override with Descriptor if present
                if time_off_plan_ref.get("Descriptor"):
                    time_off_type = time_off_plan_ref.get("Descriptor")

                # Fallback to "Unknown" if still no type found
                if not time_off_type:
                    time_off_type = "Unknown"

                # Unit of time
                unit_ref = record.get("Unit_of_Time_Reference", {})
                unit_ids = unit_ref.get("ID", [])
                balance_unit = "Hours"
                if isinstance(unit_ids, list):
                    for unit_id in unit_ids:
                        if isinstance(unit_id, dict) and unit_id.get("type") == "Unit_of_Time_ID":
                            balance_unit = unit_id.get("_value_1", "Hours")
                            break

                # Balance from position record (can be list or dict)
                position_records = record.get("Time_Off_Plan_Balance_Position_Record", [])

                balance_value = 0.0
                if isinstance(position_records, list) and len(position_records) > 0:
                    position_record = position_records[0]
                    if isinstance(position_record, dict):
                        balance_raw = position_record.get("Time_Off_Plan_Balance")
                        balance_value = cls._parse_float(balance_raw) or 0.0
                elif isinstance(position_records, dict):
                    # Fallback if it's a single dict
                    balance_raw = position_records.get("Time_Off_Plan_Balance")
                    balance_value = cls._parse_float(balance_raw) or 0.0

                # Create TimeOffBalance object
                time_off_balance = TimeOffBalance(
                    time_off_type=time_off_type,
                    time_off_type_id=time_off_type_id,
                    balance=balance_value,
                    balance_unit=balance_unit,
                    scheduled=None,  # Not available in this API
                    available=balance_value,  # Assume full balance is available
                    accrued_ytd=None,
                    used_ytd=None,
                    carryover=None,
                    carryover_limit=None,
                    as_of_date=None,
                    plan_year_start=None,
                    plan_year_end=None
                )

                all_balances.append(time_off_balance)

                # Track quick-access balances
                time_off_type_lower = time_off_type.lower()
                if "vacation" in time_off_type_lower or "pto" in time_off_type_lower:
                    vacation_balance = balance_value
                elif "sick" in time_off_type_lower:
                    sick_balance = balance_value
                elif "personal" in time_off_type_lower:
                    personal_balance = balance_value

                # Add to total available
                total_available += balance_value

        return model_class(
            worker_id=worker_id,
            as_of_date=as_of_date,
            balances=all_balances,
            vacation_balance=vacation_balance,
            sick_balance=sick_balance,
            personal_balance=personal_balance,
            total_available_hours=total_available if total_available > 0 else None
        )

    @staticmethod
    def _parse_float(value: Any) -> Optional[float]:
        """Parse float value from Workday response (similar to flowtask)"""
        from decimal import Decimal

        if value is None:
            return None

        try:
            if isinstance(value, (int, float, Decimal)):
                return float(value)
            elif isinstance(value, str):
                return float(value)
            elif isinstance(value, dict):
                return float(value.get("_value_1", 0))
            return None
        except (ValueError, TypeError):
            return None
