#!/usr/bin/env python3
"""
Scaffold a new ai-parrot tool.

Usage:
    python scripts/scaffold_tool.py <ToolName>
"""
import sys
import re
from pathlib import Path

TOOL_TEMPLATE = '''"""
{tool_name} Tool for ai-parrot.
"""
from typing import Dict, Any, Type
from pydantic import BaseModel, Field
from .abstract import AbstractTool, ToolResult


class {tool_name}Args(BaseModel):
    """Arguments for the {tool_name}."""
    query: str = Field(description="The query or input for the tool")


class {tool_name}(AbstractTool):
    """
    {tool_name}: [Add brief description here]
    """
    name = "{tool_name}"
    description = "Description of what {tool_name} does."
    args_schema = {tool_name}Args

    async def _execute(self, query: str, **kwargs) -> ToolResult:
        """
        Execute the tool.
        
        Args:
            query: The main input for the tool.
            
        Returns:
            ToolResult object.
        """
        try:
            # TODO: Implement tool logic here
            result = f"Processed: {{query}}"
            
            return ToolResult(
                status="success",
                result=result,
                metadata={{
                    "tool": self.name
                }}
            )
        except Exception as e:
            return ToolResult(
                status="error",
                error=str(e),
                result=None
            )
'''

def to_snake_case(name: str) -> str:
    """Convert CamelCase to snake_case."""
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/scaffold_tool.py <ToolName>")
        sys.exit(1)

    tool_name = sys.argv[1]
    
    # Basic validation to ensure CamelCase or reasonable name
    if not tool_name[0].isupper():
        print(f"Warning: Tool name '{tool_name}' usually starts with an uppercase letter.")

    file_name = to_snake_case(tool_name) + ".py"
    
    # Locate parrot/tools directory
    # Assuming script is run from project root or scripts/ dir
    # we look for the parrot/tools relative to this script
    script_dir = Path(__file__).parent.resolve()
    project_root = script_dir.parent
    tools_dir = project_root / "parrot" / "tools"
    
    if not tools_dir.exists():
        print(f"Error: Could not find tools directory at {tools_dir}")
        sys.exit(1)
        
    target_file = tools_dir / file_name
    
    if target_file.exists():
        print(f"Error: File {target_file} already exists.")
        sys.exit(1)
        
    content = TOOL_TEMPLATE.format(tool_name=tool_name)
    
    try:
        with open(target_file, "w") as f:
            f.write(content)
        print(f"Successfully created tool scaffold at: {target_file}")
        print(f"Class: {tool_name}")
        print("Don't forget to implement the logic in _execute!")
    except Exception as e:
        print(f"Failed to write file: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
