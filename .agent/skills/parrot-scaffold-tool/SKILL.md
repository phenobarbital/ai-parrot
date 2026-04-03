---
name: parrot-tool-scaffold
description: Scaffolds a new custom Tool class for the ai-parrot Tool platform.
---

# ai-parrot Tool Scaffold Skill

This skill automates the creation of standard `AbstractTool` implementations for the ai-parrot framework.

## Guidelines

- **Inheritance**: Tools MUST inherit from `AbstractTool` (`parrot.tools.abstract`).
- **Imports**: Use relative imports for dependencies within `parrot/tools/` (e.g., `from .abstract import AbstractTool`).
- **Execution**: Implement the `async def _execute(self, ...)` method.
- **Return Value**: The `_execute` method MUST return a `ToolResult` object.
- **Schema**: Arguments are defined using Pydantic models (`ArgsSchema`).
- **Metadata**: Tool name and description are defined as class attributes.

## Instructions

1.  **Identify the Tool Name**:
    Extract the name of the tool the user wants to build (e.g., "StockPrice", "EmailSender").

2.  **Run the Scaffolder**:
    Execute the python script to generate the initial file in `parrot/tools/`.

    ```bash
    python scripts/scaffold_tool.py <ToolName>
    ```

3.  **Refine the Implementation**:
    After generation, edit the file in `parrot/tools/<tool_name>.py`:
    -   **Update `args_schema`**: Define the Pydantic model for arguments.
    -   **Implement `_execute`**: Add the actual logic. Ensure it handles exceptions and returns `ToolResult`.
    -   **Add Docstrings**: comprehensive docstrings for the class and methods.

## Example Usage

User: "Create a tool to search Wikipedia."

Agent:
1.  Runs `python scripts/scaffold_tool.py WikipediaSearch`
2.  Edits `parrot/tools/wikipedia_search.py` to implement the logic.
