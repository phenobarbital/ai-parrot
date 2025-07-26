from typing import List, Optional
import uuid
from pydantic import BaseModel, Field


class AbstractTool(BaseModel):
    """Base class for tools that can be used by the bot."""
    name: str = Field(..., description="The name of the tool.")
    description: str = Field(..., description="A brief description of what the tool does.")
    parameters: Optional[dict] = Field(None, description="Parameters required by the tool.")

    def execute(self, *args, **kwargs):
        """Method to execute the tool's functionality."""
        raise NotImplementedError("This method should be implemented by subclasses.")
