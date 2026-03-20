# TASK-121: DatasetManager Request/Response Models

**Feature**: DatasetManager Support for AgentTalk Handler
**Spec**: `sdd/specs/dataset-support-agenttalk.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

> This task implements Module 3 from the spec: DatasetManager Request/Response Models.

Create Pydantic models for all request and response types used by the DatasetManagerHandler endpoints.

---

## Scope

- Create `DatasetAction` enum (activate/deactivate)
- Create `DatasetPatchRequest` model for PATCH endpoint
- Create `DatasetQueryRequest` model for POST endpoint
- Create `DatasetListResponse` model for GET endpoint
- Create `DatasetUploadResponse` model for PUT endpoint

**NOT in scope**:
- HTTP handler implementation (that's TASK-122)
- Endpoint registration (that's TASK-123)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/models/datasets.py` | CREATE | Pydantic models for dataset operations |
| `parrot/models/__init__.py` | MODIFY | Export new models |

---

## Implementation Notes

### Full Model Definitions

```python
# parrot/models/datasets.py
"""Pydantic models for DatasetManager HTTP operations."""
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


class DatasetAction(str, Enum):
    """Actions that can be performed on a dataset."""
    ACTIVATE = "activate"
    DEACTIVATE = "deactivate"


class DatasetPatchRequest(BaseModel):
    """Request model for PATCH /datasets/{agent_id}."""
    dataset_name: str = Field(..., description="Name of the dataset to modify")
    action: DatasetAction = Field(..., description="Action to perform")

    class Config:
        use_enum_values = True


class DatasetQueryRequest(BaseModel):
    """Request model for POST /datasets/{agent_id} (add query)."""
    name: str = Field(..., description="Dataset name/identifier")
    query: Optional[str] = Field(None, description="Raw SQL query")
    query_slug: Optional[str] = Field(None, description="Query slug from QuerySource")
    description: Optional[str] = Field(default="", description="Dataset description")

    def validate_query_source(self) -> None:
        """Ensure exactly one of query or query_slug is provided."""
        if not self.query and not self.query_slug:
            raise ValueError("Either 'query' or 'query_slug' must be provided")
        if self.query and self.query_slug:
            raise ValueError("Provide either 'query' or 'query_slug', not both")


class DatasetListResponse(BaseModel):
    """Response model for GET /datasets/{agent_id}."""
    datasets: List[dict] = Field(..., description="List of DatasetInfo dictionaries")
    total: int = Field(..., description="Total number of datasets")
    active_count: int = Field(..., description="Number of active datasets")


class DatasetUploadResponse(BaseModel):
    """Response model for PUT /datasets/{agent_id}."""
    name: str = Field(..., description="Dataset name assigned")
    rows: int = Field(..., description="Number of rows in the uploaded dataset")
    columns: int = Field(..., description="Number of columns")
    columns_list: List[str] = Field(..., description="List of column names")
    message: str = Field(default="Dataset uploaded successfully")


class DatasetDeleteResponse(BaseModel):
    """Response model for DELETE /datasets/{agent_id}."""
    name: str = Field(..., description="Name of deleted dataset")
    message: str = Field(default="Dataset deleted successfully")


class DatasetErrorResponse(BaseModel):
    """Error response model for dataset operations."""
    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Additional error details")
```

### References in Codebase
- `parrot/models/` — existing Pydantic models
- `parrot/models/responses.py` — similar response model patterns

---

## Acceptance Criteria

- [ ] `DatasetAction` enum defined with ACTIVATE and DEACTIVATE
- [ ] `DatasetPatchRequest` model with validation
- [ ] `DatasetQueryRequest` model with query source validation
- [ ] `DatasetListResponse` model with all fields
- [ ] `DatasetUploadResponse` model with file metadata fields
- [ ] `DatasetDeleteResponse` model
- [ ] `DatasetErrorResponse` model for error cases
- [ ] Models exported from `parrot/models/__init__.py`
- [ ] Unit tests pass: `pytest tests/models/test_dataset_models.py -v`

---

## Test Specification

```python
# tests/models/test_dataset_models.py
import pytest
from pydantic import ValidationError
from parrot.models.datasets import (
    DatasetAction,
    DatasetPatchRequest,
    DatasetQueryRequest,
    DatasetListResponse,
    DatasetUploadResponse,
)


class TestDatasetAction:
    def test_activate_value(self):
        assert DatasetAction.ACTIVATE.value == "activate"

    def test_deactivate_value(self):
        assert DatasetAction.DEACTIVATE.value == "deactivate"


class TestDatasetPatchRequest:
    def test_valid_request(self):
        req = DatasetPatchRequest(
            dataset_name="sales_data",
            action=DatasetAction.ACTIVATE
        )
        assert req.dataset_name == "sales_data"
        assert req.action == DatasetAction.ACTIVATE

    def test_missing_dataset_name_fails(self):
        with pytest.raises(ValidationError):
            DatasetPatchRequest(action=DatasetAction.ACTIVATE)

    def test_missing_action_fails(self):
        with pytest.raises(ValidationError):
            DatasetPatchRequest(dataset_name="test")


class TestDatasetQueryRequest:
    def test_valid_with_query(self):
        req = DatasetQueryRequest(
            name="sales",
            query="SELECT * FROM sales"
        )
        req.validate_query_source()  # Should not raise

    def test_valid_with_slug(self):
        req = DatasetQueryRequest(
            name="sales",
            query_slug="sales_monthly"
        )
        req.validate_query_source()

    def test_neither_query_nor_slug_fails(self):
        req = DatasetQueryRequest(name="test")
        with pytest.raises(ValueError, match="Either 'query' or 'query_slug'"):
            req.validate_query_source()

    def test_both_query_and_slug_fails(self):
        req = DatasetQueryRequest(
            name="test",
            query="SELECT 1",
            query_slug="some_slug"
        )
        with pytest.raises(ValueError, match="not both"):
            req.validate_query_source()


class TestDatasetListResponse:
    def test_valid_response(self):
        resp = DatasetListResponse(
            datasets=[{"name": "df1", "rows": 100}],
            total=1,
            active_count=1
        )
        assert resp.total == 1


class TestDatasetUploadResponse:
    def test_valid_response(self):
        resp = DatasetUploadResponse(
            name="uploaded_file",
            rows=500,
            columns=10,
            columns_list=["a", "b", "c"]
        )
        assert resp.rows == 500
        assert len(resp.columns_list) == 3
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-121-dataset-request-response-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-03
**Notes**:
- Created `parrot/models/datasets.py` with 7 Pydantic models:
  - `DatasetAction` enum (ACTIVATE, DEACTIVATE)
  - `DatasetPatchRequest` for PATCH endpoint
  - `DatasetQueryRequest` with query source validation
  - `DatasetListResponse` for GET endpoint
  - `DatasetUploadResponse` for PUT endpoint
  - `DatasetDeleteResponse` for DELETE endpoint
  - `DatasetErrorResponse` for error cases
- Updated `parrot/models/__init__.py` to export all models
- Created `tests/models/test_dataset_models.py` with 31 comprehensive tests
- All tests passing, linting clean
