# calculator/tool.py
from typing import Dict, Any, Optional, List, Callable
from pathlib import Path
from pydantic import BaseModel, Field
from parrot.tools.abstract import AbstractTool, ToolResult
import importlib
import inspect


class CalculatorArgs(BaseModel):
    """Arguments for calculator operations."""
    operation: str = Field(
        description="Operation to perform (e.g., 'mean', 'std', 'correlation', 'derivative')"
    )
    values: Optional[List[float]] = Field(
        default=None,
        description="List of numerical values for statistical operations"
    )
    x: Optional[float] = Field(default=None, description="First operand or x value")
    y: Optional[float] = Field(default=None, description="Second operand or y value")
    expression: Optional[str] = Field(
        default=None,
        description="Mathematical expression for evaluation"
    )
    params: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Additional parameters for specific operations"
    )


class CalculatorTool(AbstractTool):
    """
    Advanced calculator tool with dynamically loaded operations.

    Supports mathematical, statistical, and scientific computations
    by loading operation functions from the operations/ folder.
    """

    name = "CalculatorTool"
    description = (
        "Advanced calculator supporting mathematical, statistical, and scientific operations. "
        "Available operations are dynamically loaded from operation modules."
    )
    args_schema = CalculatorArgs

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.operations: Dict[str, Callable] = {}
        self._load_operations()

    def _load_operations(self):
        """Dynamically load all operations from the operations/ folder."""
        operations_dir = Path(__file__).parent / "operations"

        if not operations_dir.exists():
            self.logger.warning(f"Operations directory not found: {operations_dir}")
            return

        # Discover all Python files in operations/
        for py_file in operations_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue

            module_name = f"parrot.tools.calculator.operations.{py_file.stem}"

            try:
                module = importlib.import_module(module_name)

                # Load all functions marked with @operation decorator
                # or all public functions
                for name, obj in inspect.getmembers(module, inspect.isfunction):
                    if not name.startswith("_"):
                        # Check if function has operation metadata
                        if hasattr(obj, "_is_operation"):
                            operation_name = obj._operation_name or name
                            self.operations[operation_name] = obj
                            self.logger.debug(
                                f"Loaded operation: {operation_name} from {py_file.name}"
                            )

            except Exception as e:
                self.logger.error(f"Failed to load operations from {py_file}: {e}")

    async def _execute(
        self,
        operation: str,
        values: Optional[List[float]] = None,
        x: Optional[float] = None,
        y: Optional[float] = None,
        expression: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute the requested operation."""

        if operation not in self.operations:
            available = ", ".join(sorted(self.operations.keys()))
            return {
                "status": "error",
                "error": f"Unknown operation '{operation}'. Available: {available}",
                "result": None
            }

        try:
            func = self.operations[operation]

            # Build kwargs for the operation function
            op_kwargs = {
                "values": values,
                "x": x,
                "y": y,
                "expression": expression,
            }

            if params:
                op_kwargs.update(params)

            # Filter None values
            op_kwargs = {k: v for k, v in op_kwargs.items() if v is not None}

            # Execute operation
            result = await self._call_operation(func, op_kwargs)

            return {
                "status": "success",
                "result": result,
                "operation": operation,
                "metadata": {
                    "available_operations": list(self.operations.keys())
                }
            }

        except Exception as e:
            self.logger.error(f"Error executing operation '{operation}': {e}")
            return {
                "status": "error",
                "error": str(e),
                "result": None
            }

    async def _call_operation(self, func: Callable, kwargs: Dict[str, Any]) -> Any:
        """Call operation function (sync or async)."""
        if inspect.iscoroutinefunction(func):
            return await func(**kwargs)
        else:
            return func(**kwargs)

    def list_operations(self) -> List[str]:
        """List all available operations."""
        return sorted(self.operations.keys())
