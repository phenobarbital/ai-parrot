---
description: Scaffold a SimpleMCPServer for a designated Parrot Tool
---

Follow these steps to generate a new MCP Server script for a Parrot Tool.

1.  **Identify the Tool**:
    *   Check if the user provided a **Tool Name** (e.g., `WeatherTool`, `JiraToolkit`).
    *   If not, **ask the user** for the name of the Tool they want to expose.

2.  **Determine Server Configuration**:
    *   **Transport**: Default to `sse` if not specified. Supported: `http`, `sse`, `stdio`.
    *   **Authentication**: Default to `none` if not specified. Supported: `none`, `api_key`.
    *   Ask the user for these details if they are critical and missing, otherwise use defaults.

3.  **Analyze the Tool**:
    *   Search for the Tool's class definition in the codebase to find its import path.
    *   Read the Tool's `__init__` method to identify required arguments (e.g., `api_key`, `base_url`).

4.  **Generate the Server Script**:
    *   Create a new Python file in the `mcp_servers/` directory. Name it appropriately (e.g., `mcp_servers/<tool_name_snake_case>_server.py`).
    *   **Imports**:
        *   Import `argparse`.
        *   Import `SimpleMCPServer` from `parrot.services.mcp.simple`.
        *   Import the target Tool class.
        *   Import `config` from `navconfig` if environment variables are needed.
    *   **Argument Parsing**:
        *   Set up `argparse` to accept:
            *   `--port` (default 8000).
            *   `--transport` (default to the chosen transport).
            *   `--auth-method` (if applicable).
            *   **Tool Arguments**: Add arguments for every required parameter of the Tool's `__init__` method.
    *   **Initialization**:
        *   Instantiate the Tool using the provided console arguments or environment variables.
        *   Instantiate `SimpleMCPServer` with the tool instance, name, transport, and auth settings.
    *   **Execution**:
        *   Call `server.run()`.

5.  **Final Review**:
    *   Show the generated code to the user.
    *   Verify the imports are correct based on the project structure.
