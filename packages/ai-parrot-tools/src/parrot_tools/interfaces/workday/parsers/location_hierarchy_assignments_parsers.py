"""
Parsers for Location Hierarchy Organization Assignments data.
"""

import logging
from typing import Any, Dict, List
from ..utils import ensure_list
from ..models.location_hierarchy_assignments import (
    LocationHierarchyAssignment,
    OrganizationAssignment,
    OrganizationReference,
    OrganizationTypeReference,
    LocationHierarchyReference
)

logger = logging.getLogger(__name__)


def parse_location_hierarchy_reference(reference_data: Dict[str, Any]) -> LocationHierarchyReference:
    """
    Parse location hierarchy reference data.
    
    Args:
        reference_data: Raw location hierarchy reference data
        
    Returns:
        Parsed LocationHierarchyReference object
    """
    try:
        # Extract IDs
        ids = ensure_list(reference_data.get("ID", []))
        location_hierarchy_id = None
        location_hierarchy_wid = None
        
        for id_info in ids:
            if isinstance(id_info, dict):
                id_type = id_info.get("type")
                id_value = id_info.get("_value_1")
                
                if id_type == "WID":
                    location_hierarchy_wid = id_value
                elif id_type == "Organization_Reference_ID":
                    location_hierarchy_id = id_value
        
        # Use location_hierarchy_id as descriptor if no descriptor is provided
        descriptor = reference_data.get("Descriptor")
        if not descriptor and location_hierarchy_id:
            descriptor = location_hierarchy_id
        
        return LocationHierarchyReference(
            location_hierarchy_id=location_hierarchy_id,
            location_hierarchy_descriptor=descriptor,
            location_hierarchy_wid=location_hierarchy_wid
        )
    except Exception as e:
        logger.error(f"Error parsing location hierarchy reference: {e}")
        return LocationHierarchyReference()


def parse_organization_type_reference(type_data: Dict[str, Any]) -> OrganizationTypeReference:
    """
    Parse organization type reference data.
    
    Args:
        type_data: Raw organization type reference data
        
    Returns:
        Parsed OrganizationTypeReference object
    """
    try:
        # Extract IDs
        ids = ensure_list(type_data.get("ID", []))
        organization_type_id = None
        
        for id_info in ids:
            if isinstance(id_info, dict):
                id_type = id_info.get("type")
                id_value = id_info.get("_value_1")
                
                if id_type == "Organization_Type_ID":
                    organization_type_id = id_value
                    break
        
        # Use organization_type_id as descriptor if no descriptor is provided
        descriptor = type_data.get("Descriptor")
        if not descriptor and organization_type_id:
            descriptor = organization_type_id
        
        return OrganizationTypeReference(
            organization_type_id=organization_type_id,
            organization_type_descriptor=descriptor
        )
    except Exception as e:
        logger.error(f"Error parsing organization type reference: {e}")
        return OrganizationTypeReference()


def parse_organization_reference(org_data: Dict[str, Any]) -> OrganizationReference:
    """
    Parse organization reference data.
    
    Args:
        org_data: Raw organization reference data
        
    Returns:
        Parsed OrganizationReference object
    """
    try:
        # Extract IDs
        ids = ensure_list(org_data.get("ID", []))
        organization_id = None
        organization_type = None
        
        for id_info in ids:
            if isinstance(id_info, dict):
                id_type = id_info.get("type")
                id_value = id_info.get("_value_1")
                
                # Store the first non-WID ID as the organization ID
                if id_type != "WID" and organization_id is None:
                    organization_id = id_value
                    organization_type = id_type
        
        return OrganizationReference(
            organization_id=organization_id,
            organization_descriptor=org_data.get("Descriptor"),
            organization_type=organization_type
        )
    except Exception as e:
        logger.error(f"Error parsing organization reference: {e}")
        return OrganizationReference()


def parse_organization_assignment(assignment_data: Dict[str, Any]) -> OrganizationAssignment:
    """
    Parse organization assignment by type data.
    
    Args:
        assignment_data: Raw organization assignment data
        
    Returns:
        Parsed OrganizationAssignment object
    """
    try:
        # Parse organization type reference
        org_type_ref = assignment_data.get("Organization_Type_Reference", {})
        org_type = parse_organization_type_reference(org_type_ref)
        
        # Parse allowed organizations
        allowed_orgs = []
        allowed_org_refs = ensure_list(assignment_data.get("Allowed_Organization_Reference", []))
        
        for org_ref in allowed_org_refs:
            if isinstance(org_ref, dict):
                org = parse_organization_reference(org_ref)
                allowed_orgs.append(org)
        
        return OrganizationAssignment(
            organization_type_id=org_type.organization_type_id,
            organization_type_descriptor=org_type.organization_type_descriptor,
            allowed_organizations=allowed_orgs,
            delete=assignment_data.get("Delete", False)
        )
    except Exception as e:
        logger.error(f"Error parsing organization assignment: {e}")
        return OrganizationAssignment()


