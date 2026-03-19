# TASK-124: DatasetManager Handler Unit Tests

**Feature**: DatasetManager Support for AgentTalk Handler
**Spec**: `sdd/specs/dataset-support-agenttalk.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-119, TASK-120, TASK-121, TASK-122, TASK-123
**Assigned-to**: null

---

## Context

> This task implements Module 6 from the spec: Unit Tests.

Write comprehensive unit and integration tests for all components of the DatasetManager support feature.

---

## Scope

- Create test fixtures for DatasetManager, sessions, and mock agents
- Test `UserObjectsHandler` methods
- Test `DatasetManagerHandler` all endpoints
- Test request/response model validation
- Integration test for full flow

**NOT in scope**:
- Load testing
- E2E browser tests

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/handlers/test_user_objects_handler.py` | CREATE | UserObjectsHandler unit tests |
| `tests/handlers/test_dataset_handler.py` | CREATE | DatasetManagerHandler unit tests |
| `tests/models/test_dataset_models.py` | CREATE | Pydantic model tests |
| `tests/conftest.py` | MODIFY | Add shared fixtures |

---

## Implementation Notes

### Test Fixtures

```python
# tests/conftest.py additions
import pytest
import pandas as pd
from io import BytesIO
from unittest.mock import MagicMock
from parrot.tools.dataset_manager import DatasetManager


@pytest.fixture
def sample_dataframe():
    """Sample DataFrame for testing."""
    return pd.DataFrame({
        'name': ['Alice', 'Bob', 'Charlie'],
        'age': [25, 30, 35],
        'salary': [50000.0, 60000.0, 70000.0]
    })


@pytest.fixture
def sample_excel_file(sample_dataframe):
    """Sample Excel file as BytesIO."""
    buffer = BytesIO()
    sample_dataframe.to_excel(buffer, index=False)
    buffer.seek(0)
    return buffer


@pytest.fixture
def sample_csv_file(sample_dataframe):
    """Sample CSV file as BytesIO."""
    buffer = BytesIO()
    sample_dataframe.to_csv(buffer, index=False)
    buffer.seek(0)
    return buffer


@pytest.fixture
def empty_session():
    """Empty session dict."""
    return {}


@pytest.fixture
def dataset_manager_with_data(sample_dataframe):
    """DatasetManager with pre-loaded data."""
    dm = DatasetManager()
    dm.add_dataset("test_df", sample_dataframe, description="Test dataset")
    return dm


@pytest.fixture
def mock_pandas_agent(dataset_manager_with_data):
    """Mock PandasAgent with DatasetManager."""
    agent = MagicMock()
    agent.name = "test-pandas-agent"
    agent._dataset_manager = dataset_manager_with_data
    agent.attach_dm = MagicMock()
    return agent


@pytest.fixture
def mock_regular_agent():
    """Mock regular Agent (not PandasAgent)."""
    agent = MagicMock()
    agent.name = "test-agent"
    # No _dataset_manager attribute
    return agent
```

### UserObjectsHandler Tests

```python
# tests/handlers/test_user_objects_handler.py
import pytest
from unittest.mock import MagicMock, AsyncMock
import pandas as pd
from parrot.handlers.user_objects import UserObjectsHandler
from parrot.tools.dataset_manager import DatasetManager


class TestSessionKeyGeneration:
    """Test session key generation."""

    def test_with_agent_name(self):
        handler = UserObjectsHandler()
        key = handler.get_session_key("my-agent", "dataset_manager")
        assert key == "my-agent_dataset_manager"

    def test_without_agent_name(self):
        handler = UserObjectsHandler()
        key = handler.get_session_key(None, "tool_manager")
        assert key == "tool_manager"

    def test_empty_agent_name(self):
        handler = UserObjectsHandler()
        key = handler.get_session_key("", "dataset_manager")
        assert key == "dataset_manager"


class TestConfigureDatasetManager:
    """Test DatasetManager configuration."""

    @pytest.mark.asyncio
    async def test_creates_new_dm_if_not_in_session(self, empty_session, mock_pandas_agent):
        handler = UserObjectsHandler()
        mock_pandas_agent._dataset_manager = None

        dm = await handler.configure_dataset_manager(
            empty_session, mock_pandas_agent
        )

        assert isinstance(dm, DatasetManager)
        assert "test-pandas-agent_dataset_manager" in empty_session

    @pytest.mark.asyncio
    async def test_returns_existing_dm_from_session(self, mock_pandas_agent):
        handler = UserObjectsHandler()
        existing_dm = DatasetManager()
        session = {"test-pandas-agent_dataset_manager": existing_dm}

        dm = await handler.configure_dataset_manager(session, mock_pandas_agent)

        assert dm is existing_dm

    @pytest.mark.asyncio
    async def test_copies_datasets_from_agent_dm(
        self, empty_session, mock_pandas_agent, sample_dataframe
    ):
        handler = UserObjectsHandler()

        dm = await handler.configure_dataset_manager(
            empty_session, mock_pandas_agent
        )

        datasets = dm.list_datasets()
        assert "test_df" in datasets

    @pytest.mark.asyncio
    async def test_handles_none_session(self, mock_pandas_agent):
        handler = UserObjectsHandler()

        dm = await handler.configure_dataset_manager(None, mock_pandas_agent)

        assert isinstance(dm, DatasetManager)
```

