# examples/openapi_toolkit_example.py
"""
Example usage of OpenAPIToolkit with PetStore API.

This demonstrates how to:
1. Load an OpenAPI spec from a URL
2. Create tools from the spec
3. Use the tools to interact with the API
"""

import asyncio
from parrot.tools.openapi_toolkit import OpenAPIToolkit


async def example_petstore_basic():
    """Basic example using PetStore API."""
    print("=" * 60)
    print("Example 1: Basic PetStore API Usage")
    print("=" * 60)

    # Create toolkit from PetStore OpenAPI spec
    # Note: PetStore uses relative URLs in spec, so we provide base_url explicitly
    toolkit = OpenAPIToolkit(
        spec="https://petstore3.swagger.io/api/v3/openapi.json",
        service="petstore",
        base_url="https://petstore3.swagger.io/api/v3",  # Explicit base URL
        debug=True
    )

    # Get all generated tools
    tools = toolkit.get_tools()
    print(f"\nGenerated {len(tools)} tools:")
    for tool in tools[:5]:  # Show first 5
        print(f"  - {tool.name}: {tool.description[:60]}...")
    print(f"  ... and {len(tools) - 5} more")

    # Example 1: Get pet by ID
    print("\n" + "-" * 60)
    print("Test 1: Get pet by ID")
    print("-" * 60)

    result = await toolkit.petstore_get_pet_petid(petId="1")
    print(f"Result: {result}")

    # Example 2: Find pets by status
    print("\n" + "-" * 60)
    print("Test 2: Find pets by status")
    print("-" * 60)

    result = await toolkit.petstore_get_pet_findbystatus(status="available")
    print(f"Found {len(result.get('result', []))} available pets")
    if result.get('result'):
        print(f"First pet: {result['result'][0]}")


async def example_petstore_with_auth():
    """Example with API key authentication."""
    print("\n" + "=" * 60)
    print("Example 2: PetStore with Authentication")
    print("=" * 60)

    # Create toolkit with API key
    toolkit = OpenAPIToolkit(
        spec="https://petstore3.swagger.io/api/v3/openapi.json",
        service="petstore",
        base_url="https://petstore3.swagger.io/api/v3",  # Explicit base URL
        api_key="special-key",
        auth_type="apikey",
        api_key_location="header",
        auth_header="api_key",
        debug=True
    )

    # Example: Create a new pet (requires auth)
    print("\nTest: Create new pet")
    print("-" * 60)

    # Pass parameters individually
    result = await toolkit.petstore_post_pet(
        name="Fluffy",
        photoUrls=["https://example.com/fluffy.jpg"],
        status="available"
    )
    print(f"Result: {result}")


async def example_custom_api():
    """Example with a custom API spec."""
    print("\n" + "=" * 60)
    print("Example 3: Custom API with Bearer Token")
    print("=" * 60)

    # Example with a custom API spec (as dict)
    custom_spec = {
        "openapi": "3.0.0",
        "info": {
            "title": "My API",
            "version": "1.0.0"
        },
        "servers": [
            {"url": "https://api.example.com/v1"}
        ],
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
                            "description": "Maximum number of users to return"
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Successful response"
                        }
                    }
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
                    "responses": {
                        "200": {
                            "description": "Successful response"
                        }
                    }
                }
            }
        }
    }

    toolkit = OpenAPIToolkit(
        spec=custom_spec,
        service="myapi",
        api_key="your-bearer-token",
        auth_type="bearer",
        debug=True
    )

    tools = toolkit.get_tools()
    print(f"\nGenerated {len(tools)} tools:")
    for tool in tools:
        print(f"  - {tool.name}: {tool.description}")

    # Show tool schemas
    print("\nTool schemas:")
    for tool in tools:
        schema = tool.get_tool_schema()
        print(f"\n{tool.name}:")
        # The schema may have 'input_schema' or 'parameters'
        params_key = 'input_schema' if 'input_schema' in schema else 'parameters'
        if params_key in schema and 'properties' in schema[params_key]:
            print(f"  Input: {list(schema[params_key]['properties'].keys())}")
        else:
            print("  Input: (no parameters)")


