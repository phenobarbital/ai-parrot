---
type: Wiki Summary
title: parrot_tools.interfaces.workday.models.location_hierarchy_assignments
id: mod:parrot_tools.interfaces.workday.models.location_hierarchy_assignments
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic models for Location Hierarchy Organization Assignments.
relates_to:
- concept: class:parrot_tools.interfaces.workday.models.location_hierarchy_assignments.LocationHierarchyAssignment
  rel: defines
- concept: class:parrot_tools.interfaces.workday.models.location_hierarchy_assignments.LocationHierarchyAssignmentsResponse
  rel: defines
- concept: class:parrot_tools.interfaces.workday.models.location_hierarchy_assignments.LocationHierarchyReference
  rel: defines
- concept: class:parrot_tools.interfaces.workday.models.location_hierarchy_assignments.OrganizationAssignment
  rel: defines
- concept: class:parrot_tools.interfaces.workday.models.location_hierarchy_assignments.OrganizationReference
  rel: defines
- concept: class:parrot_tools.interfaces.workday.models.location_hierarchy_assignments.OrganizationTypeReference
  rel: defines
---

# `parrot_tools.interfaces.workday.models.location_hierarchy_assignments`

Pydantic models for Location Hierarchy Organization Assignments.

## Classes

- **`OrganizationReference(BaseModel)`** — Model for organization reference in assignments.
- **`OrganizationTypeReference(BaseModel)`** — Model for organization type reference.
- **`OrganizationAssignment(BaseModel)`** — Model for organization assignment by type.
- **`LocationHierarchyReference(BaseModel)`** — Model for location hierarchy reference.
- **`LocationHierarchyAssignment(BaseModel)`** — Model for location hierarchy organization assignment.
- **`LocationHierarchyAssignmentsResponse(BaseModel)`** — Model for the complete location hierarchy assignments response.
