"""
Job Posting parsers for Workday Get_Job_Postings operation.
"""

from typing import Dict, List, Any, Union
from ..utils import ensure_list, extract_by_type


def coalesce(*args):
    """
    Return the first non-None value from the arguments.
    Unlike `or`, this properly handles falsy values like 0 and False.
    """
    for arg in args:
        if arg is not None:
            return arg
    return None


def parse_job_posting_reference(jp_ref: Dict) -> Dict[str, str]:
    """
    Parse Job Posting Reference to extract WID and ID.

    Args:
        jp_ref: Job Posting Reference data

    Returns:
        Dictionary with job_posting_wid, job_posting_id, and job_posting_name
    """
    result = {"job_posting_wid": None, "job_posting_id": None, "job_posting_name": None}

    if not jp_ref or not isinstance(jp_ref, dict):
        return result

    id_list = ensure_list(jp_ref.get("ID", []))
    if isinstance(id_list, list):
        result["job_posting_wid"] = extract_by_type(id_list, "WID")
        result["job_posting_id"] = extract_by_type(id_list, "Job_Posting_ID")

    result["job_posting_name"] = jp_ref.get("Descriptor")

    return result


def parse_job_requisition_reference(jr_ref: Dict) -> Dict[str, str]:
    """
    Parse Job Requisition Reference from Job Posting.

    Args:
        jr_ref: Job Requisition Reference data

    Returns:
        Dictionary with job_requisition_wid, job_requisition_id, and job_requisition_name
    """
    result = {"job_requisition_wid": None, "job_requisition_id": None, "job_requisition_name": None}

    if not jr_ref or not isinstance(jr_ref, dict):
        return result

    id_list = ensure_list(jr_ref.get("ID", []))
    if isinstance(id_list, list):
        result["job_requisition_wid"] = extract_by_type(id_list, "WID")
        result["job_requisition_id"] = (
            extract_by_type(id_list, "Job_Requisition_ID") or
            extract_by_type(id_list, "Requisition_ID")
        )

    result["job_requisition_name"] = jr_ref.get("Descriptor")

    return result


def parse_job_posting_sites(sites_data: Union[List, Dict, None]) -> Dict[str, List[str]]:
    """
    Parse Job Posting Sites data.

    Args:
        sites_data: Job Posting Sites data from response

    Returns:
        Dictionary with lists of site names and IDs
    """
    result = {
        "job_posting_sites": [],
        "job_posting_site_ids": []
    }

    if not sites_data:
        return result

    # Ensure it's a list
    sites_list = sites_data if isinstance(sites_data, list) else [sites_data]

    for site_item in sites_list:
        if not isinstance(site_item, dict):
            continue

        # Get site reference
        site_ref = site_item.get("Job_Posting_Site_Reference", {})
        if not isinstance(site_ref, dict):
            continue

        # Extract site name
        site_name = site_ref.get("Descriptor")
        if site_name:
            result["job_posting_sites"].append(site_name)

        # Extract site ID
        id_list = ensure_list(site_ref.get("ID", []))
        site_id = extract_by_type(id_list, "Job_Posting_Site_ID") or extract_by_type(id_list, "WID")
        if site_id:
            result["job_posting_site_ids"].append(site_id)

    return result


def parse_location_data(location_ref: Dict) -> Dict[str, Any]:
    """
    Parse Location Reference data.

    Args:
        location_ref: Location Reference from the response

    Returns:
        Dictionary with parsed location information
    """
    if not location_ref or not isinstance(location_ref, dict):
        return {}

    id_list = ensure_list(location_ref.get("ID", []))

    return {
        "location_id": extract_by_type(id_list, "Location_ID"),
        "location_wid": extract_by_type(id_list, "WID"),
        "location_name": location_ref.get("Descriptor")
    }


def parse_supervisory_organization_data(org_ref: Dict) -> Dict[str, Any]:
    """
    Parse Supervisory Organization Reference data.

    Args:
        org_ref: Organization Reference from the response

    Returns:
        Dictionary with parsed organization information
    """
    if not org_ref or not isinstance(org_ref, dict):
        return {}

    id_list = ensure_list(org_ref.get("ID", []))

    return {
        "supervisory_organization_id": extract_by_type(id_list, "Organization_Reference_ID"),
        "supervisory_organization_wid": extract_by_type(id_list, "WID"),
        "supervisory_organization_name": org_ref.get("Descriptor")
    }


