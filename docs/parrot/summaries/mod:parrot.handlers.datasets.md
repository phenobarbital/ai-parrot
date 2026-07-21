---
type: Wiki Summary
title: parrot.handlers.datasets
id: mod:parrot.handlers.datasets
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: HTTP handler for managing user's DatasetManager.
relates_to:
- concept: class:parrot.handlers.datasets.DatasetManagerHandler
  rel: defines
- concept: mod:parrot.handlers.user_objects
  rel: references
- concept: mod:parrot.models.datasets
  rel: references
- concept: mod:parrot.tools.dataset_manager
  rel: references
---

# `parrot.handlers.datasets`

HTTP handler for managing user's DatasetManager.

Provides REST endpoints for dataset operations:
- GET    /api/v1/agents/datasets/{agent_id}              - List datasets
- PATCH  /api/v1/agents/datasets/{agent_id}              - Activate/deactivate dataset
- PUT    /api/v1/agents/datasets/{agent_id}              - Upload Excel/CSV file
- POST   /api/v1/agents/datasets/{agent_id}              - Add SQL query or query slug
- DELETE /api/v1/agents/datasets/{agent_id}              - Delete dataset
- GET    /api/v1/agents/datasets/{agent_id}/{dataset_id} - Describe a single dataset

## Classes

- **`DatasetManagerHandler(BaseView)`** — HTTP handler for managing a user's DatasetManager via REST API.
