"""
RESTTool - A tool for calling REST APIs with natural language interface.
"""
from typing import Dict, Any, Optional, Union, Type, List
from pathlib import Path
from pydantic import BaseModel, Field, create_model
from ..interfaces.http import HTTPService
from .abstract import AbstractTool, AbstractToolArgsSchema, ToolResult


class RESTArgsSchema(AbstractToolArgsSchema):
    """Base schema for REST API calls."""
    endpoint: str = Field(
        description="The API endpoint to call (e.g., 'get_batch', 'users/list')"
    )
    method: str = Field(
        default="GET",
        description="HTTP method to use (GET, POST, PUT, DELETE, PATCH)"
    )
    params: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Query parameters for GET requests"
    )
    data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Body data for POST/PUT/PATCH requests"
    )
    headers: Optional[Dict[str, str]] = Field(
        default=None,
        description="Additional HTTP headers"
    )


class RESTTool(AbstractTool):
    """
    Base class for creating REST API tools.

    This tool allows LLMs to call REST APIs with natural language instructions like:
    - "please, run via GET get_batch for batch_id=xyz"
    - "create a new user with POST to /users endpoint"
    - "update user 123 with PUT"

    The tool automatically:
    - Composes URLs from base_url + endpoint
    - Handles JSON inputs/outputs
    - Supports all HTTP methods
    - Provides retry logic via HTTPService
    - Returns structured responses

    Example:
        class MyAPITool(RESTTool):
            name = "my_api"
            description = "Tool for accessing MyAPI service"
            base_url = "https://api.example.com/v1"

        # Usage by LLM
        result = await tool.run(
            endpoint="users/123",
            method="GET"
        )
    """

    name: str = "rest_api"
    description: str = "Call REST API endpoints"
    args_schema: Type[BaseModel] = RESTArgsSchema

    # Class-level configuration
    base_url: str = None
    default_headers: Dict[str, str] = {}
    use_auth: bool = True
    auth_header_name: str = "Authorization"
    auth_token_prefix: str = "Bearer"

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        credentials: Optional[Dict[str, str]] = None,
        use_http2: bool = False,
        use_proxy: bool = False,
        timeout: int = 30,
        debug: bool = False,
        **kwargs
    ):
        """
        Initialize REST tool.

        Args:
            base_url: Base URL for the API (e.g., "https://api.example.com/v1")
            api_key: API key for authentication
            credentials: Dictionary with authentication credentials
            use_http2: Enable HTTP/2
            use_proxy: Enable proxy usage
            timeout: Request timeout in seconds
            debug: Enable debug logging
            **kwargs: Additional arguments passed to AbstractTool
        """
        super().__init__(**kwargs)

        # Override base_url if provided
        if base_url:
            self.base_url = base_url

        if not self.base_url:
            raise ValueError("base_url must be provided either as class attribute or __init__ parameter")

        # Setup authentication
        credentials = credentials or {}
        if api_key:
            credentials['apikey'] = api_key

        # Prepare headers
        headers = self.default_headers.copy()
        headers.update(kwargs.pop('headers', {}))

        # Initialize HTTP service
        self.http_service = HTTPService(
            accept='application/json',
            headers=headers,
            credentials=credentials,
            use_http2=use_http2,
            use_proxy=use_proxy,
            timeout=timeout,
            debug=debug,
            **kwargs
        )
        self._debug = debug

    def _build_url(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> str:
        """
        Build complete URL from base_url and endpoint.

        Args:
            endpoint: API endpoint (e.g., "get_batch", "users/123")
            params: Optional query parameters

        Returns:
            Complete URL
        """
        # Remove leading slash from endpoint if present
        endpoint = endpoint.lstrip('/')

        # Combine base_url and endpoint
        url = f"{self.base_url.rstrip('/')}/{endpoint}"

        # Add query parameters if provided
        if params:
            url = self.http_service.build_url(url, params=params)

        if self._debug:
            self.logger.debug(f"Built URL: {url}")

        return url

    def _prepare_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Prepare request parameters.

        Args:
            endpoint: API endpoint
            method: HTTP method
            params: Query parameters
            data: Request body data
            headers: Additional headers

        Returns:
            Dictionary with request parameters
        """
        method = method.upper()
        url = self._build_url(endpoint, params)

        request_kwargs = {
            "url": url,
            "method": method,
            "headers": headers or {},
        }

        # For GET/DELETE, params go in URL (already handled)
        # For POST/PUT/PATCH, data goes in body
        if method in ['POST', 'PUT', 'PATCH'] and data:
            request_kwargs["data"] = data
            request_kwargs["use_json"] = True

        return request_kwargs

    async def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> ToolResult:
        """
        Make HTTP request and return structured result.

        Args:
            endpoint: API endpoint
            method: HTTP method
            params: Query parameters
            data: Request body
            headers: Additional headers

        Returns:
            ToolResult with response data or error
        """
        try:
            # Prepare request
            request_kwargs = self._prepare_request(
                endpoint=endpoint,
                method=method,
                params=params,
                data=data,
                headers=headers
            )

            # Make request using httpx (default client)
            result, error = await self.http_service.request(
                client='httpx',
                **request_kwargs
            )

            if error:
                return ToolResult(
                    status="error",
                    result=None,
                    error=str(error),
                    metadata={
                        "endpoint": endpoint,
                        "method": method
                    }
                )

            return ToolResult(
                status="success",
                result=result,
                error=None,
                metadata={
                    "endpoint": endpoint,
                    "method": method,
                    "url": request_kwargs["url"]
                }
            )

        except Exception as e:
            self.logger.error(f"Request failed: {e}")
            return ToolResult(
                status="error",
                result=None,
                error=str(e),
                metadata={
                    "endpoint": endpoint,
                    "method": method
                }
            )

    async def _execute(
        self,
        endpoint: str,
        method: str = "GET",
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> ToolResult:
        """
        Execute the REST API call.

        This is the main method called by the LLM when using this tool.

        Args:
            endpoint: API endpoint to call
            method: HTTP method (GET, POST, PUT, DELETE, PATCH)
            params: Query parameters (for GET)
            data: Body data (for POST/PUT/PATCH)
            headers: Additional headers
            **kwargs: Additional arguments

        Returns:
            ToolResult with API response
        """
        return await self._make_request(
            endpoint=endpoint,
            method=method,
            params=params,
            data=data,
            headers=headers
        )

    def get_tool_schema(self) -> Dict[str, Any]:
        """
        Get the JSON schema for this tool.

        Returns:
            Tool schema in the format expected by LLMs
        """
        # Get base schema from args_schema
        if self.args_schema:
            schema = self.args_schema.model_json_schema()
        else:
            schema = {
                "type": "object",
                "properties": {},
                "required": []
            }

        return {
            "name": self.name,
            "description": self.description,
            "parameters": schema
        }


class DynamicRESTTool(RESTTool):
    """
    Dynamic REST tool that can be configured with custom endpoints.

    This allows creating REST tools without subclassing, by providing
    endpoint definitions at initialization.

    Example:
        tool = DynamicRESTTool(
            name="github_api",
            description="GitHub API tool",
            base_url="https://api.github.com",
            endpoints={
                "get_user": {
                    "path": "users/{username}",
                    "method": "GET",
                    "description": "Get user information"
                },
                "create_issue": {
                    "path": "repos/{owner}/{repo}/issues",
                    "method": "POST",
                    "description": "Create a new issue"
                }
            }
        )
    """

    def __init__(
        self,
        endpoints: Optional[Dict[str, Dict[str, Any]]] = None,
        **kwargs
    ):
        """
        Initialize dynamic REST tool.

        Args:
            endpoints: Dictionary of endpoint definitions
            **kwargs: Arguments passed to RESTTool
        """
        super().__init__(**kwargs)
        self.endpoints = endpoints or {}

        # Generate dynamic schema based on endpoints
        if self.endpoints:
            self.args_schema = self._generate_dynamic_schema()

    def _generate_dynamic_schema(self) -> Type[BaseModel]:
        """Generate Pydantic schema from endpoint definitions."""
        # Build choice of endpoints
        endpoint_choices = list(self.endpoints.keys())

        # Create dynamic model
        fields = {
            'endpoint': (
                str,
                Field(
                    description=f"Choose endpoint: {', '.join(endpoint_choices)}"
                )
            ),
            'method': (
                Optional[str],
                Field(
                    default=None,
                    description="HTTP method (optional, defaults to endpoint's method)"
                )
            ),
            'params': (
                Optional[Dict[str, Any]],
                Field(
                    default=None,
                    description="Query parameters or path variables"
                )
            ),
            'data': (
                Optional[Dict[str, Any]],
                Field(
                    default=None,
                    description="Request body data"
                )
            ),
        }

        return create_model(
            f"{self.name}_schema",
            **fields,
            __base__=AbstractToolArgsSchema
        )

    def _resolve_endpoint(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Resolve endpoint path with path variables.

        Args:
            endpoint: Endpoint name
            params: Parameters (may contain path variables)

        Returns:
            Resolved endpoint path
        """
        if endpoint not in self.endpoints:
            return endpoint

        endpoint_config = self.endpoints[endpoint]
        path = endpoint_config.get('path', endpoint)

        # Replace path variables
        if params:
            try:
                path = path.format(**params)
            except KeyError as e:
                self.logger.warning(f"Missing path variable: {e}")

        return path

    async def _run(
        self,
        endpoint: str,
        method: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> ToolResult:
        """
        Execute dynamic REST API call.

        Args:
            endpoint: Endpoint name or path
            method: HTTP method (optional, uses endpoint's default)
            params: Parameters (path variables + query params)
            data: Request body
            headers: Additional headers
            **kwargs: Additional arguments

        Returns:
            ToolResult with API response
        """
        # Get endpoint configuration if available
        endpoint_config = self.endpoints.get(endpoint, {})

        # Use endpoint's method if not specified
        if method is None:
            method = endpoint_config.get('method', 'GET')

        # Resolve endpoint path with variables
        resolved_path = self._resolve_endpoint(endpoint, params)

        # Make request
        return await self._make_request(
            endpoint=resolved_path,
            method=method,
            params=params,
            data=data,
            headers=headers
        )


class SimpleRESTTool(RESTTool):
    """
    Simplified REST tool for quick API integrations.

    Provides convenience methods for common operations.

    Example:
        class ProductAPI(SimpleRESTTool):
            name = "product_api"
            description = "Product management API"
            base_url = "https://api.example.com/products"

        # Usage
        tool = ProductAPI(api_key="secret")

        # Get product
        result = await tool.get("123")

        # Create product
        result = await tool.post("", data={"name": "Widget"})

        # Update product
        result = await tool.put("123", data={"price": 9.99})

        # Delete product
        result = await tool.delete("123")
    """

    async def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> ToolResult:
        """Convenience method for GET requests."""
        return await self._execute(endpoint=endpoint, method="GET", params=params, **kwargs)

    async def post(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> ToolResult:
        """Convenience method for POST requests."""
        return await self._execute(endpoint=endpoint, method="POST", data=data, **kwargs)

    async def put(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> ToolResult:
        """Convenience method for PUT requests."""
        return await self._execute(endpoint=endpoint, method="PUT", data=data, **kwargs)

    async def patch(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> ToolResult:
        """Convenience method for PATCH requests."""
        return await self._execute(endpoint=endpoint, method="PATCH", data=data, **kwargs)

    async def delete(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> ToolResult:
        """Convenience method for DELETE requests."""
        return await self._execute(endpoint=endpoint, method="DELETE", params=params, **kwargs)