def parse_job_profile_data(job_profile_ref: Dict) -> Dict[str, Any]:
    """
    Parse Job Profile Reference data.

    Args:
        job_profile_ref: Job Profile Reference from the response

    Returns:
        Dictionary with parsed job profile information
    """
    if not job_profile_ref or not isinstance(job_profile_ref, dict):
        return {}

    id_list = ensure_list(job_profile_ref.get("ID", []))

    return {
        "job_profile_id": extract_by_type(id_list, "Job_Profile_ID"),
        "job_profile_wid": extract_by_type(id_list, "WID"),
        "job_profile_name": job_profile_ref.get("Descriptor")
    }


def parse_worker_type_data(worker_type_ref: Dict) -> Dict[str, Any]:
    """
    Parse Worker Type Reference data.

    Args:
        worker_type_ref: Worker Type Reference from the response

    Returns:
        Dictionary with parsed worker type information
    """
    if not worker_type_ref or not isinstance(worker_type_ref, dict):
        return {}

    id_list = ensure_list(worker_type_ref.get("ID", []))

    return {
        "worker_type_id": extract_by_type(id_list, "Worker_Type_ID") or extract_by_type(id_list, "Employee_Type_ID"),
        "worker_type_wid": extract_by_type(id_list, "WID"),
        "worker_type_name": worker_type_ref.get("Descriptor")
    }


def parse_integration_id_data(integration_data: Union[List, Dict, None]) -> Dict[str, Any]:
    """
    Parse Integration ID Data from Job Posting response.

    Args:
        integration_data: Integration ID data from the response

    Returns:
        Dictionary with parsed integration data
    """
    result = {
        "integration_ids": [],
        "external_integration_id": None
    }

    if not integration_data:
        return result

    # Handle both dict and list cases
    id_items = []
    if isinstance(integration_data, dict):
        id_items = integration_data.get("ID", [])
        if not isinstance(id_items, list):
            id_items = [id_items]
    elif isinstance(integration_data, list):
        id_items = integration_data

    for id_item in id_items:
        if isinstance(id_item, dict):
            # Handle structured ID objects
            id_value = id_item.get("_value_1") or id_item.get("ID")
            system_id = id_item.get("System_ID")

            if id_value:
                result["integration_ids"].append(str(id_value))
                if system_id == "WD-WID" and not result["external_integration_id"]:
                    result["external_integration_id"] = str(id_value)
        elif id_item:
            # Handle direct text IDs
            result["integration_ids"].append(str(id_item))
            if not result["external_integration_id"]:
                result["external_integration_id"] = str(id_item)

    return result


def parse_qualifications_data(qualifications_data: Union[List, Dict, None]) -> Dict[str, List[str]]:
    """
    Parse Qualifications data (competencies).

    Args:
        qualifications_data: Qualifications data from the response

    Returns:
        Dictionary with lists of competencies
    """
    result = {
        "competencies": []
    }

    if not qualifications_data:
        return result

    # Parse Competency_Data (can be list or dict)
    competency_data = qualifications_data.get("Competency_Data") if isinstance(qualifications_data, dict) else None
    if competency_data:
        if isinstance(competency_data, dict):
            competency_data = [competency_data]

        for comp_item in competency_data:
            if isinstance(comp_item, dict):
                # Navigate to Competency_Profile_Data
                profile_data = comp_item.get("Competency_Profile_Data", {})
                if isinstance(profile_data, dict):
                    comp_ref = profile_data.get("Competency_Reference", {})
                    if isinstance(comp_ref, dict):
                        # Try to get ID with type Competency_ID
                        id_list = ensure_list(comp_ref.get("ID", []))
                        competency_name = extract_by_type(id_list, "Competency_ID")
                        if not competency_name:
                            # Fallback to Descriptor
                            competency_name = comp_ref.get("Descriptor")
                        if competency_name:
                            result["competencies"].append(competency_name)

    return result


