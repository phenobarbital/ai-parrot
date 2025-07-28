from typing import Dict, Any, Union

class MathTool:
    """A tool for performing basic arithmetic operations."""

    def add(self, a: float, b: float) -> float:
        """Adds two numbers."""
        return a + b

    def subtract(self, a: float, b: float) -> float:
        """Subtracts two numbers."""
        return a - b

    def multiply(self, a: float, b: float) -> float:
        """Multiplies two numbers."""
        return a * b

    def divide(self, a: float, b: float) -> float:
        """Divides two numbers."""
        if b == 0:
            return "Error: Cannot divide by zero."
        return a / b

    def get_tool_schema(self) -> Dict[str, Any]:
        """Get the tool schema for LLM registration."""
        return {
            "type": "object",
            "properties": {
                "a": {
                    "type": "number",
                    "description": "First number"
                },
                "b": {
                    "type": "number",
                    "description": "Second number"
                },
                "operation": {
                    "type": "string",
                    "enum": ["add", "subtract", "multiply", "divide"],
                    "description": "Mathematical operation to perform"
                }
            },
            "required": ["a", "b", "operation"],
            "additionalProperties": False
        }
