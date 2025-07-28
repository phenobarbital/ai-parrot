from typing import Dict, Any
from pydantic import BaseModel, Field
from .abstract import AbstractTool


# MathTool Arguments Schema
class MathToolArgs(BaseModel):
    """Arguments schema for MathTool."""
    a: float = Field(description="First number")
    b: float = Field(description="Second number")
    operation: str = Field(
        description="Mathematical operation to perform",
        pattern="^(add|subtract|multiply|divide)$"
    )


class MathTool(AbstractTool):
    """A tool for performing basic arithmetic operations."""

    name = "MathTool"
    description = "Performs basic arithmetic operations: addition, subtraction, multiplication, and division"
    args_schema = MathToolArgs

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def _execute(self, a: float, b: float, operation: str, **kwargs) -> Dict[str, Any]:
        """
        Execute the mathematical operation.

        Args:
            a: First number
            b: Second number
            operation: Operation to perform

        Returns:
            Dictionary with the result
        """
        operations = {
            "add": self.add,
            "subtract": self.subtract,
            "multiply": self.multiply,
            "divide": self.divide
        }

        if operation not in operations:
            raise ValueError(f"Unsupported operation: {operation}")

        result = operations[operation](a, b)

        return {
            "operation": operation,
            "operands": [a, b],
            "result": result,
            "expression": self._format_expression(a, b, operation, result)
        }

    def add(self, a: float, b: float) -> float:
        """Add two numbers."""
        return a + b

    def subtract(self, a: float, b: float) -> float:
        """Subtract two numbers."""
        return a - b

    def multiply(self, a: float, b: float) -> float:
        """Multiply two numbers."""
        return a * b

    def divide(self, a: float, b: float) -> float:
        """Divide two numbers."""
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return a / b

    def _format_expression(self, a: float, b: float, operation: str, result: float) -> str:
        """Format the mathematical expression as a string."""
        operators = {
            "add": "+",
            "subtract": "-",
            "multiply": "*",
            "divide": "/"
        }

        operator = operators.get(operation, operation)
        return f"{a} {operator} {b} = {result}"
