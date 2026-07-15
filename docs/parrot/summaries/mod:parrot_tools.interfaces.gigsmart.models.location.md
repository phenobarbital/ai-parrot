---
type: Wiki Summary
title: parrot_tools.interfaces.gigsmart.models.location
id: mod:parrot_tools.interfaces.gigsmart.models.location
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pydantic v2 models for GigSmart locations API surface.
relates_to:
- concept: class:parrot_tools.interfaces.gigsmart.models.location.AddOrganizationLocationInput
  rel: defines
- concept: class:parrot_tools.interfaces.gigsmart.models.location.OrganizationLocation
  rel: defines
- concept: class:parrot_tools.interfaces.gigsmart.models.location.PlaceResult
  rel: defines
---

# `parrot_tools.interfaces.gigsmart.models.location`

Pydantic v2 models for GigSmart locations API surface.

## Classes

- **`PlaceResult(BaseModel)`** — A single address suggestion from the placeAutocomplete query.
- **`AddOrganizationLocationInput(BaseModel)`** — Input for the ``addOrganizationLocation`` mutation.
- **`OrganizationLocation(BaseModel)`** — A location belonging to a GigSmart organisation.
