# tests/test_openapi_toolkit.py
"""
Unit tests for OpenAPIToolkit.

Tests cover:
- Spec loading (URL, file, string, dict)
- Reference resolution
- Operation parsing
- Tool generation
- URL building
- Parameter extraction
- Authentication handling
"""

import pytest
import json
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
from parrot.tools.openapi_toolkit import OpenAPIToolkit


# Sample OpenAPI specs for testing
SIMPLE_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "servers": [{"url": "https://api.example.com"}],
    "paths": {
        "/users": {
            "get": {
                "operationId": "list_users",
                "summary": "List all users",
                "parameters": [
                    {
                        "name": "limit",
                        "in": "query",
                        "schema": {"type": "integer"},
                        "description": "Max users to return"
                    }
                ],
                "responses": {"200": {"description": "Success"}}
            },
            "post": {
                "operationId": "create_user",
                "summary": "Create a new user",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "email": {"type": "string"}
                                },
                                "required": ["name", "email"]
                            }
                        }
                    }
                },
                "responses": {"201": {"description": "Created"}}
            }
        },
        "/users/{userId}": {
            "get": {
                "operationId": "get_user",
                "summary": "Get user by ID",
                "parameters": [
                    {
                        "name": "userId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"}
                    }
                ],
                "responses": {"200": {"description": "Success"}}
            }
        }
    }
}


SPEC_WITH_REFS = {
    "openapi": "3.0.0",
    "info": {"title": "Ref Test", "version": "1.0.0"},
    "servers": [{"url": "https://api.example.com"}],
    "paths": {
        "/products": {
            "post": {
                "operationId": "create_product",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Product"}
                        }
                    }
                },
                "responses": {"200": {"description": "OK"}}
            }
        }
    },
    "components": {
        "schemas": {
            "Product": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "price": {"type": "number"},
                    "category": {"$ref": "#/components/schemas/Category"}
                }
            },
            "Category": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"}
                }
            }
        }
    }
}


class TestOpenAPIToolkitInit:
    """Test toolkit initialization."""

    def test_init_with_dict_spec(self):
        """Test initialization with dict spec."""
        toolkit = OpenAPIToolkit(
            spec=SIMPLE_SPEC,
            service="test"
        )

        assert toolkit.service == "test"
        assert toolkit.base_url == "https://api.example.com"
        assert len(toolkit.operations) == 3

    def test_init_with_custom_base_url(self):
        """Test base URL override."""
        toolkit = OpenAPIToolkit(
            spec=SIMPLE_SPEC,
            service="test",
            base_url="https://custom.api.com"
        )

        assert toolkit.base_url == "https://custom.api.com"

    def test_init_with_api_key_bearer(self):
        """Test Bearer token authentication."""
        toolkit = OpenAPIToolkit(
            spec=SIMPLE_SPEC,
            service="test",
            api_key="test-token",
            auth_type="bearer"
        )

        assert toolkit.api_key == "test-token"
        assert toolkit.auth_type == "bearer"

    def test_init_with_api_key_header(self):
        """Test API key in header."""
        toolkit = OpenAPIToolkit(
            spec=SIMPLE_SPEC,
            service="test",
            api_key="test-key",
            auth_type="apikey",
            api_key_location="header",
            auth_header="X-API-Key"
        )

        assert toolkit.api_key == "test-key"
        assert toolkit.api_key_location == "header"
        assert toolkit.auth_header == "X-API-Key"

    def test_init_without_base_url_raises(self):
        """Test that missing base URL raises error."""
        spec_no_servers = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "paths": {}
        }

        with pytest.raises(ValueError, match="No base URL found"):
            OpenAPIToolkit(spec=spec_no_servers, service="test")


class TestSpecLoading:
    """Test specification loading from various sources."""

    def test_load_dict_spec(self):
        """Test loading from dictionary."""
        toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="test")
        assert toolkit.spec == SIMPLE_SPEC

    def test_load_json_string(self):
        """Test loading from JSON string."""
        json_str = json.dumps(SIMPLE_SPEC)
        toolkit = OpenAPIToolkit(spec=json_str, service="test")
        assert toolkit.spec == SIMPLE_SPEC

    def test_load_yaml_string(self):
        """Test loading from YAML string."""
        yaml_str = """
openapi: 3.0.0
info:
  title: Test API
  version: 1.0.0
servers:
  - url: https://api.example.com
paths:
  /test:
    get:
      operationId: test_op
      responses:
        '200':
          description: OK
"""
        toolkit = OpenAPIToolkit(spec=yaml_str, service="test")
        assert toolkit.spec['info']['title'] == "Test API"
        assert '/test' in toolkit.spec['paths']

    @patch('httpx.get')
    def test_load_from_url(self, mock_get):
        """Test loading from URL."""
        mock_response = Mock()
        mock_response.text = json.dumps(SIMPLE_SPEC)
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        toolkit = OpenAPIToolkit(
            spec="https://api.example.com/openapi.json",
            service="test"
        )

        assert mock_get.called
        assert toolkit.spec == SIMPLE_SPEC

    def test_load_from_file(self, tmp_path):
        """Test loading from local file."""
        spec_file = tmp_path / "openapi.json"
        spec_file.write_text(json.dumps(SIMPLE_SPEC))

        toolkit = OpenAPIToolkit(spec=str(spec_file), service="test")
        assert toolkit.spec == SIMPLE_SPEC


