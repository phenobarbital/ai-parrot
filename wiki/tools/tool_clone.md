# AbstractTool Clone Method

## Overview

The `AbstractTool` class now includes a `clone()` method that allows you to create a new instance of a tool with the same configuration. This is useful when you need multiple instances of the same tool with identical settings.

## Basic Usage

```python
from parrot.tools.your_tool import YourTool

# Create a tool with configuration
original_tool = YourTool(
    name="MyTool",
    connection_string="postgresql://localhost/mydb",
    pool_size=10
)

# Clone the tool - creates a new instance with the same configuration
cloned_tool = original_tool.clone()

# Verify they are different instances
assert cloned_tool is not original_tool  # True - different instances
assert type(cloned_tool) == type(original_tool)  # True - same class
assert cloned_tool.connection_string == original_tool.connection_string  # True - same config
```

## How It Works

The `clone()` method works by:

1. Storing all initialization parameters in `_init_kwargs` during `__init__()`
2. Creating a new instance of the same class with those parameters when `clone()` is called
3. Allowing subclasses to customize which parameters are cloned via `_get_clone_kwargs()`

## Creating Tools That Support Cloning

To ensure your custom tool properly supports cloning, pass all custom parameters to `super().__init__()`:

```python
from parrot.tools.abstract import AbstractTool
from typing import Any

class DatabaseTool(AbstractTool):
    """Example tool with custom parameters."""
    
    name = "DatabaseTool"
    description = "A database tool"
    
    def __init__(self, connection_string=None, pool_size=5, **kwargs):
        # IMPORTANT: Pass custom parameters to super().__init__()
        super().__init__(
            connection_string=connection_string,
            pool_size=pool_size,
            **kwargs
        )
        # Then set instance attributes
        self.connection_string = connection_string
        self.pool_size = pool_size
    
    async def _execute(self, **kwargs) -> Any:
        # Your implementation
        pass
```

## Customizing Clone Behavior

You can override `_get_clone_kwargs()` to customize which parameters are cloned. This is useful for:
- Excluding sensitive data (passwords, API keys)
- Excluding stateful data (connections, caches)
- Modifying parameters during cloning

### Example: Excluding Sensitive Data

```python
from typing import Dict, Any
from parrot.tools.abstract import AbstractTool

class SecureTool(AbstractTool):
    """Tool that excludes password from cloning."""
    
    def __init__(self, connection_string=None, password=None, **kwargs):
        super().__init__(
            connection_string=connection_string,
            password=password,
            **kwargs
        )
        self.connection_string = connection_string
        self.password = password
    
    def _get_clone_kwargs(self) -> Dict[str, Any]:
        """Override to exclude password from cloning."""
        kwargs = super()._get_clone_kwargs()
        # Remove sensitive data
        kwargs.pop('password', None)
        return kwargs
    
    async def _execute(self, **kwargs) -> Any:
        pass

# Usage
original = SecureTool(
    connection_string="postgresql://localhost/db",
    password="super_secret"
)

cloned = original.clone()

assert original.password == "super_secret"  # Original has password
assert cloned.password is None  # Clone does not have password
```

### Example: Excluding Stateful Objects

```python
class StatefulTool(AbstractTool):
    """Tool that excludes stateful objects from cloning."""
    
    def __init__(self, config=None, **kwargs):
        super().__init__(config=config, **kwargs)
        self.config = config
        self._connection = None  # Stateful object, should not be cloned
    
    def _get_clone_kwargs(self) -> Dict[str, Any]:
        """Exclude stateful objects from cloning."""
        kwargs = super()._get_clone_kwargs()
        # Don't clone internal state
        kwargs.pop('_connection', None)
        return kwargs
    
    async def connect(self):
        """Establish connection (called separately on each instance)."""
        self._connection = create_connection(self.config)
    
    async def _execute(self, **kwargs) -> Any:
        # Use self._connection
        pass
```

## Use Cases

1. **Multiple Independent Instances**: Create multiple instances of the same tool with   the same configuration but independent state.

```python
# Create primary tool
primary_db = DatabaseTool(connection_string="postgresql://localhost/primary")

# Clone for backup operations
backup_db = primary_db.clone()

# Both have same config but independent connections
await primary_db.connect()
await backup_db.connect()
```

2. **Template Pattern**: Create a template tool and clone it for different uses.

```python
# Create template tool with common settings
template = WebScraperTool(
    timeout=30,
    retries=3,
    headers={"User-Agent": "MyBot/1.0"}
)

# Clone for different URLs
scraper1 = template.clone()
scraper2 = template.clone()

# Use independently
await scraper1.execute(url="https://example.com/page1")
await scraper2.execute(url="https://example.com/page2")
```

3. **Testing**: Create test fixtures easily.

```python
# Create a configured tool for testing
def test_tool_fixture():
    return DatabaseTool(
        connection_string="postgresql://localhost/test_db",
        pool_size=1
    )

# Use in tests
def test_query():
    tool = test_tool_fixture().clone()  # Fresh instance for each test
    result = await tool.execute(query="SELECT 1")
    assert result.success
```

## Implementation Details

### What Gets Cloned

By default, `clone()` clones all parameters passed to `__init__()`:

- `name`: Tool name
- `description`: Tool description
- `output_dir`: Output directory path
- `base_url`: Base URL for static files
- `static_dir`: Static directory path
- All custom parameters passed in `**kwargs`

### What Doesn't Get Cloned

The following are NOT cloned automatically:

- Instance state created after `__init__()` (connections, caches, etc.)
- Class attributes
- Logger instances (new logger is created for each instance)
- Internal references and computed values

### Inheritance

The `clone()` method works correctly with inheritance:

```python
class BaseTool(AbstractTool):
    def __init__(self, base_param=None, **kwargs):
        super().__init__(base_param=base_param, **kwargs)
        self.base_param = base_param

class DerivedTool(BaseTool):
    def __init__(self, derived_param=None, **kwargs):
        super().__init__(derived_param=derived_param, **kwargs)
        self.derived_param = derived_param

# Cloning works for derived classes
derived = DerivedTool(base_param="base", derived_param="derived")
cloned = derived.clone()

assert cloned.base_param == "base"  # Base class param cloned
assert cloned.derived_param == "derived"  # Derived class param cloned
```

## Best Practices

1. **Always pass custom parameters to `super().__init__()`**: This ensures they are captured in `_init_kwargs`.

2. **Override `_get_clone_kwargs()` for sensitive data**: Exclude passwords, API keys, and other sensitive information.

3. **Don't clone stateful objects**: Connections, caches, and other stateful objects should be created fresh in each instance.

4. **Initialize state separately**: If your tool has state that needs initialization, provide a separate initialization method that can be called after cloning.

5. **Document cloning behavior**: If your tool has special cloning behavior, document it in the class docstring.

## Troubleshooting

**Problem**: Custom parameter is `None` in cloned instance.

**Solution**: Make sure you pass the custom parameter to `super().__init__()`:

```python
# WRONG
def __init__(self, custom_param=None, **kwargs):
    self.custom_param = custom_param  # Set before super()
    super().__init__(**kwargs)  # custom_param not passed!

# CORRECT
def __init__(self, custom_param=None, **kwargs):
    super().__init__(custom_param=custom_param, **kwargs)  # Pass it!
    self.custom_param = custom_param  # Then set it
```

**Problem**: Tool has unexpected state after cloning.

**Solution**: Override `_get_clone_kwargs()` to exclude stateful parameters or initialize state in a separate method.
