---
type: Wiki Entity
title: SimpleRESTTool
id: class:parrot_tools.resttool.SimpleRESTTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Simplified REST tool for quick API integrations.
relates_to:
- concept: class:parrot_tools.resttool.RESTTool
  rel: extends
---

# SimpleRESTTool

Defined in [`parrot_tools.resttool`](../summaries/mod:parrot_tools.resttool.md).

```python
class SimpleRESTTool(RESTTool)
```

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

## Methods

- `async def get(self, endpoint: str, params: Optional[Dict[str, Any]]=None, **kwargs) -> ToolResult` — Convenience method for GET requests.
- `async def post(self, endpoint: str, data: Optional[Dict[str, Any]]=None, **kwargs) -> ToolResult` — Convenience method for POST requests.
- `async def put(self, endpoint: str, data: Optional[Dict[str, Any]]=None, **kwargs) -> ToolResult` — Convenience method for PUT requests.
- `async def patch(self, endpoint: str, data: Optional[Dict[str, Any]]=None, **kwargs) -> ToolResult` — Convenience method for PATCH requests.
- `async def delete(self, endpoint: str, params: Optional[Dict[str, Any]]=None, **kwargs) -> ToolResult` — Convenience method for DELETE requests.