class TestReferenceResolution:
    """Test $ref reference resolution."""

    def test_resolve_simple_ref(self):
        """Test resolving simple component reference."""
        toolkit = OpenAPIToolkit(spec=SPEC_WITH_REFS, service="test")

        # Check that reference was resolved
        operation = toolkit.operations[0]
        schema = operation['request_body']['schema']

        assert 'properties' in schema
        assert 'name' in schema['properties']
        assert 'category' in schema['properties']

    def test_resolve_nested_refs(self):
        """Test resolving nested references."""
        toolkit = OpenAPIToolkit(spec=SPEC_WITH_REFS, service="test")

        operation = toolkit.operations[0]
        schema = operation['request_body']['schema']
        category_schema = schema['properties']['category']

        # Category should be resolved
        assert 'properties' in category_schema
        assert 'id' in category_schema['properties']
        assert 'name' in category_schema['properties']


class TestOperationParsing:
    """Test parsing of OpenAPI operations."""

    def test_parse_get_with_query_params(self):
        """Test parsing GET operation with query parameters."""
        toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="test")

        list_users_op = next(
            op for op in toolkit.operations
            if op['operation_id'] == 'list_users'
        )

        assert list_users_op['method'] == 'GET'
        assert list_users_op['path'] == '/users'
        assert len(list_users_op['parameters']['query']) == 1
        assert list_users_op['parameters']['query'][0]['name'] == 'limit'

    def test_parse_post_with_body(self):
        """Test parsing POST operation with request body."""
        toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="test")

        create_user_op = next(
            op for op in toolkit.operations
            if op['operation_id'] == 'create_user'
        )

        assert create_user_op['method'] == 'POST'
        assert create_user_op['request_body'] is not None
        assert create_user_op['request_body']['required'] is True

        schema = create_user_op['request_body']['schema']
        assert 'name' in schema['properties']
        assert 'email' in schema['properties']

    def test_parse_path_parameters(self):
        """Test parsing path parameters."""
        toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="test")

        get_user_op = next(
            op for op in toolkit.operations
            if op['operation_id'] == 'get_user'
        )

        assert len(get_user_op['parameters']['path']) == 1
        assert get_user_op['parameters']['path'][0]['name'] == 'userId'
        assert get_user_op['parameters']['path'][0]['required'] is True

    def test_operation_id_generation(self):
        """Test auto-generation of operation IDs."""
        spec = SIMPLE_SPEC.copy()
        # Remove operation ID
        del spec['paths']['/users']['get']['operationId']

        toolkit = OpenAPIToolkit(spec=spec, service="test")

        # Should generate operation ID from method and path
        ops = [op['operation_id'] for op in toolkit.operations]
        assert any('get_users' in op for op in ops)


class TestToolGeneration:
    """Test dynamic tool generation."""

    def test_tools_created_for_all_operations(self):
        """Test that tools are created for all operations."""
        toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="test")
        tools = toolkit.get_tools()

        assert len(tools) == 3  # GET /users, POST /users, GET /users/{userId}

    def test_tool_naming_convention(self):
        """Test tool naming follows convention: {service}_{method}_{path}."""
        toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="myapi")

        # Check method exists
        assert hasattr(toolkit, 'myapi_get_users')
        assert hasattr(toolkit, 'myapi_post_users')
        assert hasattr(toolkit, 'myapi_get_users_userid')

    def test_tool_names_in_tools_list(self):
        """Test that generated tools have correct names."""
        toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="test")
        tools = toolkit.get_tools()

        tool_names = {tool.name for tool in tools}

        assert 'test_get_users' in tool_names
        assert 'test_post_users' in tool_names
        assert 'test_get_users_userid' in tool_names

    def test_tool_has_description(self):
        """Test that tools have descriptions."""
        toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="test")
        tools = toolkit.get_tools()

        for tool in tools:
            assert tool.description
            assert len(tool.description) > 0


