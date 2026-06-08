"""
Job Posting Site parsers for Workday Get_Job_Posting_Sites operation.
"""

from typing import Dict, List, Any, Union
from ..utils import ensure_list, extract_by_type


def parse_job_posting_site_reference(site_ref: Dict) -> Dict[str, str]:
    """
    Parse Job Posting Site Reference to extract WID and ID.

    Args:
        site_ref: Job Posting Site Reference data

    Returns:
        Dictionary with job_posting_site_wid, job_posting_site_id, and job_posting_site_name
    """
    result = {
        "job_posting_site_wid": None,
        "job_posting_site_id": None,
        "job_posting_site_name": None
    }

    if not site_ref or not isinstance(site_ref, dict):
        return result

    id_list = ensure_list(site_ref.get("ID", []))
    if isinstance(id_list, list):
        result["job_posting_site_wid"] = extract_by_type(id_list, "WID")
        result["job_posting_site_id"] = extract_by_type(id_list, "Job_Posting_Site_ID")

    result["job_posting_site_name"] = site_ref.get("Descriptor")

    return result


def parse_site_type_data(site_type_ref: Dict) -> Dict[str, str]:
    """
    Parse Site Type Reference data.

    Args:
        site_type_ref: Site Type Reference from the response

    Returns:
        Dictionary with site_type_id and site_type
    """
    if not site_type_ref or not isinstance(site_type_ref, dict):
        return {}

    id_list = ensure_list(site_type_ref.get("ID", []))

    return {
        "site_type_id": extract_by_type(id_list, "Job_Posting_Site_Type_ID"),
        "site_type": site_type_ref.get("Descriptor")
    }


def parse_integration_id_data(integration_data: Union[List, Dict, None]) -> Dict[str, Any]:
    """
    Parse Integration ID Data from Job Posting Site response.

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


def parse_job_posting_site_data(job_posting_site: Dict) -> Dict[str, Any]:
    """
    Parse complete Job Posting Site data from Workday response.

    Args:
        job_posting_site: Job Posting Site data from Get_Job_Posting_Sites response

    Returns:
        Dictionary with all parsed job posting site information
    """
    if not job_posting_site or not isinstance(job_posting_site, dict):
        return {}

    # Extract Job Posting Site Reference
    site_reference = job_posting_site.get("Job_Posting_Site_Reference", {})
    site_ref_data = parse_job_posting_site_reference(site_reference)

    # Extract Job Posting Site Data
    site_data = job_posting_site.get("Job_Posting_Site_Data", {})
    if not isinstance(site_data, dict):
        site_data = {}

    # Parse Site Type
    site_type_ref = site_data.get("Job_Posting_Site_Type_Reference", {})
    site_type_data = parse_site_type_data(site_type_ref)

    # Parse Integration ID Data
    integration_data = parse_integration_id_data(site_data.get("Integration_ID_Data"))

    # Build the complete parsed data
    parsed_data = {
        **site_ref_data,
        **site_type_data,

        # Site Configuration
        "external_url": site_data.get("External_URL") or site_data.get("Site_URL"),
        "site_url": site_data.get("Site_URL"),
        "description": site_data.get("Description") or site_data.get("Site_Description"),
        "instructions": site_data.get("Instructions") or site_data.get("Posting_Instructions"),

        # Status flags
        "is_active": site_data.get("Is_Active") or site_data.get("Active"),
        "is_internal": site_data.get("Is_Internal") or site_data.get("Internal_Site"),
        "is_external": site_data.get("Is_External") or site_data.get("External_Site"),

        # Priority/Order
        "display_order": site_data.get("Display_Order") or site_data.get("Order"),
        "priority": site_data.get("Priority"),

        # Dates
        "created_date": site_data.get("Created_Date") or site_data.get("Created_Moment"),
        "last_updated_date": site_data.get("Last_Updated_Date") or site_data.get("Last_Updated"),

        # Integration IDs
        **integration_data
    }

    return parsed_data


__all__ = [
    "parse_job_posting_site_data",
    "parse_job_posting_site_reference",
    "parse_site_type_data",
    "parse_integration_id_data"
]
