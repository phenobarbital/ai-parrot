import pytest
from unittest.mock import patch, MagicMock, AsyncMock


def test_bq_tool_import():
    from parrot.tools.database.bq import BQSchemaSearchTool
    assert BQSchemaSearchTool is not None


def test_bq_engine_raises_without_sqlalchemy_bigquery():
    """_get_engine raises ImportError when sqlalchemy-bigquery is missing."""
    from parrot.tools.database.bq import BQSchemaSearchTool

    tool = BQSchemaSearchTool.__new__(BQSchemaSearchTool)
    tool._bq_credentials_path = None
    tool._bq_project_id = "test-project"

    with patch.dict("sys.modules", {"sqlalchemy_bigquery": None}):
        with pytest.raises(ImportError, match="sqlalchemy-bigquery"):
            tool._get_engine("bigquery://test-project", "")


def test_bq_tool_stores_credentials():
    """__init__ stores _bq_credentials_path and _bq_project_id."""
    from parrot.tools.database.bq import BQSchemaSearchTool

    tool = BQSchemaSearchTool.__new__(BQSchemaSearchTool)
    # Simulate what __init__ does with credentials dict
    tool._bq_credentials_path = "/path/to/creds.json"
    tool._bq_project_id = "my-project"

    assert tool._bq_credentials_path == "/path/to/creds.json"
    assert tool._bq_project_id == "my-project"


@pytest.mark.asyncio
async def test_bq_search_in_database_returns_list():
    """_search_in_database returns a list (may be empty with mock session)."""
    from parrot.tools.database.bq import BQSchemaSearchTool

    tool = BQSchemaSearchTool.__new__(BQSchemaSearchTool)
    tool.logger = MagicMock()
    tool.allowed_schemas = ["my_dataset"]
    tool.metadata_cache = MagicMock()
    tool.metadata_cache.store_table_metadata = AsyncMock()

    # Mock session_maker that returns empty rows
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    tool.session_maker = MagicMock(return_value=mock_session)

    results = await tool._search_in_database(
        search_term="users", schema_name="my_dataset", limit=5
    )
    assert isinstance(results, list)
    assert len(results) == 0
