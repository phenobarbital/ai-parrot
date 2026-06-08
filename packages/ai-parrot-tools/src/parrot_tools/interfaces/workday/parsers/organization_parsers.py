import logging
from typing import Any, Dict, List, Union
from collections import OrderedDict

from ..models.organizations import Organization
from ..utils import safe_serialize


logger = logging.getLogger(__name__)


def parse_organization_data(org_data: Union[Dict[str, Any], OrderedDict]) -> Organization:
    """
    Parse organization data from Workday SOAP response.
    
    :param org_data: Raw organization data from Workday
    :return: Parsed Organization model
    """
    try:
        # Convert to dict if needed
        if isinstance(org_data, OrderedDict):
            org_data = dict(org_data)
        
       
        # Extract reference data
        reference_data = org_data.get("Organization_Reference", {}) or {}
        ids_data = reference_data.get("ID", []) or []
        
        # Extract different types of IDs
        organization_id = None
        organization_reference_id = None
        cost_center_reference_id = None
        wid = None
        
        if isinstance(ids_data, list):
            for id_item in ids_data:
                if isinstance(id_item, dict):
                    id_type = id_item.get("type")
                    id_value = id_item.get("_value_1")
                    if id_type == "Organization_Reference_ID":
                        organization_reference_id = id_value
                    elif id_type == "Cost_Center_Reference_ID":
                        cost_center_reference_id = id_value
                    elif id_type == "WID":
                        wid = id_value
            
            # Priority for organization_id
            organization_id = organization_reference_id or cost_center_reference_id or wid
        
        # Extract core organization data
        org_core_data = org_data.get("Organization_Data", {}) or {}
        
        # Basic organization info - these are direct text values in XML
        reference_id = org_core_data.get("Reference_ID")
        name = org_core_data.get("Name")
        description = org_core_data.get("Description")
        organization_code = org_core_data.get("Organization_Code")
        
        # Boolean fields - these come as "0"/"1" strings in XML
        include_manager_in_name_raw = org_core_data.get("Include_Manager_in_Name")
        include_manager_in_name = None
        if include_manager_in_name_raw is not None:
            if isinstance(include_manager_in_name_raw, str):
                include_manager_in_name = include_manager_in_name_raw == "1"
            else:
                include_manager_in_name = bool(include_manager_in_name_raw)
        
        include_organization_code_in_name_raw = org_core_data.get("Include_Organization_Code_in_Name")
        include_organization_code_in_name = None
        if include_organization_code_in_name_raw is not None:
            if isinstance(include_organization_code_in_name_raw, str):
                include_organization_code_in_name = include_organization_code_in_name_raw == "1"
            else:
                include_organization_code_in_name = bool(include_organization_code_in_name_raw)
        
        # Organization type and subtype
        org_type_ref = org_core_data.get("Organization_Type_Reference", {}) or {}
        org_type_ids = org_type_ref.get("ID", []) or []
        organization_type_id = None
        if isinstance(org_type_ids, list):
            for id_item in org_type_ids:
                if isinstance(id_item, dict) and id_item.get("type") == "Organization_Type_ID":
                    organization_type_id = id_item.get("_value_1")
                    break
        
        org_subtype_ref = org_core_data.get("Organization_Subtype_Reference", {}) or {}
        org_subtype_ids = org_subtype_ref.get("ID", []) or []
        organization_subtype_id = None
        if isinstance(org_subtype_ids, list):
            for id_item in org_subtype_ids:
                if isinstance(id_item, dict) and id_item.get("type") == "Organization_Subtype_ID":
                    organization_subtype_id = id_item.get("_value_1")
                    break
        
        # Extract dates
        availability_date = org_core_data.get("Availibility_Date")
        last_updated_datetime = org_core_data.get("Last_Updated_DateTime")
        inactive_date = org_core_data.get("Inactive_Date")
        
        # Convert datetime objects to strings if needed
        if availability_date and hasattr(availability_date, 'isoformat'):
            availability_date = str(availability_date)
        if last_updated_datetime and hasattr(last_updated_datetime, 'isoformat'):
            last_updated_datetime = str(last_updated_datetime)
        if inactive_date and hasattr(inactive_date, 'isoformat'):
            inactive_date = str(inactive_date)
        
        # Status - convert "0"/"1" to boolean
        inactive_raw = org_core_data.get("Inactive")
        inactive = None
        if inactive_raw is not None:
            if isinstance(inactive_raw, str):
                inactive = inactive_raw == "1"
            else:
                inactive = bool(inactive_raw)
        
        # Manager information - not present in basic response
        manager_reference = None
        manager_name = None
        manager_id = None
        
        # Hierarchy data - now available with Include_Hierarchy_Data
        parent_organization_id = None
        parent_organization_name = None
        hierarchy_level = None
        is_top_level = None
        
        hierarchy_data = org_core_data.get("Hierarchy_Data", {}) or {}
        if hierarchy_data:
            # Check if it's a top-level organization
            top_level_ref = hierarchy_data.get("Top-Level_Organization_Reference", {}) or {}
            is_top_level = bool(top_level_ref) if top_level_ref else False
            
            # Get parent organization (Included_In_Organization_Reference)
            included_in_ref = hierarchy_data.get("Included_In_Organization_Reference", []) or []
            if included_in_ref:
                # Handle as list (can be multiple parent organizations)
                if isinstance(included_in_ref, list) and included_in_ref:
                    # Take the first parent organization
                    first_parent = included_in_ref[0]
                    if isinstance(first_parent, dict):
                        included_ids = first_parent.get("ID", []) or []
                        if isinstance(included_ids, list):
                            for id_item in included_ids:
                                if isinstance(id_item, dict) and id_item.get("type") == "Organization_Reference_ID":
                                    parent_organization_id = id_item.get("_value_1")
                                    break
                        parent_organization_name = first_parent.get("Descriptor")
                # Handle as single dictionary (fallback)
                elif isinstance(included_in_ref, dict):
                    included_ids = included_in_ref.get("ID", []) or []
                    if isinstance(included_ids, list):
                        for id_item in included_ids:
                            if isinstance(id_item, dict) and id_item.get("type") == "Organization_Reference_ID":
                                parent_organization_id = id_item.get("_value_1")
                                break
                    parent_organization_name = included_in_ref.get("Descriptor")
        
        # Supervisory data - not present in basic response
        staffing_model = None
        location_reference = None
        staffing_restrictions = []
        available_for_hire = None
        hiring_freeze = None
        
        # Roles data - now available with Include_Roles_Data
        roles = []
        roles_data = org_core_data.get("Roles_Data", {}) or {}
        if roles_data:
            org_role_data = roles_data.get("Organization_Role_Data", []) or []
            if not isinstance(org_role_data, list):
                org_role_data = [org_role_data] if org_role_data else []
            
            for i, role_data in enumerate(org_role_data):
                if role_data:
                    role_ref = role_data.get("Role_Reference", {}) or {}
                    role_ids = role_ref.get("ID", []) or []
                    role_name = None
                    if isinstance(role_ids, list):
                        for id_item in role_ids:
                            if isinstance(id_item, dict) and id_item.get("type") == "Organization_Role_ID":
                                role_name = id_item.get("_value_1")
                                break
                    if role_name:
                        roles.append(role_name)
        
        # External IDs - handle the actual structure
        external_ids = []
        external_ids_data = org_core_data.get("External_IDs_Data", {}) or {}
        if external_ids_data:
            ext_ids_list = external_ids_data.get("ID", []) or []
            if not isinstance(ext_ids_list, list):
                ext_ids_list = [ext_ids_list] if ext_ids_list else []
            
            for ext_id in ext_ids_list:
                if ext_id and isinstance(ext_id, dict):
                    ext_id_value = ext_id.get("_value_1")
                    system_id = ext_id.get("System_ID")
                    if ext_id_value:
                        external_ids.append(f"{system_id}:{ext_id_value}" if system_id else ext_id_value)
        
        # Organization visibility reference
        organization_visibility_ref = org_core_data.get("Organization_Visibility_Reference", {}) or {}
        organization_visibility_reference = None
        if organization_visibility_ref:
            visibility_ids = organization_visibility_ref.get("ID", []) or []
            if isinstance(visibility_ids, list):
                for id_item in visibility_ids:
                    if isinstance(id_item, dict) and id_item.get("type") == "WID":
                        organization_visibility_reference = id_item.get("_value_1")
                        break
        
        # Leadership and owner references - not present in basic response
        leadership_reference = []
        organization_owner_reference = None
        external_url_reference = None
        
        # Create Organization model
        organization = Organization(
            # Organization Reference
            organization_id=organization_id,
            organization_name=name,  # Use name from core data
            organization_code=organization_code,
            organization_type=organization_type_id,
            organization_subtype=organization_subtype_id,
            
            # Core Organization Data
            reference_id=reference_id,
            name=name,
            description=description,
            organization_code_data=organization_code,
            include_manager_in_name=include_manager_in_name,
            include_organization_code_in_name=include_organization_code_in_name,
            
            # Type and Subtype References
            organization_type_id=organization_type_id,
            organization_subtype_id=organization_subtype_id,
            
            # Dates
            availability_date=availability_date,
            last_updated_datetime=last_updated_datetime,
            inactive_date=inactive_date,
            
            # Status
            inactive=inactive,
            
            # Manager Information
            manager_reference=manager_reference,
            manager_name=manager_name,
            manager_id=manager_id,
            
            # Hierarchy Data
            parent_organization_id=parent_organization_id,
            parent_organization_name=parent_organization_name,
            hierarchy_level=hierarchy_level,
            is_top_level=is_top_level,
            
            # Supervisory Data
            staffing_model=staffing_model,
            location_reference=location_reference,
            staffing_restrictions=staffing_restrictions,
            available_for_hire=available_for_hire,
            hiring_freeze=hiring_freeze,
            
            # Roles Data
            roles=roles,
            
            # External IDs
            external_ids=external_ids,
            
            # Leadership and Owner References
            leadership_reference=leadership_reference,
            organization_owner_reference=organization_owner_reference,
            organization_visibility_reference=organization_visibility_reference,
            external_url_reference=external_url_reference
        )
        
        return organization
        
    except Exception as e:
        logger.error(f"Error parsing organization data: {e}")
        logger.error(f"Raw data: {safe_serialize(org_data)}")
        raise


def parse_organizations_response(response_data: Dict[str, Any]) -> List[Organization]:
    """
    Parse the complete organizations response from Workday.
    
    :param response_data: Raw response data from Workday
    :return: List of parsed Organization models
    """
    organizations = []
    
    try:
        # Extract organizations from response
        orgs_data = response_data.get("Response_Data", {}).get("Organization", [])
        
        # Ensure it's a list
        if not isinstance(orgs_data, list):
            orgs_data = [orgs_data] if orgs_data else []
        
        # Parse each organization
        for org_data in orgs_data:
            try:
                organization = parse_organization_data(org_data)
                organizations.append(organization)
            except Exception as e:
                logger.error(f"Error parsing individual organization: {e}")
                continue
        
    except Exception as e:
        logger.error(f"Error parsing organizations response: {e}")
        raise
    
    return organizations 