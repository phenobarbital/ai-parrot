# Feature Specification: DatasetManager Support for AgentTalk Handler

**Feature ID**: FEAT-021
**Date**: 2026-03-03
**Author**: claude-session
**Status**: approved
**Target version**: 1.x.x
**Proposal**: `sdd/proposals/dataset-support-agenttalk.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

`DatasetManager` at `parrot/tools/dataset_manager.py` is a powerful Dataset Catalog and Toolkit for managing DataFrames and queries. While `PandasAgent` can receive dataframes and use an internal `DatasetManager`, users cannot currently:

1. Override, enable, or disable datasets from the AgentTalk HTTP handler
2. Register their own `DatasetManager` instance per user session (like they can with `ToolManager`)
3. Upload Excel files to be converted to DataFrames and added to their session's DatasetManager
4. Add SQL queries or query slugs via HTTP endpoints

### Goals

- Allow users to register their own `DatasetManager` instance per session (exactly like `ToolManager`)
- Expose HTTP endpoints for managing datasets: list, enable/disable, upload, add queries, delete
- Replace the agent's `DatasetManager` with the user's instance using `attach_dm()` method
- Reduce complexity of `AgentTalk` by extracting user object configuration to a dedicated class

### Non-Goals (explicitly out of scope)

- Real-time synchronization of DatasetManager across multiple sessions
- Data transformation pipelines within the handler
- Authentication/authorization for specific datasets (use existing permission system)
- Direct database connectivity from the handler (use query slugs)

---

## 2. Architectural Design

### Overview

The design introduces two new components:
1. **UserObjectsHandler**: A helper class to manage session-scoped ToolManager and DatasetManager instances
2. **DatasetManagerHandler**: An HTTP endpoint handler for CRUD operations on user's DatasetManager

### Component Diagram

```
┌────────────────────────────────────────────────────────────────────────────┐
│                            User Session                                     │
│  ┌─────────────────────┐     ┌─────────────────────┐                       │
│  │ {agent}_tool_manager│     │{agent}_dataset_manager│                      │
│  │    ToolManager      │     │   DatasetManager     │                       │
│  └──────────┬──────────┘     └──────────┬──────────┘                       │
└─────────────┼───────────────────────────┼──────────────────────────────────┘
              │                           │
              ▼                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        UserObjectsHandler                                   │
│  ┌──────────────────────────┐    ┌──────────────────────────┐              │
│  │ _configure_tool_manager  │    │ _configure_dataset_manager│             │
│  └──────────────────────────┘    └──────────────────────────┘              │
│                                                                             │
│  Responsibilities:                                                          │
│  - Create/retrieve session-scoped managers                                  │
│  - Copy datasets/tools from agent defaults to user instance                │
│  - Sync user instance back to agent via attach_dm()/attach_tool_manager() │
└─────────────────────────────────────────────────────────────────────────────┘
              │                           │
              ▼                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            HTTP Handlers                                    │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ AgentTalk                                                             │  │
│  │ POST /api/v1/agents/chat/{agent_id}                                  │  │
│  │   → Uses UserObjectsHandler to get session managers                   │  │
│  │   → Calls agent.attach_dm() / agent.attach_tool_manager()            │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ DatasetManagerHandler                                                 │  │
│  │ /api/v1/agents/datasets/{agent_id}                                   │  │
│  │   GET    → List datasets with metadata (optional EDA)                │  │
│  │   PATCH  → Activate/deactivate datasets                              │  │
│  │   PUT    → Upload Excel/CSV files as new datasets                    │  │
│  │   POST   → Add SQL queries or query slugs                            │  │
│  │   DELETE → Remove dataset from manager                               │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AgentTalk` | modifies | Extract `_configure_tool_manager` to `UserObjectsHandler`, add dataset configuration |
| `PandasAgent` | uses | Use existing `attach_dm()` method |
| `DatasetManager` | uses | Session-scoped instances per user |
| `navigator_session` | uses | Store managers in user session |
| `BaseView` | extends | New `DatasetManagerHandler` inherits from it |

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


class DatasetAction(str, Enum):
    """Actions that can be performed on a dataset."""
    ACTIVATE = "activate"
    DEACTIVATE = "deactivate"


class DatasetPatchRequest(BaseModel):
    """Request model for PATCH /datasets/{agent_id}."""
    dataset_name: str = Field(..., description="Name of the dataset to modify")
    action: DatasetAction = Field(..., description="Action to perform")


class DatasetQueryRequest(BaseModel):
    """Request model for POST /datasets/{agent_id} (add query)."""
    name: str = Field(..., description="Dataset name/identifier")
    query: Optional[str] = Field(None, description="Raw SQL query")
    query_slug: Optional[str] = Field(None, description="Query slug from QuerySource")
    description: Optional[str] = Field(default="", description="Dataset description")


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
```

### New Public Interfaces

