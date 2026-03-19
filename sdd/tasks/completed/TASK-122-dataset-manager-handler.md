# TASK-122: DatasetManagerHandler HTTP Handler

**Feature**: DatasetManager Support for AgentTalk Handler
**Spec**: `sdd/specs/dataset-support-agenttalk.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-6h)
**Depends-on**: TASK-119, TASK-121
**Assigned-to**: null

---

## Context

> This task implements Module 4 from the spec: DatasetManagerHandler.

Create the HTTP handler for managing user's DatasetManager via REST API endpoints at `/api/v1/agents/datasets/{agent_id}`.

---

## Scope

- Create `DatasetManagerHandler` class inheriting from `BaseView`
- Implement GET endpoint (list datasets with optional EDA)
- Implement PATCH endpoint (activate/deactivate dataset)
- Implement PUT endpoint (upload Excel/CSV file)
- Implement POST endpoint (add SQL query or query slug)
- Implement DELETE endpoint (remove dataset)
- Use `UserObjectsHandler` to get/create session-scoped DatasetManager

**NOT in scope**:
- Route registration (that's TASK-123)
- Streaming uploads for very large files (P2)
- WebSocket notifications (P2)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/datasets.py` | CREATE | DatasetManagerHandler class |

---

## Implementation Notes

### Handler Structure

