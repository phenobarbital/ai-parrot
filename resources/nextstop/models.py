from datetime import datetime
# Pydantic:
from pydantic import BaseModel, Field, ConfigDict

class StoreInfoInput(BaseModel):
    """Input schema for store-related operations requiring a Store ID."""
    store_id: str = Field(
        ...,
        description="The unique identifier of the store you want to visit or know about.",
        example="BBY123",
        title="Store ID",
        min_length=1,
        max_length=50
    )
    # Add a model_config to prevent additional properties
    model_config = ConfigDict(
        arbitrary_types_allowed=False,
        extra="forbid",
        json_schema_extra={
            "required": ["store_id"]
        }
    )

class ManagerInput(BaseModel):
    """Input schema for manager-related operations requiring a Manager ID."""
    manager_id: str = Field(
        ...,
        description="The unique identifier of the manager you want to know about.",
        example="MGR456",
        title="Manager ID",
        min_length=1,
        max_length=50
    )
    # Add a model_config to prevent additional properties
    model_config = ConfigDict(
        arbitrary_types_allowed=False,
        extra="forbid",
        json_schema_extra={
            "required": ["manager_id"]
        }
    )


class EmployeeInput(BaseModel):
    """Input schema for employee-related operations requiring an Employee ID."""
    employee_id: str = Field(
        ...,
        description="The unique identifier of the employee you want to know about.",
        example="EMP789",
        title="Employee ID",
        min_length=1,
        max_length=50
    )
    # Add a model_config to prevent additional properties
    model_config = ConfigDict(
        arbitrary_types_allowed=False,
        extra="forbid",
        json_schema_extra={
            "required": ["employee_id"]
        }
    )