```python
# UserObjectsHandler - extracted from AgentTalk
class UserObjectsHandler:
    """
    Manages session-scoped ToolManager and DatasetManager instances.

    Extracted from AgentTalk to reduce complexity and centralize
    user object configuration logic.
    """

    def __init__(self, logger: logging.Logger = None):
        self.logger = logger or logging.getLogger(__name__)

    async def configure_tool_manager(
        self,
        data: Dict[str, Any],
        request_session: Any,
        agent_name: str = None
    ) -> tuple[Union[ToolManager, None], List[Dict[str, Any]]]:
        """
        Configure a ToolManager from request payload or session.

        Moved from AgentTalk._configure_tool_manager().
        """
        ...

    async def configure_dataset_manager(
        self,
        request_session: Any,
        agent: "PandasAgent",
        agent_name: str = None
    ) -> DatasetManager:
        """
        Get or create a session-scoped DatasetManager for the user.

        If the agent has an existing DatasetManager, copies all datasets
        to a new user-specific instance. Saves to session and returns.
        """
        ...

    def get_session_key(self, agent_name: str, manager_type: str) -> str:
        """Generate session key for a manager type."""
        prefix = f"{agent_name}_" if agent_name else ""
        return f"{prefix}{manager_type}"


# DatasetManagerHandler - new HTTP handler
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

    async def get(self) -> web.Response:
        """
        List all datasets in user's DatasetManager.

        Query params:
            eda: bool - Include EDA metadata (default: false)
        """
        ...

    async def patch(self) -> web.Response:
        """
        Activate or deactivate a dataset.

        Body: DatasetPatchRequest
        """
        ...

    async def put(self) -> web.Response:
        """
        Upload an Excel/CSV file as a new dataset.

        Accepts multipart/form-data with:
            file: The file to upload
            name: Optional dataset name (defaults to filename)
        """
        ...

    async def post(self) -> web.Response:
        """
        Add a SQL query or query slug as a new dataset.

        Body: DatasetQueryRequest
        """
        ...

    async def delete(self) -> web.Response:
        """
        Delete a dataset from the DatasetManager.

        Query params:
            name: str - Dataset name to delete
        """
        ...
```

---

## 3. Module Breakdown

### Module 1: UserObjectsHandler Class
- **Path**: `parrot/handlers/user_objects.py`
- **Responsibility**: Centralize session-scoped ToolManager and DatasetManager configuration
- **Depends on**: `ToolManager`, `DatasetManager`, `navigator_session`

### Module 2: AgentTalk Refactor
- **Path**: `parrot/handlers/agent.py`
- **Responsibility**: Use `UserObjectsHandler` instead of inline `_configure_tool_manager`, add dataset manager configuration
- **Depends on**: Module 1

### Module 3: DatasetManager Request/Response Models
- **Path**: `parrot/models/datasets.py`
- **Responsibility**: Pydantic models for dataset handler request/response
- **Depends on**: None

### Module 4: DatasetManagerHandler
- **Path**: `parrot/handlers/datasets.py`
- **Responsibility**: HTTP handler for dataset management endpoints
- **Depends on**: Module 1, Module 3, `DatasetManager`

### Module 5: Route Registration
- **Path**: `parrot/handlers/__init__.py`
- **Responsibility**: Register DatasetManagerHandler routes
- **Depends on**: Module 4

### Module 6: Unit Tests
- **Path**: `tests/handlers/test_dataset_handler.py`
- **Responsibility**: Test all handler endpoints
- **Depends on**: Modules 1-4

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_user_objects_handler_init` | Module 1 | UserObjectsHandler initializes with logger |
| `test_configure_dm_creates_new` | Module 1 | Creates new DatasetManager if none in session |
| `test_configure_dm_from_session` | Module 1 | Returns existing DatasetManager from session |
| `test_configure_dm_copies_agent_dm` | Module 1 | Copies datasets from agent's DatasetManager |
| `test_session_key_generation` | Module 1 | Generates correct session keys |
| `test_dataset_patch_request_validation` | Module 3 | Pydantic validation for patch request |
| `test_dataset_query_request_validation` | Module 3 | Pydantic validation for query request |
| `test_handler_get_list_datasets` | Module 4 | GET returns list of datasets |
| `test_handler_get_with_eda` | Module 4 | GET with eda=true includes EDA metadata |
| `test_handler_patch_activate` | Module 4 | PATCH activates dataset |
| `test_handler_patch_deactivate` | Module 4 | PATCH deactivates dataset |
| `test_handler_put_upload_excel` | Module 4 | PUT uploads Excel file |
| `test_handler_put_upload_csv` | Module 4 | PUT uploads CSV file |
| `test_handler_post_add_query` | Module 4 | POST adds SQL query dataset |
| `test_handler_post_add_query_slug` | Module 4 | POST adds query slug dataset |
| `test_handler_delete_dataset` | Module 4 | DELETE removes dataset |
| `test_handler_delete_nonexistent` | Module 4 | DELETE returns 404 for missing dataset |

### Integration Tests

| Test | Description |
|---|---|
| `test_full_flow_upload_and_use` | Upload file → activate → use in chat → verify results |
| `test_session_persistence` | DatasetManager persists across multiple requests |
| `test_agent_attach_dm` | User's DatasetManager correctly attached to PandasAgent |
| `test_multiple_users_isolation` | Different users have isolated DatasetManagers |

### Test Data / Fixtures

```python
import pytest
import pandas as pd
from io import BytesIO

