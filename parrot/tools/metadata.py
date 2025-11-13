"""Metadata tool for describing DataFrame schemas to the LLM."""
from typing import Any, Dict, Optional

from pydantic import Field

from .abstract import AbstractTool, AbstractToolArgsSchema, ToolResult


class MetadataToolArgs(AbstractToolArgsSchema):
    """Arguments for the MetadataTool."""

    dataframe: Optional[str] = Field(
        default=None,
        description="Name of the DataFrame to inspect"
    )
    column: Optional[str] = Field(
        default=None,
        description="Specific column within the DataFrame to describe"
    )


class MetadataTool(AbstractTool):
    """Expose DataFrame metadata (column descriptions, dtypes, EDA, samples) to the agent."""

    name = "dataframe_metadata"
    description = (
        "Retrieve metadata about available DataFrames, including schema, EDA stats, and sample rows"
    )
    args_schema = MetadataToolArgs

    def __init__(
        self,
        metadata: Optional[Dict[str, Dict[str, Any]]] = None,
        alias_map: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.metadata: Dict[str, Dict[str, Any]] = metadata or {}
        self.alias_map: Dict[str, str] = alias_map or {}

    def update_metadata(
        self,
        metadata: Dict[str, Dict[str, Any]],
        alias_map: Optional[Dict[str, str]] = None
    ) -> None:
        """Update the internal metadata dictionary and alias map."""
        self.metadata = metadata or {}
        self.alias_map = alias_map or {}

    async def _execute(
        self,
        dataframe: Optional[str] = None,
        column: Optional[str] = None,
        **_: Any
    ) -> ToolResult:
        if not self.metadata:
            return ToolResult(
                status="success",
                result={"message": "No metadata available"},
                metadata={"tool_name": self.name}
            )

        if dataframe:
            try:
                result = self._describe_dataframe(dataframe, column)
            except ValueError as exc:
                return ToolResult(
                    status="error",
                    result=None,
                    error=str(exc),
                    metadata={
                        "tool_name": self.name,
                        "dataframe": dataframe,
                        "column": column
                    }
                )
        else:
            result = {
                "available_dataframes": [
                    {
                        "name": name,
                        "standardized_name": self.alias_map.get(name),
                        "description": meta.get('description'),
                        "shape": meta.get('shape'),
                        "columns": list(meta.get('columns', {}).keys())
                    }
                    for name, meta in self.metadata.items()
                ]
            }

        return ToolResult(
            status="success",
            result=result,
            metadata={
                "tool_name": self.name,
                "dataframe": dataframe,
                "column": column
            }
        )

    def _describe_dataframe(self, dataframe: str, column: Optional[str] = None) -> Dict[str, Any]:
        """Describe a dataframe and optionally a specific column."""
        df_name = self._resolve_dataframe_name(dataframe)
        df_meta = self.metadata.get(df_name)
        if not df_meta:
            raise ValueError(f"DataFrame '{dataframe}' metadata not found")

        if column:
            column_meta = df_meta.get('columns', {}).get(column)
            if not column_meta:
                raise ValueError(
                    f"Column '{column}' metadata not found for DataFrame '{df_name}'"
                )
            return {
                "dataframe": df_name,
                "standardized_name": self.alias_map.get(df_name),
                "column": column,
                "metadata": column_meta
            }

        response = {
            "dataframe": df_name,
            "standardized_name": self.alias_map.get(df_name)
        }

        response.update({
            key: value
            for key, value in df_meta.items()
            if key != 'name'
        })

        return response

    def _resolve_dataframe_name(self, identifier: str) -> str:
        """Resolve either a standardized key (df1) or original name to metadata key."""
        if identifier in self.metadata:
            return identifier

        for name, alias in self.alias_map.items():
            if alias == identifier:
                return name

        return identifier