```python
# parrot/handlers/datasets.py
"""HTTP handler for managing user's DatasetManager."""
from __future__ import annotations
from typing import Dict, Any, TYPE_CHECKING
from io import BytesIO
import pandas as pd
from aiohttp import web
from pydantic import ValidationError
from datamodel.parsers.json import json_encoder
from navconfig.logging import logging
from navigator_session import get_session
from navigator_auth.decorators import is_authenticated, user_session
from navigator.views import BaseView
from .user_objects import UserObjectsHandler
from ..models.datasets import (
    DatasetAction,
    DatasetPatchRequest,
    DatasetQueryRequest,
    DatasetListResponse,
    DatasetUploadResponse,
    DatasetDeleteResponse,
    DatasetErrorResponse,
)
from ..tools.dataset_manager import DatasetManager

if TYPE_CHECKING:
    from ..manager import BotManager


# Maximum file size: 50MB
MAX_FILE_SIZE = 50 * 1024 * 1024


@is_authenticated()
@user_session()
class DatasetManagerHandler(BaseView):
    """
    HTTP handler for managing user's DatasetManager via REST API.

    Endpoints:
        GET    /api/v1/agents/datasets/{agent_id} - List datasets
        PATCH  /api/v1/agents/datasets/{agent_id} - Activate/deactivate dataset
        PUT    /api/v1/agents/datasets/{agent_id} - Upload file as dataset
        POST   /api/v1/agents/datasets/{agent_id} - Add query as dataset
        DELETE /api/v1/agents/datasets/{agent_id} - Delete dataset
    """

    _user_objects_handler: UserObjectsHandler = None

    @property
    def user_objects_handler(self) -> UserObjectsHandler:
        if self._user_objects_handler is None:
            self._user_objects_handler = UserObjectsHandler(logger=self.logger)
        return self._user_objects_handler

    async def _get_dataset_manager(self, agent_id: str) -> DatasetManager:
        """Get or create user's DatasetManager from session."""
        request_session = await get_session(self.request)
        session_key = self.user_objects_handler.get_session_key(
            agent_id, "dataset_manager"
        )

        dm = request_session.get(session_key)
        if dm and isinstance(dm, DatasetManager):
            return dm

        # Create new DatasetManager
        dm = DatasetManager()
        request_session[session_key] = dm
        return dm

    async def get(self) -> web.Response:
        """
        List all datasets in user's DatasetManager.

        Query params:
            eda: bool - Include EDA metadata (default: false)

        Returns:
            DatasetListResponse with dataset information
        """
        agent_id = self.request.match_info.get('agent_id')
        if not agent_id:
            return self.json_response(
                {"error": "agent_id is required"},
                status=400
            )

        include_eda = self.request.query.get('eda', '').lower() == 'true'

        try:
            dm = await self._get_dataset_manager(agent_id)
            datasets_info = dm.list_datasets()

            datasets = []
            for name, info in datasets_info.items():
                dataset_dict = {
                    "name": name,
                    "description": info.get("description", ""),
                    "shape": info.get("shape", (0, 0)),
                    "is_active": info.get("is_active", True),
                    "loaded": info.get("loaded", False),
                }

                if include_eda and info.get("loaded"):
                    try:
                        metadata = dm.get_metadata(name, include_eda=True)
                        dataset_dict["metadata"] = metadata
                    except Exception as e:
                        self.logger.warning(f"Failed to get EDA for {name}: {e}")

                datasets.append(dataset_dict)

            response = DatasetListResponse(
                datasets=datasets,
                total=len(datasets),
                active_count=sum(1 for d in datasets if d.get("is_active", True))
            )
            return self.json_response(response.dict())

        except Exception as e:
            self.logger.error(f"Error listing datasets: {e}")
            return self.json_response(
                {"error": str(e)},
                status=500
            )

    async def patch(self) -> web.Response:
        """
        Activate or deactivate a dataset.

        Body: DatasetPatchRequest
        """
        agent_id = self.request.match_info.get('agent_id')
        if not agent_id:
            return self.json_response(
                {"error": "agent_id is required"},
                status=400
            )

        try:
            data = await self.request.json()
            request = DatasetPatchRequest(**data)
        except ValidationError as e:
            return self.json_response(
                {"error": "Invalid request", "detail": str(e)},
                status=400
            )

        try:
            dm = await self._get_dataset_manager(agent_id)

            if request.action == DatasetAction.ACTIVATE:
                dm.activate(request.dataset_name)
                message = f"Dataset '{request.dataset_name}' activated"
            else:
                dm.deactivate(request.dataset_name)
                message = f"Dataset '{request.dataset_name}' deactivated"

            return self.json_response({
                "name": request.dataset_name,
                "action": request.action,
                "message": message
            })

        except KeyError:
            return self.json_response(
                {"error": f"Dataset '{request.dataset_name}' not found"},
                status=404
            )
        except Exception as e:
            self.logger.error(f"Error patching dataset: {e}")
            return self.json_response(
                {"error": str(e)},
                status=500
            )

    async def put(self) -> web.Response:
        """
        Upload an Excel/CSV file as a new dataset.

        Accepts multipart/form-data with:
            file: The file to upload
            name: Optional dataset name (defaults to filename)
        """
        agent_id = self.request.match_info.get('agent_id')
        if not agent_id:
            return self.json_response(
                {"error": "agent_id is required"},
                status=400
            )

        try:
            reader = await self.request.multipart()
            dataset_name = None
            df = None
            filename = None

            async for field in reader:
                if field.name == 'name':
                    dataset_name = (await field.read()).decode('utf-8')
                elif field.name == 'file':
                    filename = field.filename
                    data = await field.read()

                    if len(data) > MAX_FILE_SIZE:
                        return self.json_response(
                            {"error": f"File too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB"},
                            status=400
                        )

                    # Determine format from extension
                    if filename.endswith(('.xlsx', '.xls')):
                        df = pd.read_excel(BytesIO(data))
                    elif filename.endswith('.csv'):
                        df = pd.read_csv(BytesIO(data))
                    else:
                        return self.json_response(
                            {"error": "Unsupported file format. Use .xlsx, .xls, or .csv"},
                            status=400
                        )

            if df is None:
                return self.json_response(
                    {"error": "No file provided"},
                    status=400
                )

            # Use filename without extension as default name
            if not dataset_name:
                dataset_name = filename.rsplit('.', 1)[0] if filename else "uploaded_dataset"

            dm = await self._get_dataset_manager(agent_id)
            dm.add_dataset(dataset_name, df)

            response = DatasetUploadResponse(
                name=dataset_name,
                rows=len(df),
                columns=len(df.columns),
                columns_list=list(df.columns)
            )
            return self.json_response(response.dict(), status=201)

        except Exception as e:
            self.logger.error(f"Error uploading dataset: {e}")
            return self.json_response(
                {"error": str(e)},
                status=500
            )

    async def post(self) -> web.Response:
        """
        Add a SQL query or query slug as a new dataset.

        Body: DatasetQueryRequest
        """
        agent_id = self.request.match_info.get('agent_id')
        if not agent_id:
            return self.json_response(
                {"error": "agent_id is required"},
                status=400
            )

        try:
            data = await self.request.json()
            request = DatasetQueryRequest(**data)
            request.validate_query_source()
        except ValidationError as e:
            return self.json_response(
                {"error": "Invalid request", "detail": str(e)},
                status=400
            )
        except ValueError as e:
            return self.json_response(
                {"error": str(e)},
                status=400
            )

        try:
            dm = await self._get_dataset_manager(agent_id)

            # Add query or query slug to DatasetManager
            if request.query:
                dm.add_query(
                    name=request.name,
                    query=request.query,
                    description=request.description or ""
                )
            else:
                dm.add_query_slug(
                    name=request.name,
                    slug=request.query_slug,
                    description=request.description or ""
                )

            return self.json_response({
                "name": request.name,
                "type": "query" if request.query else "query_slug",
                "message": f"Query dataset '{request.name}' added successfully"
            }, status=201)

        except Exception as e:
            self.logger.error(f"Error adding query dataset: {e}")
            return self.json_response(
                {"error": str(e)},
                status=500
            )

    async def delete(self) -> web.Response:
        """
        Delete a dataset from the DatasetManager.

        Query params:
            name: str - Dataset name to delete
        """
        agent_id = self.request.match_info.get('agent_id')
        if not agent_id:
            return self.json_response(
                {"error": "agent_id is required"},
                status=400
            )

        dataset_name = self.request.query.get('name')
        if not dataset_name:
            return self.json_response(
                {"error": "Query parameter 'name' is required"},
                status=400
            )

        try:
            dm = await self._get_dataset_manager(agent_id)
            dm.remove_dataset(dataset_name)

            response = DatasetDeleteResponse(name=dataset_name)
            return self.json_response(response.dict())

        except KeyError:
            return self.json_response(
                {"error": f"Dataset '{dataset_name}' not found"},
                status=404
            )
        except Exception as e:
            self.logger.error(f"Error deleting dataset: {e}")
            return self.json_response(
                {"error": str(e)},
                status=500
            )
```

