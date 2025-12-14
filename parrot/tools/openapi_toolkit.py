# parrot/tools/openapi_toolkit.py
"""
OpenAPIToolkit - Dynamic toolkit that exposes OpenAPI services as tools.

IMPROVEMENTS IN THIS VERSION:
- Uses prance for robust OpenAPI parsing and reference resolution
- Inline schema refs via prance (no manual recursion)
- Support for application/x-www-form-urlencoded
- Optimized schemas for single-operation specs (cleaner LLM experience)

This toolkit automatically converts OpenAPI specifications into callable tools,
allowing LLMs to interact with REST APIs without manual tool definition.

Example:
    toolkit = OpenAPIToolkit(
        spec="https://petstore3.swagger.io/api/v3/openapi.json",
        service="petstore"
    )
    tools = toolkit.get_tools()
    # Creates tools like: petstore_get_pet, petstore_post_pet, etc.
"""
from typing import Dict, List, Any, Optional, Union
import contextlib
import re
import json
from pathlib import Path
from urllib.parse import urlparse
import yaml
import httpx
from pydantic import BaseModel, Field, create_model
from navconfig.logging import logging

# Use prance for OpenAPI parsing with reference resolution
try:
    from prance import ResolvingParser
    PRANCE_AVAILABLE = True
except ImportError:
    PRANCE_AVAILABLE = False

from ..interfaces.http import HTTPService
from .toolkit import AbstractToolkit
from .abstract import ToolResult