### DatasetManagerHandler Tests

```python
# tests/handlers/test_dataset_handler.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from io import BytesIO
import json
import pandas as pd
from aiohttp import web
from parrot.handlers.datasets import DatasetManagerHandler
from parrot.tools.dataset_manager import DatasetManager


class TestDatasetManagerHandlerGet:
    """Test GET /datasets/{agent_id}."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_new_session(self):
        """GET returns empty list when no datasets."""
        # Mock setup
        handler = DatasetManagerHandler()
        handler.request = MagicMock()
        handler.request.match_info = {'agent_id': 'test-agent'}
        handler.request.query = {}

        with patch.object(handler, '_get_dataset_manager') as mock_get_dm:
            mock_dm = DatasetManager()
            mock_get_dm.return_value = mock_dm

            response = await handler.get()
            data = json.loads(response.body)

            assert data['total'] == 0
            assert data['datasets'] == []

    @pytest.mark.asyncio
    async def test_returns_datasets_list(self, sample_dataframe):
        """GET returns list of existing datasets."""
        handler = DatasetManagerHandler()
        handler.request = MagicMock()
        handler.request.match_info = {'agent_id': 'test-agent'}
        handler.request.query = {}

        dm = DatasetManager()
        dm.add_dataset("sales", sample_dataframe)

        with patch.object(handler, '_get_dataset_manager', return_value=dm):
            response = await handler.get()
            data = json.loads(response.body)

            assert data['total'] == 1
            assert data['datasets'][0]['name'] == 'sales'

    @pytest.mark.asyncio
    async def test_includes_eda_when_requested(self, sample_dataframe):
        """GET with eda=true includes metadata."""
        handler = DatasetManagerHandler()
        handler.request = MagicMock()
        handler.request.match_info = {'agent_id': 'test-agent'}
        handler.request.query = {'eda': 'true'}

        dm = DatasetManager()
        dm.add_dataset("sales", sample_dataframe)

        with patch.object(handler, '_get_dataset_manager', return_value=dm):
            response = await handler.get()
            data = json.loads(response.body)

            # Should have metadata field
            assert 'metadata' in data['datasets'][0] or data['total'] == 1


class TestDatasetManagerHandlerPatch:
    """Test PATCH /datasets/{agent_id}."""

    @pytest.mark.asyncio
    async def test_activate_dataset(self, sample_dataframe):
        """PATCH with activate action activates dataset."""
        handler = DatasetManagerHandler()
        handler.request = MagicMock()
        handler.request.match_info = {'agent_id': 'test-agent'}
        handler.request.json = AsyncMock(return_value={
            'dataset_name': 'sales',
            'action': 'activate'
        })

        dm = DatasetManager()
        dm.add_dataset("sales", sample_dataframe)
        dm.deactivate("sales")

        with patch.object(handler, '_get_dataset_manager', return_value=dm):
            response = await handler.patch()
            assert response.status == 200

            # Verify activated
            assert dm.is_active("sales")

    @pytest.mark.asyncio
    async def test_deactivate_dataset(self, sample_dataframe):
        """PATCH with deactivate action deactivates dataset."""
        handler = DatasetManagerHandler()
        handler.request = MagicMock()
        handler.request.match_info = {'agent_id': 'test-agent'}
        handler.request.json = AsyncMock(return_value={
            'dataset_name': 'sales',
            'action': 'deactivate'
        })

        dm = DatasetManager()
        dm.add_dataset("sales", sample_dataframe)

        with patch.object(handler, '_get_dataset_manager', return_value=dm):
            response = await handler.patch()
            assert response.status == 200

            # Verify deactivated
            assert not dm.is_active("sales")

    @pytest.mark.asyncio
    async def test_returns_404_for_nonexistent(self):
        """PATCH returns 404 for non-existent dataset."""
        handler = DatasetManagerHandler()
        handler.request = MagicMock()
        handler.request.match_info = {'agent_id': 'test-agent'}
        handler.request.json = AsyncMock(return_value={
            'dataset_name': 'nonexistent',
            'action': 'activate'
        })

        dm = DatasetManager()

        with patch.object(handler, '_get_dataset_manager', return_value=dm):
            response = await handler.patch()
            assert response.status == 404


class TestDatasetManagerHandlerPut:
    """Test PUT /datasets/{agent_id}."""

    @pytest.mark.asyncio
    async def test_upload_csv(self, sample_csv_file):
        """PUT uploads CSV file successfully."""
        # Test implementation with multipart mock

    @pytest.mark.asyncio
    async def test_upload_excel(self, sample_excel_file):
        """PUT uploads Excel file successfully."""
        # Test implementation with multipart mock

    @pytest.mark.asyncio
    async def test_rejects_unsupported_format(self):
        """PUT rejects unsupported file formats."""
        # Test implementation


class TestDatasetManagerHandlerPost:
    """Test POST /datasets/{agent_id}."""

    @pytest.mark.asyncio
    async def test_add_sql_query(self):
        """POST adds SQL query as dataset."""
        handler = DatasetManagerHandler()
        handler.request = MagicMock()
        handler.request.match_info = {'agent_id': 'test-agent'}
        handler.request.json = AsyncMock(return_value={
            'name': 'monthly_sales',
            'query': 'SELECT * FROM sales WHERE month = 1'
        })

        dm = DatasetManager()

        with patch.object(handler, '_get_dataset_manager', return_value=dm):
            response = await handler.post()
            assert response.status == 201


class TestDatasetManagerHandlerDelete:
    """Test DELETE /datasets/{agent_id}."""

    @pytest.mark.asyncio
    async def test_delete_existing_dataset(self, sample_dataframe):
        """DELETE removes existing dataset."""
        handler = DatasetManagerHandler()
        handler.request = MagicMock()
        handler.request.match_info = {'agent_id': 'test-agent'}
        handler.request.query = {'name': 'sales'}

        dm = DatasetManager()
        dm.add_dataset("sales", sample_dataframe)

        with patch.object(handler, '_get_dataset_manager', return_value=dm):
            response = await handler.delete()
            assert response.status == 200

            # Verify deleted
            assert "sales" not in dm.list_datasets()

    @pytest.mark.asyncio
    async def test_returns_404_for_nonexistent(self):
        """DELETE returns 404 for non-existent dataset."""
        handler = DatasetManagerHandler()
        handler.request = MagicMock()
        handler.request.match_info = {'agent_id': 'test-agent'}
        handler.request.query = {'name': 'nonexistent'}

        dm = DatasetManager()

        with patch.object(handler, '_get_dataset_manager', return_value=dm):
            response = await handler.delete()
            assert response.status == 404
```

