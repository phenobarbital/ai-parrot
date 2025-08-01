from typing import Dict, Any
from pydantic import BaseModel, Field, field_validator
from .abstract import AbstractTool


# MathTool Arguments Schema
class MathToolArgs(BaseModel):
    """Arguments schema for MathTool."""
    a: float = Field(description="First number")
    b: float = Field(description="Second number")
    operation: str = Field(
        description="Mathematical operation to perform. Supported operations: add/addition, subtract/subtraction, multiply/multiplication, divide/division"
    )

    @field_validator('operation')
    @classmethod
    def validate_operation(cls, v: str) -> str:
        """Normalize operation names to internal format."""
        # Mapping of various operation names to internal names
        operation_mapping = {
            # Standard names
            'add': 'add',
            'subtract': 'subtract',
            'multiply': 'multiply',
            'divide': 'divide',
            # Alternative names
            'addition': 'add',
            'subtraction': 'subtract',
            'multiplication': 'multiply',
            'division': 'divide',
            # Math symbols
            '+': 'add',
            '-': 'subtract',
            '*': 'multiply',
            '/': 'divide',
            '÷': 'divide',
            '×': 'multiply',
            # Common variations
            'plus': 'add',
            'minus': 'subtract',
            'times': 'multiply',
            'sum': 'add',
            'difference': 'subtract',
            'product': 'multiply',
            'quotient': 'divide'
        }

        normalized = v.lower().strip()
        if normalized in operation_mapping:
            return operation_mapping[normalized]

        # If not found, provide helpful error message
        valid_operations = list(set(operation_mapping.values()))
        raise ValueError(
            f"Unsupported operation: '{v}'. "
            f"Supported operations: {', '.join(valid_operations)} "
            f"or their aliases: {', '.join(operation_mapping.keys())}"
        )

class MathTool(AbstractTool):
    """A tool for performing basic arithmetic operations."""

    name = "MathTool"
    description = "Performs basic arithmetic operations: addition, subtraction, multiplication, and division. Accepts various operation names like 'add', 'addition', '+', 'plus', etc."
    args_schema = MathToolArgs

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def _execute(self, a: float, b: float, operation: str, **kwargs) -> Dict[str, Any]:
        """
        Execute the mathematical operation.

        Args:
            a: First number
            b: Second number
            operation: Operation to perform (already normalized by validator)

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
