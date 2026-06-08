"""
Cost Center parsers for Workday Get_Cost_Centers operation.
"""

from typing import Dict, List, Any, Union
from ..utils import ensure_list, extract_by_type


def safe_get_nested(data: Dict, *keys, default=None) -> Any:
    """
    Safely get nested dictionary values.
    
    Args:
        data: Dictionary to traverse
        *keys: Keys to traverse
        default: Default value if key path doesn't exist
        
    Returns:
        Value at key path or default
    """
    current = data
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def parse_integration_id_data(integration_data: Union[List, Dict, None]) -> Dict[str, Any]:
    """
    Parse Integration ID Data from Cost Center response.
    
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


def parse_organization_data(org_data: Dict) -> Dict[str, Any]:
    """
    Parse Organization Data section from Cost Center response.
    
    Args:
        org_data: Organization data from the response
        
    Returns:
        Dictionary with parsed organization information
    """
    if not org_data or not isinstance(org_data, dict):
        return {}
    
    # For Organization_Data, the ID is typically a direct value, not a list
    org_id = org_data.get("ID")
    if isinstance(org_id, list):
        org_id = extract_by_type(org_id, "Organization_Reference_ID")
    
    # Parse Integration ID Data to get additional IDs
    integration_data = parse_integration_id_data(org_data.get("Integration_ID_Data"))
    
    # Visibility WID
    visibility_ids = ensure_list((org_data.get("Organization_Visibility_Reference") or {}).get("ID"))
    visibility_wid = extract_by_type(visibility_ids, "WID") if visibility_ids else None
    
    return {
        "organization_id": org_id,
        "organization_name": org_data.get("Organization_Name"),
        "organization_code": org_data.get("Organization_Code"),
        "include_organization_code_in_name": org_data.get("Include_Organization_Code_in_Name"),
        "organization_active": org_data.get("Organization_Active"),
        "organization_visibility": visibility_wid,
        "external_url": org_data.get("External_URL"),
        "availability_date": org_data.get("Availability_Date"),
        "last_updated_datetime": org_data.get("Last_Updated_Datetime"),
        "inactive_date": org_data.get("Inactive_Date"),
        "inactive": org_data.get("Inactive"),
        **integration_data
    }


def parse_organization_type_data(type_data: Dict) -> Dict[str, Any]:
    """
    Parse Organization Type and Subtype data.
    
    Args:
        type_data: Organization type data from the response
        
    Returns:
        Dictionary with parsed type information
    """
    if not type_data or not isinstance(type_data, dict):
        return {}
    
    org_type_ref = type_data.get("Organization_Type_Reference", {})
    org_type_id_list = ensure_list(org_type_ref.get("ID", [])) if isinstance(org_type_ref, dict) else []
    
    org_subtype_ref = type_data.get("Organization_Subtype_Reference", {})
    org_subtype_id_list = ensure_list(org_subtype_ref.get("ID", [])) if isinstance(org_subtype_ref, dict) else []
    
    return {
        "organization_type": extract_by_type(org_type_id_list, "Organization_Type_ID"),
        "organization_type_id": extract_by_type(org_type_id_list, "WID"),
        "organization_subtype": extract_by_type(org_subtype_id_list, "Organization_Subtype_ID"),
        "organization_subtype_id": extract_by_type(org_subtype_id_list, "WID")
    }


def parse_organization_container_data(container_data: Dict) -> Dict[str, Any]:
    """
    Parse Organization Container data.
    
    Args:
        container_data: Container data from the response
        
    Returns:
        Dictionary with parsed container information
    """
    if not container_data or not isinstance(container_data, dict):
        return {}
    
    container_ref = container_data.get("Organization_Container_Reference", {})
    if not isinstance(container_ref, dict):
        return {}
    
    # Extract IDs - handle both list and single item cases
    id_list = container_ref.get("ID", [])
    if not isinstance(id_list, list):
        id_list = [id_list]
    
    container_id = None
    container_wid = None
    
    for id_item in id_list:
        if isinstance(id_item, dict):
            id_type = id_item.get("type")
            id_value = id_item.get("_value_1") or id_item.get("ID")
            
            if id_type == "Organization_Reference_ID" or id_type == "Custom_Organization_Reference_ID":
                container_id = id_value
            elif id_type == "WID":
                container_wid = id_value
    
    return {
        "container_organization_id": container_id,
        "container_organization_name": container_ref.get("Descriptor"),
        "container_organization_wid": container_wid
    }


def parse_worktags_data(worktags_data: Union[List, Dict, None]) -> List[str]:
    """
    Parse Worktags data.
    
    Args:
        worktags_data: Worktags data from the response
        
    Returns:
        List of worktag IDs
    """
    if not worktags_data:
        return []
    
    worktags = []
    
    if isinstance(worktags_data, dict):
        worktags_data = [worktags_data]
    
    if isinstance(worktags_data, list):
        for item in worktags_data:
            if isinstance(item, dict):
                worktag_ref = item.get("Worktag_Reference", {})
                if isinstance(worktag_ref, dict):
                    id_list = ensure_list(worktag_ref.get("ID", []))
                    worktag_id = extract_by_type(id_list, "Worktag_ID")
                    if worktag_id:
                        worktags.append(worktag_id)
    
    return worktags


def parse_cost_center_reference(cc_ref: Dict) -> Dict[str, str]:
    """
    Parse Cost Center Reference to extract WID and ID.
    
    Args:
        cc_ref: Cost Center Reference data
        
    Returns:
        Dictionary with cost_center_wid and cost_center_id
    """
    result = {"cost_center_wid": None, "cost_center_id": None}
    
    if not cc_ref or not isinstance(cc_ref, dict):
        return result
    
    id_list = ensure_list(cc_ref.get("ID", []))
    if isinstance(id_list, list):
        result["cost_center_wid"] = extract_by_type(id_list, "WID")
        result["cost_center_id"] = extract_by_type(id_list, "Cost_Center_Reference_ID") or extract_by_type(id_list, "Organization_Reference_ID")
    
    return result


def parse_cost_center_data(cost_center: Dict) -> Dict[str, Any]:
    """
    Parse complete Cost Center data from Workday response.
    
    Args:
        cost_center: Cost Center data from Get_Cost_Centers response
        
    Returns:
        Dictionary with all parsed cost center information
    """
    if not cost_center or not isinstance(cost_center, dict):
        return {}
    
    # Extract Cost Center Reference
    cc_reference = cost_center.get("Cost_Center_Reference", {})
    cc_ref_data = parse_cost_center_reference(cc_reference)
    
    # Extract Cost Center Data (guard against list)
    cc_data = cost_center.get("Cost_Center_Data", {}) if isinstance(cost_center.get("Cost_Center_Data", {}), dict) else {}
    
    # Parse Organization Data
    org_data = parse_organization_data(cc_data.get("Organization_Data", {}))
    
    # Parse Organization Type Data
    type_data = parse_organization_type_data(cc_data)
    
    # Parse Organization Container
    container_data = parse_organization_container_data(cc_data)
    
    # Parse Worktags
    worktags = parse_worktags_data(cc_data.get("Worktags_Data"))
    
    # Parse Integration ID Data (exists under Organization_Data)
    integration_data = parse_integration_id_data(cc_data.get("Integration_ID_Data")) if isinstance(cc_data, dict) else {"integration_ids": [], "external_integration_id": None}
    
    # Effective Date
    effective_date = cc_data.get("Effective_Date") if isinstance(cc_data, dict) else None
    
    parsed_data = {
        **cc_ref_data,
        "cost_center_name": cc_reference.get("Descriptor") if isinstance(cc_reference, dict) else None,
        "effective_date": effective_date,
        **org_data,
        **type_data,
        **container_data,
        "worktags": worktags,
        **integration_data
    }
    
    # Backfill missing display fields
    if not parsed_data.get("cost_center_name"):
        parsed_data["cost_center_name"] = parsed_data.get("organization_name")
    if not parsed_data.get("cost_center_code"):
        parsed_data["cost_center_code"] = parsed_data.get("organization_code")
    
    return parsed_data


__all__ = [
    "parse_cost_center_data",
    "parse_cost_center_reference",
    "parse_organization_data",
    "parse_organization_type_data",
    "parse_organization_container_data",
    "parse_worktags_data",
    "parse_integration_id_data",
    "extract_by_type",
    "safe_get_nested"
]