### File Upload Size Limit
Add size limit warning in response if approaching limit.

### References in Codebase
- `parrot/handlers/agent.py` — AgentTalk handler pattern
- `parrot/tools/dataset_manager.py` — DatasetManager API
- `navigator.views.BaseView` — base handler class

---

## Acceptance Criteria

- [ ] `DatasetManagerHandler` class created at `parrot/handlers/datasets.py`
- [ ] GET endpoint returns list of datasets with correct schema
- [ ] GET endpoint supports `eda=true` query parameter
- [ ] PATCH endpoint activates/deactivates datasets
- [ ] PUT endpoint uploads Excel files (.xlsx, .xls)
- [ ] PUT endpoint uploads CSV files (.csv)
- [ ] PUT endpoint enforces 50MB file size limit
- [ ] POST endpoint adds SQL queries
- [ ] POST endpoint adds query slugs
- [ ] DELETE endpoint removes datasets
- [ ] DELETE returns 404 for non-existent datasets
- [ ] All endpoints use session-scoped DatasetManager
- [ ] Unit tests pass: `pytest tests/handlers/test_dataset_handler.py -v`

---

## Test Specification

```python
# tests/handlers/test_dataset_handler.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from io import BytesIO
import pandas as pd
from aiohttp import web
from parrot.handlers.datasets import DatasetManagerHandler


class TestDatasetManagerHandlerGet:
    @pytest.mark.asyncio
    async def test_list_datasets(self):
        """GET returns list of datasets."""
        # Test implementation

    @pytest.mark.asyncio
    async def test_list_with_eda(self):
        """GET with eda=true includes metadata."""
        # Test implementation


class TestDatasetManagerHandlerPatch:
    @pytest.mark.asyncio
    async def test_activate_dataset(self):
        """PATCH activates dataset."""
        # Test implementation

    @pytest.mark.asyncio
    async def test_deactivate_dataset(self):
        """PATCH deactivates dataset."""
        # Test implementation

    @pytest.mark.asyncio
    async def test_patch_nonexistent_returns_404(self):
        """PATCH returns 404 for missing dataset."""
        # Test implementation


class TestDatasetManagerHandlerPut:
    @pytest.mark.asyncio
    async def test_upload_excel(self):
        """PUT uploads Excel file."""
        # Test implementation

    @pytest.mark.asyncio
    async def test_upload_csv(self):
        """PUT uploads CSV file."""
        # Test implementation

    @pytest.mark.asyncio
    async def test_upload_invalid_format(self):
        """PUT rejects unsupported formats."""
        # Test implementation


class TestDatasetManagerHandlerPost:
    @pytest.mark.asyncio
    async def test_add_sql_query(self):
        """POST adds SQL query."""
        # Test implementation

    @pytest.mark.asyncio
    async def test_add_query_slug(self):
        """POST adds query slug."""
        # Test implementation


class TestDatasetManagerHandlerDelete:
    @pytest.mark.asyncio
    async def test_delete_dataset(self):
        """DELETE removes dataset."""
        # Test implementation

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self):
        """DELETE returns 404 for missing dataset."""
        # Test implementation
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-119 and TASK-121 are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-122-dataset-manager-handler.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude session
**Date**: 2026-03-03
**Notes**:
- Created `parrot/handlers/datasets.py` with DatasetManagerHandler class
- Adapted API to match actual DatasetManager methods:
  - `add_dataframe()` instead of `add_dataset()`
  - `remove()` instead of `remove_dataset()`
  - `list_available()` (async) returns all datasets
  - `activate()`/`deactivate()` return lists (check if empty for 404)
- Raw SQL queries stored in metadata with `raw_sql` key
- All 26 tests pass, lint clean
