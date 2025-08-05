from typing import Dict, Any, Optional, Union
from datetime import datetime
import pandas as pd
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


class DataFrameStoreTool(BaseTool):
    """Tool specifically for storing and retrieving pandas DataFrames."""
    name: str = "store_dataframe"
    description: str = """
    Store a pandas DataFrame for later use or reference.

    Args:
        key (str): A unique identifier for the stored DataFrame
        df_variable (str): The variable name of the DataFrame to store
        description (str, optional): A brief description of what this DataFrame contains

    Returns:
        str: Confirmation message indicating the DataFrame was stored
    """

    # Storage for DataFrames, shared across all instances
    _df_storage: Dict[str, Dict[str, Any]] = {}

    def __init__(self, df_locals: Dict[str, Any]):
        """Initialize with access to the locals dictionary."""
        super().__init__()
        self.df_locals = df_locals

    def _run(
        self,
        key: str,
        df_variable: str,
        description: Optional[str] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Store a DataFrame with the given key."""
        try:
            # Check if the variable exists in df_locals
            if df_variable not in self.df_locals:
                return f"Error: DataFrame '{df_variable}' not found in available variables."

            df = self.df_locals[df_variable]

            # Verify it's actually a DataFrame
            if not str(type(df)).endswith("'pandas.core.frame.DataFrame'>"):
                return f"Error: '{df_variable}' is not a pandas DataFrame, it's a {type(df).__name__}."

            # Store the actual DataFrame (not just a representation)
            self._df_storage[key] = {
                "dataframe": df.copy(),  # Store a copy to avoid mutation
                "description": description,
                "timestamp": import_time().strftime("%Y-%m-%d %H:%M:%S"),
                "shape": df.shape,
                "columns": df.columns.tolist()
            }

            # Add a reference to the df_locals so it can be accessed in Python code
            self.df_locals[f"stored_df_{key}"] = df.copy()

            return f"Successfully stored DataFrame '{key}' with shape {df.shape}"

        except Exception as e:
            return f"Error storing DataFrame: {str(e)}"

    @classmethod
    def get_dataframe(cls, key: str) -> Union[pd.DataFrame, None]:
        """Retrieve a stored DataFrame."""
        if key in cls._df_storage:
            return cls._df_storage[key]["dataframe"]
        return None

    @classmethod
    def list_dataframes(cls) -> Dict[str, Dict[str, Any]]:
        """List all stored DataFrames with their metadata."""
        return {
            k: {
                "description": v.get("description", "No description provided"),
                "timestamp": v.get("timestamp", "Unknown"),
                "shape": v.get("shape", "Unknown"),
                "columns": v.get("columns", [])
            }
            for k, v in cls._df_storage.items()
        }

class GetDataFrameTool(BaseTool):
    """Tool for retrieving stored DataFrames."""
    name: str = "get_dataframe"
    description: str = """
    Retrieve a previously stored DataFrame by its key.

    Args:
        key (str): The unique identifier of the stored DataFrame
        target_variable (str, optional): If provided, store the retrieved DataFrame in this variable

    Returns:
        str: Information about the retrieved DataFrame
    """

    def __init__(self, df_locals: Dict[str, Any]):
        """Initialize with access to the locals dictionary."""
        super().__init__()
        self.df_locals = df_locals

    def _run(
        self,
        key: str,
        target_variable: Optional[str] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Retrieve a DataFrame with the given key."""
        df = DataFrameStoreTool.get_dataframe(key)

        if df is None:
            available_keys = list(DataFrameStoreTool._df_storage.keys())
            return f"Error: No DataFrame found with key '{key}'. Available DataFrame keys: {available_keys}"

        # If a target variable is specified, store the DataFrame there
        if target_variable:
            self.df_locals[target_variable] = df
            return f"Retrieved DataFrame '{key}' and stored in variable '{target_variable}' with shape {df.shape}"
        else:
            # Otherwise, use a default variable name
            default_var = f"retrieved_df_{key}"
            self.df_locals[default_var] = df
            return (
                f"Retrieved DataFrame '{key}' with shape {df.shape}. "
            )
