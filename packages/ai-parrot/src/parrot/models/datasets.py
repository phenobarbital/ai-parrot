"""Pydantic models for DatasetManager HTTP operations.

These models define request/response schemas for the DatasetManagerHandler
endpoints that manage session-scoped DatasetManager instances.

Endpoints:
    GET    /datasets/{agent_id} → DatasetListResponse
    PATCH  /datasets/{agent_id} → activate/deactivate datasets
    PUT    /datasets/{agent_id} → upload files → DatasetUploadResponse
    POST   /datasets/{agent_id} → add queries
    DELETE /datasets/{agent_id} → DatasetDeleteResponse
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DatasetAction(str, Enum):
    """Actions that can be performed on a dataset."""

    ACTIVATE = "activate"
    DEACTIVATE = "deactivate"


class DatasetPatchRequest(BaseModel):
    """Request model for PATCH /datasets/{agent_id}.

    Used to activate or deactivate a dataset in the user's DatasetManager.
    """

    dataset_name: str = Field(..., description="Name of the dataset to modify")
    action: DatasetAction = Field(..., description="Action to perform")

    model_config = {"use_enum_values": True}


class DatasetQueryRequest(BaseModel):
    """Request model for POST /datasets/{agent_id} (add query).

    Used to add a new dataset based on a SQL query or a predefined query slug.
    Exactly one of `query` or `query_slug` must be provided.
    """

    name: str = Field(..., description="Dataset name/identifier")
    query: Optional[str] = Field(None, description="Raw SQL query")
    query_slug: Optional[str] = Field(
        None, description="Query slug from QuerySource"
    )
    description: Optional[str] = Field(
        default="", description="Dataset description"
    )
    datasource: Optional[dict] = Field(
        default=None,
        description=(
            "Datasource configuration. Supported types: dataframe, query_slug, "
            "sql, table, airtable, smartsheet"
        ),
    )

    def validate_query_source(self) -> None:
        """Ensure exactly one of query, query_slug, or datasource is provided.

        Raises:
            ValueError: If none of the query sources are provided, if both query
                and query_slug are provided, or if datasource is provided without
                a valid ``type`` field.
        """
        if self.datasource:
            source_type = self.datasource.get("type")
            if not source_type:
                raise ValueError("datasource.type is required when datasource is provided")
            return

        if not self.query and not self.query_slug:
            raise ValueError(
                "Either 'query', 'query_slug', or 'datasource' must be provided"
            )
        if self.query and self.query_slug:
            raise ValueError("Provide either 'query' or 'query_slug', not both")


class DatasetListResponse(BaseModel):
    """Response model for GET /datasets/{agent_id}.

    Returns metadata about all datasets in the user's DatasetManager.
    """

    datasets: list[dict] = Field(
        ..., description="List of DatasetInfo dictionaries"
    )
    total: int = Field(..., description="Total number of datasets")
    active_count: int = Field(..., description="Number of active datasets")


class DatasetUploadResponse(BaseModel):
    """Response model for PUT /datasets/{agent_id}.

    Returned after successfully uploading a file (Excel, CSV) as a dataset.
    """

    name: str = Field(..., description="Dataset name assigned")
    rows: int = Field(..., description="Number of rows in the uploaded dataset")
    columns: int = Field(..., description="Number of columns")
    columns_list: list[str] = Field(..., description="List of column names")
    message: str = Field(default="Dataset uploaded successfully")


class DatasetDeleteResponse(BaseModel):
    """Response model for DELETE /datasets/{agent_id}.

    Returned after successfully deleting a dataset.
    """

    name: str = Field(..., description="Name of deleted dataset")
    message: str = Field(default="Dataset deleted successfully")


class DatasetErrorResponse(BaseModel):
    """Error response model for dataset operations.

    Used for all error responses from dataset endpoints.
    """

    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Additional error details")


__all__ = [
    "DatasetAction",
    "DatasetPatchRequest",
    "DatasetQueryRequest",
    "DatasetListResponse",
    "DatasetUploadResponse",
    "DatasetDeleteResponse",
    "DatasetErrorResponse",
]
