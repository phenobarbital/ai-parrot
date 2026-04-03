---
description: Generate comprehensive pytest suites
---

# Generate Tests Workflow

This workflow guides you through creating comprehensive pytest suites using `pytest-asyncio`, fixtures, and correct project structure.

## 1. Analyze the Context
1. Identify the module or class you need to test.
2. Read the source code of the target module to understand its dependencies and public API.
3. Determine the necessary fixtures (e.g., database connections, mock clients, sample data).

## 2. Create the Test File
1.  All tests must reside in the `tests/` directory.
2.  The filename should follow the pattern `test_<module_name>.py`.
3.  **CRITICAL**: Use "uv" as package manager.
4.  **CRITICAL**: Always enable the virtualenv first (`source .venv/bin/activate`).

## 3. Structure the Test Suite
Use the following template as a guide. Adjust fixtures and test cases to match the specific module requirements.

```python
"""
Comprehensive pytest suite for <Target Module>.

Tests cover:
- <Feature 1>
- <Feature 2>
- ...
"""
import pytest
import asyncio
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from pathlib import Path

# Import target module
# from mypackage.module import MyClass

# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def config_params():
    """Default configuration parameters for testing."""
    return {
        'param1': 'value1',
    }

@pytest.fixture
async def mock_dependency():
    """Mock external dependencies (e.g., DB, API client)."""
    mock = AsyncMock()
    yield mock

@pytest.fixture(scope='session')
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

# ============================================================================
# TEST CLASSES
# ============================================================================

class TestFeatureOne:
    """Test group for Feature One."""

    @pytest.mark.asyncio
    async def test_success_case(self, mock_dependency):
        """Test successful execution."""
        # Arrange
        # Act
        # Assert
        assert True

    @pytest.mark.asyncio
    async def test_error_handling(self):
        """Test error conditions."""
        with pytest.raises(ValueError):
             # Act that raises
             pass

# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
```

## 4. Implementation Guidelines
- **Asyncio**: Use `@pytest.mark.asyncio` for async tests.
- **Fixtures**: Use fixtures for setup/teardown. Use `scope='session'` for heavy resources if safe.
- **Mocks**: Use `unittest.mock` (`MagicMock`, `AsyncMock`, `patch`) to isolate the unit under test.
- **Coverage**: Aim to test both success paths and error handling/edge cases.

## 5. Verification
1. Run the newly created test using `pytest`:
   ```bash
   source .venv/bin/activate
   pytest tests/test_<module_name>.py -v
   ```
//turbo
2. Verify all tests pass.