from datetime import datetime, date
from pathlib import Path
# Model:
from asyncdb.models import Model, Field


def today_date() -> date:
    """Returns today's date."""
    return datetime.now().date()

class NextStopStore(Model):
    """Model representing Table for the NextStop system."""
    user_id: str = Field(
        primary_key=True,
        description="Unique identifier for the user.",
        title="User ID",
    )
    data: str = Field(
        default="",
        description="Data related to the NextStop agent's response.",
        title="Data"
    )
    content: str = Field(
        default="",
        description="Content related to the NextStop agent's response.",
        title="Content"
    )
    agent_name: str = Field(
        primary_key=True,
        description="Name of the agent associated.",
        title="Agent Name",
        default="NextStopAgent"
    )
    program_slug: str = Field(
        primary_key=True,
        description="Unique identifier for the program slug.",
        example="nextstop",
        title="Program Slug",
        default="hisense"
    )
    kind: str = Field(
        default="nextstop",
        description="Kind of the agent, default is 'nextstop'.",
        title="Kind"
    )
    request_date: date = Field(
        default_factory=today_date,
        description="Timestamp when the record was created."
    )
    output: str = Field(
        default="",
        description="Output of the NextStop agent's response.",
        title="Output"
    )
    podcast_path: str = Field(
        default=None,
        description="Path to the podcast file related to the NextStop agent's response.",
        title="Podcast Path"
    )
    pdf_path: str = Field(
        default=None,
        description="Path to the PDF file related to the NextStop agent's response.",
        title="PDF Path"
    )
    image_path: str = Field(
        default=None,
        description="Path to the image file related to the NextStop agent's response.",
        title="Image Path"
    )
    document_path: str = Field(
        default=None,
        description="Path to the document file related to the NextStop agent's response.",
        title="Document Path"
    )
    documents: list[str] = Field(
        default_factory=list,
        description="List of documents related to the NextStop agent's response.",
        title="Documents"
    )
    attributes: dict = Field(
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
