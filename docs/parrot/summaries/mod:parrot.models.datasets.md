---
type: Wiki Summary
title: parrot.models.datasets
id: mod:parrot.models.datasets
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pydantic models for DatasetManager HTTP operations.
relates_to:
- concept: class:parrot.models.datasets.DatasetAction
  rel: defines
- concept: class:parrot.models.datasets.DatasetDeleteResponse
  rel: defines
- concept: class:parrot.models.datasets.DatasetErrorResponse
  rel: defines
- concept: class:parrot.models.datasets.DatasetListResponse
  rel: defines
- concept: class:parrot.models.datasets.DatasetPatchRequest
  rel: defines
- concept: class:parrot.models.datasets.DatasetQueryRequest
  rel: defines
- concept: class:parrot.models.datasets.DatasetUploadResponse
  rel: defines
---

# `parrot.models.datasets`

Pydantic models for DatasetManager HTTP operations.

These models define request/response schemas for the DatasetManagerHandler
endpoints that manage session-scoped DatasetManager instances.

Endpoints:
    GET    /datasets/{agent_id} → DatasetListResponse
    PATCH  /datasets/{agent_id} → activate/deactivate datasets
    PUT    /datasets/{agent_id} → upload files → DatasetUploadResponse
    POST   /datasets/{agent_id} → add queries
    DELETE /datasets/{agent_id} → DatasetDeleteResponse

## Classes

- **`DatasetAction(str, Enum)`** — Actions that can be performed on a dataset.
- **`DatasetPatchRequest(BaseModel)`** — Request model for PATCH /datasets/{agent_id}.
- **`DatasetQueryRequest(BaseModel)`** — Request model for POST /datasets/{agent_id} (add query).
- **`DatasetListResponse(BaseModel)`** — Response model for GET /datasets/{agent_id}.
- **`DatasetUploadResponse(BaseModel)`** — Response model for PUT /datasets/{agent_id}.
- **`DatasetDeleteResponse(BaseModel)`** — Response model for DELETE /datasets/{agent_id}.
- **`DatasetErrorResponse(BaseModel)`** — Error response model for dataset operations.
