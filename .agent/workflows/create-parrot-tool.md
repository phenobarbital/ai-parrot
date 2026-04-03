---
description: Create a new Parrot Tool
---

---
description: Create a new Parrot Tool with standard structure and styling
---

1. Ask the user for the name of the Tool (e.g., "DbTool", "ServiceTool").
2. Create a new directory for the tool in `parrot/tools/[ToolName]`.
3. Create main tool file `parrot/tools/[ToolName]/__init__.py`.
4. Tools inherit from `AbstractTool` and return a `ToolResult`.
5. Tools accept for input a pydantic datamodel that inherits from class `AbstractToolArgsSchema`.
6. Add the following boilerplate code to `__init__.py`:
   ```python
   from ..abstract import AbstractTool, AbstractToolArgsSchema, ToolResult

   class ExampleToolArgs(AbstractToolArgsSchema):
       ...  # all arguments accepted by the tool.

   class ExampleTool(AbstractTool):
        name: str = "example_tool"
        description: str = (
            "Use the description to explain tool usage and finality"
        )
        args_schema: type[AbstractToolArgsSchema] = ExampleToolArgs

       async def _execute(self, **kwargs) -> ToolResult:
           """ main code for tool execution """
   ```
7. Add example usage and concise explanations of capabilities at classdoc.
8. Verify that the tool can be imported correctly.
9. create a pytest at `tests/` using `pytest-asyncio`.