@pytest.fixture
def sample_dataframe():
    return pd.DataFrame({
        'name': ['Alice', 'Bob', 'Charlie'],
        'age': [25, 30, 35],
        'salary': [50000.0, 60000.0, 70000.0]
    })

@pytest.fixture
def sample_excel_file(sample_dataframe):
    buffer = BytesIO()
    sample_dataframe.to_excel(buffer, index=False)
    buffer.seek(0)
    return buffer

@pytest.fixture
def mock_session():
    return {}

@pytest.fixture
def mock_pandas_agent():
    """Mock PandasAgent with DatasetManager."""
    from parrot.tools.dataset_manager import DatasetManager
    from unittest.mock import MagicMock

    agent = MagicMock()
    agent.name = "test-agent"
    agent._dataset_manager = DatasetManager()
    return agent
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `UserObjectsHandler` class extracted from AgentTalk with `configure_tool_manager()` and `configure_dataset_manager()`
- [ ] `AgentTalk` uses `UserObjectsHandler` for tool/dataset manager configuration
- [ ] `AgentTalk.post()` calls `agent.attach_dm()` with user's DatasetManager when applicable
- [ ] `DatasetManagerHandler` implements GET endpoint returning dataset list
- [ ] GET endpoint supports `eda=true` query param for extended metadata
- [ ] `DatasetManagerHandler` implements PATCH endpoint for activate/deactivate
- [ ] `DatasetManagerHandler` implements PUT endpoint for file upload (Excel/CSV)
- [ ] `DatasetManagerHandler` implements POST endpoint for SQL queries
- [ ] `DatasetManagerHandler` implements DELETE endpoint for dataset removal
- [ ] Pydantic models defined for all request/response types
- [ ] Handler routes registered at `/api/v1/agents/datasets/{agent_id}`
- [ ] User's DatasetManager persists in session across requests
- [ ] All unit tests pass: `pytest tests/handlers/test_dataset_handler.py -v`
- [ ] No breaking changes to existing AgentTalk functionality

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Use `@is_authenticated()` and `@user_session()` decorators on handler (same as AgentTalk)
- Use `navigator_session.get_session()` for session access
- Follow existing `ToolManager` session key pattern: `{agent_name}_dataset_manager`
- Use `json_encoder` from `datamodel.parsers.json` for JSON responses
- Use `self.logger` for all logging (from BaseView)

### File Upload Handling

```python
# In DatasetManagerHandler.put()
async def put(self) -> web.Response:
    reader = await self.request.multipart()

    async for field in reader:
        if field.name == 'file':
            filename = field.filename
            data = await field.read()

            # Determine format from extension
            if filename.endswith('.xlsx') or filename.endswith('.xls'):
                df = pd.read_excel(BytesIO(data))
            elif filename.endswith('.csv'):
                df = pd.read_csv(BytesIO(data))
            else:
                return self.json_response(
                    {"error": "Unsupported file format"},
                    status=400
                )
```

### Known Risks / Gotchas

- **Memory usage**: Large file uploads will consume memory; consider streaming for large files
- **Session size**: DatasetManager with large DataFrames stored in session could grow large
- **Race conditions**: Multiple concurrent requests could cause session conflicts
- **File validation**: Must validate uploaded files are valid Excel/CSV before parsing

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pandas` | existing | DataFrame operations |
| `openpyxl` | existing | Excel file reading |
| `aiohttp` | existing | Multipart file handling |

### Migration Path

1. Extract `UserObjectsHandler` without changing AgentTalk behavior
2. Add `configure_dataset_manager()` to UserObjectsHandler
3. Update AgentTalk to use UserObjectsHandler
4. Add DatasetManagerHandler with routes
5. Document new endpoints in API documentation

---

## 7. Open Questions

- [ ] **Session storage limits**: Should we warn/prevent storing large DataFrames in session? — *Owner: architect*: Yes
- [ ] **Query execution**: For POST with `query`, should we execute immediately or defer? — *Owner: backend* — Suggestion: Execute on first use (lazy): execute on first use (lazy).
- [ ] **Streaming uploads**: Do we need to support streaming for very large files? — *Owner: backend* — Suggestion: P2, add size limit for v1, add size limit.
- [ ] **WebSocket updates**: Should dataset changes notify connected clients? — *Owner: frontend* — Answer: P2

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-03 | claude-session | Initial draft from proposal |
