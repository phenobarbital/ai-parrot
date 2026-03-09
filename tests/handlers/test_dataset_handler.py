"""
Tests for DatasetManagerHandler - HTTP handler for dataset operations.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import pandas as pd
from aiohttp import web
from parrot.handlers.datasets import DatasetManagerHandler, MAX_FILE_SIZE
from parrot.tools.dataset_manager import DatasetManager


class MockRequest:
    """Mock aiohttp request for testing."""

    def __init__(
        self,
        match_info=None,
        query=None,
        json_data=None,
        multipart_data=None
    ):
        self.match_info = match_info or {}
        self.query = query or {}
        self._json_data = json_data
        self._multipart_data = multipart_data

    async def json(self):
        if self._json_data is None:
            raise Exception("No JSON body")
        return self._json_data

    async def multipart(self):
        return MockMultipartReader(self._multipart_data or [])


class MockMultipartReader:
    """Mock multipart reader for file uploads."""

    def __init__(self, fields):
        self.fields = fields
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.fields):
            raise StopAsyncIteration
        field = self.fields[self.index]
        self.index += 1
        return field


class MockField:
    """Mock multipart field."""

    def __init__(self, name, data, filename=None):
        self.name = name
        self._data = data
        self.filename = filename

    async def read(self):
        return self._data


@pytest.fixture
def mock_session():
    """Create a mock session dict."""
    return {}


@pytest.fixture
def mock_handler(mock_session):
    """Create a mock DatasetManagerHandler."""
    handler = MagicMock(spec=DatasetManagerHandler)
    handler.logger = MagicMock()
    handler._user_objects_handler = None

    # Real user_objects_handler property
    from parrot.handlers.user_objects import UserObjectsHandler
    handler.user_objects_handler = UserObjectsHandler(logger=handler.logger)

    # Track json responses
    def json_response(data, status=200):
        return {"data": data, "status": status}
    handler.json_response = json_response

    return handler


# =============================================================================
# GET ENDPOINT TESTS
# =============================================================================


class TestDatasetManagerHandlerGet:
    """Tests for GET endpoint - list datasets."""

    @pytest.mark.asyncio
    async def test_list_datasets_empty(self, mock_session):
        """GET returns empty list when no datasets."""
        dm = DatasetManager()

        with patch('parrot.handlers.datasets.get_session', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"test-agent_dataset_manager": dm}

            handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
            handler.logger = MagicMock()
            handler._user_objects_handler = None
            handler.request = MockRequest(match_info={'agent_id': 'test-agent'})

            def json_response(data, status=200):
                return web.json_response(data, status=status)
            handler.json_response = json_response

            response = await handler.get()
            data = response.body.decode()
            import json
            result = json.loads(data)

            assert result['total'] == 0
            assert result['active_count'] == 0
            assert result['datasets'] == []

    @pytest.mark.asyncio
    async def test_list_datasets_with_data(self, mock_session):
        """GET returns datasets with correct info."""
        dm = DatasetManager()
        df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
        dm.add_dataframe("test_df", df)

        with patch('parrot.handlers.datasets.get_session', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"agent_dataset_manager": dm}

            handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
            handler.logger = MagicMock()
            handler._user_objects_handler = None
            handler.request = MockRequest(match_info={'agent_id': 'agent'})

            def json_response(data, status=200):
                return web.json_response(data, status=status)
            handler.json_response = json_response

            response = await handler.get()
            import json
            result = json.loads(response.body.decode())

            assert result['total'] == 1
            assert result['active_count'] == 1
            assert len(result['datasets']) == 1
            assert result['datasets'][0]['name'] == 'test_df'
            assert result['datasets'][0]['loaded'] is True

    @pytest.mark.asyncio
    async def test_list_missing_agent_id(self):
        """GET returns 400 when agent_id missing."""
        handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
        handler.logger = MagicMock()
        handler.request = MockRequest(match_info={})

        def json_response(data, status=200):
            return web.json_response(data, status=status)
        handler.json_response = json_response

        response = await handler.get()
        assert response.status == 400

    @pytest.mark.asyncio
    async def test_list_with_eda_param(self, mock_session):
        """GET with eda=true includes metadata."""
        dm = DatasetManager()
        df = pd.DataFrame({'a': [1, 2, 3]})
        dm.add_dataframe("test_df", df)

        with patch('parrot.handlers.datasets.get_session', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"agent_dataset_manager": dm}

            handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
            handler.logger = MagicMock()
            handler._user_objects_handler = None
            handler.request = MockRequest(
                match_info={'agent_id': 'agent'},
                query={'eda': 'true'}
            )

            def json_response(data, status=200):
                return web.json_response(data, status=status)
            handler.json_response = json_response

            response = await handler.get()
            import json
            result = json.loads(response.body.decode())

            assert result['total'] == 1
            # EDA metadata should be attempted


# =============================================================================
# PATCH ENDPOINT TESTS
# =============================================================================


class TestDatasetManagerHandlerPatch:
    """Tests for PATCH endpoint - activate/deactivate datasets."""

    @pytest.mark.asyncio
    async def test_activate_dataset(self):
        """PATCH activates dataset."""
        dm = DatasetManager()
        df = pd.DataFrame({'a': [1, 2, 3]})
        dm.add_dataframe("test_df", df)
        dm.deactivate("test_df")  # Start deactivated

        with patch('parrot.handlers.datasets.get_session', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"agent_dataset_manager": dm}

            handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
            handler.logger = MagicMock()
            handler._user_objects_handler = None
            handler.request = MockRequest(
                match_info={'agent_id': 'agent'},
                json_data={'dataset_name': 'test_df', 'action': 'activate'}
            )

            def json_response(data, status=200):
                return web.json_response(data, status=status)
            handler.json_response = json_response

            response = await handler.patch()
            import json
            result = json.loads(response.body.decode())

            assert result['name'] == 'test_df'
            assert result['action'] == 'activate'

    @pytest.mark.asyncio
    async def test_deactivate_dataset(self):
        """PATCH deactivates dataset."""
        dm = DatasetManager()
        df = pd.DataFrame({'a': [1, 2, 3]})
        dm.add_dataframe("test_df", df)

        with patch('parrot.handlers.datasets.get_session', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"agent_dataset_manager": dm}

            handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
            handler.logger = MagicMock()
            handler._user_objects_handler = None
            handler.request = MockRequest(
                match_info={'agent_id': 'agent'},
                json_data={'dataset_name': 'test_df', 'action': 'deactivate'}
            )

            def json_response(data, status=200):
                return web.json_response(data, status=status)
            handler.json_response = json_response

            response = await handler.patch()
            import json
            result = json.loads(response.body.decode())

            assert result['name'] == 'test_df'
            assert result['action'] == 'deactivate'

    @pytest.mark.asyncio
    async def test_patch_nonexistent_returns_404(self):
        """PATCH returns 404 for missing dataset."""
        dm = DatasetManager()

        with patch('parrot.handlers.datasets.get_session', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"agent_dataset_manager": dm}

            handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
            handler.logger = MagicMock()
            handler._user_objects_handler = None
            handler.request = MockRequest(
                match_info={'agent_id': 'agent'},
                json_data={'dataset_name': 'nonexistent', 'action': 'activate'}
            )

            def json_response(data, status=200):
                return web.json_response(data, status=status)
            handler.json_response = json_response

            response = await handler.patch()
            assert response.status == 404

    @pytest.mark.asyncio
    async def test_patch_invalid_action(self):
        """PATCH returns 400 for invalid action."""
        handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
        handler.logger = MagicMock()
        handler.request = MockRequest(
            match_info={'agent_id': 'agent'},
            json_data={'dataset_name': 'test_df', 'action': 'invalid'}
        )

        def json_response(data, status=200):
            return web.json_response(data, status=status)
        handler.json_response = json_response

        response = await handler.patch()
        assert response.status == 400

    @pytest.mark.asyncio
    async def test_patch_missing_agent_id(self):
        """PATCH returns 400 when agent_id missing."""
        handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
        handler.logger = MagicMock()
        handler.request = MockRequest(match_info={})

        def json_response(data, status=200):
            return web.json_response(data, status=status)
        handler.json_response = json_response

        response = await handler.patch()
        assert response.status == 400


# =============================================================================
# PUT ENDPOINT TESTS
# =============================================================================


class TestDatasetManagerHandlerPut:
    """Tests for PUT endpoint - file uploads."""

    @pytest.mark.asyncio
    async def test_upload_csv(self):
        """PUT uploads CSV file."""
        dm = DatasetManager()
        csv_content = b"a,b,c\n1,2,3\n4,5,6"

        with patch('parrot.handlers.datasets.get_session', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"agent_dataset_manager": dm}

            handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
            handler.logger = MagicMock()
            handler._user_objects_handler = None
            handler.request = MockRequest(
                match_info={'agent_id': 'agent'},
                multipart_data=[
                    MockField('file', csv_content, filename='test.csv')
                ]
            )

            def json_response(data, status=200):
                return web.json_response(data, status=status)
            handler.json_response = json_response

            response = await handler.put()
            import json
            result = json.loads(response.body.decode())

            assert response.status == 201
            assert result['name'] == 'test'
            assert result['rows'] == 2
            assert result['columns'] == 3

    @pytest.mark.asyncio
    async def test_upload_with_custom_name(self):
        """PUT accepts custom dataset name."""
        dm = DatasetManager()
        csv_content = b"x,y\n1,2"

        with patch('parrot.handlers.datasets.get_session', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"agent_dataset_manager": dm}

            handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
            handler.logger = MagicMock()
            handler._user_objects_handler = None
            handler.request = MockRequest(
                match_info={'agent_id': 'agent'},
                multipart_data=[
                    MockField('name', b'custom_name'),
                    MockField('file', csv_content, filename='data.csv')
                ]
            )

            def json_response(data, status=200):
                return web.json_response(data, status=status)
            handler.json_response = json_response

            response = await handler.put()
            import json
            result = json.loads(response.body.decode())

            assert result['name'] == 'custom_name'

    @pytest.mark.asyncio
    async def test_upload_invalid_format(self):
        """PUT rejects unsupported formats."""
        handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
        handler.logger = MagicMock()
        handler.request = MockRequest(
            match_info={'agent_id': 'agent'},
            multipart_data=[
                MockField('file', b'some data', filename='test.json')
            ]
        )

        def json_response(data, status=200):
            return web.json_response(data, status=status)
        handler.json_response = json_response

        response = await handler.put()
        assert response.status == 400
        import json
        result = json.loads(response.body.decode())
        assert 'Unsupported file format' in result['error']

    @pytest.mark.asyncio
    async def test_upload_no_file(self):
        """PUT returns 400 when no file provided."""
        handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
        handler.logger = MagicMock()
        handler.request = MockRequest(
            match_info={'agent_id': 'agent'},
            multipart_data=[]
        )

        def json_response(data, status=200):
            return web.json_response(data, status=status)
        handler.json_response = json_response

        response = await handler.put()
        assert response.status == 400
        import json
        result = json.loads(response.body.decode())
        assert 'No file provided' in result['error']

    @pytest.mark.asyncio
    async def test_upload_file_too_large(self):
        """PUT rejects files exceeding size limit."""
        # Create data larger than MAX_FILE_SIZE
        large_data = b'x' * (MAX_FILE_SIZE + 1)

        handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
        handler.logger = MagicMock()
        handler.request = MockRequest(
            match_info={'agent_id': 'agent'},
            multipart_data=[
                MockField('file', large_data, filename='large.csv')
            ]
        )

        def json_response(data, status=200):
            return web.json_response(data, status=status)
        handler.json_response = json_response

        response = await handler.put()
        assert response.status == 400
        import json
        result = json.loads(response.body.decode())
        assert 'File too large' in result['error']


# =============================================================================
# POST ENDPOINT TESTS
# =============================================================================


class TestDatasetManagerHandlerPost:
    """Tests for POST endpoint - add queries."""

    @pytest.mark.asyncio
    async def test_add_query_slug(self):
        """POST adds query slug."""
        dm = DatasetManager()

        with patch('parrot.handlers.datasets.get_session', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"agent_dataset_manager": dm}

            handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
            handler.logger = MagicMock()
            handler._user_objects_handler = None
            handler.request = MockRequest(
                match_info={'agent_id': 'agent'},
                json_data={
                    'name': 'sales_data',
                    'query_slug': 'monthly_sales',
                    'description': 'Monthly sales report'
                }
            )

            def json_response(data, status=200):
                return web.json_response(data, status=status)
            handler.json_response = json_response

            response = await handler.post()
            import json
            result = json.loads(response.body.decode())

            assert response.status == 201
            assert result['name'] == 'sales_data'
            assert result['type'] == 'query_slug'

    @pytest.mark.asyncio
    async def test_add_raw_sql_query(self):
        """POST adds raw SQL query."""
        dm = DatasetManager()

        with patch('parrot.handlers.datasets.get_session', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"agent_dataset_manager": dm}

            handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
            handler.logger = MagicMock()
            handler._user_objects_handler = None
            handler.request = MockRequest(
                match_info={'agent_id': 'agent'},
                json_data={
                    'name': 'orders',
                    'query': 'SELECT * FROM orders WHERE status = active'
                }
            )

            def json_response(data, status=200):
                return web.json_response(data, status=status)
            handler.json_response = json_response

            response = await handler.post()
            import json
            result = json.loads(response.body.decode())

            assert response.status == 201
            assert result['name'] == 'orders'
            assert result['type'] == 'query'


    @pytest.mark.asyncio
    async def test_add_datasource_airtable(self):
        """POST adds Airtable datasource and eagerly fetches it."""
        dm = DatasetManager()

        with patch('parrot.handlers.datasets.get_session', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"agent_dataset_manager": dm}

            handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
            handler.logger = MagicMock()
            handler._user_objects_handler = None
            handler.request = MockRequest(
                match_info={'agent_id': 'agent'},
                json_data={
                    'name': 'airtable_ds',
                    'datasource': {
                        'type': 'airtable',
                        'base_id': 'app123',
                        'table': 'Sales',
                        'api_key': 'token'
                    }
                }
            )

            def json_response(data, status=200):
                return web.json_response(data, status=status)
            handler.json_response = json_response

            with patch.object(dm, 'add_airtable_source', new_callable=AsyncMock) as mock_add:
                response = await handler.post()
                import json
                result = json.loads(response.body.decode())

                assert response.status == 201
                assert result['name'] == 'airtable_ds'
                assert result['type'] == 'airtable'
                mock_add.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_datasource_smartsheet(self):
        """POST adds Smartsheet datasource and eagerly fetches it."""
        dm = DatasetManager()

        with patch('parrot.handlers.datasets.get_session', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"agent_dataset_manager": dm}

            handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
            handler.logger = MagicMock()
            handler._user_objects_handler = None
            handler.request = MockRequest(
                match_info={'agent_id': 'agent'},
                json_data={
                    'name': 'smartsheet_ds',
                    'datasource': {
                        'type': 'smartsheet',
                        'sheet_id': 'sheet_1',
                        'access_token': 'token'
                    }
                }
            )

            def json_response(data, status=200):
                return web.json_response(data, status=status)
            handler.json_response = json_response

            with patch.object(dm, 'add_smartsheet_source', new_callable=AsyncMock) as mock_add:
                response = await handler.post()
                import json
                result = json.loads(response.body.decode())

                assert response.status == 201
                assert result['name'] == 'smartsheet_ds'
                assert result['type'] == 'smartsheet'
                mock_add.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_post_neither_query_nor_slug(self):
        """POST returns 400 when neither query nor slug provided."""
        handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
        handler.logger = MagicMock()
        handler.request = MockRequest(
            match_info={'agent_id': 'agent'},
            json_data={'name': 'test'}
        )

        def json_response(data, status=200):
            return web.json_response(data, status=status)
        handler.json_response = json_response

        response = await handler.post()
        assert response.status == 400

    @pytest.mark.asyncio
    async def test_post_both_query_and_slug(self):
        """POST returns 400 when both query and slug provided."""
        handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
        handler.logger = MagicMock()
        handler.request = MockRequest(
            match_info={'agent_id': 'agent'},
            json_data={
                'name': 'test',
                'query': 'SELECT 1',
                'query_slug': 'some_slug'
            }
        )

        def json_response(data, status=200):
            return web.json_response(data, status=status)
        handler.json_response = json_response

        response = await handler.post()
        assert response.status == 400

    @pytest.mark.asyncio
    async def test_post_missing_name(self):
        """POST returns 400 when name missing."""
        handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
        handler.logger = MagicMock()
        handler.request = MockRequest(
            match_info={'agent_id': 'agent'},
            json_data={'query_slug': 'some_slug'}
        )

        def json_response(data, status=200):
            return web.json_response(data, status=status)
        handler.json_response = json_response

        response = await handler.post()
        assert response.status == 400


# =============================================================================
# DELETE ENDPOINT TESTS
# =============================================================================


class TestDatasetManagerHandlerDelete:
    """Tests for DELETE endpoint - remove datasets."""

    @pytest.mark.asyncio
    async def test_delete_dataset(self):
        """DELETE removes dataset."""
        dm = DatasetManager()
        df = pd.DataFrame({'a': [1, 2, 3]})
        dm.add_dataframe("test_df", df)

        with patch('parrot.handlers.datasets.get_session', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"agent_dataset_manager": dm}

            handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
            handler.logger = MagicMock()
            handler._user_objects_handler = None
            handler.request = MockRequest(
                match_info={'agent_id': 'agent'},
                query={'name': 'test_df'}
            )

            def json_response(data, status=200):
                return web.json_response(data, status=status)
            handler.json_response = json_response

            response = await handler.delete()
            import json
            result = json.loads(response.body.decode())

            assert response.status == 200
            assert result['name'] == 'test_df'

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self):
        """DELETE returns 404 for missing dataset."""
        dm = DatasetManager()

        with patch('parrot.handlers.datasets.get_session', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"agent_dataset_manager": dm}

            handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
            handler.logger = MagicMock()
            handler._user_objects_handler = None
            handler.request = MockRequest(
                match_info={'agent_id': 'agent'},
                query={'name': 'nonexistent'}
            )

            def json_response(data, status=200):
                return web.json_response(data, status=status)
            handler.json_response = json_response

            response = await handler.delete()
            assert response.status == 404

    @pytest.mark.asyncio
    async def test_delete_missing_name_param(self):
        """DELETE returns 400 when name param missing."""
        handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
        handler.logger = MagicMock()
        handler.request = MockRequest(
            match_info={'agent_id': 'agent'},
            query={}
        )

        def json_response(data, status=200):
            return web.json_response(data, status=status)
        handler.json_response = json_response

        response = await handler.delete()
        assert response.status == 400

    @pytest.mark.asyncio
    async def test_delete_missing_agent_id(self):
        """DELETE returns 400 when agent_id missing."""
        handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
        handler.logger = MagicMock()
        handler.request = MockRequest(
            match_info={},
            query={'name': 'test'}
        )

        def json_response(data, status=200):
            return web.json_response(data, status=status)
        handler.json_response = json_response

        response = await handler.delete()
        assert response.status == 400


# =============================================================================
# SESSION INTEGRATION TESTS
# =============================================================================


class TestSessionIntegration:
    """Tests for session-scoped DatasetManager behavior."""

    @pytest.mark.asyncio
    async def test_creates_dm_if_not_in_session(self):
        """Creates new DatasetManager when not in session."""
        with patch('parrot.handlers.datasets.get_session', new_callable=AsyncMock) as mock_get:
            session = {}
            mock_get.return_value = session

            handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
            handler.logger = MagicMock()
            handler._user_objects_handler = None
            handler.request = MockRequest(match_info={'agent_id': 'new-agent'})

            dm = await handler._get_dataset_manager('new-agent')

            assert isinstance(dm, DatasetManager)
            assert 'new-agent_dataset_manager' in session

    @pytest.mark.asyncio
    async def test_returns_existing_dm_from_session(self):
        """Returns existing DatasetManager from session."""
        existing_dm = DatasetManager()
        df = pd.DataFrame({'x': [1, 2]})
        existing_dm.add_dataframe("preloaded", df)

        with patch('parrot.handlers.datasets.get_session', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"my-agent_dataset_manager": existing_dm}

            handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
            handler.logger = MagicMock()
            handler._user_objects_handler = None
            handler.request = MockRequest(match_info={'agent_id': 'my-agent'})

            dm = await handler._get_dataset_manager('my-agent')

            assert dm is existing_dm
            # Verify pre-existing data is preserved
            datasets = await dm.list_available()
            assert len(datasets) == 1
            assert datasets[0]['name'] == 'preloaded'

    @pytest.mark.asyncio
    async def test_different_agents_get_different_dms(self):
        """Different agent_ids get different DatasetManagers."""
        dm1 = DatasetManager()
        dm2 = DatasetManager()

        with patch('parrot.handlers.datasets.get_session', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "agent1_dataset_manager": dm1,
                "agent2_dataset_manager": dm2
            }

            handler = DatasetManagerHandler.__new__(DatasetManagerHandler)
            handler.logger = MagicMock()
            handler._user_objects_handler = None

            handler.request = MockRequest(match_info={'agent_id': 'agent1'})
            result1 = await handler._get_dataset_manager('agent1')

            handler.request = MockRequest(match_info={'agent_id': 'agent2'})
            result2 = await handler._get_dataset_manager('agent2')

            assert result1 is dm1
            assert result2 is dm2
            assert result1 is not result2