def parse_job_posting_data(job_posting: Dict) -> Dict[str, Any]:
    """
    Parse complete Job Posting data from Workday response.

    Args:
        job_posting: Job Posting data from Get_Job_Postings response

    Returns:
        Dictionary with all parsed job posting information
    """
    if not job_posting or not isinstance(job_posting, dict):
        return {}

    # Extract Job Posting Reference
    jp_reference = job_posting.get("Job_Posting_Reference", {})
    jp_ref_data = parse_job_posting_reference(jp_reference)

    # Extract Job Posting Data
    jp_data = job_posting.get("Job_Posting_Data", {})
    if not isinstance(jp_data, dict):
        jp_data = {}

    # Parse Job Posting Status
    status_ref = jp_data.get("Job_Posting_Status_Reference", {})
    status_id_list = ensure_list(status_ref.get("ID", [])) if isinstance(status_ref, dict) else []
    status_value = status_ref.get("Descriptor") if isinstance(status_ref, dict) else None
    if not status_value:
        status_value = extract_by_type(status_id_list, "Job_Posting_Status_ID")

    # Parse Job Requisition Reference (parent)
    jr_ref = jp_data.get("Job_Requisition_Reference", {})
    jr_ref_data = parse_job_requisition_reference(jr_ref)

    # Parse Job Posting Sites (can be single dict or list)
    sites_ref = jp_data.get("Job_Posting_Site_Reference")
    if sites_ref:
        sites_list = ensure_list(sites_ref)
        sites_names = []
        sites_ids = []
        for site in sites_list:
            if isinstance(site, dict):
                id_list = ensure_list(site.get("ID", []))
                site_id = extract_by_type(id_list, "Job_Posting_Site_ID") or extract_by_type(id_list, "WID")
                site_name = site.get("Descriptor")
                if site_id:
                    sites_ids.append(site_id)
                if site_name:
                    sites_names.append(site_name)
        sites_info = {
            "job_posting_sites": sites_names,
            "job_posting_site_ids": sites_ids
        }
    else:
        sites_info = {
            "job_posting_sites": [],
            "job_posting_site_ids": []
        }

    # Parse Location from Job_Posting_Location_Data
    location_data = {}
    location_data_section = jp_data.get("Job_Posting_Location_Data", {})
    if isinstance(location_data_section, dict):
        location_ref = location_data_section.get("Primary_Location_Reference", {})
        location_data = parse_location_data(location_ref)

    # Parse Primary Job Posting Location
    primary_job_posting_location_data = {}
    primary_location_ref = jp_data.get("Primary_Job_Posting_Location_Reference", {})
    if isinstance(primary_location_ref, dict):
        id_list = ensure_list(primary_location_ref.get("ID", []))
        primary_job_posting_location_data = {
            "primary_job_posting_location_id": extract_by_type(id_list, "Location_ID"),
            "primary_job_posting_location_wid": extract_by_type(id_list, "WID"),
            "primary_job_posting_location_name": primary_location_ref.get("Descriptor")
        }

    # Extract Hiring_Requirement_Data section (nested)
    hiring_data = jp_data.get("Hiring_Requirement_Data", {})
    if not isinstance(hiring_data, dict):
        hiring_data = {}

    # Extract Job_Requisition_Detail_Data section (nested)
    detail_data = jp_data.get("Job_Requisition_Detail_Data", {})
    if not isinstance(detail_data, dict):
        detail_data = {}

    # Parse Supervisory Organization
    org_ref = jp_data.get("Supervisory_Organization_Reference", {})
    org_data = parse_supervisory_organization_data(org_ref)

    # Parse Job Profile (from Hiring_Requirement_Data OR root)
    job_profile_ref = hiring_data.get("Job_Profile_Reference") or jp_data.get("Job_Profile_Reference", {})
    job_profile_data = parse_job_profile_data(job_profile_ref)

    # Parse Worker Type (from Hiring_Requirement_Data OR root)
    worker_type_ref = hiring_data.get("Worker_Type_Reference") or jp_data.get("Worker_Type_Reference", {})
    worker_type_data = parse_worker_type_data(worker_type_ref)

    # Parse Position Worker Type (from Hiring_Requirement_Data OR root)
    position_worker_type_data = {}
    position_worker_type_ref = hiring_data.get("Position_Worker_Type_Reference") or jp_data.get("Position_Worker_Type_Reference", {})
    if isinstance(position_worker_type_ref, dict):
        id_list = ensure_list(position_worker_type_ref.get("ID", []))
        position_worker_type_data = {
            "position_worker_type_id": extract_by_type(id_list, "Employee_Type_ID"),
            "position_worker_type_wid": extract_by_type(id_list, "WID"),
            "position_worker_type_name": position_worker_type_ref.get("Descriptor")
        }

    # Parse Job Type (Employee Type)
    job_type_data = {}
    job_type_ref = jp_data.get("Job_Type_Reference", {})
    if isinstance(job_type_ref, dict):
        id_list = ensure_list(job_type_ref.get("ID", []))
        job_type_data = {
            "job_type_id": extract_by_type(id_list, "Employee_Type_ID") or extract_by_type(id_list, "Job_Type_ID"),
            "job_type_wid": extract_by_type(id_list, "WID"),
            "job_type_name": job_type_ref.get("Descriptor")
        }

    # Parse Time Type (from Hiring_Requirement_Data OR root)
    time_type_data = {}
    time_type_ref = hiring_data.get("Time_Type_Reference") or jp_data.get("Time_Type_Reference", {})
    if isinstance(time_type_ref, dict):
        id_list = ensure_list(time_type_ref.get("ID", []))
        time_type_data = {
            "time_type_id": extract_by_type(id_list, "Position_Time_Type_ID") or extract_by_type(id_list, "Time_Type_ID"),
            "time_type_name": time_type_ref.get("Descriptor")
        }

    # Parse Job Family (can come as list - pattern from worker_parsers.py line 870-875)
    job_family_data = {}
    job_family_ref = jp_data.get("Job_Family_Reference")
    if job_family_ref:
        # Handle both dict and list cases
        if isinstance(job_family_ref, list):
            job_family_ref = job_family_ref[0] if job_family_ref else {}
        if isinstance(job_family_ref, dict):
            id_list = ensure_list(job_family_ref.get("ID", []))
            job_family_data = {
                "job_family_id": extract_by_type(id_list, "Job_Family_ID"),
                "job_family_wid": extract_by_type(id_list, "WID"),
                "job_family_name": job_family_ref.get("Descriptor")
            }

    # Parse Job Family Group (can come as list, XML uses Job_Family_ID type not Job_Family_Group_ID)
    job_family_group_data = {}
    job_family_group_ref = jp_data.get("Job_Family_Group_Reference")
    if job_family_group_ref:
        # Handle both dict and list cases
        if isinstance(job_family_group_ref, list):
            job_family_group_ref = job_family_group_ref[0] if job_family_group_ref else {}
        if isinstance(job_family_group_ref, dict):
            id_list = ensure_list(job_family_group_ref.get("ID", []))
            job_family_group_data = {
                "job_family_group_id": extract_by_type(id_list, "Job_Family_Group_ID") or extract_by_type(id_list, "Job_Family_ID"),
                "job_family_group_wid": extract_by_type(id_list, "WID"),
                "job_family_group_name": job_family_group_ref.get("Descriptor")
            }

    # Parse Job Application Template (from Job_Requisition_Detail_Data OR root)
    job_app_template_data = {}
    job_app_template_ref = detail_data.get("Job_Application_Template_Reference") or jp_data.get("Job_Application_Template_Reference", {})
    if isinstance(job_app_template_ref, dict):
        id_list = ensure_list(job_app_template_ref.get("ID", []))
        job_app_template_data = {
            "job_application_template_id": extract_by_type(id_list, "Job_Application_Template_Reference_ID"),
            "job_application_template_wid": extract_by_type(id_list, "WID"),
            "job_application_template_name": job_app_template_ref.get("Descriptor")
        }

    # Parse Primary Job Posting Location from Hiring_Requirement_Data (overrides root if exists)
    if hiring_data.get("Primary_Job_Posting_Location_Reference"):
        primary_location_ref = hiring_data.get("Primary_Job_Posting_Location_Reference", {})
        if isinstance(primary_location_ref, dict):
            id_list = ensure_list(primary_location_ref.get("ID", []))
            primary_job_posting_location_data = {
                "primary_job_posting_location_id": extract_by_type(id_list, "Location_ID"),
                "primary_job_posting_location_wid": extract_by_type(id_list, "WID"),
                "primary_job_posting_location_name": primary_location_ref.get("Descriptor")
            }

    # Parse Integration ID Data
    integration_data = parse_integration_id_data(jp_data.get("Integration_ID_Data"))

    # Parse Qualifications (Competencies)
    qualifications_info = parse_qualifications_data(jp_data.get("Qualification_Data"))

    # Build the complete parsed data
    parsed_data = {
        **jp_ref_data,
        **jr_ref_data,
        "job_posting_status": status_value,
        "job_posting_status_id": extract_by_type(status_id_list, "Job_Posting_Status_ID"),

        # Job Posting Details
        "job_posting_title": jp_data.get("Job_Posting_Title") or jp_data.get("Posting_Title"),
        "job_description": jp_data.get("Job_Posting_Description") or jp_data.get("Job_Description"),
        "external_job_description": jp_data.get("External_Job_Description"),
        "posting_instructions": jp_data.get("Posting_Instructions"),

        # External URLs and paths
        "external_url": jp_data.get("External_URL") or jp_data.get("Job_Posting_URL"),
        "external_application_url": jp_data.get("External_Application_URL"),
        "external_job_path": jp_data.get("External_Job_Path"),
        "external_apply_url": jp_data.get("External_Apply_URL"),

        # Dates (from root OR Hiring_Requirement_Data)
        "posting_date": jp_data.get("Posting_Date"),
        "removal_date": jp_data.get("Removal_Date"),
        "job_posting_start_date": jp_data.get("Job_Posting_Start_Date"),
        "job_posting_end_date": jp_data.get("Job_Posting_End_Date"),
        "expiration_date": jp_data.get("Expiration_Date"),
        "created_date": jp_data.get("Created_Date") or jp_data.get("Created_Moment"),
        "last_updated_date": jp_data.get("Last_Updated_Date") or jp_data.get("Last_Updated"),
        "recruiting_start_date": coalesce(hiring_data.get("Recruiting_Start_Date"), jp_data.get("Recruiting_Start_Date")),
        "target_hire_date": coalesce(hiring_data.get("Target_Hire_Date"), jp_data.get("Target_Hire_Date")),

        # Job Posting Sites
        **sites_info,

        # Location, Organization, Profile, Worker Type
        **location_data,
        **primary_job_posting_location_data,
        **org_data,
        **job_profile_data,
        **worker_type_data,
        **position_worker_type_data,
        **job_type_data,
        **time_type_data,
        **job_family_data,
        **job_family_group_data,
        **job_app_template_data,

        # Posting flags (from root OR Job_Requisition_Detail_Data OR Hiring_Requirement_Data)
        # Using coalesce to handle falsy values like 0 and False correctly
        "is_posted": jp_data.get("Is_Posted") or jp_data.get("Posted"),
        "is_internal": jp_data.get("Is_Internal") or jp_data.get("Internal_Posting"),
        "is_external": jp_data.get("Is_External") or jp_data.get("External_Posting"),
        "primary_posting": jp_data.get("Primary_Posting"),
        "spotlight_job": coalesce(hiring_data.get("Spotlight_Job"), jp_data.get("Spotlight_Job")),
        "available_for_recruiting": coalesce(detail_data.get("Available_for_Recruiting"), jp_data.get("Available_for_Recruiting")),
        "confidential_job_requisition": coalesce(detail_data.get("Confidential_Job_Requisition"), jp_data.get("Confidential_Job_Requisition")),
        "academic_tenure_eligible": coalesce(detail_data.get("Academic_Tenure_Eligible"), jp_data.get("Academic_Tenure_Eligible")),

        # Number of openings (from Job_Requisition_Detail_Data OR root)
        # Apply explicit int conversion for 0 values (worker_parsers.py pattern)
        "number_of_openings": int(detail_data.get("Number_of_Openings")) if detail_data.get("Number_of_Openings") is not None else (int(jp_data.get("Number_of_Openings")) if jp_data.get("Number_of_Openings") is not None else None),
        "positions_allocated": int(detail_data.get("Positions_Allocated")) if detail_data.get("Positions_Allocated") is not None else (int(jp_data.get("Positions_Allocated")) if jp_data.get("Positions_Allocated") is not None else None),
        "positions_available": int(detail_data.get("Positions_Available")) if detail_data.get("Positions_Available") is not None else (int(jp_data.get("Positions_Available")) if jp_data.get("Positions_Available") is not None else None),

        # Additional fields - Apply float conversion for numeric values (worker_parsers.py pattern)
        "forecasted_payout": float(jp_data.get("Forecasted_Payout")) if jp_data.get("Forecasted_Payout") is not None else None,
        "scheduled_weekly_hours": float(hiring_data.get("Scheduled_Weekly_Hours")) if hiring_data.get("Scheduled_Weekly_Hours") is not None else (float(jp_data.get("Scheduled_Weekly_Hours")) if jp_data.get("Scheduled_Weekly_Hours") is not None else None),

        # Qualifications
        **qualifications_info,

        # Integration IDs
        **integration_data
    }

    return parsed_data


__all__ = [
    "parse_job_posting_data",
    "parse_job_posting_reference",
    "parse_job_requisition_reference",
    "parse_job_posting_sites",
    "parse_location_data",
    "parse_supervisory_organization_data",
    "parse_job_profile_data",
    "parse_worker_type_data",
    "parse_integration_id_data",
    "parse_qualifications_data"
]