async def example_with_references():
    """Example showing reference resolution."""
    print("\n" + "=" * 60)
    print("Example 4: OpenAPI with $ref Resolution")
    print("=" * 60)

    # Example spec with references
    spec_with_refs = {
        "openapi": "3.0.0",
        "info": {"title": "Ref Example", "version": "1.0.0"},
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
                    },
                    "required": ["name", "price"]
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

    toolkit = OpenAPIToolkit(
        spec=spec_with_refs,
        service="products",
        debug=True
    )

    print("\nResolved spec successfully!")
    print(f"Operations found: {len(toolkit.operations)}")
    for op in toolkit.operations:
        print(f"  - {op['operation_id']}: {op['method']} {op['path']}")


async def example_tool_registry():
    """Example showing integration with tool registry."""
    print("\n" + "=" * 60)
    print("Example 5: Integration with Tool Registry")
    print("=" * 60)

    from parrot.tools.abstract import ToolRegistry

    # Create toolkit
    toolkit = OpenAPIToolkit(
        spec="https://petstore3.swagger.io/api/v3/openapi.json",
        service="petstore",
        debug=False
    )

    # Register tools in registry
    registry = ToolRegistry()
    registry.register_toolkit(toolkit=toolkit, prefix="")

    print(f"\nRegistered {len(registry.list_tools())} tools")

    # List some tools
    tools = registry.list_tools()
    print("\nSample of registered tools:")
    for name, desc in list(tools.items())[:5]:
        print(f"  - {name}: {desc}")


async def example_with_local_spec():
    """Example loading spec from local file."""
    print("\n" + "=" * 60)
    print("Example 6: Loading from Local YAML File")
    print("=" * 60)

    # Create a sample spec file
    import tempfile
    from pathlib import Path

    spec_yaml = """
openapi: 3.0.0
info:
  title: Weather API
  version: 1.0.0
servers:
  - url: https://api.weather.com/v1
paths:
  /current:
    get:
      operationId: get_current_weather
      summary: Get current weather
      parameters:
        - name: city
          in: query
          required: true
          schema:
            type: string
          description: City name
        - name: units
          in: query
          schema:
            type: string
            enum: [metric, imperial]
          description: Temperature units
      responses:
        '200':
          description: Successful response
"""

    # Write to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(spec_yaml)
        temp_path = f.name

    try:
        # Load from file
        toolkit = OpenAPIToolkit(
            spec=temp_path,
            service="weather",
            api_key="demo-key",
            debug=True
        )

        print(f"\nLoaded spec from: {temp_path}")
        print(f"Generated {len(toolkit.get_tools())} tools")

        for tool in toolkit.get_tools():
            print(f"\n{tool.name}:")
            print(f"  Description: {tool.description}")
            schema = tool.get_tool_schema()
            # Handle both 'input_schema' and 'parameters' keys
            params_key = 'input_schema' if 'input_schema' in schema else 'parameters'
            if params_key in schema and 'properties' in schema[params_key]:
                print(f"  Parameters: {list(schema[params_key]['properties'].keys())}")
            else:
                print("  Parameters: (no parameters)")

    finally:
        # Cleanup
        Path(temp_path).unlink()


async def main():
    """Run all examples."""
    try:
        await example_petstore_basic()
    except Exception as e:
        print(f"Example 1 failed: {e}")

    try:
        await example_petstore_with_auth()
    except Exception as e:
        print(f"Example 2 failed: {e}")

    try:
        await example_custom_api()
    except Exception as e:
        print(f"Example 3 failed: {e}")

    try:
        await example_with_references()
    except Exception as e:
        print(f"Example 4 failed: {e}")

    try:
        await example_tool_registry()
    except Exception as e:
        print(f"Example 5 failed: {e}")

    try:
        await example_with_local_spec()
    except Exception as e:
        print(f"Example 6 failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
