from datetime import datetime, date
from pathlib import Path
# Pydantic:
from pydantic import BaseModel, Field, ConfigDict
# Model:
from asyncdb.models import Model, Field as ModelField


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


def today_date() -> date:
    """Returns today's date."""
    return datetime.now().date()

class NextStopStore(Model):
    """Model representing Table for the NextStop system."""
    user_id: str = ModelField(
        primary_key=True,
        description="Unique identifier for the user.",
        title="User ID",
    )
    data: str = ModelField(
        default="",
        description="Data related to the NextStop agent's response.",
        title="Data"
    )
    content: str = ModelField(
        default="",
        description="Content related to the NextStop agent's response.",
        title="Content"
    )
    agent_name: str = ModelField(
        primary_key=True,
        description="Name of the agent associated.",
        title="Agent Name",
        default="NextStopAgent"
    )
    program_slug: str = ModelField(
        primary_key=True,
        description="Unique identifier for the program slug.",
        example="nextstop",
        title="Program Slug",
        default="hisense"
    )
    kind: str = ModelField(
        default="nextstop",
        description="Kind of the agent, default is 'nextstop'.",
        title="Kind"
    )
    request_date: date = ModelField(
        default_factory=today_date,
        description="Timestamp when the record was created."
    )
    output: str = ModelField(
        default="",
        description="Output of the NextStop agent's response.",
        title="Output"
    )
    podcast_path: str = ModelField(
        default=None,
        description="Path to the podcast file related to the NextStop agent's response.",
        title="Podcast Path"
    )
    pdf_path: str = ModelField(
        default=None,
        description="Path to the PDF file related to the NextStop agent's response.",
        title="PDF Path"
    )
    image_path: str = ModelField(
        default=None,
        description="Path to the image file related to the NextStop agent's response.",
        title="Image Path"
    )
    document_path: str = ModelField(
        default=None,
        description="Path to the document file related to the NextStop agent's response.",
        title="Document Path"
    )
    documents: list[str] = ModelField(
        default_factory=list,
        description="List of documents related to the NextStop agent's response.",
        title="Documents"
    )
    attributes: dict = ModelField(
        default_factory=dict,
        description="Attributes related to the NextStop agent's response.",
        title="Attributes"
    )
    created_at: datetime

    class Meta:
        """Meta class for NextStopStore model."""
        name = "nextstop_responses"
        schema = "troc"
        strict = True
        frozen = False
