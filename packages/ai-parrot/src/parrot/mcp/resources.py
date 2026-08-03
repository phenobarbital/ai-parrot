from dataclasses import dataclass
from typing import Any


@dataclass
class MCPResource:
    """
    Represents an MCP Resource.

    Resources are read-only data sources exposed by the server.
    """
    uri: str
    name: str
    description: str | None = None
    mime_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to MCP protocol dictionary."""
        data = {
            "uri": self.uri,
            "name": self.name,
        }
        if self.description:
            data["description"] = self.description
        if self.mime_type:
            data["mimeType"] = self.mime_type
        return data
