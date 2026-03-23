from typing import Dict, Any, Optional
import math as mathlib
from pydantic import BaseModel, Field, field_validator
from .abstract import AbstractTool


# MathTool Arguments Schema
class MathToolArgs(BaseModel):
    """Arguments schema for MathTool."""
    a: float = Field(description="The number for unary operations, or the first number for binary operations.")
    operation: str = Field(
        description="Mathematical operation. Supports: add, subtract, multiply, divide, sqrt."
    )
    b: Optional[float] = Field(
        default=None,
        description="The second number for binary operations. Not used for unary operations like square root."
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
            'quotient': 'divide',
            'sqrt': 'sqrt',
            'square_root': 'sqrt',
            'square root': 'sqrt'
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
    description = "Performs basic arithmetic operations: addition, subtraction, multiplication, division and square root. Accepts various operation names like 'add', 'addition', '+', 'plus', etc."
    args_schema = MathToolArgs

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def _execute(self, a: float, operation: str = 'add', b: float = None, **kwargs) -> Dict[str, Any]:
        """
        Execute the mathematical operation.

        Args:
            a: First number
            b: Second number
            operation: Operation to perform (already normalized by validator)

        Returns:
            Dictionary with the result
        """
        unary_operations = {
            "sqrt": self.sqrt
        }
        binary_operations = {
            "add": self.add,
            "subtract": self.subtract,
            "multiply": self.multiply,
            "divide": self.divide
        }

        if operation in unary_operations:
            result = unary_operations[operation](a)
            operands = [a]
        elif operation in binary_operations:
            if b is None:
                raise ValueError(f"Operation '{operation}' requires a second number ('b').")
            result = binary_operations[operation](a, b)
            operands = [a, b]
        else:
            raise ValueError(f"Unsupported operation: {operation}")

        return {
            "operation": operation,
            "operands": operands,
            "result": result,
            "expression": self._format_expression(a, operation, result, b)
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

    def sqrt(self, a: float) -> float:
        """Calculate the square root of a number."""
        if a < 0:
            raise ValueError("Cannot calculate the square root of a negative number.")
        return mathlib.sqrt(a)

    def _format_expression(self, a: float, operation: str, result: float, b: Optional[float] = None) -> str:
        """Format the mathematical expression as a string."""
        if b is not None: # Binary operation
            operators = {"add": "+", "subtract": "-", "multiply": "*", "divide": "/"}
            operator = operators.get(operation, operation)
            return f"{a} {operator} {b} = {result}"
        else: # Unary operation
            if operation == 'sqrt':
                return f"sqrt({a}) = {result}"
            # Add other unary operations here if needed
            return f"{operation}({a}) = {result}"
