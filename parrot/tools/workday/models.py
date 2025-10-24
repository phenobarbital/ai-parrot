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
        emails = cls._extract_emails(contact_data)
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

                job_profile = JobProfile(
                    id=profile_id or "",
                    name=job_profile_data.get("Job_Profile_Name", ""),
                    job_family=cls._safe_navigate(job_profile_data, "Job_Family_Reference", "descriptor"),
                    management_level=cls._safe_navigate(job_profile_data, "Management_Level_Reference", "descriptor")
                )

            # Location
            location_data = primary_position.get("Business_Site_Summary_Data", {})
            location = location_data.get("Name") if isinstance(location_data, dict) else None

            # Time type - use safe navigation
            time_type = cls._safe_navigate(primary_position, "Position_Time_Type_Reference", "descriptor")

        # Manager
        manager = None
        manager_data = employment_data.get("Worker_Job_Data", [])
        if manager_data:
            if not isinstance(manager_data, list):
                manager_data = [manager_data]

            if manager_ref := manager_data[0].get("Position_Data", {}).get("Manager_as_of_last_detected_manager_change_Reference"):
                manager = Manager(
                    worker_id=cls._extract_id(manager_ref) or "",
                    name=cls._safe_get(manager_ref, "descriptor", "") or cls._safe_get(manager_ref, "Descriptor", ""),
                    email=None  # Would need separate lookup
                )

        # Organizations
        org_data = worker_data.get("Organization_Data", [])
        if not isinstance(org_data, list):
            org_data = [org_data] if org_data else []

        organizations = [
            org.get("Organization_Data", {}).get("Organization_Name", "")
            for org in org_data
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
        if ids and isinstance(ids[0], dict):
            return ids[0].get("_value_1")

        return None

    @staticmethod
    def _extract_emails(contact_data: Dict[str, Any]) -> List[EmailAddress]:
        """Extract email addresses."""
        emails = []
        email_data = contact_data.get("Email_Address_Data", [])

        if not isinstance(email_data, list):
            email_data = [email_data] if email_data else []

        for email_obj in email_data:
            if email_addr := email_obj.get("Email_Address"):
                # Safe navigation through Usage_Data -> Type_Data nested lists
                email_type = None
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

                        # Extract Primary flag (at usage_item level, not type_data)
                        is_primary = usage_item.get("Primary", False)
                        is_public = usage_item.get("Public", True)

                emails.append(EmailAddress(
                    email=email_addr,
                    type=email_type,
                    primary=is_primary,
                    public=is_public
                ))

        return emails

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
            try:
                return datetime.fromisoformat(date_value.replace('Z', '+00:00')).date()
            except Exception:
                pass

        return None
