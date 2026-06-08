"""
Pydantic models for Location Hierarchy Organization Assignments.
"""

from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field


class OrganizationReference(BaseModel):
    """Model for organization reference in assignments."""
    organization_id: Optional[str] = Field(None, description="Organization ID")
    organization_descriptor: Optional[str] = Field(None, description="Organization descriptor")
    organization_type: Optional[str] = Field(None, description="Type of organization reference")


class OrganizationTypeReference(BaseModel):
    """Model for organization type reference."""
    organization_type_id: Optional[str] = Field(None, description="Organization type ID")
    organization_type_descriptor: Optional[str] = Field(None, description="Organization type descriptor")


class OrganizationAssignment(BaseModel):
    """Model for organization assignment by type."""
    organization_type_id: Optional[str] = Field(None, description="Organization type ID")
    organization_type_descriptor: Optional[str] = Field(None, description="Organization type descriptor")
    allowed_organizations: List[OrganizationReference] = Field(default_factory=list, description="List of allowed organizations")
    delete: bool = Field(False, description="Whether to delete this assignment")


class LocationHierarchyReference(BaseModel):
    """Model for location hierarchy reference."""
    location_hierarchy_id: Optional[str] = Field(None, description="Location hierarchy ID")
    location_hierarchy_descriptor: Optional[str] = Field(None, description="Location hierarchy descriptor")
    location_hierarchy_wid: Optional[str] = Field(None, description="Location hierarchy WID")


class LocationHierarchyAssignment(BaseModel):
    """Model for location hierarchy organization assignment."""
    location_hierarchy_id: Optional[str] = Field(None, description="Location hierarchy ID")
    location_hierarchy_descriptor: Optional[str] = Field(None, description="Location hierarchy descriptor")
    location_hierarchy_wid: Optional[str] = Field(None, description="Location hierarchy WID")
    organization_assignments: List[OrganizationAssignment] = Field(default_factory=list, description="Organization assignments by type")
    replace_all: bool = Field(False, description="Whether to replace all assignments")
    location_hierarchy_reference: Optional[Dict[str, Any]] = Field(None, description="Raw location hierarchy reference data")


class LocationHierarchyAssignmentsResponse(BaseModel):
    """Model for the complete location hierarchy assignments response."""
    assignments: List[LocationHierarchyAssignment] = Field(default_factory=list, description="List of location hierarchy assignments")
    total_results: Optional[int] = Field(None, description="Total number of results")
    total_pages: Optional[int] = Field(None, description="Total number of pages")
    page_results: Optional[int] = Field(None, description="Number of results in current page")
    current_page: Optional[int] = Field(None, description="Current page number") 