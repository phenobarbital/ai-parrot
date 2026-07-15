---
type: Wiki Summary
title: parrot_tools.interfaces.workday.parsers.location_hierarchy_assignments_parsers
id: mod:parrot_tools.interfaces.workday.parsers.location_hierarchy_assignments_parsers
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parsers for Location Hierarchy Organization Assignments data.
relates_to:
- concept: func:parrot_tools.interfaces.workday.parsers.location_hierarchy_assignments_parsers.parse_location_hierarchy_assignment
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.location_hierarchy_assignments_parsers.parse_location_hierarchy_assignments_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.location_hierarchy_assignments_parsers.parse_location_hierarchy_assignments_response
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.location_hierarchy_assignments_parsers.parse_location_hierarchy_reference
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.location_hierarchy_assignments_parsers.parse_organization_assignment
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.location_hierarchy_assignments_parsers.parse_organization_reference
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.location_hierarchy_assignments_parsers.parse_organization_type_reference
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.location_hierarchy_assignments_parsers.parse_response_results
  rel: defines
- concept: mod:parrot_tools.interfaces.workday.models.location_hierarchy_assignments
  rel: references
- concept: mod:parrot_tools.interfaces.workday.utils
  rel: references
---

# `parrot_tools.interfaces.workday.parsers.location_hierarchy_assignments_parsers`

Parsers for Location Hierarchy Organization Assignments data.

## Functions

- `def parse_location_hierarchy_reference(reference_data: Dict[str, Any]) -> LocationHierarchyReference` — Parse location hierarchy reference data.
- `def parse_organization_type_reference(type_data: Dict[str, Any]) -> OrganizationTypeReference` — Parse organization type reference data.
- `def parse_organization_reference(org_data: Dict[str, Any]) -> OrganizationReference` — Parse organization reference data.
- `def parse_organization_assignment(assignment_data: Dict[str, Any]) -> OrganizationAssignment` — Parse organization assignment by type data.
- `def parse_location_hierarchy_assignment(assignment_data: Dict[str, Any]) -> LocationHierarchyAssignment` — Parse location hierarchy organization assignment data.
- `def parse_location_hierarchy_assignments_response(response_data: Dict[str, Any]) -> List[LocationHierarchyAssignment]` — Parse the complete location hierarchy assignments response.
- `def parse_response_results(response_data: Dict[str, Any]) -> Dict[str, Any]` — Parse response results (pagination info).
- `def parse_location_hierarchy_assignments_data(raw_data: Dict[str, Any]) -> Dict[str, Any]` — Main parser function for location hierarchy assignments data.
