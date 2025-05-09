from typing import Dict, Any, Optional, Union
from datetime import datetime
import json
from langchain_core.tools import BaseTool
from langchain_core.callbacks.manager import CallbackManagerForToolRun


# Helper function to import datetime safely (for use in the tool)
def import_time():
    return datetime

class ResultStoreTool(BaseTool):
    """Tool for storing and retrieving intermediate results during agent execution."""
    name: str = "store_result"
    description: str = """
    Store an intermediate result for later use. Use this to save important analysis outputs,
    DataFrame snippets, calculations, or any other values you want to refer to in later steps.

    Args:
        key (str): A unique identifier for the stored result
        value (Any): The value to store (can be a string, number, dict, list, or DataFrame info)
        description (str, optional): A brief description of what this value represents

    Returns:
        str: Confirmation message indicating the value was stored
    """

    # Storage for results, shared across all instances
    _storage: Dict[str, Dict[str, Any]] = {}

    def _run(
        self,
        key: str,
        value: Any,
        description: Optional[str] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Store a result with the given key."""
        try:
            # Handle DataFrame serialization
            if str(type(value)).endswith("'pandas.core.frame.DataFrame'>"):
                # Store a serializable representation of the DataFrame
                stored_value = {
                    "type": "pandas_dataframe",
                    "shape": value.shape,
                    "columns": value.columns.tolist(),
                    "data": value.head(10).to_dict(orient="records")  # Store first 10 rows
                }
            else:
                # Try JSON serialization to check if value is serializable
                try:
                    json.dumps(value)
                    stored_value = value
                except (TypeError, OverflowError):
                    # If not JSON serializable, convert to string representation
                    stored_value = {
                        "type": "non_serializable",
                        "string_repr": str(value),
                        "python_type": str(type(value))
                    }

            # Store the value with metadata
            self._storage[key] = {
                "value": stored_value,
                "description": description,
                "timestamp": import_time().strftime("%Y-%m-%d %H:%M:%S")
            }

            return f"Successfully stored result '{key}'"

        except Exception as e:
            return f"Error storing result: {str(e)}"

    @classmethod
    def get_result(cls, key: str) -> Union[Any, None]:
        """Retrieve a stored result."""
        if key in cls._storage:
            return cls._storage[key]["value"]
        return None

    @classmethod
    def list_results(cls) -> Dict[str, Dict[str, Any]]:
        """List all stored results with their metadata."""
        return {
            k: {
                "description": v.get("description", "No description provided"),
                "timestamp": v.get("timestamp", "Unknown"),
                "type": type(v["value"]).__name__
            }
            for k, v in cls._storage.items()
        }

    @classmethod
    def clear_results(cls) -> None:
        """Clear all stored results."""
        cls._storage.clear()

    @classmethod
    def delete_result(cls, key: str) -> bool:
        """Delete a specific stored result."""
        if key in cls._storage:
            del cls._storage[key]
            return True
        return False


class GetResultTool(BaseTool):
    """Tool for retrieving previously stored results."""
    name: str = "get_result"
    description: str = """
    Retrieve a previously stored result by its key.

    Args:
        key (str): The unique identifier of the stored result

    Returns:
        Any: The stored value, or an error message if the key doesn't exist
    """

    def _run(
        self,
        key: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> Any:
        """Retrieve a result with the given key."""
        result = ResultStoreTool.get_result(key)

        if result is None:
            return f"Error: No result found with key '{key}'. Available keys: {list(ResultStoreTool._storage.keys())}"

        return result

class ListResultsTool(BaseTool):
    """Tool for listing all stored results."""
    name: str = "list_results"
    description: str = """
    List all currently stored results with their metadata.

    Returns:
        Dict: A dictionary mapping result keys to their metadata
    """

    def _run(
        self,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """List all stored results."""
        results = ResultStoreTool.list_results()

        if not results:
            return "No results have been stored yet."

        return results