class TestURLBuilding:
    """Test URL construction."""

    def test_build_simple_url(self):
        """Test building URL without parameters."""
        toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="test")

        operation = toolkit.operations[0]
        url = toolkit._build_operation_url(operation, {})

        expected = "https://api.example.com/users"
        assert url == expected

    def test_build_url_with_path_params(self):
        """Test building URL with path parameters."""
        toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="test")

        get_user_op = next(
            op for op in toolkit.operations
            if op['operation_id'] == 'get_user'
        )

        url = toolkit._build_operation_url(get_user_op, {'userId': '123'})

        expected = "https://api.example.com/users/123"
        assert url == expected

    def test_normalize_path_for_method_name(self):
        """Test path normalization for method names."""
        toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="test")

        assert toolkit._normalize_path_for_method_name('/users') == 'users'
        assert toolkit._normalize_path_for_method_name('/users/{userId}') == 'users_userid'
        assert toolkit._normalize_path_for_method_name('/api/v1/store/inventory') == 'api_v1_store_inventory'


class TestParameterExtraction:
    """Test parameter extraction from tool calls."""

    def test_extract_query_params(self):
        """Test extracting query parameters."""
        toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="test")

        list_users_op = next(
            op for op in toolkit.operations
            if op['operation_id'] == 'list_users'
        )

        params = toolkit._extract_query_params(
            list_users_op,
            {'limit': 10}
        )

        assert params == {'limit': 10}

    def test_extract_query_params_with_api_key(self):
        """Test query params include API key when configured."""
        toolkit = OpenAPIToolkit(
            spec=SIMPLE_SPEC,
            service="test",
            api_key="test-key",
            api_key_location="query",
            api_key_name="apiKey"
        )

        list_users_op = next(
            op for op in toolkit.operations
            if op['operation_id'] == 'list_users'
        )

        params = toolkit._extract_query_params(list_users_op, {})

        assert 'apiKey' in params
        assert params['apiKey'] == "test-key"

    def test_extract_body_data(self):
        """Test extracting request body data."""
        toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="test")

        create_user_op = next(
            op for op in toolkit.operations
            if op['operation_id'] == 'create_user'
        )

        body = toolkit._extract_body_data(
            create_user_op,
            {'name': 'John Doe', 'email': 'john@example.com'}
        )

        assert body == {'name': 'John Doe', 'email': 'john@example.com'}


@pytest.mark.asyncio
class TestToolExecution:
    """Test executing operations via tools."""

    async def test_execute_get_operation(self):
        """Test executing a GET operation."""
        with patch.object(HTTPService, 'request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                {'users': [{'id': 1, 'name': 'John'}]},
                None
            )

            toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="test")
            result = await toolkit.test_get_users(limit=10)

            assert result['status'] == 'success'
            assert 'users' in result['result']

            # Verify HTTP request was made correctly
            call_args = mock_request.call_args
            assert 'limit' in call_args.kwargs['params']

    async def test_execute_post_operation(self):
        """Test executing a POST operation."""
        with patch.object(HTTPService, 'request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                {'id': 1, 'name': 'John', 'email': 'john@example.com'},
                None
            )

            toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="test")
            result = await toolkit.test_post_users(
                name='John',
                email='john@example.com'
            )

            assert result['status'] == 'success'
            assert result['result']['name'] == 'John'

    async def test_execute_with_path_params(self):
        """Test executing operation with path parameters."""
        with patch.object(HTTPService, 'request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (
                {'id': '123', 'name': 'John'},
                None
            )

            toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="test")
            result = await toolkit.test_get_users_userid(userId='123')

            assert result['status'] == 'success'

            # Verify URL includes path parameter
            call_args = mock_request.call_args
            assert '123' in call_args.kwargs['url']

    async def test_execute_handles_errors(self):
        """Test that execution errors are handled gracefully."""
        with patch.object(HTTPService, 'request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = (None, {'error': 'Not found'})

            toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="test")
            result = await toolkit.test_get_users_userid(userId='999')

            assert result['status'] == 'error'
            assert result['error'] is not None


class TestTypeConversion:
    """Test OpenAPI type to Python type conversion."""

    def test_convert_string_type(self):
        """Test string type conversion."""
        toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="test")

        python_type = toolkit._openapi_type_to_python({'type': 'string'})
        assert python_type == str

    def test_convert_integer_type(self):
        """Test integer type conversion."""
        toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="test")

        python_type = toolkit._openapi_type_to_python({'type': 'integer'})
        assert python_type == int

    def test_convert_array_type(self):
        """Test array type conversion."""
        toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="test")

        python_type = toolkit._openapi_type_to_python({
            'type': 'array',
            'items': {'type': 'string'}
        })

        # Should be List[str]
        assert hasattr(python_type, '__origin__')
        assert python_type.__origin__ == list

    def test_convert_object_type(self):
        """Test object type conversion."""
        toolkit = OpenAPIToolkit(spec=SIMPLE_SPEC, service="test")

        python_type = toolkit._openapi_type_to_python({'type': 'object'})

        # Should be Dict[str, Any]
        assert hasattr(python_type, '__origin__')
        assert python_type.__origin__ == dict


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