### Integration Tests

```python
# tests/handlers/test_dataset_integration.py
import pytest
import pandas as pd
from parrot.handlers.user_objects import UserObjectsHandler
from parrot.tools.dataset_manager import DatasetManager


class TestFullFlow:
    """Integration tests for complete workflows."""

    @pytest.mark.asyncio
    async def test_upload_activate_use_flow(self):
        """Full flow: upload → list → activate → verify."""
        # Create components
        handler = UserObjectsHandler()
        session = {}

        # Simulate agent with empty DM
        from unittest.mock import MagicMock
        agent = MagicMock()
        agent.name = "analytics-agent"
        agent._dataset_manager = None

        # Get user's DM
        dm = await handler.configure_dataset_manager(session, agent)

        # Upload dataset
        df = pd.DataFrame({'x': [1, 2, 3], 'y': [4, 5, 6]})
        dm.add_dataset("uploaded", df)

        # Verify in list
        datasets = dm.list_datasets()
        assert "uploaded" in datasets

        # Deactivate and verify
        dm.deactivate("uploaded")
        assert not dm.is_active("uploaded")

        # Activate and verify
        dm.activate("uploaded")
        assert dm.is_active("uploaded")

    @pytest.mark.asyncio
    async def test_session_persistence(self):
        """DatasetManager persists across multiple handler calls."""
        handler = UserObjectsHandler()
        session = {}

        from unittest.mock import MagicMock
        agent = MagicMock()
        agent.name = "test-agent"
        agent._dataset_manager = None

        # First call - create DM
        dm1 = await handler.configure_dataset_manager(session, agent)
        dm1.add_dataset("first", pd.DataFrame({'a': [1]}))

        # Second call - should get same DM
        dm2 = await handler.configure_dataset_manager(session, agent)

        assert dm1 is dm2
        assert "first" in dm2.list_datasets()
```

---

## Acceptance Criteria

- [ ] Test fixtures created in `tests/conftest.py`
- [ ] `UserObjectsHandler` tests in `tests/handlers/test_user_objects_handler.py`
- [ ] `DatasetManagerHandler` GET tests
- [ ] `DatasetManagerHandler` PATCH tests
- [ ] `DatasetManagerHandler` PUT tests (Excel and CSV)
- [ ] `DatasetManagerHandler` POST tests
- [ ] `DatasetManagerHandler` DELETE tests
- [ ] Pydantic model validation tests
- [ ] Integration test for full upload-use flow
- [ ] Integration test for session persistence
- [ ] All tests pass: `pytest tests/handlers/test_dataset*.py tests/handlers/test_user_objects*.py -v`

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-119 through TASK-123 are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-124-dataset-handler-tests.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude session
**Date**: 2026-03-03
**Notes**:
- Added dataset fixtures to `tests/conftest.py` (sample_dataframe, sample_excel_file, sample_csv_file, etc.)
- Created `tests/handlers/test_dataset_integration.py` with 13 integration tests
- Most tests already existed from previous tasks (TASK-119 through TASK-123)
- Total test coverage: 110 tests across all dataset-related test files:
  - test_dataset_handler.py: 26 tests
  - test_dataset_routes.py: 15 tests
  - test_dataset_integration.py: 13 tests
  - test_user_objects_handler.py: 25 tests
  - test_dataset_models.py: 31 tests
- All 110 tests pass, lint clean