def parse_location_hierarchy_assignment(assignment_data: Dict[str, Any]) -> LocationHierarchyAssignment:
    """
    Parse location hierarchy organization assignment data.
    
    Args:
        assignment_data: Raw assignment data from the API (already Location_Hierarchy_Organization_Assignments_Data)
        
    Returns:
        Parsed LocationHierarchyAssignment object
    """
    try:
        logger.debug(f"Parsing assignment_data type: {type(assignment_data)}")
        logger.debug(f"Parsing assignment_data: {assignment_data}")
        
        # assignment_data is already Location_Hierarchy_Organization_Assignments_Data
        assignment_info = assignment_data
        
        # Parse location hierarchy reference
        location_hierarchy_ref = assignment_info.get("Location_Hierarchy_Reference", {})
        location_hierarchy = parse_location_hierarchy_reference(location_hierarchy_ref)
        
        # Parse organization assignments by type
        organization_assignments = []
        assignments_by_type = ensure_list(assignment_info.get("Location_Hierarchy_Organization_Assignments_by_Type_Data", []))
        
        for assignment_type in assignments_by_type:
            if isinstance(assignment_type, dict):
                # Each assignment_type contains an Organization_Type_Reference
                org_type_ref = assignment_type.get("Organization_Type_Reference", {})
                if org_type_ref:
                    org_type = parse_organization_type_reference(org_type_ref)
                    
                    # Create organization assignment with the parsed type
                    assignment = OrganizationAssignment(
                        organization_type_id=org_type.organization_type_id,
                        organization_type_descriptor=org_type.organization_type_descriptor,
                        allowed_organizations=[],  # No allowed organizations in this response
                        delete=False  # No delete flag in this response
                    )
                    organization_assignments.append(assignment)
        
        # Convert Replace_All to boolean, treating None as False
        replace_all_value = assignment_info.get("Replace_All")
        replace_all_bool = bool(replace_all_value) if replace_all_value is not None else False
        
        return LocationHierarchyAssignment(
            location_hierarchy_id=location_hierarchy.location_hierarchy_id,
            location_hierarchy_descriptor=location_hierarchy.location_hierarchy_descriptor,
            location_hierarchy_wid=location_hierarchy.location_hierarchy_wid,
            organization_assignments=organization_assignments,
            replace_all=replace_all_bool,
            location_hierarchy_reference=location_hierarchy_ref
        )
        
    except Exception as e:
        logger.error(f"Error parsing location hierarchy assignment: {e}")
        logger.error(f"Assignment data that caused error: {assignment_data}")
        return LocationHierarchyAssignment()


def parse_location_hierarchy_assignments_response(response_data: Dict[str, Any]) -> List[LocationHierarchyAssignment]:
    """
    Parse the complete location hierarchy assignments response.
    
    Args:
        response_data: Raw response data from the API
        
    Returns:
        List of parsed LocationHierarchyAssignment objects
    """
    try:
        assignments = []
        
        # Extract assignments from response data
        response_data_section = response_data.get("Response_Data", {})
        assignments_list = ensure_list(response_data_section.get("Location_Hierarchy_Organization_Assignments", []))
        
        for assignment in assignments_list:
            if isinstance(assignment, dict):
                # Extract the data section from the assignment
                assignment_data = assignment.get("Location_Hierarchy_Organization_Assignments_Data", {})
                if assignment_data:
                    parsed_assignment = parse_location_hierarchy_assignment(assignment_data)
                    assignments.append(parsed_assignment)
            elif isinstance(assignment, list):
                # Handle case where assignment is directly a list of data
                for item in assignment:
                    if isinstance(item, dict):
                        parsed_assignment = parse_location_hierarchy_assignment(item)
                        assignments.append(parsed_assignment)
        
        return assignments
        
    except Exception as e:
        logger.error(f"Error parsing location hierarchy assignments response: {e}")
        return []


def parse_response_results(response_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse response results (pagination info).
    
    Args:
        response_data: Raw response data from the API
        
    Returns:
        Dictionary with pagination information
    """
    try:
        results = response_data.get("Response_Results", {})
        return {
            "total_results": results.get("Total_Results"),
            "total_pages": results.get("Total_Pages"),
            "page_results": results.get("Page_Results"),
            "current_page": results.get("Page")
        }
    except Exception as e:
        logger.error(f"Error parsing response results: {e}")
        return {}


def parse_location_hierarchy_assignments_data(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main parser function for location hierarchy assignments data.
    
    Args:
        raw_data: Raw data from the API response
        
    Returns:
        Dictionary with parsed assignments and metadata
    """
    try:
        # Parse assignments
        assignments = parse_location_hierarchy_assignments_response(raw_data)
        
        # Parse response results
        results = parse_response_results(raw_data)
        
        return {
            "assignments": assignments,
            **results
        }
        
    except Exception as e:
        logger.error(f"Error parsing location hierarchy assignments data: {e}")
        return {"assignments": []} 