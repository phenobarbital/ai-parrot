---
type: Wiki Summary
title: parrot.handlers.dashboard_handler
id: mod:parrot.handlers.dashboard_handler
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: REST API Handler for Dashboard Persistence.
relates_to:
- concept: class:parrot.handlers.dashboard_handler.DashboardHandler
  rel: defines
- concept: class:parrot.handlers.dashboard_handler.DashboardTabHandler
  rel: defines
- concept: mod:parrot.interfaces.documentdb
  rel: references
---

# `parrot.handlers.dashboard_handler`

REST API Handler for Dashboard Persistence.

Provides CRUD endpoints for managing dashboards and dashboard tabs
using DocumentDB (MongoDB) as the persistence layer.

Endpoints:
    GET    /api/v1/dashboards                         — list all dashboards
    GET    /api/v1/dashboards/{dashboard_id}          — get single dashboard
    POST   /api/v1/dashboards                         — create new dashboard
    PUT    /api/v1/dashboards/{dashboard_id}          — update existing dashboard
    PATCH  /api/v1/dashboards/{dashboard_id}          — partial update
    DELETE /api/v1/dashboards/{dashboard_id}          — delete dashboard

    GET    /api/v1/dashboards/{dashboard_id}/tabs              — list tabs
    POST   /api/v1/dashboards/{dashboard_id}/tabs              — create tab
    PUT    /api/v1/dashboards/{dashboard_id}/tabs/{tab_id}     — update tab
    DELETE /api/v1/dashboards/{dashboard_id}/tabs/{tab_id}     — delete tab
    PATCH  /api/v1/dashboards/{dashboard_id}/tabs/{tab_id}     — partial tab update

## Classes

- **`DashboardHandler(BaseView)`** — REST API Handler for Dashboard CRUD operations.
- **`DashboardTabHandler(BaseView)`** — REST API Handler for Dashboard Tab CRUD operations.