class OpenAPIToolkit(AbstractToolkit):
    """
    Toolkit that dynamically generates tools from OpenAPI specifications.

    This toolkit:
    - Uses prance for robust OpenAPI 3.x parsing (JSON/YAML, local or remote)
    - Automatically resolves ALL $ref references (internal and external)
    - Creates one tool per operation with naming: {service}_{method}_{path}
    - Handles path parameters, query parameters, and request bodies
    - Supports multiple content types: application/json, application/x-www-form-urlencoded
    - Optimizes schemas for single-operation specs (cleaner for LLMs)
    - Supports multiple authentication methods (API keys, Bearer tokens, Basic auth)

    The tools are generated dynamically and integrated with HTTPService
    for robust HTTP handling with retry logic, proxy support, etc.
    """

    def __init__(
        self,
        spec: Union[str, Dict[str, Any]],
        service: str,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        auth_type: str = "bearer",  # "bearer", "apikey", "basic"
        auth_header: str = "Authorization",
        api_key_location: str = "header",  # "header", "query"
        api_key_name: str = "api_key",
        credentials: Optional[Dict[str, str]] = None,
        use_proxy: bool = False,
        timeout: int = 30,
        debug: bool = False,
        **kwargs
    ):
        """
        Initialize OpenAPI toolkit.

        Args:
            spec: OpenAPI spec as JSON string, YAML string, URL, dict, or file path
            service: Service name used as prefix for tool names (e.g., "petstore")
            base_url: Override base URL from spec
            api_key: API key for authentication
            auth_type: Authentication type ("bearer", "apikey", "basic")
            auth_header: Header name for authentication (default: "Authorization")
            api_key_location: Where to put API key ("header" or "query")
            api_key_name: Name of API key parameter (for query params)
            credentials: Alternative credentials dict (username/password for basic auth)
            use_proxy: Enable proxy usage
            timeout: Request timeout in seconds
            debug: Enable debug logging
            **kwargs: Additional toolkit configuration
        """
        super().__init__(**kwargs)

        self.service = service
        self.debug = debug
        self.logger = logging.getLogger(f'Parrot.Tools.OpenAPIToolkit.{service}')

        # Load and parse OpenAPI spec with prance (auto-resolves all $refs)
        self.raw_spec = self._load_spec_with_prance(spec)
        self.spec = self.raw_spec  # Already resolved by prance

        # Extract base URL
        self.base_url = base_url or self._extract_base_url()
        if not self.base_url:
            raise ValueError("No base URL found in spec and none provided")

        # Validate base URL is absolute
        if self.base_url.startswith('/'):
            raise ValueError(
                f"Base URL '{self.base_url}' is relative. "
                "Please provide an absolute base_url parameter or ensure the OpenAPI spec "
                "contains an absolute server URL. "
                f"Example: OpenAPIToolkit(spec=..., service='{service}', "
                f"base_url='https://example.com{self.base_url}')"
            )

        # Ensure base URL has protocol
        parsed_base = urlparse(self.base_url)
        if not parsed_base.scheme:
            raise ValueError(
                f"Base URL '{self.base_url}' is missing protocol (http:// or https://). "
                "Please provide a complete base_url parameter."
            )

        # Setup authentication
        self.api_key = api_key
        self.auth_type = auth_type
        self.auth_header = auth_header
        self.api_key_location = api_key_location
        self.api_key_name = api_key_name

        # Prepare credentials and headers for HTTPService
        creds = credentials or {}
        headers = {}

        if api_key:
            if auth_type == "bearer":
                creds['token'] = api_key
            elif auth_type == "apikey":
                if api_key_location == "header":
                    headers[auth_header] = api_key
                # For query params, we'll add it per request
                else:
                    creds['apikey'] = api_key

        # Initialize HTTPService
        self.http_service = HTTPService(
            accept='application/json',
            headers=headers,
            credentials=creds,
            use_proxy=use_proxy,
            timeout=timeout,
            debug=debug,
            **kwargs
        )

        # Parse operations from spec
        self.operations = self._parse_operations()

        # OPTIMIZATION 3: Detect if this is a single-operation spec
        self.is_single_operation = len(self.operations) == 1

        if self.debug:
            self.logger.debug(
                f"Loaded {len(self.operations)} operations. "
                f"Single operation mode: {self.is_single_operation}"
            )

        # Generate tools dynamically
        self._generate_dynamic_methods()

    def _load_spec_with_prance(self, spec: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Load OpenAPI specification using prance for automatic reference resolution.

        prance automatically:
        - Resolves ALL $ref references (internal and external)
        - Validates OpenAPI spec
        - Handles YAML and JSON
        - Supports local files and URLs

        Args:
            spec: URL, file path, JSON/YAML string, or dict

        Returns:
            Fully resolved specification as dictionary (NEVER returns None)
        """
        # Track source URL for relative URL resolution
        self._spec_source_url = None

        # If already a dict, use prance to resolve it
        if isinstance(spec, dict):
            if PRANCE_AVAILABLE:
                try:
                    # Create temporary file for prance to parse
                    import tempfile
                    temp_path = None
                    try:
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                            json.dump(spec, f)
                            temp_path = f.name

                        parser = ResolvingParser(temp_path, lazy=True, strict=False)
                        resolved_spec = parser.specification

                        # Clean up temp file
                        if temp_path:
                            Path(temp_path).unlink(missing_ok=True)

                        # Ensure we have a valid spec
                        if resolved_spec and isinstance(resolved_spec, dict):
                            return resolved_spec
                        else:
                            self.logger.warning("prance returned invalid spec, using original dict")
                            return spec

                    except Exception as inner_e:
                        # Clean up temp file on error
                        if temp_path:
                            with contextlib.suppress(Exception):
                                Path(temp_path).unlink(missing_ok=True)
                        raise inner_e

                except Exception as e:
                    self.logger.warning(f"prance parsing failed, using dict as-is: {e}")
                    # ALWAYS return the original spec as fallback
                    return spec
            else:
                # Prance not available, return original dict
                return spec

        # Check if it's a URL
        parsed = urlparse(spec)
        if parsed.scheme in ('http', 'https'):
            if self.debug:
                self.logger.debug(f"Loading spec from URL: {spec}")
            self._spec_source_url = spec

            if PRANCE_AVAILABLE:
                # Let prance handle the URL directly
                try:
                    parser = ResolvingParser(spec, lazy=True, strict=False)
                    resolved_spec = parser.specification
                    if resolved_spec and isinstance(resolved_spec, dict):
                        return resolved_spec
                except Exception as e:
                    self.logger.warning(f"prance URL parsing failed: {e}")
                    # Fall through to manual loading

            # Fallback: manual download and parse
            response = httpx.get(spec, timeout=30)
            response.raise_for_status()
            content = response.text

            # Parse manually
            try:
                loaded = yaml.safe_load(content)
                if loaded and isinstance(loaded, dict):
                    return loaded
            except Exception:
                pass

            # Try JSON
            loaded = json.loads(content)
            if loaded and isinstance(loaded, dict):
                return loaded

            raise ValueError(f"Failed to parse spec from URL: {spec}")

        # Check if it's a file path
        elif Path(spec).exists():
            if self.debug:
                self.logger.debug(f"Loading spec from file: {spec}")

            if PRANCE_AVAILABLE:
                try:
                    parser = ResolvingParser(str(spec), lazy=True, strict=False)
                    resolved_spec = parser.specification
                    if resolved_spec and isinstance(resolved_spec, dict):
                        return resolved_spec
                except Exception as e:
                    self.logger.warning(f"prance file parsing failed: {e}")
                    # Fall through to manual loading

            # Fallback: manual loading
            with open(spec, 'r', encoding='utf-8') as f:
                content = f.read()

            try:
                loaded = yaml.safe_load(content)
                if loaded and isinstance(loaded, dict):
                    return loaded
            except Exception:
                pass

            # Try JSON
            loaded = json.loads(content)
            if loaded and isinstance(loaded, dict):
                return loaded

            raise ValueError(f"Failed to parse spec from file: {spec}")

        # Otherwise, treat as string content
        else:
            if self.debug:
                self.logger.debug("Parsing spec from string")

            # Try YAML first (superset of JSON)
            try:
                loaded = yaml.safe_load(spec)
                if loaded and isinstance(loaded, dict):
                    return loaded
            except Exception:
                pass

            # Try JSON
            try:
                loaded = json.loads(spec)
                if loaded and isinstance(loaded, dict):
                    return loaded
            except Exception:
                pass

            raise ValueError(
                "Failed to parse spec from string"
            )

    def _extract_base_url(self) -> Optional[str]:
        """Extract base URL from OpenAPI servers section."""
        servers = self.spec.get('servers', [])
        if servers and len(servers) > 0:
            server_url = servers[0].get('url', '')

            # Handle server variables if present
            variables = servers[0].get('variables', {})
            for var_name, var_config in variables.items():
                default_value = var_config.get('default', '')
                server_url = server_url.replace(f'{{{var_name}}}', default_value)

            # If server URL is relative (starts with /), construct absolute URL
            # from the spec source if it was loaded from URL
            if server_url.startswith('/') and hasattr(self, '_spec_source_url') and self._spec_source_url:
                parsed = urlparse(self._spec_source_url)
                base = f"{parsed.scheme}://{parsed.netloc}"
                server_url = base + server_url

            return server_url
        return None

    def _parse_operations(self) -> List[Dict[str, Any]]:
        """
        Parse OpenAPI paths into operation definitions.

        Each operation includes:
        - operation_id: Unique identifier
        - path: API path
        - method: HTTP method
        - parameters: Path, query, and header params
        - request_body: Body schema with content type info
        - description/summary: Operation description
        """
        operations = []

        for path, path_item in self.spec.get('paths', {}).items():
            # HTTP methods
            for method in ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']:
                if method not in path_item:
                    continue

                operation_spec = path_item[method]

                # Generate operation ID if not present
                operation_id = operation_spec.get(
                    'operationId',
                    f"{method}_{path.replace('/', '_').replace('{', '').replace('}', '')}"
                )

                # Parse parameters
                parameters = {
                    'path': [],
                    'query': [],
                    'header': [],
                    'cookie': []
                }

                for param in operation_spec.get('parameters', []):
                    param_in = param.get('in', 'query')
                    if param_in in parameters:
                        parameters[param_in].append(param)

                # IMPROVEMENT 2: Parse request body with content type detection
                request_body = None
                if 'requestBody' in operation_spec:
                    request_body_spec = operation_spec['requestBody']
                    content = request_body_spec.get('content', {})

                    # Detect content type - prioritize JSON, then form-urlencoded
                    content_type = None
                    schema = None

                    if 'application/json' in content:
                        content_type = 'application/json'
                        schema = content['application/json'].get('schema', {})
                    elif 'application/x-www-form-urlencoded' in content:
                        content_type = 'application/x-www-form-urlencoded'
                        schema = content['application/x-www-form-urlencoded'].get('schema', {})
                    elif content:
                        # Fallback to first available content type
                        content_type = list(content.keys())[0]
                        schema = content[content_type].get('schema', {})

                    if schema:
                        request_body = {
                            'schema': schema,
                            'required': request_body_spec.get('required', False),
                            'description': request_body_spec.get('description', ''),
                            'content_type': content_type  # Track content type
                        }

                operations.append({
                    'operation_id': operation_id,
                    'path': path,
                    'method': method.upper(),
                    'parameters': parameters,
                    'request_body': request_body,
                    'summary': operation_spec.get('summary', ''),
                    'description': operation_spec.get('description', ''),
                })

        return operations

    def _normalize_path_for_method_name(self, path: str) -> str:
        """
        Normalize path for method name.

        Examples:
            /pet/{petId} -> pet_petid
            /store/inventory -> store_inventory
            /user/login -> user_login
        """
        # Remove leading/trailing slashes
        path = path.strip('/')

        # Replace path parameters {petId} with just petid
        path = re.sub(r'\{([^}]+)\}', r'\1', path)

        # Replace slashes and special chars with underscores
        path = re.sub(r'[^a-zA-Z0-9]+', '_', path)

        # Convert to lowercase
        path = path.lower()

        return path

    def _resolve_schema_ref(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Manually resolve $ref if present.

        This is a fallback for when prance fails to resolve references.
        Works with internal references only (#/components/schemas/...).
        """
        if '$ref' not in schema:
            return schema

        ref_path = schema['$ref']
        if not ref_path.startswith('#/'):
            # External refs not supported in this fallback
            return schema

        # Navigate the reference path
        parts = ref_path[2:].split('/')  # Remove '#/' prefix
        resolved = self.spec

        try:
            for part in parts:
                resolved = resolved[part]

            # Recursively resolve nested refs
            return self._resolve_schema_ref(resolved)
        except (KeyError, TypeError):
            # If resolution fails, return original
            return schema

    def _create_pydantic_schema(
        self,
        operation: Dict[str, Any]
    ) -> type[BaseModel]:
        """
        Create Pydantic model for operation parameters.

        IMPROVEMENT 3: For single-operation specs, create minimal schema
        without redundant path/method fields for better LLM experience.
        """
        fields = {}

        # OPTIMIZATION: Skip path/method fields for single-operation specs
        skip_meta_fields = self.is_single_operation

        # Add path parameters (always required)
        for param in operation['parameters'].get('path', []):
            field_type = self._openapi_type_to_python(param['schema'])
            field_info = Field(
                description=param.get('description', f"Path parameter: {param['name']}")
            )
            fields[param['name']] = (field_type, field_info)

        # Add query parameters
        for param in operation['parameters'].get('query', []):
            field_type = self._openapi_type_to_python(param['schema'])
            if is_required := param.get('required', False):
                field_info = Field(
                    description=param.get('description', f"Query parameter: {param['name']}")
                )
                fields[param['name']] = (field_type, field_info)
            else:
                field_info = Field(
                    default=None,
                    description=param.get('description', f"Query parameter: {param['name']}")
                )
                fields[param['name']] = (Optional[field_type], field_info)

        # Add header parameters (usually optional)
        for param in operation['parameters'].get('header', []):
            field_type = self._openapi_type_to_python(param['schema'])
            if is_required := param.get('required', False):
                field_info = Field(
                    description=param.get('description', f"Header parameter: {param['name']}")
                )
                fields[param['name']] = (field_type, field_info)
            else:
                field_info = Field(
                    default=None,
                    description=param.get('description', f"Header parameter: {param['name']}")
                )
                fields[param['name']] = (Optional[field_type], field_info)

        # Add request body fields
        if operation['request_body']:
            schema = operation['request_body']['schema']

            # CRITICAL FIX: Manually resolve $ref if prance failed
            # This ensures we always get the actual schema with type and properties
            schema = self._resolve_schema_ref(schema)

            # If request body is a single object, flatten its properties
            if schema.get('type') == 'object' and 'properties' in schema:
                for field_name, field_schema in schema['properties'].items():
                    field_type = self._openapi_type_to_python(field_schema)
                    required = field_name in schema.get('required', [])

                    if required:
                        field_info = Field(
                            description=field_schema.get('description', f"Body parameter: {field_name}")
                        )
                        fields[field_name] = (field_type, field_info)
                    else:
                        field_info = Field(
                            default=None,
                            description=field_schema.get('description', f"Body parameter: {field_name}")
                        )
                        fields[field_name] = (Optional[field_type], field_info)
            else:
                # For non-object bodies, create a single 'body' field
                field_type = self._openapi_type_to_python(schema)
                if is_required := operation['request_body'].get('required', False):
                    field_info = Field(
                        description=operation['request_body'].get('description', 'Request body')
                    )
                    fields['body'] = (field_type, field_info)
                else:
                    field_info = Field(
                        default=None,
                        description=operation['request_body'].get('description', 'Request body')
                    )
                    fields['body'] = (Optional[field_type], field_info)

        # Create dynamic model
        model_name = f"{operation['operation_id']}_Schema"

        # If no fields, create empty schema
        if not fields:
            return create_model(model_name)

        return create_model(model_name, **fields)

    def _openapi_type_to_python(self, schema: Dict[str, Any]) -> type:
        """
        Convert OpenAPI schema type to Python type.

        Args:
            schema: OpenAPI schema definition

        Returns:
            Corresponding Python type
        """
        schema_type = schema.get('type', 'string')
        schema_format = schema.get('format')

        # Handle arrays
        if schema_type == 'array':
            items_schema = schema.get('items', {'type': 'string'})
            item_type = self._openapi_type_to_python(items_schema)
            return List[item_type]

        # Handle objects (as dict)
        if schema_type == 'object':
            return Dict[str, Any]

        # Handle primitive types
        type_mapping = {
            'string': str,
            'integer': int,
            'number': float,
            'boolean': bool,
        }

        # Consider format for more specific types
        if schema_type == 'integer' and schema_format == 'int64':
            return int
        if schema_type == 'number' and schema_format == 'float':
            return float

        return type_mapping.get(schema_type, str)

    def _generate_dynamic_methods(self):
        """
        Generate dynamic async methods for each operation.

        This is the magic that converts OpenAPI operations into toolkit methods.
        Each method becomes a tool automatically via AbstractToolkit.get_tools().
        """
        for operation in self.operations:
            # Generate method name: {service}_{method}_{normalized_path}
            method_name = self._create_method_name(operation)

            # Create the async method
            async_method = self._create_operation_method(operation)

            # Create and attach Pydantic schema for argument validation
            pydantic_schema = self._create_pydantic_schema(operation)
            async_method._args_schema = pydantic_schema

            # Bind method to instance
            bound_method = async_method.__get__(self, self.__class__)
            setattr(self, method_name, bound_method)

            if self.debug:
                self.logger.debug(
                    f"Created tool method: {method_name} "
                    f"for {operation['method']} {operation['path']}"
                )

    def _create_method_name(self, operation: Dict[str, Any]) -> str:
        """
        Create method name following convention: {service}_{method}_{path}

        Examples:
            petstore_get_pet_petid
            petstore_post_pet
            petstore_get_store_inventory
        """
        method = operation['method'].lower()
        path = self._normalize_path_for_method_name(operation['path'])

        # Combine with service prefix
        method_name = f"{self.service}_{method}_{path}"

        # Clean up multiple underscores
        method_name = re.sub(r'_+', '_', method_name)

        # Remove trailing underscores
        method_name = method_name.strip('_')

        return method_name

    def _create_operation_method(self, operation: Dict[str, Any]):
        """
        Create an async method that executes the OpenAPI operation.

        This method will be called when the LLM uses the tool.
        """
        # Create the implementation
        async def operation_method(self_ref, **kwargs) -> Dict[str, Any]:
            """
            Execute OpenAPI operation.

            This docstring will be dynamically set for each operation.
            """
            try:
                # Build URL with path parameters
                url = self_ref._build_operation_url(operation, kwargs)

                # Separate query parameters
                query_params = self_ref._extract_query_params(operation, kwargs)

                # Extract header parameters
                header_params = self_ref._extract_header_params(operation, kwargs)

                # IMPROVEMENT 2: Build request body with content type handling
                body_data, content_type = self_ref._extract_body_data(operation, kwargs)

                # Make request
                method = operation['method']

                if self_ref.debug:
                    self_ref.logger.debug(
                        f"Executing {method} {url} with "
                        f"params={query_params}, headers={header_params}, "
                        f"body={body_data}, content_type={content_type}"
                    )

                # Prepare request headers
                request_headers = header_params.copy() if header_params else {}

                # Determine content type and prepare request body
                use_json = True
                if method in ['POST', 'PUT', 'PATCH'] and body_data:
                    if content_type == 'application/x-www-form-urlencoded':
                        # Send as form data
                        use_json = False
                        request_headers['Content-Type'] = 'application/x-www-form-urlencoded'

                # Create request kwargs
                request_kwargs = {
                    'url': url,
                    'method': method,
                    'params': query_params,
                }

                # Only add headers if we have any
                if request_headers:
                    request_kwargs['headers'] = request_headers

                # Add body data for POST/PUT/PATCH
                if method in ['POST', 'PUT', 'PATCH'] and body_data:
                    request_kwargs['use_json'] = use_json
                    request_kwargs['data'] = body_data

                # Execute request via HTTPService
                result, error = await self_ref.http_service.request(
                    **request_kwargs,
                    full_response=False,
                )

                if error:
                    return ToolResult(
                        status="error",
                        result=None,
                        error=str(error),
                        metadata={
                            'operation_id': operation['operation_id'],
                            'method': method,
                            'url': url,
                        }
                    ).model_dump()

                return ToolResult(
                    status="success",
                    result=result,
                    metadata={
                        'operation_id': operation['operation_id'],
                        'method': method,
                        'url': url,
                    }
                ).model_dump()

            except Exception as e:
                self_ref.logger.error(f"Error executing operation: {e}", exc_info=True)
                return ToolResult(
                    status="error",
                    result=None,
                    error=str(e),
                    metadata={'operation_id': operation['operation_id']}
                ).model_dump()

        # Set dynamic docstring
        description = (
            operation.get('description') or
            operation.get('summary', '') or
            f"{operation['method']} {operation['path']}"
        )

        operation_method.__doc__ = f"{description}\n\nOperation: {operation['operation_id']}"
        operation_method.__name__ = self._create_method_name(operation)

        # Store operation for later reference
        operation_method._operation = operation

        return operation_method

    def _build_operation_url(
        self,
        operation: Dict[str, Any],
        params: Dict[str, Any]
    ) -> str:
        """
        Build complete URL with path parameters substituted.

        Args:
            operation: Operation definition
            params: Parameters provided by LLM

        Returns:
            Complete URL with path params substituted
        """
        path = operation['path']

        # Substitute path parameters
        for param in operation['parameters'].get('path', []):
            param_name = param['name']
            if param_name in params:
                placeholder = f"{{{param_name}}}"
                path = path.replace(placeholder, str(params[param_name]))

        # Combine with base URL
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    def _extract_query_params(
        self,
        operation: Dict[str, Any],
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract query parameters from provided params."""
        query_params = {}

        for param in operation['parameters'].get('query', []):
            param_name = param['name']
            if param_name in params and params[param_name] is not None:
                query_params[param_name] = params[param_name]

        # Add API key if configured for query params
        if self.api_key and self.api_key_location == "query":
            query_params[self.api_key_name] = self.api_key

        return query_params

    def _extract_header_params(
        self,
        operation: Dict[str, Any],
        params: Dict[str, Any]
    ) -> Dict[str, str]:
        """Extract header parameters from provided params."""
        header_params = {}

        for param in operation['parameters'].get('header', []):
            param_name = param['name']
            if param_name in params and params[param_name] is not None:
                header_params[param_name] = str(params[param_name])

        return header_params

    def _extract_body_data(
        self,
        operation: Dict[str, Any],
        params: Dict[str, Any]
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Extract request body data from provided params.

        IMPROVEMENT 2: Returns tuple of (body_data, content_type) to handle
        different content types like application/json and application/x-www-form-urlencoded

        Returns:
            Tuple of (body_data, content_type)
        """
        if not operation['request_body']:
            return None, None

        # Get schema and content type
        schema = operation['request_body']['schema']
        content_type = operation['request_body'].get('content_type', 'application/json')

        # If schema is an object with properties, extract those fields
        if schema.get('type') == 'object' and 'properties' in schema:
            body = {
                prop_name: params[prop_name]
                for prop_name in schema['properties'].keys()
                if prop_name in params and params[prop_name] is not None
            }
            return body or None, content_type

        # Otherwise, look for a 'body' parameter
        if 'body' in params:
            return params['body'], content_type

        # Fallback: use all non-path, non-query, and non-header params
        path_params = {p['name'] for p in operation['parameters'].get('path', [])}
        query_params = {p['name'] for p in operation['parameters'].get('query', [])}
        header_params = {p['name'] for p in operation['parameters'].get('header', [])}

        body = {
            key: value
            for key, value in params.items()
            if key not in path_params
            and key not in query_params
            and key not in header_params
            and value is not None
        }

        return body or None, content_type
