from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel, Field
from .abstract import AbstractTool


class FileOutputToolArgs(BaseModel):
    """Arguments for tools that output files."""
    content: str = Field(description="Content to write to file")
    filename: Optional[str] = Field(default=None, description="Output filename")

class TextFileTool(AbstractTool):
    """Example tool that generates text files."""

    name = "TextFileTool"
    description = "Creates text files with specified content"
    args_schema = FileOutputToolArgs

    def _default_output_dir(self) -> Path:
        """Default output directory for text files."""
        return self.static_dir / "documents" / "text"

    async def _execute(
        self,
        content: str,
        filename: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a text file with the specified content.

        Args:
            content: Text content to write
            filename: Optional filename

        Returns:
            Dictionary with file information
        """
        if not filename:
            filename = self.generate_filename("text_output", ".txt")

        file_path = self.output_dir / filename
        file_path = self.validate_output_path(file_path)

        # Write content to file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

        # Generate URL for the file
        file_url = self.to_static_url(file_path)

        return {
            "filename": filename,
            "file_path": str(file_path),
            "file_url": file_url,
            "content_length": len(content),
            "created_at": datetime.now().isoformat()
        }
