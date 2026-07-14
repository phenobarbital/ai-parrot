---
type: Wiki Summary
title: parrot_tools.google.tools
id: mod:parrot_tools.google.tools
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Migrated Google Tools using the AbstractTool framework.
relates_to:
- concept: class:parrot_tools.google.tools.GoogleLocationArgs
  rel: defines
- concept: class:parrot_tools.google.tools.GoogleLocationTool
  rel: defines
- concept: class:parrot_tools.google.tools.GooglePlaceReviewsArgs
  rel: defines
- concept: class:parrot_tools.google.tools.GooglePlacesBaseTool
  rel: defines
- concept: class:parrot_tools.google.tools.GoogleReviewsTool
  rel: defines
- concept: class:parrot_tools.google.tools.GoogleRouteArgs
  rel: defines
- concept: class:parrot_tools.google.tools.GoogleRoutesTool
  rel: defines
- concept: class:parrot_tools.google.tools.GoogleSearchArgs
  rel: defines
- concept: class:parrot_tools.google.tools.GoogleSearchTool
  rel: defines
- concept: class:parrot_tools.google.tools.GoogleSiteSearchArgs
  rel: defines
- concept: class:parrot_tools.google.tools.GoogleSiteSearchTool
  rel: defines
- concept: class:parrot_tools.google.tools.GoogleTrafficArgs
  rel: defines
- concept: class:parrot_tools.google.tools.GoogleTrafficTool
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.google.tools`

Migrated Google Tools using the AbstractTool framework.

## Classes

- **`GoogleSearchArgs(BaseModel)`** — Arguments schema for Google Search Tool.
- **`GoogleSiteSearchArgs(BaseModel)`** — Arguments schema for Google Site Search Tool.
- **`GoogleLocationArgs(BaseModel)`** — Arguments schema for Google Location Finder.
- **`GoogleRouteArgs(BaseModel)`** — Arguments schema for Google Route Search.
- **`GooglePlaceReviewsArgs(BaseModel)`** — Arguments schema for Google Place Reviews tool.
- **`GoogleTrafficArgs(BaseModel)`** — Arguments schema for Google Place traffic tool.
- **`GooglePlacesBaseTool(AbstractTool)`** — Shared helpers for Google Places based tools.
- **`GoogleSearchTool(AbstractTool)`** — Enhanced Google Search tool with content preview capabilities.
- **`GoogleSiteSearchTool(GoogleSearchTool)`** — Google Site Search tool - extends GoogleSearchTool with site restriction.
- **`GoogleLocationTool(AbstractTool)`** — Google Geocoding tool for location information.
- **`GoogleReviewsTool(GooglePlacesBaseTool)`** — Retrieve reviews, rating, and metadata for a Google Place.
- **`GoogleTrafficTool(GooglePlacesBaseTool)`** — Retrieve Google popular times data to estimate venue traffic.
- **`GoogleRoutesTool(AbstractTool)`** — Google Routes tool using the new Routes API v2.
